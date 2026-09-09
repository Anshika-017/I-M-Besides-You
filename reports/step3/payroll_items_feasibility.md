# Step 3 Feasibility Investigation: the "payroll-items" candidate

Read-only investigation. Does not modify `segments.jsonl`, Step 1, or Step 2
code/methodology. Uses `scripts/trace_workflow.py` (new, read-only) to
reconstruct raw event sequences for representative executions of Step 2's
dominant payroll-items variant group (`group_009`, 107/138 segments in the
family, 15/15 sessions, 4/4 operators). Compliance: nowhere in this
investigation is the leaked test-harness/generator text used as evidence —
every claim below is sourced from genuine on-screen content
(`context.extracted_text`), DOM/click event payloads, and window titles
captured during actual recorded work, which is legitimate log data per
`DATA_SCHEMA.md`.

## 0. Headline finding: "payroll-items" is not one process

This is the most important result of this investigation, and it changes the
Step 3 scope. Tracing `group_009`'s raw events (not just Step 2's coarse
route label) shows `#/payroll-items` is a **generic queue-confirmation UI
template reused identically across at least three different portals**
(`127.0.0.1:5132`, `5133`, `5134` — window titles "HR人事給与システム",
"財務会計システム", and a third, ops-flavored one respectively), each
processing entirely different business content through the exact same
click-paste-click interaction. Classifying every observed confirmation note
by its opening phrase across all 107 segments (`reports/step3/` note survey,
reproducible via the commands in §11) found **at least 9 distinct business
processes** sharing this one route:

| business process (from note text) | observed captures |
|---|---|
| 経費精算確認済み (expense settlement confirmation) | 31 direct + ~13 "staged in Notepad" variants ≈ **44** |
| 在庫調整登録 (inventory adjustment) | 20 |
| 請求書照合完了 (invoice reconciliation) | 19 |
| 給与変更登録 (payroll/salary change) | 11 |
| IT申請処理完了 (IT request processing) | 3 |
| 発注管理処理 (purchase order management) | 2 |
| 入社照合完了 (new-hire verification) | 2 |
| 勤怠申請確認 (attendance/leave confirmation) | 1 |
| 契約管理処理 (contract management) | 1 |

Step 1/2's route-based label (`payroll-items`) is a naming artifact of the
first-observed sub-flow, not a description of the whole family. **Per
instruction #6, this rules out "automate payroll" as the Step 3 promise** —
there is no single "payroll process" here to automate end-to-end. What *is*
real and valuable is the shared mechanical pattern underneath, and the
single largest concrete business process within it: **expense settlement
confirmation**, which is ~40% of everything observed in this family — by
far the largest specific, coherent sub-flow, ahead of inventory adjustment
(20) and invoice reconciliation (19).

## 1. The invariant mechanical pattern (all sub-flows)

Traced via raw `browser_click`/`browser_form_input`/`keystroke` payloads
(exact DOM selectors, not inferred):

1. A table of pending items is visible at `#pi-table` (route
   `#/<portal-specific-name>`, e.g. `#/payroll-items`).
2. **Click a row**: `#pi-table > tbody > tr:nth-of-type(N) > td:nth-of-type(4)`
   — selects/opens item *N* (rows processed in increasing table order:
   observed N=14→15→16 within one segment).
3. **Click the note field**: `<textarea id="pi-note">`, placeholder
   "処理内容・確認コメントを入力してください…" ("please enter processing
   content / confirmation comment").
4. **Paste** (`Ctrl+V`, confirmed via `keystroke.modifiers.ctrl=true,
   key="v"`) a short (observed: consistently ~39 chars for the expense
   sub-flow) pre-composed confirmation note into that field. A
   `clipboard_change` event immediately precedes each paste.
5. **Click the confirm button**: `<button id="btn-pi-ok" class="btn
   success">`.
6. Repeat from step 2 for the next row. Observed 1–3 repetitions inside a
   single Step 1 segment (our boundary detector doesn't cut between these —
   a known, already-documented limitation from Step 1's evaluation, not a
   new finding, but visibly confirmed here).

This exact 5-step loop, with these exact selectors, was observed
identically across all 9 business processes in §0 — genuinely invariant,
not just similar.

## 2. What varies

- **Which queue/portal is open** (determines the business domain) — not
  captured within these short segments; presumably set by earlier
  navigation outside the traced window.
- **The note's content** — domain-specific data (expense category + amount;
  inventory item code + adjustment quantity; invoice number + amount;
  applicant name; dates), always following one fixed template per domain
  (e.g. `経費精算確認済み。費目：{category}　金額：{amount}円。規程内であ
  ることを確認した。`).
