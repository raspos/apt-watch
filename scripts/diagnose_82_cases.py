import json
from pathlib import Path
from collections import defaultdict
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
report_path = ROOT / 'data' / 'nego_matching_audit_report.json'

data = json.loads(report_path.read_text(encoding='utf-8'))
cases = data.get('sampleMatchingCases', [])
print(f"Sample cases in json: {len(cases)}")
for i, c in enumerate(cases):
    print(f"[{i+1}] {c['complex']} ({c['district']} {c['dong']}) | "
          f"Contract: {c['contractDay']} vs Obs: {c['listingFirstObserved']} ~ {c['listingLastObserved']} | "
          f"Gap(First - Contract): {c['daysBetweenContractAndFirstObs']}d | "
          f"Price: Ask {c['p_last_manwon']} vs Contract {c['p_contract_manwon']} -> Nego: {c['closingNegoPct']}%")
