"""How SeaweedFS really expires objects (ISS-20261012-1825).

Findings these tests keep true:
1. A bucket lifecycle rule that is only *stored* does not put an expiry time on any object.
2. The opt-in "TTL fast path" (a weed shell command, not an S3 call) stamps the expiry on objects
   that match a Days rule, at write time.
3. The lifecycle worker (normally run by the SeaweedFS admin on a daily schedule; not part of a
   plain ``weed server``) deletes due objects and keeps the others. Here one pass is run by hand.

A released SeaweedFS counts a day as 24 hours, so a ``Days`` rule cannot be observed expiring in a
test; a rule dated in the past is due at once and shows what the worker does.
"""

import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from tests.support.compose import compose

HTTP_NOT_FOUND = 404


def weed_shell(command: str) -> str:
    """Run one ``weed shell`` command inside the test storage container and return its output."""
    result = compose(
        "exec",
        "-T",
        "storage-test",
        "sh",
        "-c",
        f"echo '{command}' | timeout 120 weed shell -master=localhost:9333 2>&1",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def ttl_seconds(bucket: str, key: str) -> int:
    """The expiry time the filer holds for an object (0 means none)."""
    output = weed_shell(f"fs.meta.cat /buckets/{bucket}/{key}")
    found = re.search(r'"ttlSec":\s*(\d+)', output)
    assert found, output
    return int(found.group(1))


def exists(s3: Any, bucket: str, key: str) -> bool:
    keys = [item["Key"] for item in s3.list_objects_v2(Bucket=bucket).get("Contents", [])]
    return key in keys


def days_rule(prefix: str = "orgs/", days: int = 1) -> dict[str, Any]:
    return {
        "Rules": [
            {
                "ID": "expire",
                "Status": "Enabled",
                "Filter": {"Prefix": prefix},
                "Expiration": {"Days": days},
            }
        ]
    }


def test_a_stored_lifecycle_rule_alone_puts_no_expiry_time_on_objects(s3: Any, bucket: str) -> None:
    s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=days_rule())
    s3.put_object(Bucket=bucket, Key="orgs/after-rule.txt", Body=b"x")
    assert ttl_seconds(bucket, "orgs/after-rule.txt") == 0


def test_the_ttl_fast_path_stamps_the_expiry_on_matching_objects_only(s3: Any, bucket: str) -> None:
    s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=days_rule())
    assert "fast path enabled" in weed_shell(f"s3.bucket.lifecycle.fastpath -name {bucket} -enable")
    s3.put_object(Bucket=bucket, Key="orgs/matching.txt", Body=b"x")
    s3.put_object(Bucket=bucket, Key="other/not-matching.txt", Body=b"y")
    assert ttl_seconds(bucket, "orgs/matching.txt") == 24 * 60 * 60
    assert ttl_seconds(bucket, "other/not-matching.txt") == 0


def test_one_lifecycle_worker_pass_deletes_due_objects_and_keeps_the_others(
    s3: Any, bucket: str
) -> None:
    s3.put_object(Bucket=bucket, Key="orgs/due.txt", Body=b"x")
    s3.put_object(Bucket=bucket, Key="other/untouched.txt", Body=b"y")
    long_ago = (datetime.now(UTC) - timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "past-date",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "orgs/"},
                    "Expiration": {"Date": long_ago},
                }
            ]
        },
    )
    assert exists(s3, bucket, "orgs/due.txt")
    started = time.monotonic()
    weed_shell("s3.lifecycle.run-shard -shards 0-15 -s3 localhost:18333 -refresh 1s -runtime 30s")
    assert time.monotonic() - started < 120
    assert not exists(s3, bucket, "orgs/due.txt")
    assert exists(s3, bucket, "other/untouched.txt")
