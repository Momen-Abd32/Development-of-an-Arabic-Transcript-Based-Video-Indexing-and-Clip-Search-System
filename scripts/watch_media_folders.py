"""Watch local folders and enqueue stable new audio/video files."""
from __future__ import annotations

import argparse

from src.media.folder_watcher import FolderWatcher


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folder",
        action="append",
        required=True,
        help="Folder to watch. Repeat this option to watch multiple folders.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Seconds between scans (default: 5).",
    )
    parser.add_argument(
        "--stable-scans",
        type=int,
        default=2,
        help="Consecutive unchanged scans before a file is queued (default: 2).",
    )
    parser.add_argument(
        "--non-recursive",
        action="store_true",
        help="Watch only the top level of each folder.",
    )
    parser.add_argument(
        "--database",
        default="data/database/processing_queue.db",
        help="Queue and watcher-state SQLite database.",
    )
    args = parser.parse_args()

    watcher = FolderWatcher(
        args.folder,
        database_path=args.database,
        recursive=not args.non_recursive,
        stable_scans=args.stable_scans,
    )
    try:
        print(
            "Watching folders for stable media files. "
            "Run scripts/run_processing_worker.py in a separate process."
        )
        watcher.run_forever(args.poll_seconds)
    except KeyboardInterrupt:
        watcher.stop()
    finally:
        watcher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
