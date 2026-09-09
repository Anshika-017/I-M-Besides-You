# Work Log

Running record of what was actually done, in order. Written as work happens,
not reconstructed afterward.

---

## Day 1 — Setup and data verification

**Read `README.md` and `DATA_SCHEMA.md`.** Assignment: recover business-process
executions from raw PC-operation logs (Step 1), analyze the results to find
automation candidates (Step 2), and build a working automation prototype for
the best candidate (Step 3). Explicit deliverables: `segments.jsonl` for
Dataset B, full repo with git history, a report, and this work log.

**Inspected the provided zip files without extracting them** (`unzip -l`).
Found a serious problem: `dataset_a-20260908T164343Z-1-003.zip` contained
*only* screenshots (7,138 `.jpg` files, 31 of the 63 sessions) — no
`events.jsonl`, no `manifest.json`, no ground truth at all. The `-1-003`
suffix is the naming pattern Google Drive uses when a folder download is
split into multiple zip parts, so this was clearly one part of a larger
export, missing its other parts. Reported this to the user and paused —
did not proceed with Dataset A until the missing parts were provided.

Meanwhile, `dataset_b-20260908T164409Z-1-001.zip` looked complete (15
sessions, 20 `events.jsonl`/`manifest.json` pairs, matching the README's
"15 sessions / ~20,000 events"), so extracted only its `events.jsonl` and
`manifest.json` files (83 MB) into `data/dataset_b/`, leaving the 1.65 GB of
screenshots inside the zip. Decision: screenshots aren't needed for
segmentation since screen text is already available in the log via
`context.extracted_text`; extracting them would just be 1.65 GB of unused
duplication.

**While inspecting dataset_b's raw events, found an unplanned data leak**:
one `app_switch` event's `extracted_text` captured the on-screen output of
the test harness's own setup script ("Theme M2" generator), showing process
codes (`P1..P13`), named variants (e.g. `V3_manager_entertain`), and an
operator/department. Checked how often this recurs — found it in 9 of 20
dataset_b chunks. Decided to treat this as a secondary sanity-check signal
only (it's real log content, not something we searched for or requires
lucky timing across all sessions), not as ground truth — the README is
explicit that Dataset B has none, and I don't want to quietly rely on an
incidental artifact for the primary evaluation.

**User located and re-downloaded the missing dataset_a parts** — 5 new zip
files (`dataset_a-20260908T171747Z-1-001.zip` through `-1-005.zip`).
Verified completeness before extracting: listed every part's contents and
cross-checked file-type counts, session/chunk pairing, and screenshot
filename sets.

Findings:
- All 63 sessions, all 117 chunk-level `events.jsonl`/`manifest.json` pairs,
  and all 63 `gt.jsonl`/`gt_manifest.json` pairs are present, and every
  single one of them is inside `-1-001.zip` alone. Parts `-002` through
  `-005` are screenshot-only overflow.
- Confirmed the original single-part zip (`...T164343Z-1-003.zip`) is a
  strict subset of the new export: all 7,137 unique screenshot filenames in
  it also appear in the new 5-part export. It's redundant and safe to
  ignore (not deleted, per instructions — just unused going forward).
- Found one naming quirk: for 17 chunks, the export split a chunk's
  `events.jsonl`/`manifest.json` (under the chunk's full name) from that
  same chunk's `screenshots/` folder (under a short-form sibling directory
  name, e.g. `chunk_1200` vs `chunk_20260630-1200-LAPTOP-R36BQBTE`).
  Verified via one `manifest.json`'s declared `screenshots.file_count` that
  this is just a path-naming split, not lost data. Doesn't affect anything
  since screenshots aren't being used for segmentation.

Extracted `events.jsonl`, `manifest.json`, `gt.jsonl`, `gt_manifest.json`
from `dataset_a-...-1-001.zip` into `data/dataset_a/` (711 MB, 360 files —
matches the expected 117+117+63+63 exactly).

**Set up the actual project skeleton**: `git init`, `.gitignore` (excludes
the zips and the extracted `data/` folders — datasets are regenerable via
`scripts/extract_data.sh`, not stored in git), and an initial commit of the
assignment spec files plus the extraction script.

---

## Day 1 (cont.) — Exploring Dataset A for Step 1

Built `src/procmine/io.py` — a small loader module (`list_sessions`,
`list_chunks`, `iter_events`, `load_gt`, `load_gt_manifest`) that hides the
session/chunk split behind one `iter_events(session_dir)` call yielding a
single chronological stream. This is the shared foundation exploration code
and the eventual segmentation code both use — written now so both can share
one tested source of truth for "what does the event stream for this session
look like."

