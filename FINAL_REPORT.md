# Final Report — From Operation Logs to an Automation Proposal

This report is the top-level narrative. Every number below was independently
re-verified against the actual committed artifacts during a final audit
pass (§13) — re-running scripts fresh and diffing output against what's
committed, not just reading prose. Detailed evidence lives in
`WORKLOG.md` (chronological, including corrected mistakes) and
`reports/{step1,step2,step3}/`.

---

## 1. Executive Summary

Given 63 sessions of ground-truthed PC-operation logs (Dataset A) and 15
sessions of ungrounded production logs (Dataset B), this project:

- Built and validated a **segmentation** algorithm (Step 1) that cuts a raw
  event stream into candidate business-process spans — held-out test
  boundary **F1 = 0.689** (precision 0.545, recall 0.937, 10s tolerance).
- Built and validated a **labeling** method (Step 1) that clusters segments
  by feature similarity so the same process gets the same label — held-out
  test **V-measure = 0.622** on oracle segments, **0.509** on our own
  predicted segments (these are clustering-quality scores, not "accuracy" —
  see §13 for why that distinction is enforced throughout this report).
- Applied that **frozen, unmodified** pipeline once to Dataset B, producing
  `segments.jsonl` — **456 segments across all 15 sessions, 99 distinct
  labels** — verified byte-for-byte reproducible from the code.
- Ran **process mining** (Step 2) on that output: found the 99 raw labels
  over-fragment the real process count, built an evidence-based 3-level
  view (99 labels → 40 groups → 8 process families), and ranked automation
  candidates with a transparent, non-monetary scoring formula.
- Ran a **feasibility investigation** (Step 3) on the top candidate before
  building anything, which overturned the candidate's own label: the
  Step 2 "payroll-items" family turned out to be a generic UI template
  shared by **9 different business processes**, not one process.
- Built a **working, tested Playwright automation prototype** for the
  single largest, best-evidenced sub-flow — expense-settlement
  confirmation — with a deterministic, fully-cited decision rule and a
  mandatory human-review fallback. Demo result, re-verified fresh during
  this audit: **5 auto-confirmed (all UI-verified), 4 routed to human
  review, 0 errors**, 35/35 tests passing.

**What this is not:** a claim to have automated "payroll," or even all of
"expense settlement." It is one narrow, well-evidenced slice, with the
rest of the discovered work explicitly scoped out and stated as future
work (§7, §11).

---

## 2. Dataset and Problem Understanding

`events.jsonl` records raw keystrokes/clicks/app-switches with no markers
for where a business process starts or ends. Dataset A (63 sessions, ~162k
events) has ground truth (`gt.jsonl`/`gt_manifest.json`: 15 processes,
2,009 executions); Dataset B (15 sessions, ~20k events, verified: 15
session directories on disk, matching `segments.jsonl`'s session set
exactly) has none.

Before any modeling: found that the originally-provided `dataset_a` zip
was incomplete (screenshots only, missing all `events.jsonl`/ground truth)
and paused until the correct multi-part export was supplied — verified the
replacement covered all 63 sessions before proceeding. See `WORKLOG.md`'s
opening entries (initial understanding and preparation).

---

## 3. Step 1 — Segmentation

**Approach:** three-stage, evidence-driven design in `src/procmine/segment.py`:
1. Candidate generation from debounced `app_switch`/`browser_navigation`
   events + a self-computed idle-gap fallback.
2. Minimum-segment-duration merging to counter over-segmentation.
3. An optional "freshness" filter (tested, not assumed to help).

