# Step 3 Prototype: Expense Settlement Confirmation Automation

Working, runnable prototype built strictly from the findings in
`reports/step3/payroll_items_feasibility.md`. This document explains what
it does, exactly what it doesn't do, and how to run it yourself.

## 1. Exact process scope

**In scope:** the expense-settlement confirmation sub-flow identified as
the single largest, best-characterized, lowest-ambiguity business process
sharing the observed queue-confirmation UI pattern (~40% of everything in
Step 2's "payroll-items" family; see the feasibility report §0 for the
full breakdown of all 9 sub-flows sharing that UI).

**Out of scope, explicitly:** the other 8 business processes sharing the
same mechanical UI pattern (inventory adjustment, invoice reconciliation,
payroll/salary changes, IT requests, purchase orders, new-hire
verification, attendance, contract management), and the glimpsed
management-approval escalation tier. None of these are touched by this
prototype. This is a deliberate, evidence-based scoping decision, not an
oversight — see the feasibility report for why "automate payroll-items"
was rejected as a goal.

## 2. Observed workflow being automated

From `payroll_items_feasibility.md` §1, re-verified against raw
`browser_click`/`browser_form_input`/`keystroke` payloads while building
this prototype:

1. A table of pending items (`#pi-table`), each row's 4th `<td>` clicked
   to select it.
