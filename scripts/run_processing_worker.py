import argparse
import json
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.media.processing_queue import ProcessingQueue
from src.media.processing_worker import ProcessingWorker


def main():
    parser = argparse.ArgumentParser(
        description="Run the durable media-processing queue worker."
    )
    parser.add_argument(
        "--database",
        default="data/database/processing_queue.db",
        help="SQLite processing queue database path.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5,
        help="How often to check for new jobs when the queue is empty.",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=900,
        help="Worker lease duration; heartbeat extends active leases.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job, then exit.",
    )
    args = parser.parse_args()

    queue = ProcessingQueue(args.database)
    worker = ProcessingWorker(
        queue=queue,
        lease_seconds=args.lease_seconds,
    )
    try:
        if args.once:
            result = worker.run_once()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Processing worker started. Press Ctrl+C to stop after the current job.")
            signal.signal(signal.SIGINT, lambda signum, frame: worker.stop())
            signal.signal(signal.SIGTERM, lambda signum, frame: worker.stop())
            worker.run_forever(poll_seconds=args.poll_seconds)
    except KeyboardInterrupt:
        worker.stop()
        print("\nProcessing worker stopped.")
    finally:
        queue.close()


if __name__ == "__main__":
    main()
