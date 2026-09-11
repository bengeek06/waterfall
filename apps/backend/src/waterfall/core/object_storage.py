"""S3-compatible object storage client for uploaded import sources.

Backed by Garage in dev/prod (see infra/docker/garage/) and by moto's in-memory S3
in the test suite. Lives in `core/` rather than `services/`: like config, logging and
security, this is infrastructure plumbing, not business logic.

Every botocore failure is translated into one of the two exceptions below, so callers
never have to know about `ClientError`/`BotoCoreError` -- and, more importantly, so an
unreachable store surfaces as a deliberate HTTP status (503) instead of leaking as an
unhandled 500.
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from waterfall.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover - typing-only import (boto3-stubs is a dev dep)
    from mypy_boto3_s3.client import S3Client

# Never let an unreachable store hang a request: a stuck upload would also hold the
# project row lock in imports.upload_xml's final copy step.
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 3

# The one code that means "this object is gone", and nothing else. `NoSuchBucket` is
# deliberately *not* here: a missing bucket is not a missing object, it is infrastructure
# that is not in the expected state (a half-finished garage-init, a wiped volume), so it
# has to reach the caller as a transient 503 like any other outage -- never as the 409
# "Uploaded XML is unavailable" that would tell a user their batch is permanently dead.
_NOT_FOUND_CODES = frozenset({"NoSuchKey"})


class ObjectStorageUnavailableError(Exception):
    """The object store could not be reached, or refused the request.

    Distinct from "the object is missing": the caller must report a transient backend
    failure (503) rather than a permanent state conflict.
    """


class ObjectStorageKeyNotFoundError(Exception):
    """The requested object key does not exist in the bucket."""


class ObjectStorage:
    """Thin, lazily-connected wrapper around the S3 operations this app needs."""

    def __init__(self) -> None:
        self._client: S3Client | None = None
        self._bucket: str | None = None

    def _connect(self) -> tuple[S3Client, str]:
        # Lazy, like LoginRateLimiter's Redis client: the module-level singleton is
        # created at import time, well before tests get a chance to point the settings
        # at a mock endpoint.
        if self._client is None or self._bucket is None:
            settings = get_settings()
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.garage_endpoint_url,
                aws_access_key_id=settings.garage_access_key_id,
                aws_secret_access_key=settings.garage_secret_access_key,
                region_name=settings.garage_region,
                config=Config(
                    # Garage serves path-style URLs only: boto3's default virtual-host
                    # style would resolve `<bucket>.<endpoint>`, which no local DNS
                    # answers, and every call would fail with a connection error.
                    s3={"addressing_style": "path"},
                    connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                    read_timeout=_READ_TIMEOUT_SECONDS,
                    retries={"max_attempts": _MAX_ATTEMPTS, "mode": "standard"},
                ),
            )
            self._bucket = settings.garage_bucket
        return self._client, self._bucket

    def reset(self) -> None:
        """Drop the cached client so the next call re-reads the settings.

        Test utility: the suite swaps the S3 backend (and the endpoint URL it points
        at) between tests, and a client bound to a previous backend would keep talking
        to it.
        """
        self._client = None
        self._bucket = None

    def upload(self, key: str, content: IO[bytes]) -> None:
        """Upload a file-like object under `key`, replacing any existing object.

        `put_object`, not `upload_fileobj`: the latter goes through s3transfer, which
        switches to a multipart upload above 8 MiB and re-buffers every part in memory
        (`UploadSeekableInputManager.stores_body_in_memory()` returns True) -- so an
        upload just under imports' 25 MB limit would be held in RAM in full, defeating
        the caller's spooled buffer. A single PUT streams the seekable file object
        straight out, with no threads, and tops out at 5 GB.
        """
        client, bucket = self._connect()
        try:
            client.put_object(Bucket=bucket, Key=key, Body=content)
        except (BotoCoreError, ClientError) as exc:
            raise _unavailable("upload", key) from exc

    def download(self, key: str) -> bytes:
        """Return the full content of `key`.

        Bounded by imports.upload_xml's own size limit, which is enforced before an
        object ever reaches the bucket.
        """
        client, bucket = self._connect()
        try:
            response = client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectStorageKeyNotFoundError(key) from exc
            raise _unavailable("download", key) from exc
        except BotoCoreError as exc:
            raise _unavailable("download", key) from exc

    def copy(self, source_key: str, destination_key: str) -> None:
        """Server-side copy: S3 has no rename, and re-uploading would mean re-reading."""
        client, bucket = self._connect()
        try:
            client.copy_object(
                Bucket=bucket,
                Key=destination_key,
                CopySource={"Bucket": bucket, "Key": source_key},
            )
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectStorageKeyNotFoundError(source_key) from exc
            raise _unavailable("copy", source_key) from exc
        except BotoCoreError as exc:
            raise _unavailable("copy", source_key) from exc

    def delete(self, key: str) -> None:
        """Delete `key`. Deleting a missing key is a no-op, as in S3 itself."""
        client, bucket = self._connect()
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise _unavailable("delete", key) from exc


def _is_not_found(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    return str(error.get("Code", "")) in _NOT_FOUND_CODES


def _unavailable(operation: str, key: str) -> ObjectStorageUnavailableError:
    # The key is safe to include (it is generated by the app, never user-controlled) and
    # is what makes a storage incident diagnosable from the logs -- the routes that catch
    # this exception log it, with the botocore cause attached (see imports._storage_unavailable).
    return ObjectStorageUnavailableError(f"Object storage {operation} failed for {key!r}")


import_object_storage = ObjectStorage()
