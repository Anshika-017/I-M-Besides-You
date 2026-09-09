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

---

## Day 1 (cont.) — Digging into the ~20-25% "hard" boundaries

Wrote `scripts/explore_same_app_boundaries.py`. Instead of looking at
execution starts/ends independently, this works at the **transition**
level: order every session's ground-truth executions by start time, and
look at each (end of execution i → start of execution i+1) pair. Output:
`reports/exploration/same_app_boundaries.json` (1,689 transitions across
61 sessions with ≥2 dated executions).

**First result overturned my own hypothesis.** I expected the hard case to
be "two back-to-back executions of the *same* process" (per the README:
"the same process appears many times a day"). Measured it directly:
**0 of 1,689 transitions have the same process code on both sides.**
Checked why — the leaked test-harness schedule found on Day 1 explains it:
the synthetic scheduler explicitly interleaves different process codes
(`[1/16] proc=P1 ... [2/16] proc=P13 ... [3/16] proc=P12 ...`), so a given
process type does recur many times in a session, but never twice in a row.
**Correction:** that specific hard case doesn't exist in this data. Noted
as a real finding, not silently dropped.

**So what actually causes the ~20-25% gap?** Pulled raw events around
several "hard" transitions (no app_switch/browser_navigation within 1s)
and found a consistent pattern: the business portals are **single-page
apps** using hash-based client routing (e.g. `127.0.0.1:5123/#/payroll-items`,
`.../#/leave-applications`) inside a small number of already-open Chrome
windows (matches the leaked setup script: "Launching Edge HR Portal...
Finance Portal... Ops Portal..." — one window per domain). In every example
inspected, the ground-truth `start_ts` for the new execution lands 3-6
seconds *before* any observable click or app_switch — i.e. there's a
built-in lag between "the test harness's internal decision to start the
next case" (what `gt_manifest.json` timestamps) and "the first visible UI
action for it" (what `events.jsonl` records). This lines up with the
README's own note that recorded wait times are compressed relative to real
usage, and with `run_config`'s `dwell_scale` field seen earlier.

**Quantified it properly** by testing how much of the 1,689-transition set
falls within increasing time windows of an app_switch/browser_navigation
event:

| window | coverage |
|---|---|
| 500ms | 59.3% |
| 1,000ms | 74.1% |
| 2,000ms | 83.4% |
| 5,000ms | 86.3% |
| **8,000ms** | **98.3%** |
| 15,000ms | 98.7% |

There's a sharp step between 5s and 8s, not a smooth tail — strong evidence
this is one consistent timing-lag effect, not a mix of unrelated causes.
Also checked `clipboard_change` and `window_title_change` as alternative
secondary signals — both fire near less than 1% of boundaries, so they're
not useful here (ruled out, not just unused).

**Residual:** 29 of 1,689 transitions (1.7%) have no app_switch/navigation
within even 8s (gaps 10s-134s, scattered across sessions/processes, no
shared pattern). Treating this as an accepted, documented limitation rather
than chasing a fix for 1.7% of cases.

**DECISION:** the segmentation heuristic will generate candidate cut
points from `app_switch` + `browser_navigation` events using a wide match
window (~8s), plus a self-computed idle-gap fallback for the residual.
**WHY:** measured, not assumed — this single change recovers boundary
coverage from 74% to 98%.

**New risk this surfaces, to address when designing the actual algorithm:**
`gt_manifest.json` shows many single executions span multiple apps (e.g.
`apps: ["chrome", "excel", "notepad"]`) — meaning plenty of app_switch
events happen *inside* one execution, not just at its boundaries. Naively
treating every app_switch as a cut point would over-segment badly. The
next design step needs a way to tell "this app switch starts a new
process" apart from "this app switch is just this process's normal
back-and-forth between apps" — candidate generation (solved above) is not
the same problem as candidate pruning/merging (not yet solved).

Committed: `scripts/explore_same_app_boundaries.py`,
`reports/exploration/same_app_boundaries.json`, this log update.

---

## Day 1 (cont.) — Over-segmentation / precision investigation

Wrote `scripts/explore_oversegmentation.py`. Question: now that
app_switch/browser_navigation events are confirmed to find ~98% of
boundaries, how many of these events fire *inside* a single execution
(where treating them as a cut would be wrong)?

**Result: this is a real, large problem, not an edge case.** Per
execution: median 2 "interior" (non-boundary) signal events, p90 = 15,
max = 142 — and 7,125 interior events total vs only ~1,689 real
transitions in the same data. A naive "every app_switch is a cut" rule
would over-segment by roughly 4-5x.

**Caught and fixed my own bug before trusting a result.** First pass at
"does a boundary's destination app already appear in the previous
execution's app set" gave a suspiciously clean 0% — turned out
`gt_manifest.json`'s `apps` field uses lowercase short tokens
(`"chrome"`, `"excel"`) while raw `app_switch` events use full display
names (`"Google Chrome"`, `"Microsoft Excel"`), so the string comparison
silently never matched anything. Fixed by comparing against apps
*actually observed* in the previous execution's own raw events instead of
the declared field (which, separately, turned out to be incomplete — e.g.
raw events show "Microsoft Word" used during an execution whose declared
`apps` list doesn't mention Word at all. Treating `gt_manifest`'s `apps`
field as approximate metadata from here on, not an exhaustive list).

**Corrected result, properly measured:** boundary-triggering switches land
on an app *also used in the previous execution* **92.3%** of the time —
the opposite of the buggy first result. This makes sense once you see it:
the whole environment only has ~5-6 apps total (chrome, excel, notepad,
onenote, outlook, word), so almost any switch reuses an app someone was
already in earlier that day. **Decision: app identity alone is not a
usable precision signal** — ruled out with evidence, not by assumption.

Tested two mitigations:
1. **Debouncing** (collapsing app_switch/navigation events that occur
   within 2s of each other into a single candidate): cuts total interior
   events from 7,125 to 3,036 (-57%), median interior-per-execution from 2
   to 1. Real reduction, but doesn't fully solve it — median is still 1,
   p90 still 4, after debouncing.
2. **Finer-grained destination identity** — `(app_name, window_title)` for
   app_switch, `(browser, url)` for browser_navigation, instead of
   app_name alone. This exploits the earlier SPA finding (different
   process = different hash route, even within the same Chrome window).
   Improves the boundary "introduces something genuinely new" rate from
   7.7% (app-name only) to **35.7%** — real, meaningful improvement, but
   still not a clean single-feature separator: 64.3% of true boundaries
   still reuse a window_title/url also seen in the previous execution
   (generic windows like plain "Notepad" or a shared portal landing page
   don't change their title/URL per case).

**Conclusion for the segmentation design:** no single feature (app
identity, fine-grained window/URL identity, or debouncing alone) cleanly
separates true boundaries from interior noise. The plan going into the
actual algorithm: (1) debounce raw candidates first (cheap, -57% noise),
(2) use fine-grained destination identity as a *weighted* signal, not a
hard rule, (3) accept the assignment's own framing that "good enough" is
a judgment call — measure actual precision/recall against dataset_a's
ground truth once built, and report the real number rather than assume one.

Committed: `scripts/explore_oversegmentation.py`,
`reports/exploration/oversegmentation.json`, this log update.

---

## Day 1 (cont.) — Designing and implementing the Step 1 algorithm

**WHAT WE DID:** Turned the last three explorations into actual, evaluated
code: `src/procmine/segment.py` (the boundary-detection algorithm),
`src/procmine/evaluate.py` (boundary-matching scorer), and
`scripts/evaluate_segmentation.py` (the driver that compares configurations
and picks one using held-out data). Scope for this pass: boundary detection
only — cutting a session into (start, end) spans. Assigning a consistent
label to each segment (so the same real process gets the same label) is a
separate step, deferred deliberately, because it needs different evidence
(feature similarity across segments) than deciding where to cut does.

**WHY this three-stage design:** directly maps to the three prior
explorations. (1) Candidate generation = debounced app_switch/
browser_navigation events + a self-computed idle-gap fallback, because
that combination was shown to sit within 8s of ~98% of true boundaries.
(2) Filtering by minimum segment duration, because interior (non-boundary)
signal events were shown to be common (median 2, up to 142 per execution)
and the shortest real execution observed is ~16.6s, so short predicted
segments are much more likely to be noise than real. (3) An optional
freshness filter (suppress a candidate if its destination was already seen
recently in the still-open segment), included as a variant to test, not
assumed to help, because the measurement showed it's a real but weak
signal (35.7% vs 7.7%, not close to a clean rule).

**HOW we evaluated it, and why a train/holdout split within dataset_a:**
`scripts/evaluate_segmentation.py` splits dataset_a's 63 sessions into 51
"dev" sessions (used to compare configurations) and 12 held-out "test"
sessions (looked at exactly once, after a configuration was already
chosen). This exists because the assignment's own overfitting warning
(dataset_a's approach may not transfer to dataset_b) is really a special
case of a more general risk — a configuration could just as easily overfit
to dataset_a's own 63 sessions as a whole. Checking generalization one
level down, where we actually have ground truth to check it against, is
cheap and catches that risk early. Evaluation metric: boundary
precision/recall/F1 via nearest-neighbor greedy matching within a 10s
tolerance (chosen because exploration showed the observable-action lag
behind a true boundary is usually under ~8s), plus mean predicted/true
segment-count ratio as an over/under-segmentation summary, plus the signed
timing error (predicted − true) for matched pairs.

**RESULT: comparing 10 configurations on the dev set** (full table in
`reports/step1/dev_comparison.json`):

| config | P | R | F1 | pred/true seg ratio |
|---|---|---|---|---|
| V1 naive (debounce only, no merging) | 0.263 | 0.968 | 0.414 | 4.51x |
| min_duration=5s | 0.338 | 0.959 | 0.500 | 3.47x |
| min_duration=8s | 0.398 | 0.949 | 0.561 | 2.91x |
| min_duration=12s | 0.487 | 0.929 | 0.639 | 2.32x |
| **min_duration=15s** | **0.533** | **0.919** | **0.674** | **2.09x** |
| min_duration=20s | 0.506 | 0.683 | 0.582 | 1.63x |
| min_duration=8s + freshness filter | 0.458 | 0.878 | 0.602 | 2.34x |
| min_duration=15s + freshness filter | 0.556 | 0.797 | 0.655 | 1.74x |
| min_duration=12s, no idle fallback | 0.493 | 0.927 | 0.644 | 2.29x |

**WHAT IT MEANS:**
- V1 (the "obvious" naive baseline — cut on every debounced app switch)
  confirms the over-segmentation problem is exactly as bad as measured
  during exploration: 4.5x too many segments, precision 0.26.
  Min-duration merging is doing real, substantial work.
- Precision rises monotonically with min_duration up to 15s, then recall
  collapses at 20s (0.919 → 0.683) as real short executions start getting
  merged away — this lines up exactly with the ~16.6s shortest observed
  execution, and gives an evidence-based reason the sweep didn't need to
  go higher.
- The freshness filter *does* help at low min_duration (8s: F1 0.561 →
  0.602) — it's doing some of the same job min_duration merging does at
  higher thresholds — but once min_duration is already at 15s, it makes
  things worse (F1 0.674 → 0.655): it trades away real recall (0.919 →
  0.797) for a small precision gain, a bad trade given recall was already
  the stronger side of the ledger. **Decision: don't ship the freshness
  filter** — confirmed by measurement, not by the a priori "app identity
  is weak" finding alone.
- Removing the idle-gap fallback made no real difference (F1 0.639 vs
  0.644) — expected, since it only targets a ~1.7% edge case. Left it on:
  free (essentially neutral on dataset_a) and should matter more wherever
  behavior differs, e.g. dataset_b.

**DECISION:** ship `min_duration_ms=15000, debounce_ms=2000,
idle_gap_ms=8000, use_idle_fallback=True, use_freshness_filter=False` —
best dev F1 (0.674), and it's the configuration set as
`SegmentationConfig`'s defaults in `src/procmine/segment.py`.

**RESULT: held-out test set (12 sessions, never touched during the
comparison above):** precision 0.545, recall 0.937, **F1 0.689** — matches
(in fact very slightly exceeds) the dev F1 of 0.674. This is the outcome
we wanted from the split: if test F1 had been much lower than dev F1,
that would mean the config was fit to dev's specific sessions rather than
to the real underlying pattern. It wasn't.

**Failure inspection (dev set, so the held-out test set stays untouched
for future use):** categorized every false positive as either a "near
miss" (within 20s of some true boundary — likely just the observable-
action lag pushing a real detection past the 10s match window) or "far"
(more than 20s from any true boundary — a genuinely spurious cut).
Result: **62.1% of false positives are near-misses, 37.9% are far.**
Pulled a concrete "far" example and found it's at the very start of a
session, during `WindowsTerminal` activity — this is the test harness's
own setup script running (the same leaked "Theme M2 - Run Setup" terminal
capture seen earlier), which is real, correctly-detected activity that
simply isn't a business process at all, so ground truth has no boundary
there for it to match. **This is a real limitation but not entirely a
segmentation bug**: the current algorithm has no notion of "process vs.
non-process time" (that's deferred to the labeling stage per the module
docstring), so some of its "false positives" are actually correct cuts in
time that was never going to be labeled a process to begin with.

**Tolerance sensitivity (same frozen config, not re-tuned — a diagnostic
on the config already chosen above, run on the test set):**

| tolerance | P | R | F1 |
|---|---|---|---|
| 5s | 0.273 | 0.470 | 0.346 |
| 10s (primary, used for selection) | 0.545 | 0.937 | 0.689 |
| 15s | 0.561 | 0.964 | 0.709 |
| 20s | 0.562 | 0.966 | 0.711 |

Recall keeps climbing up to 15-20s tolerance (0.937 → 0.966) then flattens
— consistent with the earlier finding that ~98% of boundaries have a
signal event within 8s. Precision, however, plateaus around 0.56 even at
generous tolerance — meaning roughly 44% of predicted cuts genuinely don't
correspond to a nearby true boundary, not just a timing-tolerance artifact.
Some of that is the noise-time detections described above; the rest is
real residual over-segmentation that minimum-duration merging alone
doesn't catch.

**LIMITATIONS, stated plainly:**
- Recall is strong (~94-97% depending on tolerance) — the algorithm rarely
  misses a real transition.
- Precision is moderate (~54-56%) — roughly every other predicted segment
  either isn't a real boundary or falls in genuinely unlabeled (noise)
  time. This is the main known weakness of this baseline.
- No process/noise classification yet — deferred to labeling. Once
  segments get labeled, filtering out segments that don't look like any
  real process cluster should recover some of that precision loss "for
  free," but that's not measured yet and shouldn't be assumed to fully
  fix it.
- A content/similarity-based merge pass (comparing adjacent segments'
  features rather than just duration) is the natural next lever if more
  precision is needed later — not implemented now, to keep this baseline
  simple and match the assignment's "don't over-build, state what you
  deferred" guidance.

Added `tests/test_segment.py` and `tests/test_evaluate.py` — small unit
tests against synthetic event lists (no dataset needed) for the core
logic: debounce collapsing bursts, min-duration merging dropping/keeping
boundaries correctly, segments tiling a session with no gaps/overlaps,
and the boundary matcher being one-to-one (not many-to-many) and
tolerance-respecting. Installed `pytest` (`requirements.txt` added — the
only dependency; `src/procmine/` itself uses only the standard library on
purpose). All 12 tests pass.

Committed: `src/procmine/segment.py`, `src/procmine/evaluate.py`,
`scripts/evaluate_segmentation.py`, `reports/step1/{dev_comparison,
test_result,chosen_config}.json`, `tests/`, `requirements.txt`, this log
update.
