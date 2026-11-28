# SADA 2022 sample integration

The project can import a bounded sample of the original SADA 2022 Arabic audio
dataset. SADA contains full-episode WAV recordings and CSV rows with segment
timestamps and supplied Arabic transcripts. It is an **audio-only** dataset;
it does not provide the original video frames. The project therefore indexes
each episode as audio, supports archive-wide and selected-recording transcript
search, and can extract timestamped **audio clips**. Video clip extraction
continues to work for video sources imported separately.

## Dataset source and attribution

- Original dataset: https://www.kaggle.com/datasets/sdaiancai/sada2022
- Curators: Saudi Data and AI Authority (SDAIA) and Saudi Broadcasting Authority (SBA).
- License: CC BY-NC-SA 4.0. Use is non-commercial, requires attribution, and
  derivative distributions must use the same license. Review the dataset's
  license before redistribution or any external use.
- Citation: SDAIA and SBA, *SADA: Saudi Audio Dataset for Arabic* (2022).

The CSV rows reference the original audio through `FileName` and provide
`SegmentStart`, `SegmentEnd`, `GroundTruthText`, `ProcessedText`, and
speaker metadata. The importer prefers `GroundTruthText`, falling back to
`ProcessedText` only when the original transcript is empty. It does not run
Whisper over these already-annotated segments.

## Download and import a small sample

1. Install the Kaggle CLI: `python -m pip install kaggle`.
2. Configure Kaggle API credentials as described in Kaggle's CLI documentation.
3. From the project root, run:

```bash
python scripts/download_sada_sample.py --episodes 3 --split train
```

This downloads only `train.csv` and the first three unique WAV episodes
referenced by that split, rather than downloading the complete dataset. The
audio and annotations are then copied into the project's archive, catalogued,
and indexed in SQLite.

To inspect the selected sample without importing it:

```bash
python scripts/download_sada_sample.py --episodes 3 --split train --dry-run
```

To import files that have already been downloaded into
`data/external/sada2022`, use:

```bash
python -c "from src.media.sada_dataset_importer import SadaDatasetImporter; print(SadaDatasetImporter(max_episodes=3).import_dataset())"
```

Use `--split valid` for validation data. The default is `train`; the
`test` split should be kept separate when conducting a formal evaluation.
