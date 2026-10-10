"""The storage behaviours the design relies on, proved against the real SeaweedFS service from the
host (docs/specs/FEAT-20261010-1209-seaweedfs-checks.md). These tests are the first running proof of
what had only been read in documentation; they stay as regression tests for the storage adapter."""

import asyncio
import http.client
import time
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from tests.support.environment import load_test_environment

ONE_MIB = 1024 * 1024
HTTP_NOT_FOUND = 404
HTTP_FORBIDDEN = 403
HTTP_BAD_REQUEST = 400


def make_policy(
    s3: Any, bucket: str, key: str, *, max_size: int = ONE_MIB, expires: int = 60
) -> dict[str, Any]:
    """A presigned POST for exactly one key, text/plain, size 1..max_size."""
    policy: dict[str, Any] = s3.generate_presigned_post(
        bucket,
        key,
        Fields={"Content-Type": "text/plain"},
        Conditions=[{"Content-Type": "text/plain"}, ["content-length-range", 1, max_size]],
        ExpiresIn=expires,
    )
    return policy


def upload(policy: dict[str, Any], data: bytes) -> httpx.Response:
    return httpx.post(
        policy["url"],
        data=policy["fields"],
        files={"file": ("f.txt", data, "text/plain")},
        timeout=60,
    )


def head(s3: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        result = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] == HTTP_NOT_FOUND:
            return None
        raise
    return dict(result)


# --- 1 to 3: presigned POST with a size range


def test_an_upload_inside_the_size_range_is_accepted(s3: Any, bucket: str) -> None:
    key = f"orgs/o1/{uuid.uuid4().hex}"
    response = upload(make_policy(s3, bucket, key), b"a" * 100_000)
    assert response.status_code in (200, 201, 204), response.text
    info = head(s3, bucket, key)
    assert info is not None
    assert info["ContentLength"] == 100_000
    assert info["ContentType"] == "text/plain"


def test_an_upload_over_the_size_range_is_refused_and_leaves_no_object(
    s3: Any, bucket: str
) -> None:
    key = f"orgs/o1/{uuid.uuid4().hex}"
    response = upload(make_policy(s3, bucket, key, max_size=ONE_MIB), b"a" * (5 * ONE_MIB))
    assert response.status_code == HTTP_BAD_REQUEST
    assert "EntityTooLarge" in response.text
    assert head(s3, bucket, key) is None


def test_an_empty_upload_is_refused(s3: Any, bucket: str) -> None:
    key = f"orgs/o1/{uuid.uuid4().hex}"
    response = upload(make_policy(s3, bucket, key), b"")
    assert response.status_code == HTTP_BAD_REQUEST
    assert "EntityTooSmall" in response.text
    assert head(s3, bucket, key) is None


