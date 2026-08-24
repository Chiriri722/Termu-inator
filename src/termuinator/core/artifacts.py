"""Typed artifact storage boundary and deterministic in-memory harness."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Callable, Protocol

from ..contracts import Artifact, ArtifactChunk, ErrorCode
from ..errors import TermuinatorError


class ArtifactStore(Protocol):
    """Project-bound artifact storage interface."""

    def put(self, *, session_id: str, data: bytes, mime_type: str) -> Artifact:
        ...

    def read(
        self,
        *,
        session_id: str,
        uri: str,
        offset: int,
        limit: int,
    ) -> ArtifactChunk:
        ...


@dataclass
class _MemoryArtifact:
    metadata: Artifact
    data: bytes
    expires_at: datetime
    last_accessed_at: datetime


class InMemoryArtifactStore:
    """Deterministic test implementation with production-equivalent bounds."""

    def __init__(
        self,
        *,
        owner_project_digest: str,
        authorize_session: Callable[[str], bool],
        retention_seconds: int,
        quota_bytes: int,
        max_chunk_bytes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", owner_project_digest):
            raise ValueError("owner_project_digest must be a lowercase SHA-256")
        if not 1 <= retention_seconds <= 31 * 86_400:
            raise ValueError("retention_seconds is out of bounds")
        if quota_bytes < 1:
            raise ValueError("quota_bytes must be positive")
        if not 1 <= max_chunk_bytes <= 512 * 1024:
            raise ValueError("max_chunk_bytes must be between 1 and 512 KiB")
        self.owner_project_digest = owner_project_digest
        self._authorize_session = authorize_session
        self._retention_seconds = retention_seconds
        self._quota_bytes = quota_bytes
        self._max_chunk_bytes = max_chunk_bytes
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._entries: dict[str, _MemoryArtifact] = {}

    def put(self, *, session_id: str, data: bytes, mime_type: str) -> Artifact:
        self._authorize(session_id)
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        if not isinstance(mime_type, str) or not 1 <= len(mime_type) <= 255:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact mime_type must contain 1 to 255 characters",
            )
        if len(data) > self._quota_bytes:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact exceeds the project quota",
            )

        now = self._current_time()
        self._remove_expired(now)
        digest = hashlib.sha256(data).hexdigest()
        expires_at = now + timedelta(seconds=self._retention_seconds)
        metadata = Artifact(
            uri=f"artifact://sha256/{digest}",
            sha256=digest,
            size_bytes=len(data),
            mime_type=mime_type,
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        self._entries[digest] = _MemoryArtifact(
            metadata=metadata,
            data=data,
            expires_at=expires_at,
            last_accessed_at=now,
        )
        self._evict_to_quota(exclude_digest=digest)
        return metadata

    def read(
        self,
        *,
        session_id: str,
        uri: str,
        offset: int,
        limit: int,
    ) -> ArtifactChunk:
        self._authorize(session_id)
        digest = self._parse_uri(uri)
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self._max_chunk_bytes
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact offset or limit is out of bounds",
            )

        now = self._current_time()
        self._remove_expired(now)
        entry = self._entries.get(digest)
        if entry is None:
            raise TermuinatorError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                "Artifact was not found or has expired",
            )
        if offset > len(entry.data):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact offset exceeds its size",
            )

        raw = entry.data[offset : offset + limit]
        next_offset = offset + len(raw)
        entry.last_accessed_at = now
        return ArtifactChunk(
            uri=uri,
            offset=offset,
            next_offset=next_offset,
            eof=next_offset >= len(entry.data),
            data_base64=base64.b64encode(raw).decode("ascii"),
        )

    def _authorize(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not self._authorize_session(session_id):
            raise TermuinatorError(
                ErrorCode.OWNERSHIP_DENIED,
                "The active session does not own this artifact namespace",
            )

    @staticmethod
    def _parse_uri(uri: str) -> str:
        prefix = "artifact://sha256/"
        if not isinstance(uri, str) or not re.fullmatch(
            r"artifact://sha256/[0-9a-f]{64}", uri
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact URI must be content-addressed",
            )
        return uri.removeprefix(prefix)

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("artifact clock must return a timezone-aware datetime")
        return value

    def _remove_expired(self, now: datetime) -> None:
        expired = [
            digest
            for digest, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for digest in expired:
            del self._entries[digest]

    def _evict_to_quota(self, *, exclude_digest: str) -> None:
        while sum(len(entry.data) for entry in self._entries.values()) > self._quota_bytes:
            candidates = [
                (entry.last_accessed_at, digest)
                for digest, entry in self._entries.items()
                if digest != exclude_digest
            ]
            if not candidates:
                break
            _, digest = min(candidates)
            del self._entries[digest]


__all__ = ["ArtifactStore", "InMemoryArtifactStore"]
