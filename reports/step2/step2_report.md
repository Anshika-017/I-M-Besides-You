# Step 2 — Process Mining & Analysis (Dataset B)

Analysis of `segments.jsonl` (456 segments, 15 dataset_b sessions), produced
by the frozen Step 1 pipeline (`SegmentationConfig()` / `LabelingConfig()`
defaults, unchanged — see `WORKLOG.md`). All numbers below are reproducible
by running `scripts/step2_analysis.py`; every figure traces back to a file
under `reports/step2/`.

## 1. Three levels of granularity, and why

Step 1's labeling evaluation already showed the 99 raw discovered labels
over-fragment the real process count (dataset_a's oracle-segment validation:
25 discovered clusters vs. 15 true classes). Rather than pretend the 99
labels are 99 real processes, this analysis builds two coarser, evidence-based
views on top of them, keeping the original 99 fully traceable underneath:

- **99 raw labels** — Step 1's direct clustering output (`label_stats.json`).
- **40 groups** — raw labels whose feature centroids are close *in the same
  feature space Step 1's clustering used* (average-linkage agglomerative
  clustering, cosine distance, `distance_threshold=0.40`, looser than Step
  1's own 0.30 merge threshold) (`process_groups.json`).
- **8 process families** — groups sharing the same top-level SPA route
  token (e.g. `#/payroll-items`), a simple, fully transparent grouping used
  to cross-check the similarity-based grouping above (`process_families.json`).

**A failed approach, corrected before use:** the first attempt at
consolidation connected any pair of labels with centroid cosine similarity
≥ 0.5 and took connected components (union-find). That's mathematically
single-linkage clustering, and it chained catastrophically — 95 of 99 labels
collapsed into one meaningless mega-group, because individually-reasonable
pairwise links transitively connected almost everything. Fixed by using
average-linkage agglomerative clustering instead (requires groups to be
similar *on average*, not linked by one weak edge), checked via a threshold
sweep (0.30→0.60) to confirm sane behavior (40 groups at 0.40, largest group
13 members; no runaway collapse until much higher thresholds). See
`WORKLOG.md` for the full account.

## 2. Corpus-level numbers (self-audited)

- 456 segments, 15 sessions, **10,574.0s** total segment duration.
- Cross-check: summed session span (first→last event per session) =
  10,574.8s — matches within rounding, confirming segments tile sessions
  exactly (no gaps/double-counted time).
- Sum of per-label, per-group, and per-family counts each independently
  equal 456 — verified programmatically before writing this report.
- **Headcount**: 4 distinct operators recorded, from `source.machine_id` /
  `source.username_hash` in the raw dataset_b events (confirmed 1:1 — 4
  distinct machines, 4 distinct username hashes) and cross-checked against
  the session directory naming (`ses_<date>-<time>-<machine>`). This is
  genuine observed log data — **not** the leaked test-harness text, which is
  not read anywhere in this analysis (see `WORKLOG.md`).

## 3. Process family summary (primary table)

| family | segments | share of segments | total time (s) | share of time | median dur (s) | sessions | operators | consistency | dominant app | variant groups |
|---|---|---|---|---|---|---|---|---|---|---|
| payroll-items | 138 | 30.3% | 3318.0 | 31.4% | 21 | 15/15 | 4/4 | 0.575 | Edge (75%) | 7 |
| leave-applications | 100 | 21.9% | 2272.0 | 21.5% | 20 | 14/15 | 4/4 | 0.515 | Edge (58%) | 5 |
| onboarding | 83 | 18.2% | 1737.0 | 16.4% | 19 | 11/15 | 4/4 | 0.694 | Edge (57%) | 7 |
| social-insurance | 56 | 12.3% | 1298.0 | 12.3% | 20 | 11/15 | 4/4 | 0.578 | Edge (56%) | 4 |
| resident-tax | 32 | 7.0% | 840.0 | 7.9% | 23 | 7/15 | 4/4 | 0.592 | Edge (91%) | 2 |
| http: *(navigation artifact)* | 25 | 5.5% | 717.0 | 6.8% | — | 9/15 | 4/4 | — | Edge (77%) | 5 |
| dashboard *(navigation artifact)* | 13 | 2.9% | 251.0 | 2.4% | — | 10/15 | 4/4 | — | Edge (80%) | 3 |
| no_route *(no browser page)* | 9 | 2.0% | 141.0 | 1.3% | — | 6/15 | 3/4 | — | procmine-agent (63%) | 7 |

