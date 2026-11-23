"""Download direct media URLs from allowlisted hosts and enqueue file imports."""
from __future__ import annotations

import argparse
import json
import sys

from src.media.processing_queue import ProcessingQueue
from src.media.url_ingestion import RemoteURLAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        action="append",
        required=True,
        help="Direct HTTPS media URL. Repeat to import multiple files.",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        required=True,
        help="Exact trusted host name. Repeat for each approved host.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=2 * 1024 * 1024 * 1024,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30,
    )
    parser.add_argument(
        "--download-directory",
        default="data/incoming/remote",
    )
    parser.add_argument(
        "--database",
        default="data/database/processing_queue.db",
    )
    args = parser.parse_args()

    try:
        adapter = RemoteURLAdapter(
            args.allowed_host,
            args.download_directory,
            max_bytes=args.max_bytes,
            timeout_seconds=args.timeout_seconds,
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))

    queue = ProcessingQueue(args.database)
    queued = []
    failures = []
    try:
        for url in args.url:
            try:
                downloaded = adapter.download(url)
                job = queue.enqueue(
                    "file_import",
                    {
                        "files": [downloaded["path"]],
                        "source": "remote_url",
                        "source_host": downloaded["source_host"],
                    },
                    max_attempts=3,
                )
                queued.append({
                    "source_host": downloaded["source_host"],
                    "path": downloaded["path"],
                    "size_bytes": downloaded["size_bytes"],
                    "sha256": downloaded["sha256"],
                    "job_id": job["job_id"],
                })
            except Exception as error:
                failures.append({"error": str(error)})

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