def test_how_much_of_a_too_large_upload_is_received_before_it_is_refused(
    s3: Any, bucket: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A measurement more than a check: does storage stop reading early? The result is printed
    and recorded in the notepad; the assertions only require that the upload is refused."""
    key = f"orgs/o1/{uuid.uuid4().hex}"
    policy = make_policy(s3, bucket, key, max_size=ONE_MIB)
    total = 64 * ONE_MIB
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in policy["fields"].items()
    ]
    file_head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    sent = 0

    def body() -> Iterator[bytes]:
        nonlocal sent
        yield b"".join(parts) + file_head
        chunk = b"a" * 65536
        for _ in range(total // len(chunk)):
            sent += len(chunk)
            yield chunk
        yield tail

    target = urlsplit(policy["url"])
    connection = http.client.HTTPConnection(target.hostname or "", target.port, timeout=60)
    started = time.perf_counter()
    status: int | str
    try:
        connection.request(
            "POST",
            target.path,
            body=body(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            encode_chunked=True,
        )
        status = connection.getresponse().status
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as error:
        status = type(error).__name__
    finally:
        connection.close()
    elapsed = time.perf_counter() - started
    with capsys.disabled():
        print(
            f"\n[measurement] upload of {total // ONE_MIB} MiB with a 1 MiB limit: "
            f"status={status}, sent {sent // ONE_MIB} MiB before the answer, {elapsed:.1f}s"
        )
    assert head(s3, bucket, key) is None


# --- 4: the public address


def test_a_link_signed_for_the_public_address_works_from_outside_docker(
    s3: Any, bucket: str
) -> None:
    key = "orgs/o1/public.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=b"hello", ContentType="text/plain")
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60
    )
    response = httpx.get(url)
    assert response.status_code == 200
    assert response.content == b"hello"


def test_a_link_signed_for_an_internal_host_name_is_refused(s3: Any, bucket: str) -> None:
    """Why the public storage URL setting is required: a link signed for a Docker-internal host
    name does not work when the client reaches storage by its public address."""
    env = load_test_environment()
    key = "orgs/o1/internal.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=b"hello", ContentType="text/plain")
    internal = boto3.client(
        "s3",
        endpoint_url="http://storage-test:8333",  # the name inside Docker, not reachable here
        aws_access_key_id=env["QFE_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=env["QFE_STORAGE_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    signed = internal.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60
    )
    public = urlsplit(s3.meta.endpoint_url)
    wrong = signed.replace("http://storage-test:8333", f"{public.scheme}://{public.netloc}")
    response = httpx.get(wrong)
    assert response.status_code == HTTP_FORBIDDEN
    assert "SignatureDoesNotMatch" in response.text or "AccessDenied" in response.text


# --- 5, 6, 9: HEAD, download links, delete


def test_head_reports_size_and_type_and_a_missing_key_is_404(s3: Any, bucket: str) -> None:
    s3.put_object(Bucket=bucket, Key="k1", Body=b"12345", ContentType="application/pdf")
    info = head(s3, bucket, "k1")
    assert info is not None
    assert (info["ContentLength"], info["ContentType"]) == (5, "application/pdf")
    assert head(s3, bucket, "missing") is None


def test_a_download_link_returns_the_bytes_and_expires(s3: Any, bucket: str) -> None:
    s3.put_object(Bucket=bucket, Key="dl", Body=b"payload", ContentType="text/plain")
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": "dl"}, ExpiresIn=2
    )
    assert httpx.get(url).content == b"payload"
    time.sleep(4)
    assert httpx.get(url).status_code == HTTP_FORBIDDEN


def test_delete_removes_the_object(s3: Any, bucket: str) -> None:
    s3.put_object(Bucket=bucket, Key="gone", Body=b"x")
    s3.delete_object(Bucket=bucket, Key="gone")
    assert head(s3, bucket, "gone") is None
    s3.delete_object(Bucket=bucket, Key="gone")  # deleting a missing key is not an error


# --- 7: keys


@pytest.mark.parametrize(
    "key",
    [
        "orgs/0192a-b3/files/plain.txt",
        "orgs/o1/a file with spaces.txt",
        "orgs/o1/ünïcode-文件.txt",
        "orgs/o1/plus+and&amp.txt",
    ],
)
def test_keys_round_trip_unchanged(s3: Any, bucket: str, key: str) -> None:
    s3.put_object(Bucket=bucket, Key=key, Body=b"v")
    listed = [item["Key"] for item in s3.list_objects_v2(Bucket=bucket).get("Contents", [])]
    assert key in listed
    assert s3.get_object(Bucket=bucket, Key=key)["Body"].read() == b"v"


# --- 8: lifecycle


def test_a_lifecycle_expiry_rule_is_accepted_and_read_back(s3: Any, bucket: str) -> None:
    """Only the storing of the rule is proved. Whether SeaweedFS then deletes objects needs days
    to observe (the smallest unit is one day), so expiry itself is recorded as not verified."""
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "expire-old",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "orgs/"},
                    "Expiration": {"Days": 30},
                }
            ]
        },
    )
    rules = s3.get_bucket_lifecycle_configuration(Bucket=bucket)["Rules"]
    assert [rule["ID"] for rule in rules] == ["expire-old"]
    assert rules[0]["Expiration"]["Days"] == 30


# --- 10: calls from threads


async def test_many_head_calls_from_threads_at_once_all_succeed(s3: Any, bucket: str) -> None:
    s3.put_object(Bucket=bucket, Key="shared", Body=b"abc")
    results = await asyncio.gather(
        *(asyncio.to_thread(head, s3, bucket, "shared") for _ in range(20))
    )
    assert all(item is not None and item["ContentLength"] == 3 for item in results)