Wrote `scripts/explore_dataset_a.py` and ran it against all 63 dataset_a
sessions. Full numeric output: `reports/exploration/dataset_a_summary.json`.
Findings:

- **Corpus:** 63 sessions, mostly 2 chunks each, ~162k events total
  (matches the README). `app_switch` (50,588) and `keystroke` (38,717) are
  the two most common event types; `screenshot_smart` (34,580) is third
  but that's a fixed capture cadence, not a work signal.
- **Ground truth shape (`gt_manifest.json`):** 15 processes (codes A–O),
  5 each in `hr`/`finance`/`ops`, 2,009 total executions, median duration
  31.7s (p95 88s, one 1,144s outlier). Only 6 of the 15 processes have more
  than one variant (`std`/`exc` or `reg`/`adj`); the other 9 are single-path.
  On average only **80% of session time is covered by any labeled
  execution** — the other ~20% is exactly the "operations unrelated to any
  business process" the README warned about, and our segmenter must be
  allowed to leave time unlabeled rather than forcing 100% coverage.
- **Found a real data quality issue and fixed it in `io.py`:** ~6.7% of
  events have a *negative* `ms_since_last_event`, meaning file order (by
  `sequence_number`) isn't always chronological order. Worst case: a
  `SYSTEM upload_started` event was 12 minutes out of place relative to the
  next line in the file. Root cause looks like SYSTEM/L1 events being
  appended by a different internal pipeline than L2/L3 capture, so their
  write order can lag their timestamp. Fixed by sorting each chunk's events
  by `timestamp_ms` before yielding, in `iter_events`.
  **Follow-on finding:** re-running after the fix produced identical
  min/max gap values — because `ms_since_last_event` is a field the
  recording agent computed itself (at write time), not something we derive.
  So the field is unreliable exactly where it matters (the ~6.7% out-of-order
  cases), independent of how we sort on our end.
  **Decision:** when the real segmentation code needs an idle-gap signal,
  compute gaps ourselves from our own sorted `timestamp_ms` values, not
  from the provided `ms_since_last_event` field.
- **Found 257 of 2,009 executions (12.8%) have `end_ts: null`** in
  `gt_manifest.json`. Checked: not correlated with the
  `continues_to_next` flag (only 63 executions have any continuation flag
  set at all). Cross-referenced against `gt.jsonl`'s event counts
  (99 `process_suspended` vs 190 `process_resumed` — more resumes than
  suspends within the same session logs) — consistent with some processes
  being suspended and only resumed in a *different* session's recording, so
  this session's ground truth genuinely has no end time for them. Decision:
  these 257 executions will be excluded from strict boundary-accuracy
  scoring in Step 1 validation (there's nothing to score them against), and
  this will be stated explicitly in the report rather than silently dropped.
- **The core question — do raw event signals predict ground-truth
  boundaries?** Measured nearest-event and nearest-app_switch time deltas
  at all 3,761 boundary timestamps (execution starts+ends), against a
  random-timestamp control group from the same sessions.
  - Boundaries sit far closer to *some* recorded event than random points
    do (median 192ms vs 857ms).
  - **App switches specifically: boundary median delta 204ms vs control
    median 3,299ms — 16x tighter.** 61.3% of all boundaries fall within
    500ms of an app_switch event.
  - But that means ~39% of boundaries are *not* near an app switch. Checked
    what the single nearest event actually is for every boundary:
    `app_switch` 55.6%, `browser_navigation` 22.9%, `screenshot_smart`
    15.0% (a byproduct of capture cadence, not a driving signal),
    `mouse_click` 4.7%.
  - **Decision: app_switch + browser_navigation together are the primary
    boundary-candidate signal (~78.5% of boundaries sit right at one of
    these two event types).** The remaining ~20% need a secondary signal —
    most likely idle-gap detection and/or window-title changes — since
    those cases are process transitions that stay inside the same
    application and the same browser tab (e.g. two back-to-back executions
    of the same process in the same portal page, or a transition between
    two processes that both live in the same spreadsheet). This is expected
    to be the hardest sub-case: telling apart *two consecutive executions of
    the same process* with no app/page change between them at all.

Committed: `src/procmine/`, `scripts/explore_dataset_a.py`,
`reports/exploration/dataset_a_summary.json`, this log update.
