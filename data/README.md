# Data folder

This folder is deliberately empty in git. The original datasets are large
(the dataset_a export alone is ~5.5 GB across its zip parts) and are provided
separately, not through source control.

## How to reproduce this folder

1. Place the provided zip files in the project root (next to this repo's
   top-level `README.md`):
   - `dataset_a-<timestamp>-1-001.zip` (contains events.jsonl, manifest.json,
     gt.jsonl, gt_manifest.json, and a partial set of screenshots for all 63
     dataset_a sessions — this is the only dataset_a zip part that is
     actually needed)
   - `dataset_b-<timestamp>-1-001.zip` (contains events.jsonl, manifest.json,
     and screenshots for all 15 dataset_b sessions)

2. Run:
   ```bash
   scripts/extract_data.sh
   ```
   This extracts only `events.jsonl`, `manifest.json`, `gt.jsonl`, and
   `gt_manifest.json` from each zip into `data/dataset_a/` and
   `data/dataset_b/`. Screenshots are intentionally left inside the zip
   files and are not extracted, since segmentation and analysis rely on
   `context.extracted_text` in the event log rather than the images
   themselves. See WORKLOG.md for why.

After extraction you should have:
```
data/dataset_a/ses_.../chunk_.../events.jsonl, manifest.json
data/dataset_a/ses_.../gt.jsonl, gt_manifest.json
data/dataset_b/ses_.../chunk_.../events.jsonl, manifest.json
```
