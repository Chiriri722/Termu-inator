"""Browser and Xvfb lifecycle management."""

import asyncio
import atexit
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import stat
import sys
import tempfile
import urllib.error
import urllib.request

# Track temp dirs for crash cleanup
_temp_dirs_to_clean = set()


def _atexit_cleanup():
    """Clean up temp Chrome user-data-dirs on unclean exit."""
    for d in list(_temp_dirs_to_clean):
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


atexit.register(_atexit_cleanup)


logger = logging.getLogger(__name__)

# Allow forcing single-process for devices where multi-process fails
_FORCE_SINGLE_PROCESS = os.environ.get(
    "TBP_SINGLE_PROCESS", ""
).lower() in ("1", "true", "yes")

# Default config
XVFB_DISPLAY = ":99"
XVFB_RESOLUTION = "1920x1080x24"
CDP_PORT = 9222
CHROMIUM_STDERR_LIMIT = 64 * 1024
CHROMIUM_BIN = shutil.which("chromium-browser") or shutil.which("chromium") or "chromium-browser"
CHROMIUM_CANDIDATES = ("chromium", "chromium-browser", "google-chrome-stable")


def _validated_chromium_tmpdir(environment):
    candidates = [environment.get("TMPDIR")]
    prefix = environment.get("PREFIX")
    if prefix:
        candidates.append(str(Path(prefix) / "tmp"))
    candidates.append(str(Path(sys.base_prefix) / "tmp"))

    for candidate in candidates:
        if not candidate or not os.path.isabs(candidate):
            continue
        path = Path(candidate)
        try:
            if (
                path.is_dir()
                and not path.is_symlink()
                and os.access(path, os.W_OK | os.X_OK)
            ):
                return str(path)
        except OSError:
            continue
    return None


# Chromium flags for Termux — minimal set to avoid automation fingerprint
CHROMIUM_BASE_FLAGS = [
    # Required for Termux (no root, no namespaces, no /dev/shm)
    "--no-sandbox",
    "--no-zygote",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    # Single-process only if forced (causes OOM + CF detection issues)
    *(["--single-process"] if _FORCE_SINGLE_PROCESS else []),
    # Suppress "unsupported flag" info bar (avoids visible automation signal)
    "--test-type",
    # Anti-detection: prevents navigator.webdriver=true
    "--disable-blink-features=AutomationControlled",
    # Normal browser behavior
    "--start-maximized",
    "--lang=en-US,en",
    "--js-flags=--max-old-space-size=1024",
    # Safe stability flags (low detection risk)
    "--disable-breakpad",
    "--disable-component-update",
]


def _get_gl_flags(gpu_mode):
    """Return Chrome GL flags based on GPU rendering mode."""
    if gpu_mode == "virgl":
        # Use ANGLE with native GL backend for virgl GPU passthrough.
        # --use-gl=egl crashes in single-process; --use-angle=gl works.
        return [
            "--enable-webgl",
            "--use-gl=angle",
            "--use-angle=gl",
        ]
    else:
        # Fallback: SwiftShader software rendering
        return [
            "--enable-webgl",
            "--use-gl=angle",
            "--use-angle=swiftshader-webgl",
        ]


