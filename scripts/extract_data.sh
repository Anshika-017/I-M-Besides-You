#!/usr/bin/env bash
# Extracts only the text/JSON files we need for segmentation and analysis
# (events.jsonl, manifest.json, gt.jsonl, gt_manifest.json) from the
# provided dataset zips, leaving screenshots inside the zips.
#
# Usage: run from the project root: ./scripts/extract_data.sh
set -euo pipefail
cd "$(dirname "$0")/.."

A_ZIP=$(ls dataset_a-*-1-001.zip 2>/dev/null | head -1)
B_ZIP=$(ls dataset_b-*-1-001.zip 2>/dev/null | head -1)

if [ -z "$A_ZIP" ]; then
  echo "ERROR: could not find dataset_a-*-1-001.zip in project root" >&2
  exit 1
fi
if [ -z "$B_ZIP" ]; then
  echo "ERROR: could not find dataset_b-*-1-001.zip in project root" >&2
  exit 1
fi

mkdir -p data
echo "Extracting from $A_ZIP ..."
unzip -q -n "$A_ZIP" "dataset_a/*/events.jsonl" "dataset_a/*/manifest.json" \
  "dataset_a/*/gt.jsonl" "dataset_a/*/gt_manifest.json" -d data/

echo "Extracting from $B_ZIP ..."
unzip -q -n "$B_ZIP" "dataset_b/*/events.jsonl" "dataset_b/*/manifest.json" -d data/

echo "Done."
find data/dataset_a data/dataset_b -type f 2>/dev/null | wc -l | xargs echo "Total files extracted (cumulative):"
