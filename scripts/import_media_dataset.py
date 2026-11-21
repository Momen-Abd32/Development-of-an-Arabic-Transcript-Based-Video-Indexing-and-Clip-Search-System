import argparse

from src.media.batch_processor import MediaBatchProcessor


def main():
    parser = argparse.ArgumentParser(
        description="Import and transcribe Arabic audio/video files in a folder."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing audio and video files.",
    )
    parser.add_argument(
        "--non-recursive",
        action="store_true",
        help="Process only files directly inside the input directory.",
    )
    parser.add_argument("--model-size", default="tiny")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    processor = MediaBatchProcessor(
        model_size=args.model_size,
        device=args.device,
        compute_type=args.compute_type,
    )
    results = processor.process_directory(
        args.input_dir,
        recursive=not args.non_recursive,
    )

    for result in results:
        status = result["status"].upper()
        source = result["source"]
        segment_count = result.get("segments", 0)
        print(f"[{status}] {source} — {segment_count} transcript segments")
        if result.get("error"):
            print(f"  Error: {result['error']}")

    processed = sum(item["status"] == "processed" for item in results)
    existing = sum(item["status"] == "already_transcribed" for item in results)
    duplicates = sum(
        item["status"] == "duplicate_in_batch" for item in results
    )
    failed = sum(item["status"] == "failed" for item in results)

    print()
    print(
        f"Total: {len(results)} | Processed: {processed} | "
        f"Already transcribed: {existing} | Duplicates: {duplicates} | "
        f"Failed: {failed}"
    )


if __name__ == "__main__":
    main()
