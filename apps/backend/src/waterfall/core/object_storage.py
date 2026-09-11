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

from waterfall.core.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover - typing-only import (boto3-stubs is a dev dep)
    from mypy_boto3_s3.client import S3Client

# Never let an unreachable store hang a request: a stuck upload would also hold the
# project row lock in imports.upload_xml's final copy step.
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 3

# `check_bucket` (the readiness probe, E13-03) gets its own, much tighter budget: it runs
# behind a ~2s per-dependency deadline in api/routes/health.py, so the data-path values
# above -- up to 3 attempts x 5s just to connect -- would guarantee the probe is cut off
# by its deadline instead of returning a real answer, and would leave a socket-holding
# thread behind on every poll. One attempt, fail fast, report honestly.
_PROBE_CONNECT_TIMEOUT_SECONDS = 1
_PROBE_READ_TIMEOUT_SECONDS = 1
_PROBE_MAX_ATTEMPTS = 1

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
        self._probe_client: S3Client | None = None
        self._bucket: str | None = None

    def _connect(self) -> tuple[S3Client, str]:
        # Lazy, like LoginRateLimiter's Redis client: the module-level singleton is
        # created at import time, well before tests get a chance to point the settings
        # at a mock endpoint.
        if self._client is None or self._bucket is None:
            settings = get_settings()
            self._client = _new_client(
                settings,
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                read_timeout=_READ_TIMEOUT_SECONDS,
                max_attempts=_MAX_ATTEMPTS,
            )
            self._bucket = settings.garage_bucket
        return self._client, self._bucket

    def _connect_probe(self) -> tuple[S3Client, str]:
        """Same endpoint and credentials as `_connect`, fail-fast timeouts.

        A separate client rather than a separate `Config` per call: botocore builds the
        endpoint resolver and the signer once per client, so reusing one keeps the
        readiness probe cheap enough to be polled every few seconds.

        Deliberately does not populate `self._bucket`, unlike `_connect`: this runs on the
        readiness probe's own thread (see api/routes/health.py), so writing that shared
        attribute would race a concurrent `_connect`/`reset`, and a probe in flight when
        `reset()` lands could read the `None` back and call `head_bucket(Bucket=None)`.
        Reading the (cached) settings per call costs nothing and keeps the probe free of
        shared mutable state.
        """
        settings = get_settings()
        if self._probe_client is None:
            self._probe_client = _new_client(
                settings,
                connect_timeout=_PROBE_CONNECT_TIMEOUT_SECONDS,
                read_timeout=_PROBE_READ_TIMEOUT_SECONDS,
                max_attempts=_PROBE_MAX_ATTEMPTS,
            )
        return self._probe_client, settings.garage_bucket

    def reset(self) -> None:
        """Close and drop the cached clients so the next call re-reads the settings.

        Test utility: the suite swaps the S3 backend (and the endpoint URL it points
        at) between tests, and a client bound to a previous backend would keep talking
        to it.

        Closed, not just dropped: a botocore client owns an urllib3 `PoolManager` and its
        open sockets, which only `close()` releases -- dropping the reference leaves them
        to the garbage collector. This runs from an autouse fixture on every test of the
        ~20 modules that touch object storage, twice each, so "the GC will get to it"
        would mean hundreds of abandoned connection pools in a single pytest process.
        """
        for client in (self._client, self._probe_client):
            if client is not None:
                client.close()
        self._client = None
        self._probe_client = None
        self._bucket = None

    def check_bucket(self) -> None:
        """Raise unless the configured bucket is reachable right now (readiness probe).

        `head_bucket`, not a listing: it is the cheapest call that exercises the whole
        chain the import path depends on -- network, SigV4 with the configured region,
        and the existence of *that* bucket for *these* credentials -- while transferring
        no object data.

        Every failure is an outage here, with no "missing" case to distinguish: a HEAD on
        an absent bucket answers a bodiless 404 (botocore reports `Error.Code == "404"`,
        not `NoSuchBucket`) and an invisible one answers 403, and both mean the store is
        not in the state the API needs. So this deliberately does not consult
        `_NOT_FOUND_CODES` -- which is also why "404" must stay out of that set: it is the
        answer to "is this object gone?", and a bucket-level HEAD is not that question.
        """
        client, bucket = self._connect_probe()
        try:
            client.head_bucket(Bucket=bucket)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailableError(
                f"Object storage bucket {bucket!r} is unreachable"
            ) from exc

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


def _new_client(
    settings: Settings, *, connect_timeout: int, read_timeout: int, max_attempts: int
) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=settings.garage_endpoint_url,
        aws_access_key_id=settings.garage_access_key_id,
        aws_secret_access_key=settings.garage_secret_access_key,
        region_name=settings.garage_region,
        config=Config(
            # Garage serves path-style URLs only: boto3's default virtual-host style
            # would resolve `<bucket>.<endpoint>`, which no local DNS answers, and every
            # call would fail with a connection error.
            s3={"addressing_style": "path"},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


def _is_not_found(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    return str(error.get("Code", "")) in _NOT_FOUND_CODES


def _unavailable(operation: str, key: str) -> ObjectStorageUnavailableError:
    # The key is safe to include (it is generated by the app, never user-controlled) and
    # is what makes a storage incident diagnosable from the logs -- the routes that catch
    # this exception log it, with the botocore cause attached (see imports._storage_unavailable).
    return ObjectStorageUnavailableError(f"Object storage {operation} failed for {key!r}")


import_object_storage = ObjectStorage()