**Experiments / failed approaches (recorded honestly, not smoothed over):**
- Found and fixed a chronological-ordering bug: ~6.7% of events have file
  order that doesn't match timestamp order (worst case, a `SYSTEM
  upload_started` event 12 minutes out of place). Fixed by sorting each
  chunk by `timestamp_ms` in `iter_events`. Follow-on: the recording
  agent's own `ms_since_last_event` field is unreliable for the same
  reason — the segmentation code computes gaps itself instead.
- Hypothesized the hardest boundary case would be "two back-to-back
  executions of the same process." Measured it directly: **0 of 1,689**
  transitions have the same process on both sides — the synthetic
  scheduler always interleaves process types. Hypothesis rejected with
  evidence, not assumed away.
- Found the real hard case instead: SPA (single-page-app) portals where
  the ground-truth boundary timestamp precedes the first observable UI
  event by several seconds. Widening the candidate-matching window from 1s
  to 8s recovered boundary coverage from 74% to 98.3%.
- Quantified the resulting over-segmentation risk directly: a naive
  "every switch is a cut" rule produces ~4-5x too many segments (median 2,
  up to 142, non-boundary switches inside a single true execution).

**Final configuration** (`SegmentationConfig` defaults, `src/procmine/segment.py`):
`debounce_ms=2000, min_duration_ms=15000, idle_gap_ms=8000,
use_idle_fallback=True, use_freshness_filter=False`. Chosen by comparing
10 configurations on a 51-session dev split of Dataset A, selected by F1,
then confirmed on a 12-session held-out test split never touched during
selection.

**Evaluation** (boundary-matching P/R/F1 at 10s tolerance — a boundary
tolerance-window metric, not exact-segment accuracy):

| | precision | recall | F1 |
|---|---|---|---|
| dev (51 sessions) | 0.533 | 0.919 | 0.674 |
| **held-out test (12 sessions)** | **0.545** | **0.937** | **0.689** |

Test F1 slightly exceeds dev F1 — the intended outcome of the split (no
sign of overfitting to dev's specific sessions). Source:
`reports/step1/{dev_comparison,test_result,chosen_config}.json`,
re-verified reproducible during this audit (fresh re-run byte-identical to
committed output).

**Limitations:** precision (~0.55) is the weak point — roughly every other
predicted cut isn't a real boundary at 10s tolerance (this improves to
~0.56 at looser tolerance, but that mostly reflects the same observable-
action lag, not new information). Root causes investigated and disclosed:
some "false positives" are genuinely correct detections in unlabeled
noise/administrative time, which the algorithm has no concept of
excluding (that's deferred to labeling). No process/noise classification
exists yet.

---

## 4. Step 1 — Labeling

**Features** (`src/procmine/features.py`), checked before assuming they'd
help: 99.5% of Dataset A's ground-truth executions have substantial
`context.extracted_text` (median ~2,225 characters) — much richer than
DATA_SCHEMA.md's raw "~4% of events" figure suggests. Three feature
groups per segment: active-app counts, coarse SPA routes (numeric/ID path
segments normalized so `#/cases/482` and `#/cases/119` match), and
character n-gram TF-IDF over the on-screen text.

**Clustering:** `AgglomerativeClustering` (cosine distance, average
linkage) with a `distance_threshold` — not a fixed `n_clusters`, since the
true process count on Dataset B is unknown and mustn't be assumed.

**Evaluation methodology:** two phases on the same dev/test split as
segmentation. Phase 1 clusters TRUE (oracle) executions, isolating
labeling quality from segmentation noise. Phase 2 clusters our OWN
predicted segments, scored against a pseudo-label from majority
ground-truth overlap, to measure real end-to-end degradation.

