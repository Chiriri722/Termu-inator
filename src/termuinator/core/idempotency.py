"""Crash-safe idempotency journal for browser actions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterator, Mapping

from ..contracts import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ErrorCode,
    PageRevision,
    Verification,
    to_wire,
)
from ..errors import TermuinatorError


_FORMAT = "termuinator-action-journal-v1"
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ARTIFACT_URI = re.compile(r"^artifact://sha256/[0-9a-f]{64}$")


class JournalState(str, Enum):
    """Persisted action states; terminal payloads are replayable."""

    RESERVED = "reserved"
    WAITING_CONFIRMATION = "waiting_confirmation"
    DISPATCHED = "dispatched"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class JournalClaim:
    state: JournalState
    result: ActionResult | None = None

    def __post_init__(self) -> None:
        if (self.state is JournalState.TERMINAL) != (self.result is not None):
            raise ValueError("only terminal journal claims contain a result")


def canonical_action_digest(request: ActionRequest) -> str:
    """Hash effect-bearing fields, excluding retry and approval handles."""

    if not isinstance(request, ActionRequest):
        raise TypeError("request must be an ActionRequest")
    payload = {
        "contract": "termuinator-action-v1",
        "session_id": request.session_id,
        "tab_id": request.tab_id,
        "page_id": request.page_id,
        "expected_page_revision": str(request.expected_page_revision),
        "kind": request.kind.value,
        "target_ref": request.target_ref,
        "parameters": to_wire(request.parameters),
        "timeout_ms": request.timeout_ms,
        "risk": request.risk.value,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(b"termuinator-action-digest-v1\x00" + encoded).hexdigest()


class DurableActionJournal:
    """Store one action state machine per owner/project/key on private disk."""

    def __init__(self, *, root: Path, owner_scope: str, project_id: str) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("journal root must be an absolute Path")
        if not isinstance(owner_scope, str) or not owner_scope.strip():
            raise ValueError("owner_scope must be a non-empty string")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        self._root = root
        scope_material = (
            b"termuinator-action-owner-v1\x00"
            + owner_scope.encode("utf-8")
            + b"\x00"
            + project_id.encode("utf-8")
        )
        self._scope_digest = hashlib.sha256(scope_material).hexdigest()

    def reserve(self, request: ActionRequest) -> JournalClaim:
        digest = canonical_action_digest(request)
        with self._locked_record(request.idempotency_key) as (path, key_digest):
            record = self._read_record(path)
            if record is None:
                self._write_record(
                    path,
                    self._new_record(
                        key_digest=key_digest,
                        action_digest=digest,
                    ),
                )
                return JournalClaim(JournalState.RESERVED)

            state = self._matching_state(
                record,
                key_digest=key_digest,
                action_digest=digest,
            )
            if state is JournalState.DISPATCHED:
                raise TermuinatorError(
                    ErrorCode.OUTCOME_UNKNOWN,
                    "The action may have been dispatched before interruption",
                )
            if state is JournalState.TERMINAL:
                return JournalClaim(
                    state,
                    self._decode_action_result(record["result"]),
                )
            return JournalClaim(state)

    def mark_waiting_confirmation(self, request: ActionRequest) -> JournalClaim:
        return self._transition(
            request,
            allowed=(JournalState.RESERVED,),
            destination=JournalState.WAITING_CONFIRMATION,
            idempotent=(JournalState.WAITING_CONFIRMATION,),
        )

    def mark_dispatched(self, request: ActionRequest) -> JournalClaim:
        return self._transition(
            request,
            allowed=(JournalState.RESERVED, JournalState.WAITING_CONFIRMATION),
            destination=JournalState.DISPATCHED,
        )

    def record_terminal(
        self,
        request: ActionRequest,
        result: ActionResult,
    ) -> JournalClaim:
        if not isinstance(result, ActionResult):
            raise TypeError("result must be an ActionResult")
        digest = canonical_action_digest(request)
        with self._locked_record(request.idempotency_key) as (path, key_digest):
            record = self._required_record(path)
            state = self._matching_state(
                record,
                key_digest=key_digest,
                action_digest=digest,
            )
            if state is not JournalState.DISPATCHED:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "A terminal result requires a dispatched journal record",
                )
            wire_result = to_wire(result)
            self._decode_action_result(wire_result)
            updated = dict(record)
            updated["state"] = JournalState.TERMINAL.value
            updated["result"] = wire_result
            self._write_record(path, updated)
            return JournalClaim(JournalState.TERMINAL, result)

    def _transition(
        self,
        request: ActionRequest,
        *,
        allowed: tuple[JournalState, ...],
        destination: JournalState,
        idempotent: tuple[JournalState, ...] = (),
    ) -> JournalClaim:
        digest = canonical_action_digest(request)
        with self._locked_record(request.idempotency_key) as (path, key_digest):
            record = self._required_record(path)
            state = self._matching_state(
                record,
                key_digest=key_digest,
                action_digest=digest,
            )
            if state in idempotent:
                return JournalClaim(state)
            if state not in allowed:
                if state is JournalState.DISPATCHED:
                    raise TermuinatorError(
                        ErrorCode.OUTCOME_UNKNOWN,
                        "The action is already marked as dispatched",
                    )
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    f"Cannot transition action from {state.value} to {destination.value}",
                )
            updated = dict(record)
            updated["state"] = destination.value
            self._write_record(path, updated)
            return JournalClaim(destination)

    def _matching_state(
        self,
        record: Mapping[str, Any],
        *,
        key_digest: str,
        action_digest: str,
    ) -> JournalState:
        self._validate_record(record)
        if record["scope_digest"] != self._scope_digest:
            raise self._corrupt("Journal owner scope does not match its path")
        if record["key_digest"] != key_digest:
            raise self._corrupt("Journal key does not match its path")
        if record["action_digest"] != action_digest:
            raise TermuinatorError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "The idempotency key is already bound to another action",
            )
        return JournalState(record["state"])

    @staticmethod
    def _new_record(*, key_digest: str, action_digest: str) -> dict[str, Any]:
        return {
            "format": _FORMAT,
            "scope_digest": "",
            "key_digest": key_digest,
            "action_digest": action_digest,
            "state": JournalState.RESERVED.value,
            "result": None,
        }

    def _required_record(self, path: Path) -> Mapping[str, Any]:
        record = self._read_record(path)
        if record is None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "The action has no reserved idempotency record",
            )
        return record

    @contextmanager
    def _locked_record(self, key: str) -> Iterator[tuple[Path, str]]:
        directory = self._ensure_directory()
        key_digest = hashlib.sha256(
            b"termuinator-idempotency-key-v1\x00" + key.encode("utf-8")
        ).hexdigest()
        record_path = directory / f"{key_digest}.json"
        lock_path = directory / f"{key_digest}.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise self._corrupt("Journal lock path is unsafe") from exc
        try:
            self._require_private_regular(fd, "Journal lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise TermuinatorError(
                    ErrorCode.SESSION_BUSY,
                    "Another process is updating this action journal",
                ) from exc
            try:
                yield record_path, key_digest
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _ensure_directory(self) -> Path:
        if self._root.is_symlink() or not self._root.is_dir():
            raise self._corrupt("Journal root must be a real directory")
        parent = self._root / "idempotency"
        directory = parent / self._scope_digest
        for item in (parent, directory):
            try:
                if item.is_symlink():
                    raise self._corrupt(
                        "Journal directories cannot be symbolic links"
                    )
                item.mkdir(mode=0o700, exist_ok=True)
                info = item.lstat()
            except TermuinatorError:
                raise
            except OSError as exc:
                raise self._corrupt("Journal directory path is unsafe") from exc
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                raise self._corrupt("Journal directories must be private mode 0700")
        return directory

    def _read_record(self, path: Path) -> Mapping[str, Any] | None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise self._corrupt("Journal record path is unsafe") from exc
        try:
            self._require_private_regular(fd, "Journal record")
            size = os.fstat(fd).st_size
            if not 1 <= size <= _MAX_RECORD_BYTES:
                raise self._corrupt("Journal record size is invalid")
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                chunk = os.read(fd, min(remaining, 65_536))
                if not chunk:
                    raise self._corrupt("Journal record was truncated while reading")
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)
        try:
            parsed = json.loads(
                b"".join(chunks).decode("utf-8"),
                parse_constant=self._reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise self._corrupt("Journal record is not valid closed JSON") from exc
        if not isinstance(parsed, Mapping):
            raise self._corrupt("Journal record root must be an object")
        self._validate_record(parsed)
        return parsed

    def _write_record(self, path: Path, record: Mapping[str, Any]) -> None:
        normalized = dict(record)
        normalized["scope_digest"] = self._scope_digest
        self._validate_record(normalized)
        payload = (
            json.dumps(
                normalized,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) > _MAX_RECORD_BYTES:
            raise self._corrupt("Journal record exceeds the size limit")
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise self._corrupt("Journal record path is unsafe")

        temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        try:
            fd = os.open(temporary, flags, 0o600)
            self._require_private_regular(fd, "Temporary journal record")
            written = 0
            while written < len(payload):
                count = os.write(fd, payload[written:])
                if count <= 0:
                    raise OSError("short journal write")
                written += count
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(temporary, path)
            directory_fd = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except TermuinatorError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise self._corrupt("Journal record could not be published atomically") from exc
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _require_private_regular(fd: int, label: str) -> None:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                f"{label} must be a private mode 0600 regular file",
            )

    def _validate_record(self, record: Mapping[str, Any]) -> None:
        expected = {
            "format",
            "scope_digest",
            "key_digest",
            "action_digest",
            "state",
            "result",
        }
        if set(record) != expected or record.get("format") != _FORMAT:
            raise self._corrupt("Journal record fields or format are invalid")
        for name in ("scope_digest", "key_digest", "action_digest"):
            if not isinstance(record[name], str) or not _HEX_DIGEST.fullmatch(
                record[name]
            ):
                raise self._corrupt(f"Journal {name} is invalid")
        try:
            state = JournalState(record["state"])
        except (TypeError, ValueError) as exc:
            raise self._corrupt("Journal state is invalid") from exc
        result = record["result"]
        if state is JournalState.TERMINAL:
            self._decode_action_result(result)
        elif result is not None:
            raise self._corrupt("A nonterminal journal record cannot contain a result")

    def _decode_action_result(self, value: Any) -> ActionResult:
        expected = {
            "status",
            "before_revision",
            "after_revision",
            "executed_method",
            "verification",
            "changed_url",
            "changed_elements",
            "download",
            "artifact_uri",
            "diagnostics_id",
            "revalidated",
        }
        data = self._closed_object(value, expected, "terminal action result")
        verifications = data["verification"]
        changed_elements = data["changed_elements"]
        if not isinstance(verifications, list) or not isinstance(changed_elements, list):
            raise self._corrupt("Terminal action result arrays are invalid")
        if not isinstance(data["revalidated"], bool):
            raise self._corrupt("Terminal action revalidated flag is invalid")
        try:
            return ActionResult(
                status=ActionStatus(data["status"]),
                before_revision=PageRevision.parse(data["before_revision"]),
                after_revision=PageRevision.parse(data["after_revision"]),
                executed_method=self._required_string(data["executed_method"]),
                verification=tuple(
                    self._decode_verification(item) for item in verifications
                ),
                changed_url=self._optional_string(data["changed_url"]),
                changed_elements=tuple(changed_elements),
                download=self._decode_download(data["download"]),
                artifact_uri=self._optional_string(data["artifact_uri"]),
                diagnostics_id=self._optional_string(data["diagnostics_id"]),
                revalidated=data["revalidated"],
            )
        except (TypeError, ValueError) as exc:
            raise self._corrupt("Terminal action result violates its contract") from exc

    def _decode_verification(self, value: Any) -> Verification:
        expected = {
            "verification_id",
            "action_id",
            "kind",
            "target_ref",
            "passed",
            "causal",
            "expected_summary",
            "actual_summary",
            "observed_revision",
            "observed_at",
        }
        data = self._closed_object(value, expected, "verification")
        if not isinstance(data["passed"], bool) or not isinstance(data["causal"], bool):
            raise self._corrupt("Verification flags are invalid")
        try:
            return Verification(
                verification_id=self._required_string(data["verification_id"]),
                action_id=self._required_string(data["action_id"]),
                kind=self._required_string(data["kind"]),
                target_ref=self._optional_string(data["target_ref"]),
                passed=data["passed"],
                causal=data["causal"],
                expected_summary=self._required_string(data["expected_summary"]),
                actual_summary=self._required_string(data["actual_summary"]),
                observed_revision=PageRevision.parse(data["observed_revision"]),
                observed_at=self._required_string(data["observed_at"]),
            )
        except (TypeError, ValueError) as exc:
            raise self._corrupt("Verification violates its contract") from exc

    def _decode_download(self, value: Any) -> Mapping[str, Any] | None:
        if value is None:
            return None
        expected = {
            "download_id",
            "state",
            "filename",
            "mime_type",
            "size_bytes",
            "artifact_uri",
            "reason_code",
        }
        data = self._closed_object(value, expected, "download")
        download_id = data["download_id"]
        state_value = data["state"]
        filename = data["filename"]
        mime_type = data["mime_type"]
        size_bytes = data["size_bytes"]
        artifact_uri = data["artifact_uri"]
        reason_code = data["reason_code"]
        if not isinstance(download_id, str) or not _ID.fullmatch(download_id):
            raise self._corrupt("Download identifier is invalid")
        if state_value not in {
            "started",
            "in_progress",
            "completed",
            "failed",
            "cancelled",
        }:
            raise self._corrupt("Download state is invalid")
        if not isinstance(filename, str) or len(filename) > 255:
            raise self._corrupt("Download filename is invalid")
        if mime_type is not None and (
            not isinstance(mime_type, str) or len(mime_type) > 255
        ):
            raise self._corrupt("Download MIME type is invalid")
        if size_bytes is not None and (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or not 0 <= size_bytes <= 1_099_511_627_776
        ):
            raise self._corrupt("Download size is invalid")
        if artifact_uri is not None and (
            not isinstance(artifact_uri, str)
            or not _ARTIFACT_URI.fullmatch(artifact_uri)
        ):
            raise self._corrupt("Download artifact URI is invalid")
        if reason_code is not None and (
            not isinstance(reason_code, str) or not _REASON.fullmatch(reason_code)
        ):
            raise self._corrupt("Download reason code is invalid")
        return dict(data)

    @staticmethod
    def _closed_object(
        value: Any,
        expected: set[str],
        label: str,
    ) -> Mapping[str, Any]:
        if not isinstance(value, Mapping) or set(value) != expected:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                f"Stored {label} has unknown or missing fields",
            )
        return value

    @staticmethod
    def _required_string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("expected a string")
        return value

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("expected a string or null")
        return value

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError(f"invalid JSON numeric constant: {value}")

    @staticmethod
    def _corrupt(message: str) -> TermuinatorError:
        return TermuinatorError(ErrorCode.INTERNAL_ERROR, message)


__all__ = [
    "DurableActionJournal",
    "JournalClaim",
    "JournalState",
    "canonical_action_digest",
]
