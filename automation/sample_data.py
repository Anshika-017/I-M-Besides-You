"""Deterministic sample expense-settlement items for the mock app.

Not real data -- constructed to exercise every branch of decision.py's
rule (see reports/step3/step3_prototype.md for the mapping from item to
expected outcome). Category names and the note template match what was
directly observed in dataset_b (see automation/decision.py's citations);
the specific people/amounts here are invented sample data for the demo,
clearly not drawn from any real record.
"""

ITEMS = [
    {"id": 1, "category": "交通費精算", "amount": 12_500, "applicant": "田中 一郎"},
    {"id": 2, "category": "出張旅費", "amount": 45_000, "applicant": "佐藤 花子"},
    {"id": 3, "category": "研修費", "amount": 30_000, "applicant": "鈴木 健太"},
    {"id": 4, "category": "消耗品費", "amount": 8_000, "applicant": "高橋 美咲"},
    {"id": 5, "category": "接待交際費", "amount": 35_000, "applicant": "伊藤 直樹"},
    {"id": 6, "category": "接待交際費", "amount": 50_000, "applicant": "渡辺 亮"},
    {"id": 7, "category": "接待交際費", "amount": 120_000, "applicant": "山本 さくら"},
    {"id": 8, "category": "福利厚生費", "amount": 15_000, "applicant": "小林 大輔"},
    {"id": 9, "category": "出張旅費", "amount": None, "applicant": "加藤 美穂"},
]