**A threshold-sweep finding:** a coarse grid first suggested a sharp
cliff; a finer sweep resolved a genuine plateau (V-measure ~0.567-0.570
across thresholds 0.25-0.32) before a real cliff at 0.35. Shipped
**0.30** (plateau center, `LabelingConfig` default in `src/procmine/label.py`)
over the raw argmax (0.32, at the plateau's edge) for robustness to
Dataset B's different vocabulary.

**Held-out test results** (re-verified during this audit by re-running
`scripts/evaluate_labeling.py` fresh — see §13 for a reproducibility bug
found and fixed here):

| | ARI | V-measure | clusters found | true classes |
|---|---|---|---|---|
| oracle segments | 0.206 | **0.622** | 25 | 15 |
| our own predicted segments | 0.128 | **0.509** | 53 | 15 |

**These are clustering-agreement scores (Adjusted Rand Index, V-measure —
homogeneity/completeness harmonic mean), not "accuracy."** No document in
this project calls them accuracy; this is enforced language, checked by
grep during the audit (§13).

**Limitations:** clustering over-produces clusters relative to true
classes (25 vs 15 oracle, 53 vs 15 predicted) — a real, disclosed
precision gap. Failure inspection found confusion concentrated among
same-domain (HR) processes sharing vocabulary; cross-domain confusion is
rare, evidence the text features are doing real discriminative work, just
not perfectly.

---

## 5. Dataset B Output — `segments.jsonl`

Produced once by `scripts/run_step1_dataset_b.py` applying the frozen
`SegmentationConfig()`/`LabelingConfig()` defaults unchanged. Verified
during this audit, directly against the file (not against prior
documentation):

- **456 lines**, every line valid JSON with exactly the four required
  keys (`session_id`, `start`, `end`, `label`).
- All timestamps match `YYYY-MM-DDTHH:MM:SSZ`; `start < end` on all 456.
- **15 distinct session_ids**, an exact match (both directions) against
  the 15 session directories actually present in `data/dataset_b/`.
- **99 distinct labels.**
- Re-ran the generating script fresh during this audit: output is
  **byte-for-byte identical** to the committed file — confirms this
  wasn't hand-edited and is genuinely reproducible from the frozen code.
- `git diff` confirms `src/procmine/segment.py` and `src/procmine/label.py`
  (the two files that determine this output) are unchanged since their
  original commits — Dataset B was never used to tune anything.

---

## 6. Step 2 — Process Mining

**Why a 3-level view, not "99 processes":** Step 1's own evaluation
already showed the labeling stage over-produces clusters relative to true
process count. Treating the 99 raw labels as 99 real processes would
misrepresent frequency for ranking purposes.

**Methodology** (`src/procmine/analyze.py`, `scripts/step2_analysis.py`),
re-run fresh during this audit — **byte-for-byte identical** to the
committed artifacts:
- **99 raw labels** (Step 1's direct output).
- **40 groups**: labels whose feature centroids are close in the *same*
  space Step 1's clustering used (average-linkage, `distance_threshold=0.40`).
  A first attempt used naive threshold+union-find (single-linkage) and
  chained 95 of 99 labels into one mega-group — caught before reporting,
  fixed with proper average-linkage clustering, validated via threshold
  sweep, and covered by a regression test
  (`test_cluster_centroids_does_not_chain_everything_together`).
- **8 process families**: groups sharing a top-level SPA route token.

**Frequency / duration / headcount / recurrence** (from
`reports/step2/process_families.json`, re-verified: sums to 456 segments
and 10,574.0s, which matches the sum of each session's own event span to
within 0.8s — segments tile sessions exactly):

| family | segments | share | total time | sessions | operators |
|---|---|---|---|---|---|
| payroll-items | 138 | 30.3% | 3,318.0s | 15/15 | 4/4 |
| leave-applications | 100 | 21.9% | 2,272.0s | 14/15 | 4/4 |
| onboarding | 83 | 18.2% | 1,737.0s | 11/15 | 4/4 |
| social-insurance | 56 | 12.3% | 1,298.0s | 11/15 | 4/4 |
| resident-tax | 32 | 7.0% | 840.0s | 7/15 | 4/4 |
| (3 navigation-artifact families, excluded from candidacy) | 47 | 10.3% | 1,109.0s | — | — |

**Headcount (4 operators)** comes from `source.machine_id`/`username_hash`
in the raw events (confirmed 1:1 — 4 distinct machines, 4 distinct
username hashes) — genuine observed log data, **not** the leaked
test-harness text (checked explicitly, see §13).

**Variants** ("different handling patterns within the same process," per
the assignment): several families split into multiple groups despite
sharing one route — e.g. leave-applications' dominant group (65/100
segments) has *lower* duration consistency than its smaller siblings,
suggesting it covers a range of case complexity while the smaller groups
are narrower sub-patterns.

**Candidate ranking:** transparent weighted formula — frequency 0.35,
time-share 0.25, consistency 0.20, recurrence 0.10, headcount 0.10 (full
rationale in `reports/step2/step2_report.md` §5). **No dollar figures,
hourly rates, or FTE-cost numbers appear anywhere** — checked by grep
during the audit (§13); only relative comparison, consistent with the
README's own caveat that recorded durations are compressed relative to
real production use. Payroll-items ranks #1 by the composite score *and*
independently by raw frequency alone *and* by raw time alone — the
recommendation doesn't depend on the specific weights chosen.

**Top 3 candidates:** payroll-items (score 0.915), leave-applications
(0.721), onboarding (0.653).

---

## 7. Step 3 — Automation Prototype

**Selected process, and why:** Before building anything, ran a feasibility
investigation (`reports/step3/payroll_items_feasibility.md`) that traced
raw events for the "payroll-items" family's dominant variant. **Finding:
"payroll-items" is not one process** — it's a generic queue-confirmation
UI template (`#pi-table` row click → `#pi-note` paste → `#btn-pi-ok`
click) reused identically across 3 portals (ports 5132/5133/5134) for **9
distinct business processes** (expense settlement ~44 notes, inventory
adjustment 20, invoice reconciliation 19 [with a real approve/flag
branch], payroll/salary changes 11, plus 5 smaller categories). This
overturned "automate payroll-items" as a goal and rescoped Step 3 to the
single largest, best-characterized sub-flow: **expense-settlement
confirmation** (~40% of the family's volume).

**Exact scope:** automate confirmation of expense items in 5 categories
directly observed processed through this queue with **zero exceptions
across 43 distinct samples** (交通費精算/transportation, 出張旅費/travel,
接待交際費/entertainment, 消耗品費/supplies, 研修費/training), with a
¥50,000 cap on entertainment specifically — the one number backed by a
complete, non-truncated regulation document found in the data (re-verified
during Step 3 build: a genuine on-screen Word document capture, "Article 2:
under ¥50,000 = department-head approval, ¥50,000+ = executive approval").
An honest, disclosed complication: the 7 *routine* entertainment
confirmations actually observed in this queue (¥60,936-¥129,596) are
already above this cap — not resolved by assumption; the cap is applied
as a conservative ceiling regardless.

**Implementation form:** Playwright browser automation (`automation/`),
chosen over two alternatives explicitly compared in
`reports/step3/step3_prototype.md` §8:
- *Desktop RPA suite (UiPath):* more setup/licensing overhead than
  justified for one narrow, code-friendly slice now; reasonable for a
  later multi-domain rollout.
- *AI agent:* rejected for the prototype — the in-scope decision is a
  bounded, deterministic threshold check with real (simulated)
  compliance weight; non-deterministic LLM judgment adds risk without
  adding capability this narrow scope needs. No LLM/AI component exists
  anywhere in `automation/decision.py` — checked during the audit.

**Demo, re-run fresh during this audit** (`python3 automation/run_automation.py`,
exit code 0): 9 deterministic sample items covering every rule branch →
**5 auto-confirmed (each independently verified by re-reading the live
DOM after the click, not assumed from the click succeeding), 4 routed to
human review, 0 errors.** Screenshot
(`automation/output/final_queue_state.png`) visually confirms the split.

**The mock reproduction, stated plainly:** `automation/mock_app.py` runs
against a **local mock reproduction** of the observed queue UI — the real
Dataset B application is a test-harness server we never had access to.
The mock page displays a visible "MOCK / REPRODUCTION -- not the original
Dataset B application" banner and is built only from directly-observed DOM
structure (`#pi-table`, `#pi-note`, `#btn-pi-ok`, the exact note template).
It is not, and is never described as, the real system.

**Alternatives considered and rejected:** see above (UiPath, AI agent) —
both compared with concrete reasons tied to the observed evidence, not
generic pros/cons.

**What remains manual:** the other 8 business processes sharing this UI
pattern; any entertainment item ≥¥50,000; any unrecognized category; any
item with missing/invalid data; the glimpsed management-escalation tier;
real authentication (never observed in any log, not built); genuine
rejections (never observed, not built).

**Realistic expected impact:** the largest single sub-flow within a
family that's 30.3% of all observed Dataset B activity — but that 30.3%
describes 9 processes, not one, and the rule covers only the
categories/amounts directly observed with no exceptions. The honest
framing: a meaningful slice of one mid-sized recurring task, not a
company-wide time-savings claim — consistent with the README's own note
that recorded durations don't map cleanly to real production time.

**Risks and mitigations:** see `reports/step3/step3_prototype.md` §10 —
authentication mechanism unknown (no login ever observed; prototype
doesn't attempt one), row-data readability assumed but not confirmed
against the real system, only one category's policy threshold is
confirmed in writing, zero observed rejection cases (a blind spot,
explicitly not designed around), fragile position-based row selectors
(mitigated by re-querying per action rather than caching).

---

## 8. What Did Not Work / Important Methodological Corrections

Recorded in full in `WORKLOG.md`; summarized here because the assignment
explicitly values seeing judgment under uncertainty, not just final
numbers:

1. **Event ordering bug** — `sequence_number` file order isn't always
   chronological; fixed in `iter_events`, and the implication (the
   recording agent's own gap field is equally unreliable) was carried
   forward into the segmentation design.
2. **"Same-process-back-to-back" hypothesis rejected** — measured 0/1,689
   transitions match it; the real hard case (SPA timing lag) was found
   instead by looking at the data rather than defending the hypothesis.
3. **Over-segmentation quantified before it was fixed** — median 2 (up to
   142) non-boundary switches per execution; this number is what justified
   the minimum-duration-merge design, not intuition.
4. **Labeling threshold plateau vs. cliff** — a coarse grid nearly led to
   picking a threshold right at a collapse edge; a finer sweep found the
   real shape and a more robust choice.
5. **A tuning-discipline mistake caught and reverted**: an early version of
   the labeling evaluation independently re-optimized a second threshold
   specifically for predicted (noisy) segments, landing on a degenerate
   350-cluster near-singleton solution. Recognized as effectively the same
   overfitting risk the assignment warns about for Dataset A→B, just one
   level down — fixed by carrying the oracle-selected config forward
   unchanged instead.
6. **Single-linkage collapse in Step 2** — naive union-find consolidation
   chained 95 of 99 labels into one group; caught, replaced with
   average-linkage clustering, and covered by a regression test so it
   can't silently regress.
7. **"payroll-items is 9 processes, not 1"** — the single biggest scope
   correction in the whole project, found specifically by tracing raw
   events *before* writing any Step 3 code, exactly per the assignment's
   instruction to anticipate risks from limited information rather than
   build on optimistic assumptions.
8. **A reproducibility gap found during this final audit** — the
   committed `reports/step1/labeling_results.json` had been hand-patched
   at one point to reflect the shipped `LabelingConfig` default (0.30)
   rather than the evaluation script's own raw argmax (0.32, a
   negligible-but-real difference within the plateau). Re-running the
   script during the audit reproduced the *old* argmax-based numbers, not
   the patched ones — a genuine reproducibility bug. Fixed by making
   `scripts/evaluate_labeling.py` explicitly evaluate the shipped
   `LabelingConfig()` default rather than silently re-deriving a
   slightly-different one each run; re-verified deterministic across
   repeated runs afterward.

---

## 9. GenAI Usage

Full disclosure in `WORKLOG.md` (top of file). In short: Claude Code
(Anthropic's AI coding agent) was used throughout the assignment as a
development and analysis assistant — exploring the datasets, implementing
the segmentation/labeling pipeline, running experiments and analyses,
developing the automation prototype, testing, debugging, and maintaining
documentation, and executing the pipelines that generated the reported
results. The workflow was iterative, with earlier findings informing
later implementation and investigation. Dataset A's ground truth was used
for developing and evaluating Step 1; Dataset B was kept separate during
development since it has no ground truth. The final pipelines and key
numerical results were rerun during the submission audit (§13) to verify
consistency. My role was to provide the task direction, constraints, and
major decisions, and to review the resulting work and final outputs.

---

## 10. Time Allocation

**Actual execution timeline, stated plainly:** understanding and
preparation happened on 2026-09-08 (reading the assignment, resolving the
incomplete `dataset_a` zip), before git was initialized. The entire
technical build — Dataset A exploration through segmentation, labeling,
applying the frozen pipeline to Dataset B, Step 2's process mining, and
Step 3's feasibility investigation and working prototype, including the
self-verification pass that closed out that session — was then carried
out in one compressed, continuous AI-assisted session on 2026-09-09
(commit timestamps span 09:54-12:12; see `git log`). In the days that
followed, the work was reviewed again rather than treated as final
immediately — going back over the outputs, deepening understanding of the
implementation, and re-checking results — without producing new commits,
since the technical artifacts and their audit were already complete.
Immediately before submission, the wording of this log's own framing and
the GenAI-usage disclosure was revisited for accuracy (git-verified as
later, separate commits). None of this was literally paced across 7
calendar days of development.

The README separately asks "how you allocated the 7 days, and why" —
that's a question about prioritization judgment, not a literal timesheet,
so the table below maps the actual work above onto that 7-day framing to
answer it directly. **This table is that mapping, not a second, competing
account of when things happened** — the real chronology is the paragraph
above; splitting the two largest bodies of work (Task 1 and Task 3) into
sub-stages here is purely to answer the "why" of each priority in order:

| day (allocation framing) | focus | why | actual stage (see above) |
|---|---|---|---|
| 1 | Assignment understanding + Task 1 prep: read README/DATA_SCHEMA, catch and resolve the incomplete dataset_a zip, initial Dataset A exploration (corpus stats, ground-truth shape, data-quality fixes) | Understand the hardest, most uncertain part *before* committing to an algorithm design — a wrong assumption here would have wasted every later day | Initial understanding and preparation |
| 2 | Task 1 boundary analysis + segmentation design: does-it-predict-boundaries analysis, hard-boundary investigation, over-segmentation investigation, segmentation algorithm design, dev/test evaluation, config selection | Get a validated, held-out-tested boundary detector before trusting it with anything | Main implementation |
| 3 | Task 1 labeling + freeze + apply to Dataset B: features, clustering, two-phase evaluation, freezing the Step 1 config, applying it once to Dataset B, producing `segments.jsonl` | Same discipline applied to the second half of Step 1, then the actual Step 1 deliverable, done only after both pieces were validated | Main implementation |
| 4 | Step 2 process mining: frequency/duration/headcount, evidence-based consolidation, candidate ranking | Turn the raw output into an actionable, evidence-backed priority list | Main implementation |
| 5 | Step 3 feasibility investigation *before* writing any prototype code | Directly follows the assignment's instruction to assess feasibility and anticipate risks from limited information — this is what caught the "9 processes, not 1" finding, which would have been far more costly to discover mid-build | Main implementation |
| 6 | Step 3 prototype build, testing, documentation | Narrow, well-scoped build informed by the feasibility findings above | Main implementation |
| 7 | Final audit (this document) — independent re-verification of every number, a real reproducibility bug found and fixed, submission packaging | Judgment includes checking your own work before handing it over, not just producing it | Main implementation (audit) + continued review/final documentation |

---

## 11. Limitations (project-wide summary)

- **Step 1 precision (~0.55)** is the main technical weak point; recall is
  strong (~94%). Some of the gap is legitimate (correct detections in
  unlabeled noise time), some is residual over-segmentation not fully
  solved by minimum-duration merging alone.
- **No ground truth exists for Dataset B at any level.** Everything in
  Step 2 and Step 3 is inference built on Step 1's own measured, imperfect
  output. Some fraction of the 456 segments are very likely non-process
  time (per Dataset A's evaluation), with no current way to detect which
  ones specifically on Dataset B.
- **Durations reflect a compressed test environment** — only relative
  comparisons are used anywhere in this project; no absolute time-savings
  or monetary figures are claimed.
- **Step 3 automates a genuinely narrow slice** — 5 of 9 identified
  business processes sharing the queue UI pattern, only the lower tier of
  the one sub-flow with a confirmed threshold, demonstrated against a
  clearly-labeled mock reproduction rather than the real system (which
  isn't available to us).
- **The entertainment-expense threshold inconsistency** (§7) is disclosed,
  not resolved — a real deployment needs the client's actual answer.

---

## 12. Reproduction Instructions

All commands below were re-run during the final audit and confirmed to
work exactly as written, from the repository root.

```bash
# 1. Environment
pip install -r requirements.txt
python3 -m playwright install chromium   # one-time, for Step 3 only

# 2. Data (place the provided zips in the repo root first — see data/README.md)
bash scripts/extract_data.sh

# 3. Step 1 — reproduce the segmentation evaluation (dev/test split, config sweep)
python3 scripts/evaluate_segmentation.py
# writes reports/step1/{dev_comparison,test_result,chosen_config}.json

# 4. Step 1 — reproduce the labeling evaluation
python3 scripts/evaluate_labeling.py
# writes reports/step1/labeling_results.json

# 5. Step 1 — apply the frozen pipeline to dataset_b (produces the deliverable)
python3 scripts/run_step1_dataset_b.py
# writes segments.jsonl (repo root) + reports/step1/dataset_b_segmentation_summary.json

# 6. Step 2 — process mining and candidate ranking
python3 scripts/step2_analysis.py
# writes reports/step2/*.{json,csv,md}

# 7. Step 3 — run the working prototype end to end
python3 automation/run_automation.py
# writes automation/output/{automation_log.json,human_review_queue.json,final_queue_state.png}
# also browsable by hand at http://127.0.0.1:5001/ afterward

# 8. Full test suite
python3 -m pytest tests/ -v
```

Exploratory/diagnostic scripts (`scripts/explore_*.py`,
`scripts/trace_workflow.py`) are not part of this reproduction chain —
they were one-off investigations recorded in `WORKLOG.md`, not pipeline
steps that need to be re-run.

---

## 13. Final Submission Audit

Performed as a strict, independent re-verification pass — re-running code
and reading actual output files, not trusting prior prose. See
`WORKLOG.md`'s final entry for the full account.

### Requirement checklist

| requirement | status | evidence | caveat |
|---|---|---|---|
| Dataset A segmentation methodology + evaluation | ✅ | `src/procmine/segment.py`, `scripts/evaluate_segmentation.py`, `reports/step1/{dev_comparison,test_result,chosen_config}.json` — re-run fresh, byte-identical | precision ~0.55 is a real, disclosed weak point |
| Dataset A labeling methodology + evaluation | ✅ | `src/procmine/{features,label}.py`, `scripts/evaluate_labeling.py`, `reports/step1/labeling_results.json` | fixed a reproducibility bug during this audit (§8 item 8) |
| Frozen Step 1 pipeline applied to Dataset B | ✅ | `scripts/run_step1_dataset_b.py`; `git diff` confirms `segment.py`/`label.py` unchanged since original commits | — |
| `segments.jsonl` schema/validity | ✅ | 456/456 lines valid, exact 4 keys, valid timestamps, start<end, re-verified by direct parse | — |
| All Dataset B sessions represented | ✅ | 15/15, exact set match vs `data/dataset_b/` on disk | — |
| Dataset B process mining (frequency/duration/headcount/variants) | ✅ | `reports/step2/process_families.json`, re-run fresh, byte-identical | family labels are route-inferred, not client-confirmed |
| Automation candidate prioritization + ROI reasoning | ✅ | `reports/step2/candidate_ranking_family_level.json`; grepped for invented $/hour figures — none found | weights are a disclosed judgment call, checked for robustness |
| Step 3 working prototype | ✅ | `automation/`, re-run fresh: 5 auto-confirmed (UI-verified)/4 human-review/0 errors | mock reproduction, not the real system — stated explicitly |
| Prototype scope stated (expense-settlement, not all of payroll-items) | ✅ | `reports/step3/step3_prototype.md` §1, title itself | — |
| Implementation form + alternatives considered | ✅ | `reports/step3/step3_prototype.md` §8 (UiPath, AI agent, both rejected with reasons) | — |
| Remaining manual work stated | ✅ | §7 above, `step3_prototype.md` §8 | — |
| Risks + mitigations | ✅ | `step3_prototype.md` §10 | — |
| Work log (thinking, tried, failed) | ✅ | `WORKLOG.md`, organized by actual work stage (initial preparation, main implementation, continued review/validation, final documentation) matching the assignment's 3 tasks, all 8 required corrections present (§8 above) | — |
| GenAI usage recorded | ✅ (fixed this audit) | `WORKLOG.md` top section | was missing before this audit — genuine gap, now fixed |
| Time allocation (7 days, why) | ✅ (fixed this audit) | §10 above | was missing before this audit — genuine gap, now fixed |
| Git history, meaningful incremental commits | ✅ | `git log --oneline`: 14 commits — 11 substantive development commits (2026-09-09) plus 3 later documentation-only commits (2026-09-15: GenAI-disclosure wording, Day 1-5 timeline correction) | history was rewritten during finalization — to fix an author identity picked up from machine git config on 11 commits, and to drop one exact-duplicate commit plus the merge and stray Co-Authored-By trailers it produced. Disclosed here, not hidden; no commit's file content, dates, or development/methodology substance was altered by the rewrite |
| Reproducibility / run instructions | ✅ | §12 above, every command re-run during audit | — |
| No Dataset B leakage into methodology | ✅ | grepped all code for leaked-text markers — none found; only doc sentences stating non-use | — |

### Dataset B leakage check (explicit)

Searched `src/`, `scripts/`, `automation/`, `tests/` for the leaked
PowerShell/generator text markers ("Theme M2", "orchestrator_m2",
"gt-logs", etc.) — **zero matches in actual code**; the only matches
anywhere in the repository are documentation sentences stating the text
was *not* used. Separately re-verified the one piece of Dataset B evidence
with real decision-making weight — the ¥50,000 entertainment-expense
threshold in `automation/decision.py` — traces to a genuine Microsoft Word
document capture (`context.extracted_text`, source app "Microsoft Word",
window title "settai_keihi_kitei"), not the terminal/PowerShell capture.
This is a legitimate, code-verified distinction, not an assertion.

### Terminology check

Grepped all documentation for "accuracy" used near F1/V-measure/ARI —
found only two hits, both in the original, unmodified `README.md` (not
authored by this project) and one generic phrase in `WORKLOG.md`
("boundary-accuracy scoring," used descriptively before the P/R/F1
methodology existed, not as a synonym for F1). No document in this
project calls V-measure, ARI, or boundary F1 "accuracy."

### Fixes made during this audit (documentation/reproducibility only — no methodology changes)

1. Added the missing GenAI usage disclosure to `WORKLOG.md`.
2. Added this `FINAL_REPORT.md` with the required time-allocation section.
3. Fixed a real reproducibility bug in `scripts/evaluate_labeling.py`
   (§8 item 8) — the script now evaluates the actually-shipped
   `LabelingConfig()` default rather than silently re-deriving a
   slightly-different threshold from its own raw argmax each run.
   Re-verified deterministic across two independent re-runs.

No segmentation/labeling/analysis methodology, thresholds, or weights were
changed to improve any metric — every fix above is either new
documentation or a fix that makes code match what was already decided and
already documented elsewhere.

### Final test run (this audit, fresh)

```
35 passed in 1.84s
```
(24 from Step 1/2 + 9 Step 3 decision-logic unit tests + 2 Step 3
Playwright integration tests.)

### Final demo run (this audit, fresh)

```
total items:      9
auto-confirmed:   5 (verified in UI)
human review:     4
errors:           0
```