- **Whether a decision branch exists.** Invoice reconciliation clearly
  branches: **19 observed notes split into two outcomes** — "差異あり要
  確認" (discrepancy, needs review, appears in a majority of the sampled
  invoice notes) vs. "差異なし承認" (no discrepancy, approved). Expense
  settlement showed **zero exceptions in 46 distinct observed notes** — every
  single one ends "規程内であることを確認した" (confirmed within
  regulation). This is a real difference in observed risk profile between
  sub-flows, not an assumption.
- **A staging step for some expense items.** ~13 of the expense notes carry
  a `精算確認メモP1-<id>-<n>` prefix suggesting the note was first drafted
  in Notepad (a top app for this family) before being pasted — others go
  straight from clipboard to the form. Cause not confirmed; noted as an
  open question.
- **An apparent second approval tier.** One incidental capture reads
  "経費承認（管理職）。費目：接待交際費　金額：44,872円。規程確認のうえ承
  認。" — a *different* template ("management approval") for at least one
  higher-value entertainment-expense case. Only 2-3 instances seen; not
  enough to characterize the threshold, but enough to know a
  management-escalation path exists and should not be silently automated.

## 3. Evidence for a real, discoverable policy (not opaque human judgment)

A fragment of an actual regulation document was captured on-screen:
"接待交際費規程第１条（目的）取引先接待に関する費用の承認・計上基準を定
め...第２条（承認権限）1回あ..." ("Entertainment Expense Regulation,
Art.1: establishes approval/accounting standards for client-entertainment
costs... Art.2: approval authority per occurrence..."). This is genuine,
on-screen regulation text (not the leaked generator text) — real evidence
that the "within regulation" check has a written, discoverable rule behind
it, not just tacit reviewer judgment. **We only have a fragment of one
category's regulation** (entertainment expenses); the other four observed
categories' (transportation, business travel, supplies, training) thresholds
are not confirmed from the logs. This is stated as a gap, not filled in with
a guess.

## 4. Inputs, outputs, decision points

