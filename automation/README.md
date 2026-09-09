# Step 3 prototype: expense settlement confirmation automation

Full writeup: `../reports/step3/step3_prototype.md` (scope, evidence,
architecture, risks, limitations). This file is just a quick-start.

```bash
pip install -r ../requirements.txt
python3 -m playwright install chromium   # one-time

python3 run_automation.py                # runs everything end to end
```

- `decision.py` — the business rule (pure Python, no browser dependency)
- `mock_app.py` — Flask reproduction of the observed queue UI (clearly
  labeled as a mock — see the full report for what it's based on)
- `sample_data.py` — deterministic demo data
- `run_automation.py` — Playwright driver
- `output/` — generated each run: `automation_log.json`,
  `human_review_queue.json`, `final_queue_state.png`

Tests: `python3 -m pytest ../tests/test_step3_decision.py ../tests/test_step3_integration.py -v`
