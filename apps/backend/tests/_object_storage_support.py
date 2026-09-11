"""In-memory S3 backend for every test that touches the import object storage.

Unlike Redis (E13-01), the object store is *mocked* rather than required to be reachable:
around twenty test modules upload or read an import source, and making the whole suite
depend on a locally started Garage would be exactly the trap that made the Redis switch
painful. moto answers through botocore's own request pipeline -- same signing, same
`ClientError` shapes -- so `core/object_storage.py`'s error translation stays honest.

The fixture is autouse and function-scoped: it recreates an empty bucket per test, which
also gives the same isolation the database fixtures provide. A test that needs the real
(unmocked) client -- e.g. to prove an unreachable store surfaces as a 503 -- opts out with
`@pytest.mark.no_object_storage_mock`.

Deliberately not named test_*.py, for the same reason as _postgres_support.py: pytest's
default collection would otherwise try to import it as a test module.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import boto3
import pytest
from botocore.config import Config
from moto import mock_aws

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

# Not the Garage endpoint, on purpose: moto's stubber matches the *request URL* against
# the AWS backend URL patterns and passes anything else straight through to the network
# (a `http://127.0.0.1:3900` endpoint is not intercepted at all -- it really tries to
# connect). Pointing the app at the canonical S3 endpoint is what makes the mock engage;
# everything the app does above botocore -- path addressing, SigV4 with the Garage region,
# ClientError shapes -- is exercised identically.
TEST_ENDPOINT_URL = "https://s3.amazonaws.com"
TEST_ACCESS_KEY_ID = "GK00000000000000000000test"
TEST_SECRET_ACCESS_KEY = "0000000000000000000000000000000000000000000000000000000000000000"
TEST_BUCKET = "waterfall-imports-test"
TEST_REGION = "garage"

# Set here rather than in conftest.py so they cannot drift from the bucket/endpoint the
# fixture below actually serves. pytest imports plugin modules before running any test,
# i.e. before prepare_test_environment triggers the first Settings read.
#
# Assigned, never `setdefault`: there is no legitimate override, since the backend is
# mocked in-process, and a developer with GARAGE_ENDPOINT_URL exported (shell profile,
# direnv, `set -a; source .env`) would otherwise point the whole suite at their real
# Garage -- moto would not intercept anything and the tests would write to the real
# bucket. Same for the credentials and the bucket name.
os.environ["GARAGE_ENDPOINT_URL"] = TEST_ENDPOINT_URL
os.environ["GARAGE_ACCESS_KEY_ID"] = TEST_ACCESS_KEY_ID
os.environ["GARAGE_SECRET_ACCESS_KEY"] = TEST_SECRET_ACCESS_KEY
os.environ["GARAGE_BUCKET"] = TEST_BUCKET


def new_s3_client() -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=TEST_ENDPOINT_URL,
        aws_access_key_id=TEST_ACCESS_KEY_ID,
        aws_secret_access_key=TEST_SECRET_ACCESS_KEY,
        region_name=TEST_REGION,
        config=Config(s3={"addressing_style": "path"}),
    )


@contextmanager
def _forbid_the_real_aws_endpoint() -> Generator[None]:
    """Fail loudly if the application builds a client on TEST_ENDPOINT_URL unmocked.

    Enforcement, not documentation: with moto off, TEST_ENDPOINT_URL *is* Amazon S3, so
    an opted-out test that forgets to repoint GARAGE_ENDPOINT_URL would send signed
    requests over the internet. The check sits on boto3.client because that is the exact
    moment the endpoint is chosen (ObjectStorage._connect), and the fixture has just
    dropped the cached client, so every connection made during the test goes through it.
    """
    real_client = boto3.client

    def guarded_client(*args: Any, **kwargs: Any) -> Any:
        assert kwargs.get("endpoint_url") != TEST_ENDPOINT_URL, (
            "a no_object_storage_mock test must repoint GARAGE_ENDPOINT_URL away from "
            f"{TEST_ENDPOINT_URL} (see test_imports_api.UNREACHABLE_ENDPOINT_URL): "
            "without the moto backend, that endpoint is the real AWS S3"
        )
        return real_client(*args, **kwargs)

    with patch.object(boto3, "client", guarded_client):
        yield


@pytest.fixture(autouse=True)
def object_storage(request: pytest.FixtureRequest) -> Generator[S3Client | None]:
    """Serve the import bucket from moto, and hand the test a client on it.

    Yields None for tests marked `no_object_storage_mock`, which want real botocore
    failures. Either way the application's cached S3 client is dropped on both sides of
    the test: it would otherwise outlive the moto backend it was bound to and start
    answering (or failing) for the wrong one.
    """
    from waterfall.core.config import get_settings
    from waterfall.core.object_storage import import_object_storage

    import_object_storage.reset()
    if request.node.get_closest_marker("no_object_storage_mock") is not None:
        # Not asserted on the settings: an opted-out test repoints the endpoint from
        # inside its own body, well after this fixture runs, and restores it before this
        # fixture resumes. The guard below catches the real mistake at the real moment.
        with _forbid_the_real_aws_endpoint():
            yield None
        import_object_storage.reset()
        return

    # The module-level assignments above are what make moto engage at all; if anything
    # ever manages to override them, every test here would silently talk to whatever
    # store that is. Cheap to check, and it fails on the fixture rather than as a
    # puzzling 503 deep inside a test.
    assert get_settings().garage_endpoint_url == TEST_ENDPOINT_URL
    assert get_settings().garage_bucket == TEST_BUCKET

    with mock_aws():
        client = new_s3_client()
        # LocationConstraint is required for any region other than us-east-1, and the
        # app signs its requests for `garage`.
        client.create_bucket(
            Bucket=TEST_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": TEST_REGION},  # pyright: ignore[reportArgumentType]
        )
        yield client
    import_object_storage.reset()


def stored_object_keys(client: S3Client, prefix: str = "") -> list[str]:
    """List the keys currently in the import bucket (test assertion helper)."""
    response = client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=prefix)
    # `Key` is optional in the botocore type stubs (S3 omits it in some listing modes),
    # never in practice for a plain list; the .get keeps pyright happy without an ignore.
    return sorted(str(item.get("Key", "")) for item in response.get("Contents", []))