| | |
|---|---|
| **Inputs (per item)** | Row data: expense category, amount (assumed readable from the table row/detail panel — **not directly confirmed**, since we only observed the *pasted result*, not a capture of the row's own raw fields; a real implementation must verify this with live DOM/API access before relying on it) |
| **Inputs (policy)** | A per-category approval threshold — confirmed to exist as a written regulation; only one category's text fragment observed |
| **Output** | A submitted note (`#pi-note`) + confirm click (`#btn-pi-ok`), presumably updating item status server-side (not directly observed — no response payload visible in the client-side event log) |
| **Decision point** | Is the amount "within regulation" for this category? Binary in the expense sub-flow (100% approved in-sample); the invoice sub-flow shows a real approve/flag branch and should NOT be assumed to generalize to expenses |
| **External dependency** | The queue's underlying source system (unknown — never observed being written to, only the confirmation UI) |

## 5. Proposed Step 3 scope — the smallest meaningful, honest slice

**In scope:** automate the expense-settlement confirmation loop specifically
— for each pending item in the queue: read its category and amount, check
against a small, explicitly-labeled threshold table (seeded only from the
one confirmed category fragment; other categories marked
"needs-client-confirmation," not guessed), compose the note in the exact
observed template, paste it, click confirm. **If the category or amount
isn't confidently covered by a known rule, skip the item and add it to a
human-review list instead of guessing.**

**Explicitly out of scope, stated up front, not discovered later:**
inventory adjustment, invoice reconciliation (has a real discrepancy branch
we haven't characterized), payroll/salary changes, IT requests, new-hire
verification, attendance, purchase orders, contract management, and the
management-tier escalation path. All of these share the mechanical
click-paste-click pattern (§1) and are natural *future* extensions of the
same framework — stated as future work, not built now, per the assignment's
own "state what you deferred" guidance.

**Why this is realistic for 7 days:** the mechanical steps are fully
characterized with concrete, stable selectors (§1); the decision logic for
the in-scope slice is a simple, bounded threshold check, not open-ended
judgment; and the scope explicitly refuses to auto-approve anything outside
what's been directly observed and confirmed.

## 6. What remains manual after the prototype

- Every other queue/business-process sharing this UI pattern (§0 list minus
  expense settlement) — untouched.
- Any expense item in an unconfirmed category or above a confidently-known
  threshold — routed to a human, not decided by the bot.
- The management-tier escalation path.
- Confirming the actual, complete policy thresholds with the client (we
  have one regulation fragment, not a full policy document).
- Handling genuine exceptions/rejections in the expense flow — never
  observed in this data, so not designed for; the bot should flag rather
  than fail silently if it ever encounters one.
- Login/authentication to whatever the real production system is (never
  observed in any traced segment — sessions appear to start already
  authenticated).

## 7. Technical risks and mitigations

| risk | evidence | mitigation |
|---|---|---|
| **Authentication** | No login flow observed in any traced window — unknown mechanism (SSO/MFA/service account) for the real system | Prototype targets a stubbed/mock login step explicitly; flag as an open integration question for the client, not solved here |
| **Dynamic UI** | Selectors (`#pi-table`, `#pi-note`, `#btn-pi-ok`) were stable across every example checked, but the row selector (`tr:nth-of-type(N)`) is position-based, not ID-based — fragile if the list re-sorts mid-run | Re-query the table before each row action rather than caching row indices; treat a selector-not-found as a hard stop, not a silent skip |
| **Missing/incomplete data** | Row-level source data (category, amount) was inferred, not directly confirmed via a DOM capture of the table itself | Step 3 build must verify this with live inspection before relying on it; if unavailable, fall back to OCR/extracted-text parsing as observed in these logs |
| **Validation / business rules** | Only one category's policy text fragment observed; 100% of 46 expense notes were approvals — absence of a rejection case does not mean rejections don't happen | Ship a narrow, explicit threshold table; anything outside it is routed to a human, never auto-approved on a guess |
| **Ambiguous inputs** | No observed example of how the UI represents a rejected/flagged expense item | Treat any unexpected note pattern or button state as "skip, flag for human," never invent a rejection note |
| **Browser/app dependencies** | Workflow spans Edge (portal) + Notepad (drafting, for some items) + occasional Word (policy reference) | Prototype scope only automates the Edge-side mechanics; note composition is done by the bot directly (no Notepad round-trip needed since the bot can construct the string itself) |
| **Error handling** | No error/retry sequences observed in the traced windows | Prototype should stop and report on any unexpected state rather than retry blindly against a live system with financial consequences |

## 8. Implementation form comparison

| option | fit | verdict |
|---|---|---|
| **Browser automation script (Playwright)** | Workflow is 100% browser-based with stable, observed CSS selectors; the in-scope decision logic (threshold check) is simple deterministic code, not judgment | **Recommended** — lowest overhead for a 7-day prototype, fully auditable, no licensing cost, matches the evidence exactly |
| **Desktop RPA suite (UiPath / Power Automate Desktop)** | Same capability, plus native cross-app orchestration (useful for the Notepad-staging variant, §2) and enterprise credential/audit tooling | Reasonable for a production rollout across *all* nine sub-flows later; more setup/licensing overhead than justified for one narrow, code-friendly slice now |
| **AI agent (LLM-driven, given the procedure + policy docs)** | Could in principle read a row, consult the actual policy text, and decide — appealing given the pattern *repeats across 9 different domains* with different rules each | **Not recommended for the prototype.** The in-scope decision is a deterministic threshold check with real financial/compliance weight — non-deterministic LLM judgment adds risk (inconsistent policy interpretation, harder to audit) without adding capability this scope actually needs. Worth revisiting later specifically *because* of the 9-domain reuse pattern, once each domain's real rules are confirmed with the client and a scripted approach has proven the mechanical layer works |

**Recommended: Playwright-based browser automation**, with hard-coded
navigation to the confirmed expense queue, DOM-read row data, a small
explicit threshold table, templated note generation, and a mandatory
human-review fallback for anything not confidently covered.

## 9. Compliance check

- Did not modify `segments.jsonl`, `src/procmine/segment.py`,
  `src/procmine/label.py`, or any Step 1/2 config or methodology — this
  investigation only reads raw dataset_b events via the existing,
  unmodified `iter_events` loader.
- Did not use the leaked test-harness/generator text ("Theme M2" setup
  script) anywhere above — every quoted note/policy fragment is genuine
  on-screen `context.extracted_text` captured during actual recorded
  interaction, which `DATA_SCHEMA.md` explicitly says is fair to use.

## 10. Reproducing this investigation

```
python3 scripts/trace_workflow.py <session_id> <start_iso> <end_iso>
```
prints a condensed, chronological trace (app/window, route, clicks with
element info, form input, clipboard, navigation, extracted text) for any
segment. Representative examples used above:
`ses_20260701-164424-CHAITANYA0BCF 2026-07-01T16:45:51Z 2026-07-01T16:46:38Z`
(3-record HR-portal loop) and
`...16:52:31Z 16:53:09Z` (2-record finance-portal loop, shows the invoice
discrepancy branch).