**`http:`, `dashboard`, and `no_route` are excluded from automation
candidacy** — their labels indicate portal landing pages / inter-task
navigation / non-browser activity rather than a distinct recurring paperwork
task. This is a judgment call stated explicitly, not a silent filter: they
remain in the underlying data and artifacts, just not treated as process
candidates. The five real candidates (payroll-items through resident-tax)
account for **89.7%** of all segments and **89.5%** of all recorded time.

## 4. Variants — different handling patterns within the same family

Several families split into multiple **groups** at the 0.40 similarity
threshold despite sharing one route — that's the interesting signal: same
apparent business process, different enough in practice to not merge even at
a looser threshold than Step 1's own clustering used.

- **leave-applications** (5 groups): one dominant group (65/100 segments, 12
  sessions, 7 raw labels) has *lower* duration consistency (0.458) than its
  smaller siblings (0.76–0.93) — consistent with the dominant pattern
  covering a range of case complexities, while the smaller groups look like
  more narrowly-defined sub-patterns.
- **onboarding** (7 groups) and **payroll-items** (7 groups): each has one
  large dominant group (83% and 78% of the family's volume respectively)
  plus several small (1-13 segment) side groups — most likely a mix of a few
  genuinely distinct minor variants and some residual over-fragmentation
  Step 1's evaluation already flagged as a real limitation.
- **resident-tax** (2 groups) and **social-insurance** (4 groups) are more
  fragmented relative to their small size, suggesting more of their apparent
  "variants" may be over-fragmentation artifacts rather than real handling
  differences — treated with more caution in the ranking below via the
  consistency score, but not specially excluded.

None of this variant detail should be read as confirmed ground truth —
dataset_b has none. It's the strongest evidence-based structure obtainable
from Step 1's output, stated with its actual uncertainty.

## 5. Automation candidate ranking — transparent, no invented $ values

Per-family composite score:

```
score = 0.35 * frequency_score      (segment count / max segment count)
      + 0.25 * time_score           (total duration / max total duration)
      + 0.20 * consistency_score    (1 - coefficient_of_variation of duration, clipped [0,1])
      + 0.10 * recurrence_score     (n_sessions / 15)
      + 0.10 * headcount_score      (n_operators / 4)
```

**Why these weights:** frequency and time together (60%) dominate because
they directly answer "how much recurring manual effort does this represent"
— the core ROI driver the assignment asks for. Consistency (20%) reflects
that a more standardized process is more automatable, a real but secondary
concern. Recurrence and headcount (10% each) are tie-breakers that favor
processes that are widespread (many sessions, many operators) over ones that
are frequent but concentrated in one person's workflow — since the whole
point is company-wide impact, not one individual's convenience.

No dollar figures, hours-saved estimates, or FTE-cost numbers appear
anywhere in this ranking. The README explicitly says recorded wait times are
compressed relative to real production use, so absolute durations aren't a
reliable basis for a monetary estimate — only *relative* comparisons between
candidates (which is what the score captures) are defensible from this data.

**Robustness check:** payroll-items is also #1 by raw segment count alone
and by raw total-duration alone (not just the weighted composite) — the
recommendation below doesn't depend on the specific weight choices.

| rank | family | score | segments | total time (s) | sessions | operators |
|---|---|---|---|---|---|---|
| 1 | **payroll-items** | **0.915** | 138 | 3318.0 | 15/15 | 4/4 |
| 2 | leave-applications | 0.721 | 100 | 2272.0 | 14/15 | 4/4 |
| 3 | onboarding | 0.653 | 83 | 1737.0 | 11/15 | 4/4 |
| 4 | social-insurance | 0.529 | 56 | 1298.0 | 11/15 | 4/4 |
| 5 | resident-tax | 0.409 | 32 | 840.0 | 7/15 | 4/4 |

(`http:`, `dashboard`, `no_route` scored 0.359/0.265/0.234 respectively but
are excluded from candidacy per §3.)

## 6. Top 3 candidates

1. **payroll-items** — highest on every raw dimension (frequency, time,
   recurrence), and the most single-application-focused of the high-volume
   candidates (75% of its activity in one app vs. 56-58% for the next two).
2. **leave-applications** — second-highest volume, but a genuinely
   two-application workflow (Edge 58% / Word ~42% of activity) — more
   complex automation surface.
3. **onboarding** — third-highest volume, also two-application (Edge 57% /
   Word ~38%), lower recurrence (11/15 sessions vs. 14-15/15 for the top two).

## 7. Recommended Step 3 candidate: **payroll-items**

**Why, with the specific evidence:**
- **Largest observed time sink**: 138 segments (30.3% of all activity),
  3,318s (31.4% of all recorded time) — the single biggest aggregate
  opportunity in the data, by a wide margin (leave-applications, the
  runner-up, is 68% of payroll-items' volume).
- **Universal**: occurs in **100% of sessions (15/15)** and **all 4
  recorded operators** — not a niche task for one person; automating it
  benefits the whole observed workforce.
- **Narrowest automation surface among the high-volume candidates**: 75% of
  its activity is in a single application (a browser-based portal),
  compared to 56-58% for leave-applications and onboarding, which
  meaningfully involve Microsoft Word as well. A single-portal workflow is a
  much more tractable target for a 7-day prototype than one requiring
  coordinated browser + Word document automation.
- **Dominated by one large, consistent pattern**: one variant group
  (`group_009`) accounts for 107 of 138 segments (77.5%), appears in all 15
  sessions and all 4 machines — most of this process's real-world volume
  follows one broadly standardized pattern rather than many divergent
  variants each needing bespoke handling.

## 8. Limitations and risks (explicit)

- **No ground truth for dataset_b, at any level.** Every number above is
  inferred from Step 1's own segmentation/labeling output, which has known,
  measured imprecision (Step 1 evaluation on dataset_a: boundary precision
  ~0.55, labeling V-measure ~0.51-0.62). Some unknown fraction of the 456
  segments almost certainly are not real business processes (dataset_a's
  validation found ~18-20% of predicted segments didn't correspond to any
  labeled execution) — there is currently no way to detect and exclude
  those specifically in dataset_b, so family counts could be inflated or
  (less likely) deflated by this. Flagged, not fixed, consistent with the
  Step 1 decision to ship an explainable baseline and disclose its limits.
- **Durations reflect a compressed test environment**, per the README's own
  caveat. Only relative comparisons (used throughout) are defensible; no
  absolute time-savings or monetary ROI is claimed anywhere in this report.
- **Family/route labels are inferred, not confirmed.** "payroll-items" etc.
  come directly from the portal's own SPA hash-route text observed in the
  logs — strong circumstantial evidence about business content, but not a
  client-confirmed process name.
- **Consistency score is duration-based only.** It's a proxy for "looks
  standardized," not a measurement of decision-branch complexity. A process
  can have consistent *duration* while still branching internally. Step 3
  will need to look at the actual route/event sequence inside the chosen
  candidate before assuming it's simple to automate end-to-end.
- **Ranking weights are a stated judgment call**, not learned from data —
  disclosed in full in §5, and checked for robustness against the two
  dominant raw dimensions (frequency, time) independently.

## 9. What Step 3 needs to do first (not started here)

Before building anything: look at the actual sequence of routes/events
inside `group_009` (payroll-items' dominant variant) to characterize the
concrete steps of the workflow and decide what slice is realistically
automatable — this analysis identifies *what* to automate, not yet *how*.