2. A note/comment textarea (`#pi-note`, placeholder "処理内容・確認コメ
   ントを入力してください…") filled with a confirmation note.
3. A confirm button (`#btn-pi-ok`, `class="btn success"`) clicked.
4. Repeat for the next row.

For the expense-settlement sub-flow specifically, the note always follows
one fixed template (100% of 43 distinct observed cases):
```
経費精算確認済み。費目：{category}　金額：{amount}円。規程内であることを確認した。
```

## 3. The one rule this prototype applies — and exactly what it's based on

Implemented in `automation/decision.py`. Nothing here is invented; every
constant is cited to specific evidence, re-verified against raw dataset_b
events while writing this prototype (not just carried over from the
feasibility doc without a second check):

- **5 eligible categories** (交通費精算, 出張旅費, 接待交際費, 消耗品費,
  研修費) — the only categories directly observed being processed through
  this exact queue action, with **zero exceptions/rejections across 43
  distinct observed confirmations**. This — not any external knowledge of
  company policy — is the entire basis for treating these 5 as safe to
  auto-process.
- **A ¥50,000 cap on the 接待交際費 (entertainment) category specifically**
  — sourced from the *one* complete, non-truncated regulation document
  found anywhere in dataset_b (Article 2 of "接待交際費規程": "1回あたり
  5万円未満：部門長承認。5万円以上：役員承認。10万円以上：社長承認。").
  This text is genuine on-screen content, not the leaked generator text —
  confirmed while re-checking this specific evidence for the prototype
  (see §7 below for the full compliance check).

  **An honest complication, disclosed, not smoothed over:** the 7
  *routine* entertainment confirmations actually observed in this queue
  (¥60,936–¥129,596) are *all already above* this ¥50,000 cap — some above
  the ¥100,000 president tier — yet appear to go through the same
  "confirmed" action as everything else. This prototype does **not**
  resolve that inconsistency by assumption. It takes the conservative
  reading: the one number with a written source becomes a hard automation
  ceiling, even though real observed practice in this queue looks looser
  than that. Anything at or above ¥50,000 is routed to a human, explicitly
  because the regulation names a higher required authority
  (executive/president) that this bot does not have evidence of holding.
- **No other category has a confirmed written threshold anywhere in the
  data.** No cap is invented for transportation, travel, supplies, or
  training — the only gate for those is category membership + a valid
  positive amount.

## 4. What the prototype does, end to end

For every pending item in the queue, in table order:

1. **Read** its category and amount directly from the rendered table row
   (via Playwright DOM locators — no OCR, no guessing).
2. **Apply the rule** in `automation/decision.py`.
3. If `AUTO_CONFIRM`: click the row → fill `#pi-note` with the generated,
   template-based note → click `#btn-pi-ok` → **verify** the row's status
   actually changed to "confirmed" in the live DOM afterward. If
   verification fails, the item is recorded as an `ERROR`, not silently
   assumed successful.
4. If `HUMAN_REVIEW`: **the item is never clicked at all.** It's left
   exactly as-is in the queue and written to a review file with the
   specific reason.
5. Writes `automation/output/automation_log.json` (every decision + action
   + verification result), `automation/output/human_review_queue.json`
   (items needing a human), and a screenshot of the final queue state
   (`automation/output/final_queue_state.png`).

## 5. Architecture

```
automation/
  decision.py       <- pure business rule (no browser dependency, unit tested directly)
  sample_data.py    <- deterministic sample expense items for the demo
  mock_app.py       <- Flask app reproducing the observed queue UI (see §6)
  run_automation.py <- Playwright driver: reads the mock UI, applies decision.py, acts, verifies
  output/            <- generated on each run (log, human-review queue, screenshot)
```

`decision.py` has zero Playwright/Flask imports on purpose — the business
logic must be testable and auditable independent of whether a browser
happens to be available.

## 6. Why a mock app, and what it actually is

The original dataset_b application was a local test-harness server
(`127.0.0.1:5132` etc.) that only existed inside the recording environment
— we don't have its source or access to it. Per your instructions,
`automation/mock_app.py` is a **from-scratch reproduction**, clearly
labeled as such (a yellow banner reading "MOCK / REPRODUCTION -- not the
original Dataset B application" is rendered at the top of the page), built
using **only** the DOM structure, element IDs, and interaction sequence
directly observed in the raw event logs: table id `pi-table`, textarea id
`pi-note` with the exact observed placeholder, button id `btn-pi-ok` with
class `btn success`, and the same click → fill → click sequence. It is not
a guess at what the real system looks like beyond these specific,
evidenced details — its layout, styling, and backend are entirely new code
written for this prototype.

## 7. Compliance re-check (done specifically for this build, not assumed carried over)

- Re-searched dataset_b for the leaked "Theme M2"/generator setup text
  while building this prototype: not referenced anywhere in
  `automation/`.
- The ¥50,000 threshold and the 5 category names come from genuine
  `context.extracted_text` captures of real on-screen content (a
  regulation document and confirmation notes), which `DATA_SCHEMA.md`
  explicitly says is fair to use — re-verified by re-running the search
  for a complete, non-truncated capture of the regulation text before
  writing `decision.py` (a truncated fragment alone would not have been
  enough to responsibly cite a number).
- No authentication step is automated or simulated — none was ever
  observed in any traced session, so none is invented here. The mock app
  has no login page at all.
- No LLM/AI judgment is used anywhere in `decision.py` — it is a plain
  deterministic function.
- `segments.jsonl`, `src/procmine/segment.py`, and `src/procmine/label.py`
  are untouched by this work (verified via `git diff` before committing).

## 8. What remains manual after this prototype

- Every business process other than expense-settlement confirmation that
  shares this UI pattern (§1) — completely untouched.
- Any expense item outside the 5 confirmed categories.
- Any 接待交際費 (entertainment) item at or above ¥50,000.
- Any item with missing/invalid category or amount data.
- The management-tier escalation path glimpsed in the data.
- Determining the actual, complete policy thresholds for the other 4
  categories with the real client — none are known from this data.
- Login/authentication to whatever the real production system turns out
  to be.
- Handling a genuine rejection — never observed, so not built; the
  prototype cannot and does not claim to know what a rejection looks like
  in this UI.

## 9. Assumptions (stated explicitly)

- The row's category and amount are assumed readable from the DOM/table
  directly (this is true in the mock app, by construction, since it
  reproduces our best understanding of the observed pattern — but was
  **not** directly confirmed for the real system, since we only ever
  observed the *pasted result* in the real logs, not a capture of the raw
  table cells themselves). A real deployment must verify this against the
  live system before relying on it.
- The ¥50,000 entertainment cap is applied as a hard ceiling despite the
  observed inconsistency described in §3 — a deliberately conservative
  choice, not a confirmed fact about what the real system requires.

## 10. Risks and mitigations

| risk | mitigation in this prototype |
|---|---|
| Wrongly auto-confirming something that needed a human | Category allowlist + amount validation + entertainment cap, all evidence-based; anything not confidently covered is routed to a human, never guessed |
| Silently claiming success when the UI didn't actually update | Every `AUTO_CONFIRM` action is followed by a live DOM check; a mismatch is logged as `ERROR`, not swallowed |
| Fragile selectors (row-position-based click) | Re-queries the DOM by `data-item-id` per action rather than caching stale locators/indices |
| Overclaiming what's automated | This document and the code's own docstrings state the scope and exclusions explicitly, in the same place as the logic itself |
| Real-system differences from the mock | §6 and §9 state plainly that the mock reproduces *observed* structure only, not confirmed knowledge of the live system |

## 11. How to run / demo it

```bash
pip install -r requirements.txt
python3 -m playwright install chromium   # one-time browser download

# Run the full automation end-to-end (starts the mock app itself):
python3 automation/run_automation.py

# Or explore the mock UI by hand first:
python3 automation/mock_app.py
# then browse to http://127.0.0.1:5001/
```

`run_automation.py` prints a per-item decision and a summary, writes
`automation/output/automation_log.json`,
`automation/output/human_review_queue.json`, and a screenshot of the final
queue state, and leaves the mock app running afterward so the result can
be inspected in a real browser too.

**Expected result against the included sample data** (`automation/sample_data.py`,
9 items covering every branch):

| item | category | amount | expected outcome |
|---|---|---|---|
| 1-4 | transportation/travel/training/supplies | modest | AUTO_CONFIRM |
| 5 | entertainment | ¥35,000 | AUTO_CONFIRM (below cap) |
| 6 | entertainment | ¥50,000 | HUMAN_REVIEW (at cap) |
| 7 | entertainment | ¥120,000 | HUMAN_REVIEW (above cap, matches real observed range) |
| 8 | unknown category | ¥15,000 | HUMAN_REVIEW (not one of the 5 known categories) |
| 9 | travel | missing | HUMAN_REVIEW (missing amount) |

Result: **5 auto-confirmed (all verified in the live UI), 4 routed to
human review, 0 errors** — matches what was actually observed running this
prototype while building it.

## 12. Tests

- `tests/test_step3_decision.py` (9 tests) — the business rule in
  isolation: valid in-scope expense, the boundary/threshold case, unknown
  category, missing/invalid data, and confirms human-review never
  produces a note.
- `tests/test_step3_integration.py` (2 tests) — real Playwright-driven
  checks against a live instance of the mock app: a successful UI
  confirmation actually changes the DOM, and a human-review item is
  genuinely left untouched.
- Full suite: `python3 -m pytest tests/ -v` — 35/35 passing (24 from Step
  1/2 + 11 new for Step 3).

## 13. Limitations

- Demonstrated against a mock reproduction, not the real system — see §6,
  §9. The mechanical interaction pattern and the category/note-template
  evidence are real; the live system's actual DOM, authentication, and API
  behavior are not confirmed.
- Only 5 of 9 identified sub-flows sharing this UI are covered, and only
  the lower tier of the one sub-flow with a genuine amount threshold.
- The entertainment-expense inconsistency in §3 is disclosed but not
  resolved — a real deployment needs to ask the client directly why
  observed practice exceeds the written approval-authority threshold
  before trusting either the cap or the observed behavior.
- No handling for concurrent edits, network failures, or session
  timeouts — out of scope for a 7-day feasibility-driven prototype, flagged
  as needed for any production version.

## 14. Realistic expected impact

Step 2 found the whole "payroll-items" family accounts for 138/456 (30.3%)
of all observed segments and 3,318s (31.4%) of all recorded time — but
that number describes **9 different business processes**, not one. Of
those, expense-settlement confirmation is the largest single slice
(~44/138 ≈ 32% of the family's volume, ~13% of the observed dataset_b
corpus overall going by note count, not time — this analysis didn't
re-derive a precise time-share for the sub-flow specifically since Step
1's segments don't cut at this granularity). Within that slice, this
prototype's rule covers the categories/amounts actually observed with no
exceptions, which in the 43-sample survey was **100% of transportation,
travel, supplies, and training items, and the below-¥50,000 majority of
entertainment items** (4 of 7 observed entertainment amounts were below
the cap). The realistic expectation is: **a meaningful minority-to-roughly-half
of one specific, mid-sized recurring task category, automatable with the
current evidence** — not "payroll," not even all of "expense settlement,"
and explicitly not a company-wide time-savings claim, consistent with the
README's own caveat that recorded durations don't map cleanly to real
production time anyway.
