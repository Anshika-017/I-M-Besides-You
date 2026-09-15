# Work Log

Running record of what was actually done, in order. Written as work happens,
not reconstructed afterward.

## GenAI usage (required disclosure per README.md)

Claude Code (Anthropic's AI coding agent) was used throughout the
assignment as a development and analysis assistant. It was used for
exploring the provided datasets, implementing the process-segmentation
and labeling pipeline, running experiments and analyses, developing the
automation prototype, testing, debugging, and maintaining documentation.
Claude Code also executed the pipelines and generated the reported
intermediate and final results from the provided data. The assignment
workflow was carried out iteratively, with findings from earlier analyses
informing subsequent implementation and investigation. Dataset A ground
truth was used for developing and evaluating the Step 1 approach, while
Dataset B was kept separate during development because it had no ground
truth. The final pipelines and key numerical results were rerun during
the submission audit to verify consistency. My role was to provide the
task direction, constraints, and major decisions, and to review the
resulting work and final outputs.

## How this log is organized

The entries below follow the actual technical sequence of work: reading
the assignment and understanding Dataset A/B, Dataset A exploration,
boundary analysis, segmentation, labeling, applying the frozen pipeline to
Dataset B, Task 2 process mining and candidate selection, Task 3
feasibility investigation, the automation prototype, and final
validation. That sequence maps onto four broad stages of actual work,
not a literal five-calendar-day schedule:

- **Initial understanding and preparation** — reading the assignment and
  data schema, and resolving the incomplete `dataset_a` zip, on
  2026-09-08, before `git init`.
- **Main implementation and experimentation** — the bulk of the technical
  build: Dataset A exploration through segmentation, labeling, applying
  the frozen pipeline to Dataset B, Step 2's process mining, and Step 3's
  feasibility investigation and working prototype. Per `git log`, this
  happened in one concentrated, continuous session on 2026-09-09 (commit
  timestamps span 09:54-12:12, +0530), including the self-verification
  pass that closed out that session (documented below as "Final
  submission audit").
- **Continued review, modification, validation, and refinement** — in the
  days following, going back over the outputs, deepening understanding of
  the implementation, and re-checking results before treating the
  submission as final. This didn't produce new commits (the technical
  artifacts and their audit were already complete at the end of the main
  session above) — it's read/review time, not additional development.
- **Final documentation and submission audit** — revisiting the wording of
  this log's own framing and the GenAI-usage disclosure for accuracy
  immediately before submission, git-verified as later, separate commits.

`FINAL_REPORT.md` §10 maps this same work onto the README's specific
"7 days" duration question, and distinguishes that mapping from the actual
execution timeline above.

---

## Initial Understanding and Preparation (September 8), Leading Into Implementation

### Reading the assignment, and the Dataset A packaging problem

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

**While inspecting dataset_b's raw events, found an incidental data-quality
issue**: one `app_switch` event's `extracted_text` captured the on-screen
output of the test harness's own setup script ("Theme M2" generator),
showing process codes (`P1..P13`), named variants (e.g.
`V3_manager_entertain`), and an operator/department. Checked how often this
recurs — found it in 9 of 20 dataset_b chunks. **Decision:** this incidental
capture is excluded from ground truth, from any tuning or threshold
selection, and from the actual pipeline (`segment.py`, `label.py`,
`run_step1_dataset_b.py` never read or reference it anywhere) — the README
is explicit that Dataset B has no ground truth, and this artifact doesn't
change that. It is retained here only as a documented data-quality caveat.
Later in this log it is occasionally used purely as interpretive color to
help explain an already, independently measured pattern (e.g. why process
codes never repeat back-to-back in the transition-level analysis below) —
never as evidence for any threshold, metric, or decision.

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

### Initial Dataset A exploration and data-quality findings

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

This gave enough of a picture of Dataset A's shape and its real data-quality
issues to start designing Task 1's actual approach. The next question —
whether raw event signals predict ground-truth boundaries at all — is where
the segmentation work below picks up (same script run).

---

## Main Implementation — Task 1: Raw Operation Logs → segments.jsonl (September 9)

### Dataset A boundary analysis: do raw event signals predict ground-truth boundaries?

**The core question.** Measured nearest-event and nearest-app_switch time
deltas at all 3,761 boundary timestamps (execution starts+ends), against a
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

Committed (same commit as the initial-exploration findings above — one
script, one run, one commit): `src/procmine/`, `scripts/explore_dataset_a.py`,
`reports/exploration/dataset_a_summary.json`, this log update.

### Digging into the ~20-25% "hard" boundaries

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
Checked why — the leaked test-harness schedule found during initial
exploration above explains it:
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

### Over-segmentation / precision investigation

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

### Designing and implementing the segmentation algorithm

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

### Labeling: assigning consistent labels to segments

**WHAT WE DID:** Built `src/procmine/features.py` (turns a segment into a
description of what happened during it) and `src/procmine/label.py`
(clusters segments by that description, so the same real process gets the
same cluster/label across sessions), evaluated via
`scripts/evaluate_labeling.py`, using the same dev/test session split as
the segmentation stage (factored the split logic into
`io.split_dev_test` so both scripts use the exact same split).

**WHY clustering, not classification:** the assignment is explicit that
dataset_b has different processes and different applications than
dataset_a. There is no fixed set of classes to train a classifier against
that would mean anything on dataset_b — so the labeling method has to
discover groups from feature similarity alone, with no notion of "these
are the 15 possible processes" baked in anywhere.

**Feature design, checked before building, not assumed:** looked at how
much of dataset_a's ground truth executions have `context.extracted_text`
available — **99.5%**, median ~2,225 characters per execution. Far richer
than the raw "~4% of events" figure in DATA_SCHEMA.md suggests (over a
~30s execution with dozens of events, at least one usually catches
screen text). That justified making text a first-class feature, not an
afterthought. Three feature groups per segment:
  - `app_counts` — which applications were active during the segment
    (from `context.active_app`, present on nearly every event).
  - `route_counts` — browser routes visited, using the SPA hash-route
    finding from the boundary analysis above, with numeric/ID-looking path segments replaced by
    a placeholder so `#/cases/482` and `#/cases/119` count as the same
    route rather than looking unrelated.
  - `text` — all `extracted_text` seen during the segment, vectorized as
    character 2-3-gram TF-IDF (word-level tokenization doesn't apply
    cleanly to Japanese without a dedicated segmenter, and character
    n-grams are a standard lightweight approach for CJK text that avoids
    that dependency).

**Clustering method:** `AgglomerativeClustering` with `distance_threshold`
(not a fixed `n_clusters`) and cosine distance, average linkage.
`distance_threshold` instead of `n_clusters` specifically because we don't
know in advance how many distinct processes dataset_b has — a method that
discovers the count from a similarity threshold is the only kind that can
run on dataset_b without secretly depending on an answer we don't have.

**Two-phase evaluation, why:** Phase 1 clusters the TRUE (ground-truth)
executions — this isolates "is clustering itself any good" from "how much
does our own segmentation noise hurt it." Phase 2 clusters what our own
frozen boundary detector (from the previous entry) actually produces,
scored by giving each predicted segment a "pseudo-true" label via majority
time-overlap with a ground-truth execution (or `NOISE` if no execution
covers at least half of it — these are excluded from clustering-quality
scoring, but their share is reported, since it's a real limitation the
segmentation stage already flagged: predicted segments include noise
time, which has no process to be labeled correctly against).

**RESULT: threshold sweep found a real plateau, not a single lucky
point.** First pass with a coarse grid (0.3/0.5/0.7/.../1.3) showed
quality collapsing sharply somewhere between 0.3 and 0.5 down to a single
giant cluster. A finer grid resolved what was actually happening: a
stable plateau from 0.25 to 0.32 (V-measure 0.567-0.570 throughout,
`cat_plus_text` feature set), then a real cliff by 0.35 (V-measure drops
to 0.500) and total collapse by 0.7+. **Decision: ship threshold 0.30**,
the middle of that plateau — not 0.32 (which the raw argmax picked, tied
on dev but sitting right at the edge before the cliff) — because a value
from the plateau's interior is more likely to still work when the
underlying vocabulary changes (dataset_b), where the exact location of
the cliff can't be checked in advance.

**RESULT: feature-set comparison** (3 variants x thresholds, on dev):
`cat_plus_text` (equal-weighted apps/routes + text) consistently beat both
`cat_only` (peaks lower, ~0.53 V-measure, and its own plateau is narrower)
and `text_heavy` (double-weighted text — peaks around the same ~0.53-0.54,
text alone isn't enough either). **Decision: ship `cat_plus_text`
(equal weighting)** — confirmed by measurement that neither feature group
alone is sufficient; they're complementary, not redundant.

**RESULT: held-out test set, oracle segments** (328 segments, thr=0.30):
ARI 0.206, **V-measure 0.622** (homogeneity 0.592, completeness 0.654),
25 discovered clusters vs. 15 true process classes. Test V-measure
slightly exceeds dev (0.622 vs 0.570) — again the reassuring direction
(no sign of overfitting to dev's specific sessions).

**RESULT: held-out test set, our own predicted segments, same frozen
config carried over from Phase 1 (not re-tuned — see below for why):**
698 predicted segments, 20.5% pseudo-labeled `NOISE` and excluded; of the
remaining 555, ARI 0.128, **V-measure 0.509** (homogeneity 0.530,
completeness 0.489), 53 discovered clusters vs. 15 true classes. Real
degradation from the oracle-segment number (0.622 → 0.509, about -18%
relative), attributable to segmentation noise feeding fragmented/impure
segments into clustering — an honest, expected cost, not a surprise.

**A deliberate methodology fix worth recording:** the first version of
Phase 2 independently re-swept thresholds on the predicted-segment data
and picked whatever maximized V-measure there — landing on threshold
0.20, which produced 350 clusters on dev (vs. 15 true classes): mostly
tiny/singleton clusters, which inflates homogeneity almost by definition
(a cluster of size 1 can't be internally impure) while completeness
suffers. **Caught this before reporting it as a real result.** Re-tuning a
second, different threshold specifically for the noisy predicted-segment
case would mean tuning against exactly the kind of information we won't
have on dataset_b — we don't get to pick a labeling threshold knowing our
segmentation's specific error pattern there either. Fixed by carrying the
Phase-1-chosen config over unchanged into Phase 2, using Phase 2 purely as
a diagnostic for "how much does segmentation noise cost the config we
already committed to" — not as a second, independent tuning pass.

**Failure inspection — what's actually being confused:** pulled the
most-confused true-label pairs (segments from two different true
processes landing in the same cluster). Both oracle and predicted-segment
test runs show the same pattern: confusion concentrates heavily among
`A, C, D, E` — four of the five **HR-domain** processes (resident tax
notification, childcare/maternity leave, social insurance correction,
new-hire verification):
```
oracle test:    (D,N) (C,D) (D,E) (E,N) (C,E) (C,N) (A,C) (A,D)
predicted test: (D,N) (C,D) (C,E) (C,N) (E,N) (C,M) (D,E) (E,M)
```
**WHAT IT MEANS:** processes in the same department share enough
vocabulary and portal UI text (generic HR-portal navigation labels, common
form fields) that character n-gram TF-IDF alone can't always tell them
apart, even though it clearly separates *different* domains well (finance-
vs-ops-vs-HR pairs are notably absent from the confused list). The `(D,N)`
pair recurring at the top (D=HR social-insurance correction, N=ops
shipment tracking — different domains) is the one cross-domain outlier
worth flagging as unexplained rather than quietly ignored — didn't dig
further into why, noted as an open question rather than invented an
explanation.

**LIMITATIONS, stated plainly:**
- Labeling quality is real but well short of perfect: V-measure ~0.62
  under ideal (oracle) segmentation, ~0.51 once realistic segmentation
  noise is included. A meaningful fraction of same-process segments will
  land in different clusters (or vice versa), concentrated among
  same-domain processes.
- The clustering over-produces clusters relative to true classes (25 vs
  15 oracle, 53 vs 15 predicted) — some real processes are being split
  into more than one cluster (e.g. by execution variant, or by which
  specific apps happened to be used). Not measured separately from the
  "wrong merges" failure mode in this pass; homogeneity/completeness
  above capture the aggregate effect but a variant-level breakdown would
  be the natural next diagnostic if more precision were needed.
- No attempt yet to detect and exclude "noise" segments as their own
  category during labeling itself (Phase 2's `NOISE` pseudo-labels are
  only used for *evaluation*, not fed back into the pipeline) — on
  dataset_b, non-process segments will get clustered and labeled like
  anything else. Flagged here, not fixed, in the interest of shipping an
  explainable baseline first per the assignment's own guidance not to
  over-build.

Added `tests/test_features_label.py` (6 tests: route normalization
collapses IDs but keeps distinct pages distinct, feature extraction
collects apps/routes/text correctly, empty segments don't crash the
cosine-distance clustering, single-row input is handled). All 18 project
tests pass. Added `scikit-learn`/`scipy` to `requirements.txt` (the only
new dependencies — TF-IDF vectorization and agglomerative clustering
would be a lot of code to hand-roll correctly, and both are standard,
widely-used tools for exactly this).

Committed: `src/procmine/features.py`, `src/procmine/label.py`,
`scripts/evaluate_labeling.py`, `reports/step1/labeling_results.json`,
`tests/test_features_label.py`, `requirements.txt`, `io.py` refactor,
this log update.

### Freezing the Step 1 configuration, applying it to Dataset B, producing segments.jsonl

With both segmentation (`SegmentationConfig` defaults) and labeling
(`LabelingConfig` default threshold 0.30, `cat_plus_text` features)
validated on Dataset A's held-out test split, both configs are now
**frozen** — no further tuning against either dataset from this point on.

**WHAT WE DID:** Wrote `scripts/run_step1_dataset_b.py` and ran it once.
It applies `SegmentationConfig()` and `LabelingConfig()` with their
already-chosen defaults — no thresholds touched, nothing re-tuned — to
all 15 dataset_b sessions, then writes `segments.jsonl` at the repo root
in the exact format the README specifies.

**Compliance notes, checked explicitly, not assumed:**
- Dataset_b's ground truth doesn't exist, so there was nothing to peek at.
  The one thing that COULD have been misused — the leaked test-harness
  setup-script text found during initial exploration — is not read, parsed, or referenced
  anywhere in this script or the pipeline it calls. It's just ordinary log
  content the pipeline treats the same as any other `extracted_text`.
- Clustering was run **jointly across all 15 sessions at once** (not
  per-session), since the deliverable requires the same real process to
  get the same label even when it recurs in a different session.
- Verified `segments.jsonl` programmatically: 456 lines, all valid JSON,
  each with exactly the four required keys (`session_id`, `start`, `end`,
  `label`), all timestamps matching the `YYYY-MM-DDTHH:MM:SSZ` format from
  the README's own example, `start < end` on every line.

**RESULT:** 15 sessions -> 456 segments (24-49 per session, roughly
tracking each session's event count) -> **99 distinct clusters/labels**.
Cluster label strings are derived from each cluster's most common
app + browser route (e.g. `proc_04_microsoft-edge_onboarding`) — readable
enough to sanity-check by eye, though per the assignment the label text
itself isn't what's evaluated.

**HOW WE TURNED A CLUSTER INTO A LABEL:** the label string is not the
process's real name (we have no way to know that without asking the
client) — it's `proc_<cluster_id>_<dominant app>_<dominant browser
route>`, built purely from what the pipeline itself observed. This keeps
the label traceable back to *why* the pipeline grouped those segments
together, which matters for the Step 2 write-up.

**A visible limitation, honestly reported, not smoothed over:** several
different cluster IDs share the same dominant route in their label —
e.g. `proc_42`, `proc_13`, `proc_43`, `proc_83`, `proc_40`, `proc_41` are
all `..._payroll-items`, and `proc_03`/`proc_09`/`proc_08`/`proc_06` are
all `..._leave-applications`. That's the same over-clustering pattern
already measured and disclosed during labeling evaluation (25 discovered
clusters vs. 15 true classes on dataset_a's oracle test, worse — 53 vs.
15 — once real segmentation noise was included) — now visible again on
unfamiliar dataset_b vocabulary, where it's plausible the threshold
transfers even less cleanly than it did within dataset_a itself. 99
clusters for what's very likely well under 20 real recurring paperwork
types (typical for a back-office department, and roughly matching what
the earlier — not relied upon — incidental schedule text suggested) is a
real, visible sign of over-fragmentation on this dataset.

**DECISION: did not attempt to fix this by adjusting anything now.**
Two reasons. First, doing so *in response to looking at dataset_b's
specific output* is exactly the kind of dataset_b-informed tuning the
task explicitly rules out, even if the "fix" (e.g., a generic
same-signature cluster-merge pass) sounds dataset-agnostic in the
abstract — the trigger for adding it right now would still be dataset_b's
result, not evidence from dataset_a. Second, this is a pre-existing,
already-disclosed limitation of the labeling stage, not a new discovery —
the honest thing to do is let it show up as expected and document it, not
patch it selectively. Any future fix (e.g., a same-app/route consolidation
pass, or a coarser fallback threshold) would need to be designed and
validated back on dataset_a's ground truth first, the same discipline
used for every decision so far, before it could be trusted on dataset_b.

**Also worth stating plainly for whoever reads `segments.jsonl` next:**
per the segmentation-stage evaluation, an estimated ~18-20%-ish share of
predicted segments don't correspond to any real business process at all
(idle/administrative/recording-artifact time) — that finding came from
dataset_a's ground truth and generalizes as an expectation, not a
guarantee, to dataset_b. `segments.jsonl` does not filter these out (no
noise classifier exists yet — flagged, not built, consistent with earlier
decisions), so Step 2's analysis needs to treat low-frequency,
never-recurring labels with appropriate skepticism rather than at face
value. The `singleton_clusters` field in
`reports/step1/dataset_b_segmentation_summary.json` (30 of 99 clusters,
6.6% of all segments) is a *different*, weaker measurement of a related
idea — clusters that never recur across all 15 sessions — not a direct
stand-in for the dataset_a noise-rate estimate; the two aren't directly
comparable and shouldn't be read as agreeing or disagreeing with each
other.

Committed: `scripts/run_step1_dataset_b.py`, `segments.jsonl`,
`reports/step1/dataset_b_segmentation_summary.json`, this log update.

---

## Main Implementation — Task 2: Process Mining + Automation Candidate Selection

### Process mining on dataset_b's segments.jsonl

**WHAT WE DID:** Built `src/procmine/analyze.py` and
`scripts/step2_analysis.py` to profile the 456 Step 1 segments — frequency,
duration, recurrence, headcount, variants — and produce a ranked automation
candidate list. Report: `reports/step2/step2_report.md`. Raw artifacts:
`reports/step2/{label_stats,process_groups,process_families,
consolidation_groups,transitions,candidate_ranking*}.{json,csv}`.

**WHY:** `segments.jsonl` and Step 1's own evaluation already told us the 99
discovered labels over-fragment the real process count (dataset_a's oracle
validation: 25 clusters vs. 15 true classes). Analyzing the 99 raw labels
as if they were 99 real processes would misrepresent frequency/impact for
ranking purposes — so before ranking anything, needed an evidence-based way
to see which labels likely represent the same practical process.

**HOW:** Read `segments.jsonl` as-is (never modified, never re-segmented —
checked via `git diff` before writing anything). Re-extracted per-segment
app/route/text features (same `features.py` used in Step 1) purely for
descriptive analysis. Built a three-level view: 99 raw labels → 40 groups
(labels whose feature centroids are close in the *same* space Step 1's
clustering used) → 8 process families (groups sharing a top-level SPA
route, e.g. `#/payroll-items`). Headcount came from `source.machine_id`/
`username_hash` in the raw events (4 distinct operators, cross-checked
against session-dir naming) — genuine log data, not the leaked
test-harness text, which is referenced nowhere in this analysis.

**WHAT WE FOUND (a failed approach worth recording):** the first
consolidation attempt connected any pair of labels with centroid cosine
similarity ≥ 0.5 and took connected components (union-find over a
threshold graph = single-linkage clustering). It chained catastrophically:
95 of 99 labels collapsed into one meaningless mega-group, because
individually-reasonable pairwise links transitively pulled almost
everything together. Caught this before reporting it (the result was
obviously wrong — one "group" holding 452/456 segments). Fixed by using
average-linkage agglomerative clustering on the centroids instead (same
kind of algorithm Step 1 itself used, one level up), checked via a
threshold sweep (0.30→0.60) to confirm sane behavior before trusting it
(40 groups at 0.40, largest group 13 members, no runaway collapse until
much higher thresholds). Added a regression test for this specific failure
mode (`test_cluster_centroids_does_not_chain_everything_together`).

**WHAT WE FOUND (substantive results):** 456 segments = 10,574.0s total,
matching the summed session span (10,574.8s) almost exactly — confirms
segments tile sessions with no gaps, a sanity check that had to pass before
trusting anything downstream. Five families look like real recurring
processes (89.7% of all segments, 89.5% of all time): **payroll-items**
(138 segments, 31.4% of time, 15/15 sessions, 4/4 operators),
leave-applications (100, 21.5%, 14/15), onboarding (83, 16.4%, 11/15),
social-insurance (56, 12.3%, 11/15), resident-tax (32, 7.9%, 7/15). Three
families (`http:`, `dashboard`, `no_route`, 10.3% combined) look like
inter-task navigation/landing-page activity rather than distinct paperwork
— excluded from candidacy, stated explicitly rather than silently dropped.

**WHAT DECISION:** ranked candidates with a transparent weighted formula
(frequency 0.35, time 0.25, consistency 0.20, recurrence 0.10, headcount
0.10 — rationale in the report) — no invented dollar/hour figures, since
the README explicitly says recorded wait times are compressed relative to
real production use. **Recommended Step 3 candidate: payroll-items** —
highest on every raw dimension (also #1 by frequency alone and by time
alone, not just the weighted composite — checked this robustness
explicitly), and notably more single-application-focused than the next two
candidates (75% of its activity in one app vs. 56-58% for
leave-applications/onboarding, which genuinely span browser + Word) — a
narrower, more tractable automation surface for a 7-day prototype.

**Self-audit performed before committing** (all passed): per-label,
per-group, and per-family segment counts each independently sum to 456;
every label/group/family's session count ≤15 and operator count ≤4;
`segment.py`/`label.py` (the frozen Step 1 configs) show zero diff since
their last commit — no dataset_b-informed tuning was introduced anywhere in
Step 2; grepped the Step 2 code for any reference to the leaked
"Theme M2"/generator text — none found except a comment explicitly stating
it's not used.

**LIMITATIONS, stated in the report, not hidden:** no ground truth exists
for dataset_b at any level, so all of this is inference built on Step 1's
own imperfect, already-measured output (some fraction of the 456 segments
are very likely non-process time, per dataset_a's ~18-20% finding, with no
current way to detect which ones on dataset_b); duration numbers are
relative-comparison-only, not absolute time-savings claims; family labels
are inferred from observed SPA routes, not client-confirmed process names;
the ranking weights are a disclosed judgment call.

Added `tests/test_analyze.py` (6 tests, including the union-find-failure
regression test). All 24 project tests pass.

Committed: `src/procmine/analyze.py`, `scripts/step2_analysis.py`,
`reports/step2/` (report + all data artifacts), `tests/test_analyze.py`,
this log update.

**NEXT:** Step 3 — build the automation prototype for payroll-items. Per
the report's §9, first need to look at the actual route/event sequence
inside payroll-items' dominant variant group before deciding what slice of
the workflow is realistically automatable.

---

## Main Implementation — Task 3: Feasibility Investigation + Automation Scope

### Feasibility investigation, before building anything

**WHAT WE DID:** Wrote a read-only tracing tool
(`scripts/trace_workflow.py`) and used it to reconstruct the actual raw
event sequence for representative executions of `group_009` (Step 2's
dominant payroll-items variant, 107/138 segments in that family), then
cross-checked findings against a broader sample. Wrote up findings in
`reports/step3/payroll_items_feasibility.md`. No code touching Step 1/2
(`segment.py`, `label.py`, `segments.jsonl`) was changed.

**WHY:** the assignment explicitly warns that ideas need feasibility
assessment before committing to a build, and that risks should be
anticipated from evidence, not optimism. Step 2's "payroll-items" label
was itself just a route-name artifact of Step 1's labeling — needed to
verify what's actually happening in the raw events before promising to
automate anything.

**HOW:** Picked 5 representative segments from `group_009` across
different sessions/machines/durations, traced their exact
`browser_click`/`browser_form_input`/`keystroke`/`clipboard_change`
payloads (not just event-type counts), then did a corpus-wide survey:
classified every short (<100 char) `extracted_text` capture within
`group_009`'s 107 segments by its opening phrase, and separately checked
the port number embedded in each segment's `active_browser_tab.url`.

**WHAT WE FOUND — a major reframing, not a confirmation:**
"payroll-items" is not one process. It's a **generic queue-confirmation UI
template** (`#pi-table` row click → `#pi-note` textarea paste → `#btn-pi-ok`
click, repeat) reused **identically across at least 3 portals** (ports
5132/5133/5134 — HR/Finance/an ops-flavored system) for **at least 9
distinct business processes**: expense settlement (~44 notes, the largest
single sub-flow, ~40% of everything in this family), inventory adjustment
(20), invoice reconciliation (19, with a genuine approve/flag decision
branch), payroll/salary change (11), IT requests (3), purchase orders (2),
new-hire verification (2), attendance (1), contract management (1).
Classified this by literally reading the confirmation notes' business
content (Japanese text like "経費精算確認済み" / "在庫調整登録" /
"請求書照合完了"), not by assuming.

Also found: a genuine, on-screen fragment of a real expense-policy
regulation document (not the leaked generator text — legitimate
`extracted_text` capturing an actual on-screen document) confirming the
"within regulation" check has a discoverable written rule behind it, at
least for entertainment expenses; a second, different note template
("経費承認（管理職）...") suggesting a management-tier escalation path for
higher-value cases; and that 100% of 46 observed expense-settlement notes
were approvals (zero observed rejections) — treated explicitly as "we
haven't seen a rejection," not as "rejections don't happen."

**WHAT DECISION:** Do not scope Step 3 as "automate payroll" — the evidence
doesn't support that framing at all. Scope it to the single largest,
best-characterized, lowest-ambiguity concrete sub-flow: **expense
settlement confirmation** (~40% of the family, a simple bounded
threshold-check decision, one template, no observed exceptions). Explicitly
exclude the other 8 sub-flows and the management-escalation tier from the
prototype, stating them as deferred future work built on the same shared
mechanical pattern, not silently dropped. Recommended implementation form:
**Playwright-based browser automation**, not an AI agent or a heavier RPA
suite — the mechanical steps are 100% deterministic browser DOM
interactions with confirmed stable selectors, and the in-scope decision is
a bounded threshold check, not open-ended judgment an LLM's flexibility
would actually help with (that tradeoff is revisited as a real future
option, given the pattern's 9-domain reuse, once each domain's actual
rules are confirmed with the client).

**Compliance checked explicitly:** grepped the investigation for any use of
the leaked "Theme M2" text — none; all quoted evidence is genuine on-screen
`extracted_text` captured during real recorded interaction (fair use per
`DATA_SCHEMA.md`). Confirmed via `git diff` that `segment.py`/`label.py`/
`segments.jsonl` remain untouched.

Ran the full test suite after adding `scripts/trace_workflow.py` — all 24
tests still pass (no regressions; this script has no pure logic worth unit
testing beyond what `analyze.py`'s existing `iso_to_dt`/timestamp tests
already cover).

**NEXT:** Build the Step 3 prototype per this scope — not started yet.

---

## Main Implementation — Task 3: Working Prototype, and the Session-Closing Audit

### Building the working prototype

**WHAT WE DID:** Built and ran a genuine, working automation prototype for
the expense-settlement confirmation sub-flow identified in the feasibility
investigation — not pseudocode. Files: `automation/decision.py` (business
rule), `automation/mock_app.py` (Flask reproduction of the observed queue
UI), `automation/sample_data.py` (deterministic demo data),
`automation/run_automation.py` (Playwright driver), plus
`tests/test_step3_decision.py` and `tests/test_step3_integration.py`.
Full writeup: `reports/step3/step3_prototype.md`.

**WHY:** the feasibility investigation explicitly ruled out "automate
payroll-items" and scoped Step 3 down to one concrete, well-evidenced
sub-flow. Building anything broader than that would contradict the
investigation's own conclusion.

**HOW:** Before writing `decision.py`, went back to the raw dataset_b
events one more time (not just re-used the feasibility doc's summary) to
re-verify the exact evidence for every constant the rule would use — see
"what we found" below for why that mattered. Built the mock app to
reproduce only the specifically-observed DOM (`#pi-table`, `#pi-note`,
`#btn-pi-ok`, the 4th-column click, the note template) with a visible
"MOCK / REPRODUCTION" banner, since the real dataset_b application isn't
available to us. Installed Playwright + Chromium and Flask (added to
`requirements.txt`).

**WHAT WE FOUND (a real correction made before shipping the rule, not
after):** re-searching for the full, non-truncated version of the one
policy-regulation text found in dataset_b turned up something the
feasibility doc's brief mention hadn't fully resolved: a complete capture
of "接待交際費規程" (entertainment expense regulation) Article 2, with
actual numbers — under ¥50,000 needs department-head approval, ¥50,000+
needs executive approval, ¥100,000+ needs president approval. Checking
this against the routine confirmations actually observed in this queue
surfaced a real inconsistency: **all 7 observed entertainment-expense
confirmations in this queue (¥60,936–¥129,596) are already above the
¥50,000 tier**, yet went through the same "confirmed" action as everything
else. Did not resolve this by assumption. Took the conservative reading:
the one number with a real written source becomes a hard ceiling for what
the bot will auto-confirm, even though observed practice in this exact
queue looks looser than that — anything at/above ¥50,000 is routed to a
human. This is disclosed explicitly in both the code's docstring and the
report, not smoothed over.

Also computed, category by category, the full observed amount range for
all 5 eligible categories from a 43-sample survey (43 distinct routine
confirmations, zero exceptions) — this is what actually justifies treating
those 5 categories (and no others) as safe to automate, not any assumed
knowledge of company policy.

**WHAT DECISION:** Shipped a rule with exactly two gates: (1) category
must be one of the 5 directly observed with zero exceptions, (2) for
entertainment specifically, amount must be below the one confirmed written
threshold. Everything else — unknown category, missing/invalid amount,
entertainment at/above ¥50,000 — routes to human review, untouched, never
guessed at. No LLM/AI judgment anywhere in the decision path (a plain,
auditable Python function), consistent with the feasibility
recommendation that this decision is bounded/deterministic, not the kind
of open-ended judgment an LLM's flexibility would actually help with.

**Ran the prototype for real** against 9 deterministic sample items
covering every branch: **5 auto-confirmed (all independently verified by
re-reading the live DOM after clicking, not assumed from the click
succeeding), 4 routed to human review, 0 errors.** Screenshot of the final
queue state captured (`automation/output/final_queue_state.png`) and
visually confirmed it shows exactly this split. Re-ran the exact
documented command from the repo root (not just from inside `automation/`)
to confirm the run instructions work as written, and confirmed no
orphaned server process is left behind afterward.

**Self-audit before committing** (all passed): grepped `automation/` and
`reports/step3/` for the leaked "Theme M2" text — the only matches are
documentation sentences stating it was *not* used, not actual usage;
`git diff` confirms `segments.jsonl`, `src/procmine/segment.py`, and
`src/procmine/label.py` are byte-for-byte unchanged; full test suite
(35 tests: 24 from Step 1/2 + 9 decision-logic + 2 Playwright integration)
passes.

**LIMITATIONS, stated in the report, not hidden:** demonstrated against a
mock reproduction (the real dataset_b application isn't available to us),
so the DOM/auth/API behavior of the real system is unconfirmed even though
the mechanical pattern and category/note evidence are real; only 5 of 9
identified sub-flows are covered, and only the lower tier of the one
sub-flow with any confirmed threshold at all; the entertainment-expense
inconsistency above is disclosed but not resolved — a real deployment
needs the client's own answer for it, not another assumption from us.

Committed: `automation/` (all files), `tests/test_step3_decision.py`,
`tests/test_step3_integration.py`, `reports/step3/step3_prototype.md`,
`requirements.txt` update, this log update.

**NEXT:** not yet decided — final report/submission packaging, or further
prototype hardening, per the next instruction.

### Final submission audit

**WHAT WE DID:** Acted as a strict evaluator against our own work, not a
developer trying to make it look good. Re-verified every major numeric
claim by re-running the actual code fresh and diffing against committed
output (not by re-reading prior documentation), checked git history and
tracked files for secrets/oversized files/leaked-dataset material, and
wrote `FINAL_REPORT.md` as the consolidated, audit-checked top-level
report.

**WHY:** the assignment is scored after submission with no further
chances to correct mistakes — the discipline used throughout this project
(measure before trusting, catch and fix rather than assume) needed to
apply to the project's own final claims too, not just to the algorithms.

**HOW:** re-ran `scripts/evaluate_segmentation.py`,
`scripts/evaluate_labeling.py`, `scripts/step2_analysis.py`,
`scripts/run_step1_dataset_b.py`, and `automation/run_automation.py` fresh
and compared output byte-for-byte against what's committed; independently
re-parsed `segments.jsonl` directly (not via any prior summary) to check
schema/timestamps/session coverage; grepped all code (not just docs) for
leaked-generator-text markers and for invented monetary ROI figures;
grepped all documentation for "accuracy" used as a stand-in for F1/
V-measure/ARI; re-traced the specific raw event behind the Step 3
¥50,000 threshold to confirm its source app one more time; ran the full
test suite and the Step 3 demo fresh.

**WHAT WE FOUND:**
- Two genuine, previously-missing deliverable requirements: no GenAI
  usage disclosure existed anywhere, and no time-allocation reasoning
  existed anywhere, despite both being explicitly required by
  `README.md`'s Deliverables section. Neither was a methodology gap —
  both were pure documentation omissions.
- One genuine reproducibility bug: `reports/step1/labeling_results.json`
  had at one point been hand-patched (via an ad hoc script, not
  `scripts/evaluate_labeling.py` itself) to reflect the shipped
  `LabelingConfig` default (threshold 0.30) rather than the evaluation
  script's own raw argmax output (threshold 0.32 — negligibly different
  in quality, but a different number). Re-running the script during the
  audit reproduced the *old*, un-patched argmax-based numbers, silently
  diverging from what every other document in this project cites. This
  would have been an embarrassing, avoidable inconsistency to leave in a
  final submission.
- No other discrepancies: segmentation/labeling/Step 2/Step 3 numbers all
  re-derived identically from fresh runs; no leaked-text usage in any
  code path; no invented monetary figures anywhere; no "accuracy"
  mislabeling of clustering-agreement metrics; no secrets or oversized
  files in git history; `git status` clean, 10 meaningful commits, no
  history rewriting.

**WHAT DECISION:** Fixed exactly the three items above and nothing else.
Specifically for the reproducibility bug: changed
`scripts/evaluate_labeling.py` to explicitly evaluate the actually-shipped
`LabelingConfig()` default (with the plateau-robustness reasoning now
stated inline in the script itself, not left as an external, easy-to-lose
manual step), instead of changing the shipped threshold or re-tuning
anything to chase a better number. Verified the fix by re-running the
script twice independently and diffing the two runs directly against each
other (not just against git HEAD) — confirmed fully deterministic.
Did **not** touch any segmentation/labeling/ranking/decision logic,
threshold, or weight to improve a metric — every change this pass is
either new documentation or a fix that makes the code match a decision
that was already made and already documented elsewhere.

Committed: `FINAL_REPORT.md`, `WORKLOG.md` (this entry + the GenAI
disclosure), `scripts/evaluate_labeling.py` (reproducibility fix),
`reports/step1/labeling_results.json` (regenerated by the fixed script).

---

## Continued Review, and Final Documentation (the days following, before submission)

### Continued review, validation, and refinement

After the session above closed out the technical build and its own
self-verification pass, the work continued to be reviewed rather than
being treated as final immediately: going back over the outputs,
deepening understanding of the implementation, re-checking the Step 2
ranking and Step 3 scope against the underlying evidence, and generally
validating that the report's claims still held up on a second look. This
period did not produce new commits — the technical artifacts
(`segments.jsonl`, the Step 1/2/3 code, the reports, the automation
prototype) and their audit were already complete and unchanged from the
session above; this was reading and re-checking, not additional
development.

### Final documentation refinement

Immediately before submission, the wording of two things was revisited
for accuracy: this log's own organizational framing (originally described
as "Day 1-5," which read as a literal five-calendar-day schedule and was
reworded to describe the actual stages of work instead — this section),
and the GenAI-usage disclosure above (reworded to lead with the
submitter's role — direction, constraints, decisions, review — rather
than opening with a framing that overstated Claude Code's share of the
work). This is git-verified as later, separate commits from the main
implementation session. `FINAL_REPORT.md` §10 states this same
distinction explicitly.
