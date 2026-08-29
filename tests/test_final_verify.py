"""Tests for the fail-closed on-device release verifier."""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import scripts.final_verify as final_verify_module
from src.termuinator.core.sessions import ProcessSessionLock
from scripts.final_verify import (
    _child_environment,
    _PROCESS_TERMS,
    _runtime_distribution,
    VerificationFailure,
    build_parser,
    project_digest,
    reconstruct_artifact,
    runtime_platform_summary,
    validate_android_termux_identity,
    validate_artifact_store,
    validate_installed_source_binding,
    validate_observation,
    validate_tool_inventory,
    validate_wheel_provenance,
    validate_wheel_source_binding,
    verify_backend,
    write_private_json,
)


def _observation() -> dict[str, object]:
    return {
        "session_id": "session_abcdefgh",
        "page_id": "page_abcdefgh",
        "tab_id": "tab_abcdefgh",
        "sequence": 2,
        "page_revision": "epoch:1",
        "url": "http://127.0.0.1:43123/forms",
        "origin": "http://127.0.0.1:43123",
        "title": "Forms",
        "ready_state": "complete",
        "viewport": {"width": 1000, "height": 700, "device_scale_factor": 1.0},
        "timestamp": "2026-08-26T01:02:03+00:00",
        "capability_revision": "legacy-v1",
        "text": "Text input\nAccept terms\nChoose option\nSubmit fixture",
        "text_truncated": False,
        "accessibility": [
            {
                "ref": None,
                "role": "button",
                "name": "Submit fixture",
                "text": "",
                "depth": 0,
            }
        ],
        "interactive_elements": [
            {
                "ref": "ref_abcdefghijklmnop",
                "role": "button",
                "accessible_name": "Submit fixture",
                "text": "Submit fixture",
                "tag": "button",
                "type": "submit",
                "bounds": {"x": 10.0, "y": 10.0, "width": 100.0, "height": 30.0},
                "visible": True,
                "enabled": True,
                "editable": False,
                "checked": None,
                "frame_path": [],
                "shadow_path": [],
            }
        ],
        "dialogs": [],
        "challenges": [],
        "downloads_delta": [],
        "screenshot_artifact_uri": "artifact://sha256/" + ("a" * 64),
    }


class ObservationEvidenceTests(unittest.TestCase):
    def test_requires_full_accessibility_and_interactive_fixture_evidence(self) -> None:
        summary = validate_observation(
            _observation(),
            expected_url="http://127.0.0.1:43123/forms",
            expected_origin="http://127.0.0.1:43123",
            expected_text=(
                "Text input",
                "Accept terms",
                "Choose option",
                "Submit fixture",
            ),
        )

        self.assertEqual(summary["ready_state"], "complete")
        self.assertEqual(summary["accessibility_nodes"], 1)
        self.assertEqual(summary["interactive_elements"], 1)
        self.assertTrue(summary["interactive_ref_verified"])
        self.assertEqual(
            summary["screenshot_artifact_uri"],
            "artifact://sha256/" + ("a" * 64),
        )

    def test_rejects_role_name_only_accessibility_mapping(self) -> None:
        payload = _observation()
        payload["accessibility"] = [
            {"role": "button", "name": "Submit fixture"}
        ]

        with self.assertRaisesRegex(
            VerificationFailure,
            "accessibility node does not match the frozen public shape",
        ):
            validate_observation(
                payload,
                expected_url="http://127.0.0.1:43123/forms",
                expected_origin="http://127.0.0.1:43123",
                expected_text=("Submit fixture",),
            )


