"""MOCK / REPRODUCTION of the observed dataset_b "payroll-items" queue
confirmation screen. This is NOT the original Dataset B application (that
was a local test-harness server we don't have access to or source for) --
it is a small Flask app built from scratch for this prototype, reproducing
the DOM structure, element IDs, and interaction pattern that were directly
observed in the raw event logs during the Step 3 feasibility investigation
(see reports/step3/payroll_items_feasibility.md §1 and the raw payloads
captured there):

  - a table with id="pi-table", rows with a 4th <td> that's clicked to
    select/open an item
  - a textarea id="pi-note" with the exact observed placeholder text
  - a button id="btn-pi-ok" with class="btn success"

State is in-memory only (a Python list, reset every time this process
restarts) -- there is no real backend behind it. It exists purely so the
Playwright automation script (automation/run_automation.py) has something
real to drive locally, without needing access to the original recording
environment.

Run: python3 automation/mock_app.py
Then browse to http://127.0.0.1:5001/ to see it directly, or run
automation/run_automation.py against it.
"""
from __future__ import annotations

import copy

from flask import Flask, jsonify, render_template_string, request

from sample_data import ITEMS

app = Flask(__name__)
# Deep copy so re-running the automation against a fresh `flask run` always
# starts from the same known state.
items = copy.deepcopy(ITEMS)

PAGE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>MOCK: 経費精算キュー (payroll-items reproduction)</title>
<style>
  body { font-family: sans-serif; margin: 2em; }
  .banner { background: #fff3cd; border: 1px solid #ffe69c; padding: 0.75em 1em; margin-bottom: 1em; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ccc; padding: 0.5em; text-align: left; }
  td.action-cell { cursor: pointer; color: #0a58ca; }
  tr.confirmed td.action-cell { color: #198754; cursor: default; }
  .panel { margin-top: 1em; padding: 1em; border: 1px solid #999; max-width: 700px; display: none; }
  textarea#pi-note { width: 100%; height: 64px; }
  .btn.success { background: #198754; color: white; border: none; padding: 0.5em 1.2em; margin-top: 0.5em; cursor: pointer; }
</style>
</head>
<body>
  <div class="banner"><b>MOCK / REPRODUCTION</b> -- not the original Dataset B application.
  Built from observed DOM structure only. See reports/step3/step3_prototype.md.</div>
  <h1>経費精算キュー (Expense Settlement Queue)</h1>
  <table id="pi-table">
    <thead><tr><th>#</th><th>費目 (category)</th><th>金額 (amount)</th><th>操作 (action)</th></tr></thead>
    <tbody>
    {% for item in items %}
      <tr id="row-{{ item.id }}" class="{{ 'confirmed' if item.status == 'confirmed' else '' }}">
        <td>{{ item.id }}</td>
        <td>{{ item.category }}</td>
        <td>{{ '¥{:,}'.format(item.amount) if item.amount is not none else '(missing)' }}</td>
        <td class="action-cell" data-item-id="{{ item.id }}" data-category="{{ item.category }}"
            data-amount="{{ item.amount if item.amount is not none else '' }}"
            onclick="selectItem(this)">
          {{ '確認済み' if item.status == 'confirmed' else '未処理 (click to process)' }}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="panel" id="detail-panel">
    <div>選択item: <span id="detail-id"></span> / <span id="detail-category"></span> / <span id="detail-amount"></span></div>
    <textarea id="pi-note" placeholder="処理内容・確認コメントを入力してください…"></textarea><br>
    <button id="btn-pi-ok" class="btn success" onclick="confirmItem()">OK</button>
    <span id="confirm-status"></span>
  </div>

<script>
let selectedId = null;
function selectItem(el) {
  selectedId = el.dataset.itemId;
  document.getElementById('detail-panel').style.display = 'block';
  document.getElementById('detail-id').innerText = selectedId;
  document.getElementById('detail-category').innerText = el.dataset.category;
  document.getElementById('detail-amount').innerText = el.dataset.amount;
  document.getElementById('pi-note').value = '';
  document.getElementById('confirm-status').innerText = '';
}
async function confirmItem() {
  const note = document.getElementById('pi-note').value;
  const res = await fetch(`/api/items/${selectedId}/confirm`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note})
  });
  const data = await res.json();
  if (data.ok) {
    document.getElementById('confirm-status').innerText = 'OK: confirmed';
    const row = document.getElementById(`row-${selectedId}`);
    row.classList.add('confirmed');
    row.querySelector('.action-cell').innerText = '確認済み';
  } else {
    document.getElementById('confirm-status').innerText = 'ERROR: ' + data.error;
  }
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE, items=items)


@app.route("/api/items")
def api_items():
    return jsonify(items)


@app.route("/api/items/<int:item_id>/confirm", methods=["POST"])
def api_confirm(item_id):
    body = request.get_json(force=True) or {}
    note = body.get("note", "")
    for item in items:
        if item["id"] == item_id:
            if not note.strip():
                return jsonify({"ok": False, "error": "empty note"}), 400
            item["status"] = "confirmed"
            item["note"] = note
            return jsonify({"ok": True, "item": item})
    return jsonify({"ok": False, "error": "not found"}), 404


@app.route("/api/reset", methods=["POST"])
def api_reset():
    global items
    items = copy.deepcopy(ITEMS)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
