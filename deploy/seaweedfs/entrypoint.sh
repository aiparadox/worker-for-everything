#!/bin/sh
# Starts SeaweedFS (master, volume server, filer and the S3 gateway in one process) for development.
# The S3 credentials are written to a file from environment variables when the container starts,
# so no secret is stored in the repository or in the image.
set -eu

: "${QFE_STORAGE_ACCESS_KEY:?QFE_STORAGE_ACCESS_KEY is required}"
: "${QFE_STORAGE_SECRET_KEY:?QFE_STORAGE_SECRET_KEY is required}"
: "${QFE_STORAGE_PUBLIC_URL:?QFE_STORAGE_PUBLIC_URL is required}"

cat > /tmp/s3.json <<EOF
{
  "identities": [
    {
      "name": "qfe",
      "credentials": [
        { "accessKey": "${QFE_STORAGE_ACCESS_KEY}", "secretKey": "${QFE_STORAGE_SECRET_KEY}" }
      ],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
EOF

# -s3.externalUrl: presigned links are signed for this address, so it must be the address clients
# use from outside Docker (FEAT-20261010-1209 tests this).
exec weed server \
  -dir=/data \
  -master.volumeSizeLimitMB=1024 \
  -volume.max=100 \
  -s3 \
  -s3.config=/tmp/s3.json \
  -s3.externalUrl="${QFE_STORAGE_PUBLIC_URL}"
