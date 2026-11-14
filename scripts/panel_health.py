"""Collection health of the fixed panel, per complex and per run (read-only), to judge expansion readiness.

Runs covered: every day in history.sqlite3 plus archived same-day runs in data/archive/*.sqlite3.
Per complex: collection success rate, mean duration, quality pass rate, false-zero incidents
(a 0-listing read that the quality check or same-day evidence rejected), observation time-of-day.
Per run: success, quality pass, collection span, observation window.

usage: python scripts/panel_health.py [--out docs/phase2]
"""
import argparse
import json
import sqlite3
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def kst(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(KST)


def runs():
    out = []
    main = sqlite3.connect(f"file:{ROOT / 'data' / 'history.sqlite3'}?mode=ro", uri=True)
    for (d,) in main.execute("SELECT DISTINCT day FROM batches ORDER BY day"):
        out.append((d, 'main', main))
    for p in sorted((ROOT / 'data' / 'archive').glob('history_*run.sqlite3')):
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        for (d,) in db.execute("SELECT DISTINCT day FROM batches"):
            out.append((d, p.stem.replace('history_', ''), db))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'phase2'))
    a = ap.parse_args()
    panel = {str(c['complex']): c for c in json.loads((ROOT / 'data' / 'fixed-110-panel.json').read_text(encoding='utf-8-sig'))}
    per = defaultdict(lambda: {'runs': 0, 'ok': 0, 'valid': 0, 'falseZero': 0, 'dur': [], 'hours': []})
    run_rows = []
    for day, src, db in runs():
        b = {str(c): (s, o) for c, s, o in db.execute("SELECT complex, success, observed FROM batches WHERE day=?", (day,))}
        q = {str(c): (s, r or '') for c, s, r in db.execute("SELECT complex, status, reason FROM observation_quality WHERE day=?", (day,))}
        try:
            dur = {str(c): x for c, x in db.execute("SELECT complex, duration_sec FROM collection_telemetry WHERE day=?", (day,))}
        except sqlite3.OperationalError:
            dur = {}
        times = []
        for cx in panel:
            if cx not in b:
                continue
            s, o = b[cx]
            p = per[cx]
            p['runs'] += 1
            p['ok'] += int(bool(s))
            stt, why = q.get(cx, ('UNKNOWN', ''))
            p['valid'] += int(stt == 'VALID')
            if stt != 'VALID' and '0 rows' in why:
                p['falseZero'] += 1
            if dur.get(cx):
                p['dur'].append(dur[cx])
            if s and o:
                t = kst(o)
                p['hours'].append(t.hour + t.minute / 60)
                times.append(t)
        times.sort()
        run_rows.append({'day': day, 'run': src, 'planned': len(panel),
                         'collected': sum(1 for cx in panel if b.get(cx, (0,))[0]),
                         'qualityValid': sum(1 for cx in panel if q.get(cx, ('',))[0] == 'VALID'),
                         'falseZeros': sum(1 for cx in panel if q.get(cx, ('', ''))[0] != 'VALID' and '0 rows' in q.get(cx, ('', ''))[1]),
                         'observedFromKST': times[0].isoformat(timespec='minutes') if times else None,
                         'observedToKST': times[-1].isoformat(timespec='minutes') if times else None,
                         'spanHours': round((times[-1] - times[0]).total_seconds() / 3600, 2) if times else None})
    complexes = []
    for cx, p in per.items():
        complexes.append({'complex': cx, 'district': panel[cx].get('district'), 'runs': p['runs'],
                          'successRate': round(p['ok'] / p['runs'], 2), 'qualityPassRate': round(p['valid'] / p['runs'], 2),
                          'falseZeroIncidents': p['falseZero'],
                          'meanDurationSec': round(st.mean(p['dur']), 1) if p['dur'] else None})
    n_runs = len(run_rows)
    weak = sorted((c for c in complexes if c['qualityPassRate'] < 1 or c['falseZeroIncidents']), key=lambda c: (c['qualityPassRate'], -c['falseZeroIncidents']))
    summary = {
        'runs': run_rows,
        'panel': {'complexes': len(complexes),
                  'meanSuccessRate': round(st.mean(c['successRate'] for c in complexes), 3),
                  'meanQualityPassRate': round(st.mean(c['qualityPassRate'] for c in complexes), 3),
                  'falseZeroIncidents': sum(c['falseZeroIncidents'] for c in complexes),
                  'falseZeroRatePerComplexRun': round(sum(c['falseZeroIncidents'] for c in complexes) / sum(c['runs'] for c in complexes), 4),
                  'meanDurationSec': round(st.mean([c['meanDurationSec'] for c in complexes if c['meanDurationSec']]), 1),
                  'complexesAlwaysValid': sum(1 for c in complexes if c['qualityPassRate'] == 1),
                  'scheduledRuns': sum(1 for r in run_rows if r['observedFromKST'] and 6 <= int(r['observedFromKST'][11:13]) < 9)},
        'weakComplexes': weak[:20],
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'panel-health.json').write_text(json.dumps(summary | {'complexes': complexes}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return n_runs


if __name__ == '__main__':
    main()