class ArtifactChunkEvidenceTests(unittest.TestCase):
    def test_reconstructs_monotonic_eof_bounded_artifact(self) -> None:
        payload = b"\x89PNG\r\n\x1a\nfixture"
        digest = hashlib.sha256(payload).hexdigest()
        uri = f"artifact://sha256/{digest}"
        chunks = [
            {
                "uri": uri,
                "offset": 0,
                "next_offset": 8,
                "eof": False,
                "data_base64": base64.b64encode(payload[:8]).decode("ascii"),
            },
            {
                "uri": uri,
                "offset": 8,
                "next_offset": len(payload),
                "eof": True,
                "data_base64": base64.b64encode(payload[8:]).decode("ascii"),
            },
        ]

        self.assertEqual(
            reconstruct_artifact(
                chunks,
                expected_uri=uri,
                expected_sha256=digest,
                expected_size=len(payload),
            ),
            payload,
        )

    def test_rejects_non_monotonic_or_non_eof_artifact(self) -> None:
        payload = b"image"
        digest = hashlib.sha256(payload).hexdigest()
        uri = f"artifact://sha256/{digest}"
        invalid_chunks = (
            [
                {
                    "uri": uri,
                    "offset": 1,
                    "next_offset": 6,
                    "eof": True,
                    "data_base64": base64.b64encode(payload).decode("ascii"),
                }
            ],
            [
                {
                    "uri": uri,
                    "offset": 0,
                    "next_offset": 5,
                    "eof": False,
                    "data_base64": base64.b64encode(payload).decode("ascii"),
                }
            ],
        )

        for chunks in invalid_chunks:
            with self.subTest(chunks=chunks):
                with self.assertRaises(VerificationFailure):
                    reconstruct_artifact(chunks, expected_uri=uri)


class DurableArtifactEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name) / "termuinator"
        self.data_root.mkdir(mode=0o700)
        self.owner_scope = "final-verify-owner"
        self.project_id = "final-verify-chromium-deadbeef"
        self.payload = b"\x89PNG\r\n\x1a\nfixture"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.artifact = {
            "uri": f"artifact://sha256/{self.digest}",
            "sha256": self.digest,
            "size_bytes": len(self.payload),
            "mime_type": "image/png",
            "created_at": "2026-08-26T01:02:03+00:00",
            "expires_at": "2026-08-27T01:02:03+00:00",
        }
        namespace = self.data_root / "artifacts" / project_digest(
            self.owner_scope,
            self.project_id,
        )
        namespace.mkdir(parents=True, mode=0o700)
        os.chmod(namespace.parent, 0o700)
        self.data_path = namespace / f"{self.digest}.bin"
        self.metadata_path = namespace / f"{self.digest}.json"
        self.data_path.write_bytes(self.payload)
        self.metadata_path.write_text(
            json.dumps(
                {
                    "format": "termuinator-artifact-metadata-v1",
                    "owner_project_digest": namespace.name,
                    "artifact": self.artifact,
                    "last_accessed_at": "2026-08-26T01:02:04+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(self.data_path, 0o600)
        os.chmod(self.metadata_path, 0o600)

    def test_validates_exact_namespace_hash_metadata_and_private_modes(self) -> None:
        summary = validate_artifact_store(
            self.data_root,
            owner_scope=self.owner_scope,
            project_id=self.project_id,
            artifact=self.artifact,
            reconstructed=self.payload,
        )

        self.assertEqual(summary["sha256"], self.digest)
        self.assertEqual(summary["size_bytes"], len(self.payload))
        self.assertEqual(summary["data_mode"], "0600")
        self.assertEqual(summary["metadata_mode"], "0600")
        self.assertTrue(summary["png_signature"])

    def test_rejects_non_private_store_file(self) -> None:
        os.chmod(self.data_path, 0o644)

        with self.assertRaisesRegex(
            VerificationFailure,
            "artifact data must be a mode 0600 regular file",
        ):
            validate_artifact_store(
                self.data_root,
                owner_scope=self.owner_scope,
                project_id=self.project_id,
                artifact=self.artifact,
                reconstructed=self.payload,
            )


class InstalledWheelProvenanceTests(unittest.TestCase):
    def _source_binding_fixture(self, root: Path) -> tuple[Path, Path]:
        project = root / "project"
        project.mkdir()
        project.joinpath("src", "package").mkdir(parents=True)
        project.joinpath("cli.py").write_text(
            "def main():\n    return 0\n",
            encoding="utf-8",
        )
        project.joinpath("src", "package", "__init__.py").write_text(
            'VALUE = "checkout"\n',
            encoding="utf-8",
        )
        project.joinpath("README.md").write_text(
            "# Release candidate\n",
            encoding="utf-8",
        )
        project.joinpath("LICENSE").write_text("license\n", encoding="utf-8")
        project.joinpath("NOTICE.md").write_text("notice\n", encoding="utf-8")
        subprocess.run(
            ["git", "init", "-q"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "add",
                "cli.py",
                "src/package/__init__.py",
                "README.md",
                "LICENSE",
                "NOTICE.md",
            ],
            cwd=project,
            check=True,
            capture_output=True,
        )
        return project, root / "candidate.whl"

    def _write_source_binding_wheel(
        self,
        wheel: Path,
        project: Path,
        *,
        package_source: bytes | None = None,
        extra_member: tuple[str, bytes] | None = None,
        metadata_version: str = "0.1.0a1",
        license_bytes: bytes | None = None,
        tamper_record: bool = False,
    ) -> None:
        prefix = "termux_browser_pilot-0.1.0a1.dist-info"
        source = (
            project.joinpath("src", "package", "__init__.py").read_bytes()
            if package_source is None
            else package_source
        )
        metadata = (
            "Metadata-Version: 2.4\n"
            "Name: termux-browser-pilot\n"
            f"Version: {metadata_version}\n"
            "Summary: AI-first Firefox and Chromium browser runtime for "
            "Termux/Android.\n"
            "Author: Termux Browser Pilot Contributors\n"
            "License-Expression: MIT\n"
            "Project-URL: Homepage, https://github.com/Chiriri722/Termu-inator\n"
            "Project-URL: Repository, https://github.com/Chiriri722/Termu-inator\n"
            "Project-URL: Upstream, "
            "https://github.com/salviz/termux-browser-pilot\n"
            "Keywords: browser,automation,termux,android,agent,mcp\n"
            "Classifier: Development Status :: 3 - Alpha\n"
            "Classifier: Environment :: Console\n"
            "Classifier: Intended Audience :: Developers\n"
            "Classifier: Operating System :: POSIX :: Linux\n"
            "Classifier: Programming Language :: Python :: 3\n"
            "Classifier: Topic :: Internet :: WWW/HTTP :: Browsers\n"
            "Classifier: Topic :: Software Development :: Testing\n"
            "Requires-Python: >=3.10\n"
            "Description-Content-Type: text/markdown\n"
            "License-File: LICENSE\n"
            "License-File: NOTICE.md\n"
            "Requires-Dist: websockets<18,>=13\n"
            "Provides-Extra: mcp\n"
            'Requires-Dist: mcp==1.29.0; extra == "mcp"\n'
            "Dynamic: license-file\n"
            "\n"
        ).encode("utf-8") + project.joinpath("README.md").read_bytes()
        members = {
            "cli.py": project.joinpath("cli.py").read_bytes(),
            "src/package/__init__.py": source,
            f"{prefix}/METADATA": metadata,
            f"{prefix}/WHEEL": (
                b"Wheel-Version: 1.0\n"
                b"Generator: setuptools (84.0.0)\n"
                b"Root-Is-Purelib: true\n"
                b"Tag: py3-none-any\n"
                b"\n"
            ),
            f"{prefix}/entry_points.txt": (
                b"[console_scripts]\n"
                b"tbp = cli:main\n"
                b"tbp-control = src.termuinator.host_control_cli:main\n"
                b"tbp-mcp = src.mcp_entrypoint:main\n"
                b"tbp-mcp-v1 = src.mcp_entrypoint:main_v1\n"
            ),
            f"{prefix}/top_level.txt": b"cli\nsrc\n",
            f"{prefix}/licenses/LICENSE": (
                project.joinpath("LICENSE").read_bytes()
                if license_bytes is None
                else license_bytes
            ),
            f"{prefix}/licenses/NOTICE.md": project.joinpath(
                "NOTICE.md"
            ).read_bytes(),
        }
        if extra_member is not None:
            members[extra_member[0]] = extra_member[1]
        record_name = f"{prefix}/RECORD"
        record_lines = []
        for index, (name, data) in enumerate(members.items()):
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            digest_text = digest.rstrip(b"=").decode("ascii")
            if tamper_record and index == 0:
                digest_text = "A" * len(digest_text)
            record_lines.append(f"{name},sha256={digest_text},{len(data)}")
        record_lines.append(f"{record_name},,")
        members[record_name] = ("\n".join(record_lines) + "\n").encode("utf-8")
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def test_binds_wheel_python_sources_and_entrypoints_to_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project, wheel = self._source_binding_fixture(Path(temp_dir))
            self._write_source_binding_wheel(wheel, project)

            summary = validate_wheel_source_binding(wheel, project)

        self.assertEqual(summary["source_files_verified"], 2)
        self.assertRegex(summary["source_tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(summary["wheel_entrypoints_verified"])
        self.assertTrue(summary["wheel_metadata_verified"])
        self.assertTrue(summary["wheel_record_verified"])
        self.assertTrue(summary["wheel_license_files_verified"])
        self.assertNotIn("entrypoints_verified", summary)

    def test_rejects_tampered_source_or_executable_wheel_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project, wheel = self._source_binding_fixture(Path(temp_dir))
            invalid_variants = (
                {"package_source": b'VALUE = "tampered"\n'},
                {"extra_member": ("payload.pth", b"import payload\n")},
            )
            for variant in invalid_variants:
                with self.subTest(variant=variant):
                    self._write_source_binding_wheel(
                        wheel,
                        project,
                        **variant,
                    )
                    with self.assertRaises(VerificationFailure):
                        validate_wheel_source_binding(wheel, project)

    def test_rejects_tampered_metadata_license_or_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project, wheel = self._source_binding_fixture(Path(temp_dir))
            invalid_variants = (
                {"metadata_version": "9.9.9"},
                {"license_bytes": b"different license\n"},
                {"tamper_record": True},
            )
            for variant in invalid_variants:
                with self.subTest(variant=variant):
                    self._write_source_binding_wheel(wheel, project, **variant)
                    with self.assertRaises(VerificationFailure):
                        validate_wheel_source_binding(wheel, project)

    def test_rejects_tampered_installed_source_or_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, _wheel = self._source_binding_fixture(root)
            installed = root / "installed"
            installed.joinpath("src", "package").mkdir(parents=True)
            installed.joinpath("cli.py").write_bytes(
                project.joinpath("cli.py").read_bytes()
            )
            installed.joinpath("src", "package", "__init__.py").write_bytes(
                project.joinpath("src", "package", "__init__.py").read_bytes()
            )
            entrypoints = {
                "tbp": "cli:main",
                "tbp-control": "src.termuinator.host_control_cli:main",
                "tbp-mcp": "src.mcp_entrypoint:main",
                "tbp-mcp-v1": "src.mcp_entrypoint:main_v1",
            }

            summary = validate_installed_source_binding(
                project,
                installed_roots=(installed,),
                entrypoints=entrypoints,
            )
            self.assertEqual(summary["installed_source_files_verified"], 2)

            installed.joinpath("src", "package", "__init__.py").write_text(
                'VALUE = "tampered"\n',
                encoding="utf-8",
            )
            with self.assertRaises(VerificationFailure):
                validate_installed_source_binding(
                    project,
                    installed_roots=(installed,),
                    entrypoints=entrypoints,
                )

            installed.joinpath("src", "package", "__init__.py").write_bytes(
                project.joinpath("src", "package", "__init__.py").read_bytes()
            )
            with self.assertRaises(VerificationFailure):
                validate_installed_source_binding(
                    project,
                    installed_roots=(installed,),
                    entrypoints={**entrypoints, "tbp": "payload:main"},
                )

    def test_runtime_platform_summary_does_not_mislabel_kernel_as_android(self) -> None:
        summary = runtime_platform_summary()

        self.assertEqual(summary["python"], platform.python_version())
        self.assertEqual(summary["kernel_release"], platform.release())
        self.assertNotIn("android_release", summary)

    def test_accepts_modern_and_legacy_termux_runtime_identities(self) -> None:
        valid_identities = (
            ("android", "Android"),
            ("linux", "Linux"),
        )
        for python_platform, system_name in valid_identities:
            with self.subTest(
                python_platform=python_platform,
                system_name=system_name,
            ):
                summary = validate_android_termux_identity(
                    python_platform=python_platform,
                    system_name=system_name,
                    android_root="/system",
                )

                self.assertEqual(summary["python_sys_platform"], python_platform)
                self.assertEqual(summary["platform_system"], system_name)
                self.assertTrue(summary["android_runtime_verified"])

    def test_rejects_partial_or_incoherent_termux_runtime_identities(self) -> None:
        invalid_identities = (
            ("darwin", "Darwin", "/system"),
            ("android", "Android", None),
            ("linux", "Linux", "relative/system"),
            ("android", "Linux", "/system"),
            ("linux", "Android", "/system"),
            ("android", "Android", "/"),
            ("android", "Android", "/system/../system"),
        )
        for python_platform, system_name, android_root in invalid_identities:
            with self.subTest(
                python_platform=python_platform,
                system_name=system_name,
                android_root=android_root,
            ):
                with self.assertRaisesRegex(
                    VerificationFailure,
                    "final verifier must run on Android/Termux",
                ):
                    validate_android_termux_identity(
                        python_platform=python_platform,
                        system_name=system_name,
                        android_root=android_root,
                    )

    def test_runtime_distribution_is_selected_only_from_explicit_venv_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            site = root / "venv-site"
            checkout = root / "checkout"
            site.mkdir()
            checkout.mkdir()
            installed = site / "termux_browser_pilot-1.2.3.dist-info"
            source = checkout / "termux_browser_pilot.egg-info"
            installed.mkdir()
            source.mkdir()
            installed.joinpath("METADATA").write_text(
                "Metadata-Version: 2.1\nName: termux-browser-pilot\nVersion: 1.2.3\n\n",
                encoding="utf-8",
            )
            source.joinpath("PKG-INFO").write_text(
                "Metadata-Version: 2.1\nName: termux-browser-pilot\nVersion: 9.9.9\n\n",
                encoding="utf-8",
            )

            distribution = _runtime_distribution(
                "termux-browser-pilot",
                search_paths=(site,),
            )

            self.assertEqual(distribution.version, "1.2.3")

    def test_matches_preserved_wheel_bytes_to_pip_direct_url_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = Path(temp_dir) / "termux_browser_pilot.whl"
            wheel.write_bytes(b"release-candidate-wheel")
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            direct_url = json.dumps(
                {
                    "archive_info": {
                        "hash": f"sha256={digest}",
                        "hashes": {"sha256": digest},
                    },
                    "url": wheel.as_uri(),
                }
            )

            summary = validate_wheel_provenance(
                direct_url,
                expected_sha256=digest,
                wheel_path=wheel,
            )

        self.assertEqual(summary["wheel_sha256"], digest)
        self.assertEqual(summary["install_kind"], "local-wheel")

    def test_rejects_editable_or_hash_mismatched_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = Path(temp_dir) / "candidate.whl"
            wheel.write_bytes(b"wheel")
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            invalid = (
                json.dumps(
                    {
                        "dir_info": {"editable": True},
                        "url": Path(temp_dir).as_uri(),
                    }
                ),
                json.dumps(
                    {
                        "archive_info": {
                            "hashes": {"sha256": "0" * 64},
                        },
                        "url": wheel.as_uri(),
                    }
                ),
            )
            for direct_url in invalid:
                with self.subTest(direct_url=direct_url):
                    with self.assertRaises(VerificationFailure):
                        validate_wheel_provenance(
                            direct_url,
                            expected_sha256=digest,
                            wheel_path=wheel,
                        )


class ReleasedSessionLockEvidenceTests(unittest.TestCase):
    def _create_released_lock(self, lock_path: Path, owner_scope: str) -> None:
        project_root = Path(__file__).resolve().parents[1]
        code = "\n".join(
            (
                "from pathlib import Path",
                "from src.termuinator.core.sessions import ProcessSessionLock",
                "lock = ProcessSessionLock(",
                f"    lock_path=Path({str(lock_path)!r}),",
                f"    owner_scope={owner_scope!r},",
                ")",
                "lock.acquire()",
                "lock.release()",
            )
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_accepts_owner_bound_released_persistent_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "runtime" / "session.lock"
            owner_scope = "final-verify-deadbeef1234"
            self._create_released_lock(lock_path, owner_scope)
            validator = getattr(
                final_verify_module,
                "validate_released_session_lock",
                None,
            )

            self.assertTrue(callable(validator))
            assert callable(validator)
            summary = validator(lock_path, owner_scope=owner_scope)

            self.assertEqual(
                summary,
                {
                    "session_lock_path_safe": True,
                    "session_lock_owner_safe": True,
                    "session_lock_pid_inactive": True,
                    "session_lock_lease_available": True,
                },
            )
            self.assertTrue(lock_path.exists())

    def test_rejects_live_session_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "runtime" / "session.lock"
            owner_scope = "final-verify-deadbeef1234"
            lock = ProcessSessionLock(
                lock_path=lock_path,
                owner_scope=owner_scope,
            )
            lock.acquire()
            try:
                validator = final_verify_module.validate_released_session_lock
                summary = validator(lock_path, owner_scope=owner_scope)
            finally:
                lock.release()

            self.assertEqual(
                summary,
                {
                    "session_lock_path_safe": True,
                    "session_lock_owner_safe": False,
                    "session_lock_pid_inactive": False,
                    "session_lock_lease_available": False,
                },
            )

    def test_rejects_wrong_owner_or_non_private_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "runtime" / "session.lock"
            owner_scope = "final-verify-deadbeef1234"
            self._create_released_lock(lock_path, owner_scope)
            validator = final_verify_module.validate_released_session_lock

            wrong_owner = validator(
                lock_path,
                owner_scope="final-verify-cafebabefeed",
            )
            self.assertFalse(wrong_owner["session_lock_owner_safe"])

            lock_path.chmod(0o644)
            non_private = validator(lock_path, owner_scope=owner_scope)
            self.assertFalse(non_private["session_lock_path_safe"])

    def test_rejects_symlinked_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_lock = root / "real-runtime" / "session.lock"
            owner_scope = "final-verify-deadbeef1234"
            self._create_released_lock(real_lock, owner_scope)
            linked_runtime = root / "linked-runtime"
            linked_runtime.symlink_to(real_lock.parent, target_is_directory=True)

            summary = final_verify_module.validate_released_session_lock(
                linked_runtime / "session.lock",
                owner_scope=owner_scope,
            )

            self.assertFalse(summary["session_lock_path_safe"])

    def test_rejects_path_created_after_open_reports_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "runtime" / "session.lock"
            owner_scope = "final-verify-deadbeef1234"
            self._create_released_lock(lock_path, owner_scope)

            with patch.object(
                final_verify_module.os,
                "open",
                side_effect=FileNotFoundError,
            ):
                summary = final_verify_module.validate_released_session_lock(
                    lock_path,
                    owner_scope=owner_scope,
                )

            self.assertFalse(any(summary.values()))

    def test_cleanup_accepts_absent_or_released_persistent_lock(self) -> None:
        parameters = inspect.signature(
            final_verify_module._cleanup_summary
        ).parameters
        self.assertIn("owner_scope", parameters)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            temporary_root = root / "tmp"
            runtime_root = data_root / "runtime"
            runtime_root.mkdir(parents=True, mode=0o700)
            temporary_root.mkdir(mode=0o700)
            owner_scope = "final-verify-deadbeef1234"

            absent = final_verify_module._cleanup_summary(
                data_root,
                temporary_root,
                owner_scope=owner_scope,
            )
            self.assertNotIn("session_lock_absent", absent)
            self.assertTrue(all(absent.values()))

            lock_path = runtime_root / "session.lock"
            self._create_released_lock(lock_path, owner_scope)
            released = final_verify_module._cleanup_summary(
                data_root,
                temporary_root,
                owner_scope=owner_scope,
            )
            self.assertTrue(all(released.values()))
            self.assertTrue(lock_path.exists())


class ChildEnvironmentIsolationTests(unittest.TestCase):
    def test_verifier_tests_do_not_force_posix_root_tmp(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        offenders: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and function.attr == "TemporaryDirectory"
            ):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "dir"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "/tmp"
                ):
                    offenders.append(node.lineno)

        self.assertEqual(
            offenders,
            [],
            f"verifier tests force unwritable root /tmp at lines {offenders}",
        )

    def test_isolates_home_alongside_xdg_and_tmp_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)

            with patch.dict(os.environ, {"TBP_SINGLE_PROCESS": "1"}):
                environ, paths = _child_environment(
                    output,
                    owner_scope="final-verify-owner",
                )

            self.assertEqual(paths["home"], output / "h")
            self.assertEqual(paths["xdg_data"], output / "d")
            self.assertEqual(environ["HOME"], str(output / "h"))
            self.assertEqual(paths["home"].stat().st_mode & 0o777, 0o700)
            self.assertFalse((paths["home"] / ".tbp").exists())
            self.assertNotIn("TBP_SINGLE_PROCESS", environ)
            control_socket = (
                paths["xdg_data"] / "termuinator" / "runtime" / "control.sock"
            )
            self.assertLessEqual(len(os.fsencode(control_socket)), 100)

    def test_rejects_output_path_that_cannot_fit_private_control_socket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / ("x" * 80)
            output.mkdir(mode=0o700)

            with self.assertRaisesRegex(
                VerificationFailure,
                "output path is too long",
            ):
                _child_environment(output, owner_scope="final-verify-owner")

    def test_process_survivor_filter_covers_optional_browser_helpers(self) -> None:
        self.assertTrue(
            {"virgl_test_server_android", "xclip", "xdotool"}.issubset(
                _PROCESS_TERMS
            )
        )


class McpInventoryEvidenceTests(unittest.TestCase):
    def test_requires_exact_ordered_profile_surface(self) -> None:
        expected = ("browser_session_start", "browser_session_stop")
        summary = validate_tool_inventory(expected, expected, profile="interactive")

        self.assertEqual(summary, {"profile": "interactive", "tool_count": 2})
        for actual in (
            tuple(reversed(expected)),
            expected + ("browser_eval",),
            expected[:1],
        ):
            with self.subTest(actual=actual):
                with self.assertRaises(VerificationFailure):
                    validate_tool_inventory(actual, expected, profile="interactive")


class FinalVerifyCliContractTests(unittest.TestCase):
    def test_requires_commit_wheel_hash_and_installed_entrypoints(self) -> None:
        parser = build_parser()
        arguments = parser.parse_args(
            [
                "--project-root",
                "/tmp/Termu-inator",
                "--mcp-command",
                "/tmp/venv/bin/tbp-mcp-v1",
                "--control-command",
                "/tmp/venv/bin/tbp-control",
                "--wheel",
                "/tmp/candidate.whl",
                "--expected-commit",
                "a" * 40,
                "--expected-wheel-sha256",
                "b" * 64,
                "--output",
                "/tmp/final-verify",
            ]
        )

        self.assertEqual(arguments.expected_commit, "a" * 40)
        self.assertEqual(arguments.expected_wheel_sha256, "b" * 64)
        self.assertNotIn("--backend", parser.format_help())

    def test_manifest_writer_is_private_canonical_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "manifest.json"
            write_private_json(destination, {"status": "PASS", "count": 2})

            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                '{"count":2,"status":"PASS"}\n',
            )
            with self.assertRaises(VerificationFailure):
                write_private_json(destination, {"status": "FAIL"})


class BackendReleaseFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_full_observer_artifact_status_and_clean_stop_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "termuinator"
            data_root.mkdir(mode=0o700)
            output = root / "output"
            output.mkdir(mode=0o700)
            owner_scope = "final-verify-owner"
            project_id = "final-verify-chromium-deadbeef"
            fixture_origin = "http://127.0.0.1:43123"
            fixture_url = fixture_origin + "/forms"
            png = b"\x89PNG\r\n\x1a\nfixture"
            digest = hashlib.sha256(png).hexdigest()
            uri = f"artifact://sha256/{digest}"
            artifact = {
                "uri": uri,
                "sha256": digest,
                "size_bytes": len(png),
                "mime_type": "image/png",
                "created_at": "2026-08-26T01:02:03+00:00",
                "expires_at": "2026-08-27T01:02:03+00:00",
            }
            state_root = data_root / "state"
            namespace = state_root / "artifacts" / project_digest(
                owner_scope,
                project_id,
            )
            namespace.mkdir(parents=True, mode=0o700)
            os.chmod(state_root, 0o700)
            os.chmod(namespace.parent, 0o700)
            data_path = namespace / f"{digest}.bin"
            metadata_path = namespace / f"{digest}.json"
            data_path.write_bytes(png)
            metadata_path.write_text(
                json.dumps(
                    {
                        "format": "termuinator-artifact-metadata-v1",
                        "owner_project_digest": namespace.name,
                        "artifact": artifact,
                        "last_accessed_at": "2026-08-26T01:02:04+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(data_path, 0o600)
            os.chmod(metadata_path, 0o600)
            observation = _observation()
            observation["screenshot_artifact_uri"] = uri

            class Caller:
                def __init__(self) -> None:
                    self.calls: list[tuple[str, dict[str, object]]] = []

                async def __call__(
                    self,
                    name: str,
                    arguments: dict[str, object],
                ) -> dict[str, object]:
                    self.calls.append((name, arguments))
                    status = {
                        "session_id": "session_abcdefgh",
                        "state": "active",
                        "backend": "chromium",
                        "running": True,
                        "active_page_id": "page_abcdefgh",
                        "active_tab_id": "tab_abcdefgh",
                        "page_revision": "epoch:1",
                        "url": fixture_url,
                        "title": "Forms",
                        "ready_state": "complete",
                        "freshness_ms": 0,
                        "capabilities": {
                            "backend": "chromium",
                            "revision": "legacy-v1",
                            "browser_version": "149",
                            "transport_version": "cdp",
                            "capabilities": [],
                        },
                    }
                    if name == "browser_session_start":
                        return {
                            "session_id": "session_abcdefgh",
                            "capabilities": status["capabilities"],
                            "status": status,
                        }
                    if name in {"browser_navigate", "browser_observe"}:
                        return dict(observation)
                    if name == "browser_screenshot":
                        return artifact
                    if name == "browser_artifact_read":
                        return {
                            "uri": uri,
                            "offset": 0,
                            "next_offset": len(png),
                            "eof": True,
                            "data_base64": base64.b64encode(png).decode("ascii"),
                        }
                    if name == "browser_session_status":
                        return status
                    if name == "browser_session_stop":
                        return {
                            "session_id": "session_abcdefgh",
                            "state": "stopped",
                            "stopped_at": "2026-08-26T01:02:05+00:00",
                        }
                    raise AssertionError(name)

            grants: list[tuple[str, str]] = []

            async def grant(session_id: str, origin: str) -> None:
                grants.append((session_id, origin))

            caller = Caller()
            result = await verify_backend(
                caller,
                grant_permission=grant,
                backend="chromium",
                fixture_origin=fixture_origin,
                fixture_url=fixture_url,
                data_root=data_root,
                owner_scope=owner_scope,
                project_id=project_id,
                output_dir=output,
            )

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(grants, [("session_abcdefgh", fixture_origin)])
            self.assertEqual(
                [name for name, _arguments in caller.calls],
                [
                    "browser_session_start",
                    "browser_navigate",
                    "browser_observe",
                    "browser_screenshot",
                    "browser_artifact_read",
                    "browser_session_status",
                    "browser_session_stop",
                ],
            )
            observe_arguments = caller.calls[2][1]
            self.assertIs(observe_arguments["include_accessibility"], True)
            self.assertIs(observe_arguments["include_screenshot"], True)
            self.assertEqual(observe_arguments["text_limit"], 4096)
            screenshot = output / "chromium.png"
            self.assertEqual(screenshot.read_bytes(), png)
            self.assertEqual(screenshot.stat().st_mode & 0o777, 0o600)

    async def test_stops_session_when_observation_fails(self) -> None:
        calls: list[str] = []

        async def caller(
            name: str,
            arguments: dict[str, object],
        ) -> dict[str, object]:
            calls.append(name)
            if name == "browser_session_start":
                return {
                    "session_id": "session_abcdefgh",
                    "capabilities": {},
                    "status": {
                        "session_id": "session_abcdefgh",
                        "backend": "firefox",
                        "active_page_id": "page_abcdefgh",
                        "active_tab_id": "tab_abcdefgh",
                        "page_revision": "epoch:1",
                    },
                }
            if name == "browser_navigate":
                return _observation()
            if name == "browser_observe":
                raise VerificationFailure("observe failed")
            if name == "browser_session_stop":
                return {
                    "session_id": "session_abcdefgh",
                    "state": "stopped",
                    "stopped_at": "2026-08-26T01:02:05+00:00",
                }
            raise AssertionError(name)

        async def grant(_session_id: str, _origin: str) -> None:
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "termuinator"
            data_root.mkdir(mode=0o700)
            output = root / "output"
            output.mkdir(mode=0o700)
            with self.assertRaisesRegex(VerificationFailure, "observe failed"):
                await verify_backend(
                    caller,
                    grant_permission=grant,
                    backend="firefox",
                    fixture_origin="http://127.0.0.1:43123",
                    fixture_url="http://127.0.0.1:43123/forms",
                    data_root=data_root,
                    owner_scope="final-verify-owner",
                    project_id="final-verify-firefox-deadbeef",
                    output_dir=output,
                )

        self.assertEqual(calls[-1], "browser_session_stop")


if __name__ == "__main__":
    unittest.main()
