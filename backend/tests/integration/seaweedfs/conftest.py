"""A boto3 client and a fresh bucket on the SeaweedFS test service, used from the host (outside
Docker), the way a real client reaches it."""

import uuid
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.config import Config

from tests.support.environment import load_test_environment


@pytest.fixture(scope="module")
def s3() -> Any:
    env = load_test_environment()
    return boto3.client(
        "s3",
        endpoint_url=env["QFE_STORAGE_PUBLIC_URL"],
        aws_access_key_id=env["QFE_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=env["QFE_STORAGE_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 1},
            connect_timeout=5,
            read_timeout=30,
        ),
    )


@pytest.fixture
def bucket(s3: Any) -> Iterator[str]:
    name = f"qfe-t-{uuid.uuid4().hex[:12]}"
    s3.create_bucket(Bucket=name)
    yield name
    # Remove what the test left, then the bucket.
    listing = s3.list_objects_v2(Bucket=name)
    for item in listing.get("Contents", []):
        s3.delete_object(Bucket=name, Key=item["Key"])
    s3.delete_bucket(Bucket=name)
