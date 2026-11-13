"""Unattended entry point for Windows Task Scheduler (run with pythonw.exe).

Why: console processes launched by Task Scheduler on this PC were terminated immediately with
0xC000013A (Ctrl+C / console close). Running without any console avoids that.

  * full output      -> data/logs/unattended_<YYYY-MM-DD_HHMMSS>.log (line-buffered, survives a kill)
  * run summary      -> data/logs/unattended_<...>.summary.json (written at start, updated at the end)
  * child processes  -> started without a console window (collector, analysis scripts, git)
  * exit code        -> daily_operation's code (0 ok/partial, 1 quality breach, 2 deploy failure, 3 crash)
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

if sys.platform == 'win32':
    _orig_init = subprocess.Popen.__init__

    def _no_window_init(self, *args, **kwargs):
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _no_window_init


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def collect_summary(day, manifest_path):
    """Facts read back from the DB / site files after the run (never from claims in the log)."""
    out = {}
    try:
        planned = json.loads(Path(manifest_path).read_text(encoding='utf-8-sig'))
        out['plannedComplexes'] = len(planned)
        with sqlite3.connect(f"file:{ROOT / 'data' / 'history.sqlite3'}?mode=ro", uri=True) as db:
            out['batchesRecorded'] = db.execute("SELECT COUNT(*) FROM batches WHERE day=?", (day,)).fetchone()[0]
            out['collectedComplexes'] = db.execute("SELECT COUNT(*) FROM batches WHERE day=? AND success=1", (day,)).fetchone()[0]
            out['listingsStored'] = db.execute("SELECT COUNT(*) FROM listings WHERE day=?", (day,)).fetchone()[0]
            try:
                out['qualityByStatus'] = dict(db.execute("SELECT status, COUNT(*) FROM observation_quality WHERE day=? GROUP BY status", (day,)).fetchall())
                out['qualityVerifiedComplexes'] = out['qualityByStatus'].get('VALID', 0)
            except sqlite3.OperationalError:
                out['qualityVerifiedComplexes'] = None
            try:
                out['retryAttempts'] = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE day=?", (day,)).fetchone()[0]
                out['retryAccepted'] = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE day=? AND accepted=1", (day,)).fetchone()[0]
            except sqlite3.OperationalError:
                out['retryAttempts'] = 0
            out['sqliteIntegrity'] = db.execute("PRAGMA integrity_check").fetchone()[0]
        site = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8'))
        n = site.get('negoIndex') or {}
        out['nego'] = {'asOf': n.get('asOf'), 'status': n.get('status'),
                       'level': n.get('currentNegoLevel'),
                       'change1d': ((n.get('changes') or {}).get('1d') or {}).get('deltaPctPoint')}
        out['publicationAllowed'] = bool(n.get('officialPublicationAllowed')) and n.get('status') != 'HELD_VERIFICATION'
        q = ROOT / 'data' / 'logs' / f'quality_{day}.json'
        if q.exists():
            out['qualityGateInput'] = json.loads(q.read_text(encoding='utf-8'))
    except Exception as e:  # summary must never hide the run's own result
        out['summaryError'] = repr(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day')
    ap.add_argument('--manifest', default=str(ROOT / 'data' / 'fixed-110-panel.json'))
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--timeout', type=int, default=10800)
    a = ap.parse_args()
    day = a.day or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()

    log_dir = ROOT / 'data' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    log_path = log_dir / f'unattended_{stamp}.log'
    sum_path = log_dir / f'unattended_{stamp}.summary.json'
    summary = {'day': day, 'startedAt': _now(), 'finishedAt': None, 'exitCode': None,
               'status': 'RUNNING', 'python': sys.executable, 'root': str(ROOT), 'log': str(log_path)}
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    log = open(log_path, 'w', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log
    code = 3
    try:
        import daily_operation
        code = daily_operation.run_daily_operation(day=day, manifest_path=a.manifest, workers=a.workers, timeout=a.timeout)
    except Exception:
        traceback.print_exc()
        code = 3
    finally:
        text = log_path.read_text(encoding='utf-8', errors='replace') if log_path.exists() else ''
        summary.update(collect_summary(day, a.manifest))
        summary['githubPushed'] = 'Successfully pushed daily update' in text
        summary['finishedAt'] = _now()
        summary['exitCode'] = code
        summary['status'] = {0: 'COMPLETED', 1: 'QUALITY_BREACH', 2: 'DEPLOY_FAILED'}.get(code, 'CRASHED')
        summary['lastLogLines'] = text.strip().splitlines()[-5:]
        sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'EXIT CODE {code}')
        log.close()
    sys.exit(code)


if __name__ == '__main__':
    main()
