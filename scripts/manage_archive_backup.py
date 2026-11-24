"""Create, verify, or restore a complete local archive backup."""
from __future__ import annotations

import argparse
import json
import sys

from src.media.archive_backup import ArchiveBackup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-directory",
        default=".",
        help="Application root containing data/ and exports/ (default: current directory).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a new backup ZIP.")
    create_parser.add_argument("--output", required=True)

    verify_parser = subparsers.add_parser("verify", help="Verify a backup and its checksums.")
    verify_parser.add_argument("--backup", required=True)

    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore a verified backup into a new directory.",
    )
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--target", required=True)

    args = parser.parse_args()
    manager = ArchiveBackup(args.base_directory)

    try:
        if args.command == "create":
            result = manager.create_backup(args.output)
        elif args.command == "verify":
            manifest = manager.verify_backup(args.backup)
            result = {
                "verified": True,
                "file_count": len(manifest["files"]),
                "created_at": manifest["created_at"],
            }
        else:
            result = manager.restore_backup(args.backup, args.target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"Archive backup operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
