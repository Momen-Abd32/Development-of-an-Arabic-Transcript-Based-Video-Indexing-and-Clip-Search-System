"""Download allowlisted S3 media objects and enqueue normal file imports."""
from __future__ import annotations

import argparse
import json

from src.media.cloud_ingestion import S3ObjectAdapter
from src.media.processing_queue import ProcessingQueue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", action="append", required=True, help="Exact approved S3 bucket.")
    parser.add_argument("--key", action="append", required=True, help="Object key. Repeat for multiple objects.")
    parser.add_argument("--allowed-bucket", action="append", required=True, help="Exact trusted bucket. Repeat for each approved bucket.")
    parser.add_argument("--profile", help="Optional AWS shared-config profile name.")
    parser.add_argument("--region", help="Optional AWS region.")
    parser.add_argument("--endpoint-url", help="Optional operator-managed S3-compatible endpoint.")
    parser.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--download-directory", default="data/incoming/cloud")
    parser.add_argument("--database", default="data/database/processing_queue.db")
    args = parser.parse_args()

    if len(args.bucket) != len(args.key):
        parser.error("Supply one --key for each --bucket.")

    try:
        adapter = S3ObjectAdapter.from_boto3(
            args.allowed_bucket,
            args.download_directory,
            max_bytes=args.max_bytes,
            profile_name=args.profile,
            region_name=args.region,
            endpoint_url=args.endpoint_url,
        )
    except (TypeError, ValueError, RuntimeError) as error:
        parser.error(str(error))

    queue = ProcessingQueue(args.database)
    queued = []
    failures = []
    try:
        for bucket, key in zip(args.bucket, args.key):
            try:
                downloaded = adapter.download(bucket, key)
                job = queue.enqueue(
                    "file_import",
                    {
                        "files": [downloaded["path"]],
                        "source": "s3_object",
                        "bucket": downloaded["bucket"],
                        "object_key": downloaded["key"],
                    },
                    max_attempts=3,
                )
                queued.append({
                    "bucket": downloaded["bucket"],
                    "key": downloaded["key"],
                    "path": downloaded["path"],
                    "size_bytes": downloaded["size_bytes"],
                    "sha256": downloaded["sha256"],
                    "job_id": job["job_id"],
                })
            except Exception as error:
                failures.append({"bucket": bucket, "key": key, "error": str(error)})

        print(json.dumps(
            {"queued": queued, "failures": failures},
            ensure_ascii=False,
            indent=2,
        ))
        return 1 if failures else 0
    finally:
        queue.close()


if __name__ == "__main__":
    raise SystemExit(main())