class BrowserPilot:
    """Manages Xvfb and browser (Chromium or Firefox) lifecycle."""

    def __init__(self, display=XVFB_DISPLAY, cdp_port=CDP_PORT,
                 headless_xvfb=True, chromium_bin=None,
                 window_size="1920,1080", user_data_dir=None,
                 gpu_mode="auto", browser_type="chromium", proxy=None):
        self.display = display
        self.cdp_port = cdp_port
        self._auto_cdp_port = cdp_port == 0
        self.headless_xvfb = headless_xvfb
        self.chromium_bin = chromium_bin
        self.window_size = window_size
        self.browser_type = browser_type  # "chromium" or "firefox"
        self._gpu_mode = gpu_mode  # "auto", "virgl", "swiftshader"
        self._proxy = proxy  # Proxy URL for Chromium --proxy-server flag
        self._virgl = None
        self._xvfb_proc = None
        self._wm_proc = None  # Window manager (openbox)
        self._chrome_proc = None
        self._chromium_stderr_task = None
        self._chromium_stderr_tail = b""
        self._chromium_failed_attempts = []
        self._chromium_diagnostic_path = None
        self._runtime_dir = Path(tempfile.gettempdir()) / "termuinator-runtime"
        self._display_lease_path = None
        self._display_lease_identity = None
        self._ws_url = None
        self._user_data_dir = None
        self._external_user_data_dir = user_data_dir  # Persistent profile
        self._owns_user_data_dir = False  # Whether we should clean it up

    def _resolve_chromium_binary(self):
        """Resolve Chromium from the current Termux PATH without stale imports."""
        if self.chromium_bin:
            resolved = shutil.which(self.chromium_bin)
            if resolved:
                return resolved
            raise RuntimeError(
                f"Configured Chromium binary '{self.chromium_bin}' was not found"
            )

        for candidate in CHROMIUM_CANDIDATES:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        raise RuntimeError(
            "Chromium not found. Install it in Termux with: pkg install chromium"
        )

    async def start(self):
        """Start Xvfb + browser. Returns WS URL (Chromium) or None (Firefox)."""
        try:
            from ._utils import require_binaries
            require_binaries("Xvfb")
            if self.browser_type != "firefox":
                self.chromium_bin = self._resolve_chromium_binary()

            if self.headless_xvfb:
                await self._start_xvfb()

            if self.browser_type == "firefox":
                # Firefox: no geckodriver needed — NativeSession handles launch
                return None

            # Chromium path
            await self._setup_gpu()
            self._ws_url = await self._start_chromium()
            return self._ws_url
        except BaseException:
            try:
                await self.stop()
            except Exception as cleanup_error:
                logger.warning(
                    "Error cleaning failed browser start: %s",
                    type(cleanup_error).__name__,
                )
            raise

    async def _setup_gpu(self):
        """Resolve GPU rendering mode (auto-detect best available)."""
        from .gpu import VirglManager

        if self._gpu_mode == "swiftshader":
            return  # Explicitly requested software rendering

        self._virgl = VirglManager()
        if self._gpu_mode in ("auto", "virgl"):
            if self._virgl.is_available():
                started = await self._virgl.start()
                if started:
                    self._gpu_mode = "virgl"
                    logger.info("GPU: virgl (hardware-accelerated)")
                    return
                else:
                    logger.warning("Virgl failed to start, falling back")
            elif self._gpu_mode == "virgl":
                logger.warning(
                    "virglrenderer-android not installed. "
                    "Install with: pkg install virglrenderer-android"
                )

        self._gpu_mode = "swiftshader"
        self._virgl = None
        logger.info("GPU: SwiftShader (software rendering)")

    async def _start_xvfb(self):
        """Launch Xvfb virtual display (non-blocking)."""
        self.display = self._resolve_display(self.display)
        w, h = self.window_size.split(",")
        resolution = f"{w}x{h}x24"
        self._xvfb_proc = await asyncio.create_subprocess_exec(
            "Xvfb", self.display, "-screen", "0", resolution,
            "-ac", "-nolisten", "tcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)

        if self._xvfb_proc.returncode is not None:
            self._xvfb_proc = None
            self._release_display_lease()
            raise RuntimeError("Xvfb failed to start")

        # Start a lightweight window manager (required for window
        # minimize/activate/raise operations used by DevTools management).
        # This instance owns its display and must never kill foreign WMs.
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        openbox_bin = shutil.which("openbox")
        if openbox_bin:
            self._wm_proc = await asyncio.create_subprocess_exec(
                openbox_bin,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
            await asyncio.sleep(0.3)
            logger.info("Window manager started (openbox, PID %d)",
                        self._wm_proc.pid)
        else:
            self._wm_proc = None
            logger.warning("openbox not found — window management may not work")

    @staticmethod
    def _display_in_use(display):
        display_num = display.lstrip(":")
        roots = (Path("/tmp"), Path(tempfile.gettempdir()))
        candidates = []
        for root in roots:
            for relative in (
                f".X{display_num}-lock",
                f".X11-unix/X{display_num}",
            ):
                candidate = root / relative
                if candidate not in candidates:
                    candidates.append(candidate)
        return any(os.path.exists(candidate) for candidate in candidates)

    def _resolve_display(self, requested):
        if requested != "auto":
            if self._display_in_use(requested):
                raise RuntimeError(f"X display {requested} is already in use")
            return requested

        for display_num in range(99, 200):
            candidate = f":{display_num}"
            if self._claim_display(candidate):
                return candidate
        raise RuntimeError("No free X display found in :99-:199")

    def _ensure_runtime_dir(self):
        runtime_dir = Path(self._runtime_dir)
        runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if runtime_dir.is_symlink() or not runtime_dir.is_dir():
            raise RuntimeError("Termu-inator runtime path is not a private directory")
        os.chmod(runtime_dir, 0o700)
        return runtime_dir

    def _claim_display(self, display):
        if self._display_in_use(display):
            return False
        display_num = display.lstrip(":")
        lease_path = self._ensure_runtime_dir() / f"display-{display_num}.lease"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(lease_path, flags, 0o600)
        except FileExistsError:
            if not self._remove_stale_display_lease(lease_path):
                return False
            try:
                fd = os.open(lease_path, flags, 0o600)
            except FileExistsError:
                return False
        try:
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            lease_stat = os.fstat(fd)
        finally:
            os.close(fd)

        self._display_lease_path = lease_path
        self._display_lease_identity = (lease_stat.st_dev, lease_stat.st_ino)
        if self._display_in_use(display):
            self._release_display_lease()
            return False
        return True

    @staticmethod
    def _read_display_lease(lease_path):
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(lease_path, flags)
        except OSError:
            return None
        try:
            lease_stat = os.fstat(fd)
            if not stat.S_ISREG(lease_stat.st_mode):
                return None
            if lease_stat.st_uid != os.getuid() or lease_stat.st_size > 64:
                return None
            raw = os.read(fd, 64).decode("ascii").strip()
            pid = int(raw)
            if pid <= 0:
                return None
            return pid, (lease_stat.st_dev, lease_stat.st_ino)
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        finally:
            os.close(fd)

    def _remove_stale_display_lease(self, lease_path):
        lease = self._read_display_lease(lease_path)
        if lease is None:
            return False
        pid, identity = lease
        try:
            os.kill(pid, 0)
            return False
        except PermissionError:
            return False
        except ProcessLookupError:
            pass
        try:
            current = os.lstat(lease_path)
            if (current.st_dev, current.st_ino) != identity:
                return False
            os.unlink(lease_path)
            return True
        except OSError:
            return False

    def _release_display_lease(self):
        lease_path = self._display_lease_path
        lease_identity = self._display_lease_identity
        self._display_lease_path = None
        self._display_lease_identity = None
        if lease_path is None:
            return
        try:
            lease = self._read_display_lease(lease_path)
            if lease != (os.getpid(), lease_identity):
                return
            os.unlink(lease_path)
        except OSError:
            return

    async def _start_chromium(self):
        """Launch Chromium with CDP enabled (non-blocking).

        Uses multi-process mode by default. Readiness or early-exit failure
        triggers the bounded single-process fallback.
        """
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        chromium_tmpdir = _validated_chromium_tmpdir(env)
        if chromium_tmpdir is not None:
            env["TMPDIR"] = chromium_tmpdir

        if self._gpu_mode == "virgl" and self._virgl:
            env.update(self._virgl.get_env())
            env.pop("LIBGL_ALWAYS_SOFTWARE", None)
        else:
            env["LIBGL_ALWAYS_SOFTWARE"] = "1"

        # Use persistent profile if provided, otherwise temp dir
        if self._external_user_data_dir:
            self._user_data_dir = self._external_user_data_dir
            os.makedirs(self._user_data_dir, exist_ok=True)
            self._owns_user_data_dir = False
        else:
            self._user_data_dir = tempfile.mkdtemp(prefix="tbp_chrome_")
            _temp_dirs_to_clean.add(self._user_data_dir)
            self._owns_user_data_dir = True

        if _FORCE_SINGLE_PROCESS:
            logger.warning(
                "Running in single-process mode (TBP_SINGLE_PROCESS=1). "
                "OOM risk higher; CF detection stricter."
            )

        try:
            await self._launch_chromium(env, extra_flags=[])
            return await self._wait_for_cdp()
        except (RuntimeError, TimeoutError):
            await self._finish_failed_chromium_attempt("multi-process")
            if _FORCE_SINGLE_PROCESS:
                raise
            logger.warning(
                "Multi-process Chromium crashed. Retrying with --single-process."
            )
            self._clear_profile_locks()

        try:
            await self._launch_chromium(env, extra_flags=["--single-process"])
            return await self._wait_for_cdp()
        except (RuntimeError, TimeoutError):
            await self._finish_failed_chromium_attempt("single-process")
            if self._gpu_mode != "virgl":
                raise RuntimeError("Chromium failed to start (all modes)")

        logger.warning(
            "Virgl+single-process failed. Falling back to SwiftShader."
        )
        self._gpu_mode = "swiftshader"
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
        env.pop("GALLIUM_DRIVER", None)
        env.pop("MESA_GL_VERSION_OVERRIDE", None)
        if self._virgl:
            await self._virgl.stop()
            self._virgl = None
        self._clear_profile_locks()
        await self._launch_chromium(env, extra_flags=["--single-process"])
        try:
            return await self._wait_for_cdp()
        except (RuntimeError, TimeoutError) as exc:
            await self._finish_failed_chromium_attempt(
                "swiftshader-single-process"
            )
            raise RuntimeError("Chromium failed to start (all modes)") from exc

    def _clear_profile_locks(self):
        """Remove Chromium lock files left by a crashed process."""
        if not self._user_data_dir:
            return
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_path = os.path.join(self._user_data_dir, lock_name)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.debug("Could not remove %s: %s", lock_name, e)

    async def _launch_chromium(self, env, extra_flags=None):
        """Launch Chromium subprocess."""
        if self._auto_cdp_port:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
                reservation.bind(("127.0.0.1", 0))
                self.cdp_port = int(reservation.getsockname()[1])

        gl_flags = _get_gl_flags(self._gpu_mode)
        proxy_flags = []
        if self._proxy:
            proxy_flags.append(f"--proxy-server={self._proxy}")

        args = [
            self.chromium_bin,
            f"--remote-debugging-port={self.cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            f"--window-size={self.window_size}",
            f"--user-data-dir={self._user_data_dir}",
            *CHROMIUM_BASE_FLAGS,
            *gl_flags,
            *proxy_flags,
            *(extra_flags or []),
            "about:blank",
        ]

        self._chrome_proc = await asyncio.create_subprocess_exec(
            *args, env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._chromium_stderr_tail = b""
        if self._chrome_proc.stderr is not None:
            self._chromium_stderr_task = asyncio.create_task(
                self._drain_chromium_stderr(self._chrome_proc.stderr)
            )

    async def _drain_chromium_stderr(self, stream):
        """Drain Chromium stderr without allowing unbounded memory growth."""
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                return
            self._chromium_stderr_tail = (
                self._chromium_stderr_tail + chunk
            )[-CHROMIUM_STDERR_LIMIT:]

    async def _finish_failed_chromium_attempt(self, label):
        """Stop a failed attempt and persist its bounded private stderr tail."""
        proc = self._chrome_proc
        if proc is not None:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            else:
                await proc.wait()

        task = self._chromium_stderr_task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.TimeoutError:
                task.cancel()
            except Exception:
                pass

        returncode = None if proc is None else proc.returncode
        header = f"[{label}] returncode={returncode}\n".encode("utf-8")
        self._chromium_failed_attempts.append(
            header + self._chromium_stderr_tail[-CHROMIUM_STDERR_LIMIT:] + b"\n"
        )
        try:
            self._write_chromium_diagnostic()
        except OSError as exc:
            logger.warning(
                "Could not save private Chromium startup diagnostics: %s",
                type(exc).__name__,
            )
        self._chrome_proc = None
        self._chromium_stderr_task = None
        self._chromium_stderr_tail = b""

    def _write_chromium_diagnostic(self):
        runtime_dir = self._ensure_runtime_dir()
        diagnostic_path = runtime_dir / "chromium-startup.log"
        content = b"".join(self._chromium_failed_attempts[-3:])
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(diagnostic_path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, content)
        finally:
            os.close(fd)
        self._chromium_diagnostic_path = diagnostic_path
        logger.warning(
            "Chromium startup diagnostics saved privately: %s",
            diagnostic_path,
        )

    async def _wait_for_cdp(self, timeout=20):
        """Wait for CDP endpoint to be ready and return WS URL."""
        url = f"http://127.0.0.1:{self.cdp_port}/json/version"
        deadline = asyncio.get_running_loop().time() + timeout

        def _fetch():
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    return json.loads(resp.read()).get("webSocketDebuggerUrl", "")
            except (urllib.error.URLError, ConnectionRefusedError, OSError):
                return ""
            except Exception as e:
                logger.debug("Unexpected error polling CDP: %s", e)
                return ""

        while asyncio.get_running_loop().time() < deadline:
            if self._chrome_proc is not None and \
               self._chrome_proc.returncode is not None:
                raise RuntimeError(
                    "Chromium exited before CDP became ready "
                    f"(returncode={self._chrome_proc.returncode})"
                )
            ws_url = await asyncio.to_thread(_fetch)
            if ws_url:
                return ws_url
            await asyncio.sleep(0.5)

        raise TimeoutError(
            f"CDP not ready after {timeout}s on port {self.cdp_port}"
        )

    @property
    def ws_url(self):
        return self._ws_url

    async def stop(self):
        """Shut down Chromium and Xvfb gracefully (non-blocking, robust).

        Uses SIGTERM first, gives processes time to flush state, then SIGKILL.
        Cleans up temporary user-data-dir afterward.
        """
        for proc in (self._chrome_proc, self._wm_proc, self._xvfb_proc):
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                except Exception as e:
                    logger.warning("Error stopping process: %s", e)
        self._chrome_proc = None
        self._wm_proc = None
        self._xvfb_proc = None

        if self._chromium_stderr_task is not None:
            try:
                await asyncio.wait_for(self._chromium_stderr_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._chromium_stderr_task.cancel()
            except Exception:
                pass
            self._chromium_stderr_task = None

        # Stop virgl server
        if self._virgl:
            try:
                await self._virgl.stop()
            except Exception as e:
                logger.debug("Error stopping virgl: %s", e)
            self._virgl = None

        # Clean up temp profile (not persistent ones)
        if self._owns_user_data_dir and self._user_data_dir and \
           os.path.isdir(self._user_data_dir):
            _temp_dirs_to_clean.discard(self._user_data_dir)
            try:
                await asyncio.to_thread(
                    shutil.rmtree, self._user_data_dir, ignore_errors=True
                )
            except Exception as e:
                logger.debug("Error cleaning user-data-dir: %s", e)
        self._user_data_dir = None
        self._release_display_lease()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.stop()
