"""Unattended entry point for Windows Task Scheduler (run with pythonw.exe).

Why: console processes launched by Task Scheduler on this PC were terminated immediately with
0xC000013A (Ctrl+C / console close). Running without any console avoids that.

  * full output      -> data/logs/unattended_<YYYY-MM-DD_HHMMSS>.log (line-buffered)
  * run summary      -> data/logs/unattended_<...>.summary.json, rewritten whenever a stage changes
  * stale runs       -> a previous summary still in RUNNING is reclassified INTERRUPTED / UNKNOWN_TERMINATION
  * child processes  -> started without a console window (collector, analysis scripts, git)

Final status
  PUBLISHED            pushed to GitHub AND the Pages deployment for that commit succeeded
  PUBLISH_UNCONFIRMED  pushed, but the Pages deployment result could not be confirmed
  COMPLETED_WITHHELD   ran to the end, publication withheld by the quality gate (incl. PARTIAL_SUCCESS)
  FAILED               exception, crash, push failure or Pages deployment failure
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
REPO_API = 'https://api.github.com/repos/raspos/apt-watch/actions/runs'

STAGES = ('collection', 'quality', 'gate', 'analysis', 'backup', 'publicationApproval', 'githubPush', 'pagesDeploy')

# (substring in daily_operation output, stage, state)
MARKERS = [
    ('[Step 1] Starting supervised', 'collection', 'RUNNING'),
    ('[Quality] {', 'collection', 'DONE'),
    ('[Quality] {', 'quality', 'DONE'),
    ('판정 상태:', 'gate', 'DONE'),
    ('[CRITICAL QUALITY FAILURE]', 'publicationApproval', 'WITHHELD'),
    ('[Step 3] Running Analytical Pipeline', 'analysis', 'RUNNING'),
    ('[Step 5] Post-run Automated Quality', 'analysis', 'DONE'),
    ('[Step 6] Creating standalone SQLite Backup', 'backup', 'RUNNING'),
    ('Verified standalone backup saved', 'backup', 'DONE'),
    ('[Step 8] Pushing verified site payload', 'publicationApproval', 'APPROVED'),
    ('[Step 8] Skipping public GitHub deployment', 'publicationApproval', 'WITHHELD'),
    ('Successfully pushed daily update', 'githubPush', 'DONE'),
    ('[CRITICAL DEPLOYMENT FAILURE]', 'githubPush', 'FAILED'),
    ('site/data.json is unchanged; no new git commit needed', 'githubPush', 'NOT_NEEDED'),
]

# Child Python processes inherit this. Without it, pythonw children wrote cp949 to pipes that the
# parent decodes as utf-8, which killed subprocess reader threads (seen 2026-11-14).
os.environ['PYTHONIOENCODING'] = 'utf-8'

if sys.platform == 'win32':
    _orig_init = subprocess.Popen.__init__

    def _no_window_init(self, *args, **kwargs):
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _no_window_init


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Summary:
    def __init__(self, path, base):
        self.path = path
        self.data = dict(base)
        self.data['stages'] = {s: 'PENDING' for s in STAGES}
        self.data['gateStatus'] = None
        self.save()

    def stage(self, name, state):
        if self.data['stages'].get(name) != state:
            self.data['stages'][name] = state
            self.data['lastStage'] = name
            self.data['lastStageAt'] = _now()
            self.save()

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.path)


class TeeTracker:
    """File-like object: writes to the log and updates stage states from known output markers."""

    def __init__(self, log, summary):
        self.log, self.summary, self.buf = log, summary, ''

    def write(self, s):
        self.log.write(s)
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            self.feed(line)
        return len(s)

    def feed(self, line):
        for marker, stage, state in MARKERS:
            if marker in line:
                self.summary.stage(stage, state)
        if '판정 상태:' in line:
            self.summary.data['gateStatus'] = line.split(':', 1)[1].strip()
            self.summary.save()

    def flush(self):
        self.log.flush()


def mark_stale_runs(log_dir, current=None):
    """Reclassify summaries left in RUNNING by a killed process or a power loss."""
    changed = []
    for p in sorted(log_dir.glob('unattended_*.summary.json')):
        if current and p == current:
            continue
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        if d.get('status') != 'RUNNING':
            continue
        log = Path(d.get('log', ''))
        d['status'] = 'INTERRUPTED' if log.exists() and log.stat().st_size > 0 else 'UNKNOWN_TERMINATION'
        d['terminationDetectedAt'] = _now()
        d['terminationNote'] = 'process ended without writing a final status (forced kill, power loss or sleep)'
        if log.exists():
            d['lastLogLines'] = log.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-5:]
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
        changed.append(p.name)
    return changed


def classify(exit_code, stages, error=None):
    if error is not None or exit_code not in (0, 1):
        return 'FAILED'
    if stages.get('githubPush') == 'FAILED' or stages.get('pagesDeploy') == 'FAILED':
        return 'FAILED'
    if stages.get('githubPush') == 'DONE':
        return 'PUBLISHED' if stages.get('pagesDeploy') == 'DONE' else 'PUBLISH_UNCONFIRMED'
    return 'COMPLETED_WITHHELD'


def check_pages_deploy(sha, wait_sec=900, poll=30):
    """Return DONE / FAILED / UNCONFIRMED for the Pages workflow run of `sha`."""
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'{REPO_API}?head_sha={sha}&per_page=5', timeout=20) as r:
                runs = json.load(r).get('workflow_runs', [])
            runs = [x for x in runs if 'Pages' in (x.get('name') or '')] or runs
            if runs and runs[0].get('status') == 'completed':
                return 'DONE' if runs[0].get('conclusion') == 'success' else 'FAILED'
        except Exception:
            pass
        time.sleep(poll)
    return 'UNCONFIRMED'


def collect_facts(day, manifest_path):
    """Facts read back from the DB / site files after the run (never from claims in the log)."""
    out = {}
    try:
        out['plannedComplexes'] = len(json.loads(Path(manifest_path).read_text(encoding='utf-8-sig')))
        with sqlite3.connect(f"file:{ROOT / 'data' / 'history.sqlite3'}?mode=ro", uri=True) as db:
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
        n = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8')).get('negoIndex') or {}
        out['nego'] = {'asOf': n.get('asOf'), 'status': n.get('status'), 'level': n.get('currentNegoLevel'),
                       'change1d': ((n.get('changes') or {}).get('1d') or {}).get('deltaPctPoint')}
    except Exception as e:  # facts must never hide the run's own result
        out['factsError'] = repr(e)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--day')
    ap.add_argument('--manifest', default=str(ROOT / 'data' / 'fixed-110-panel.json'))
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--timeout', type=int, default=10800)
    ap.add_argument('--log-dir', default=str(ROOT / 'data' / 'logs'))
    a = ap.parse_args(argv)
    day = a.day or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()

    log_dir = Path(a.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stale = mark_stale_runs(log_dir)
    stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    log_path = log_dir / f'unattended_{stamp}.log'
    summary = Summary(log_dir / f'unattended_{stamp}.summary.json', {
        'day': day, 'startedAt': _now(), 'finishedAt': None, 'exitCode': None, 'status': 'RUNNING',
        'python': sys.executable, 'root': str(ROOT), 'log': str(log_path), 'staleRunsReclassified': stale})

    log = open(log_path, 'w', encoding='utf-8', buffering=1)
    tee = TeeTracker(log, summary)
    sys.stdout = sys.stderr = tee
    code, error = 3, None
    try:
        import daily_operation
        code = daily_operation.run_daily_operation(day=day, manifest_path=a.manifest, workers=a.workers, timeout=a.timeout)
    except BaseException as e:  # includes SystemExit / KeyboardInterrupt
        error = f'{type(e).__name__}: {e}'
        traceback.print_exc()
        code = getattr(e, 'code', None) if isinstance(e, SystemExit) and isinstance(getattr(e, 'code', None), int) else 3
    finally:
        st = summary.data['stages']
        if st['githubPush'] == 'DONE':
            sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            summary.data['pushedCommit'] = sha
            summary.stage('pagesDeploy', 'RUNNING')
            summary.stage('pagesDeploy', check_pages_deploy(sha))
        elif st['githubPush'] == 'PENDING':
            summary.stage('githubPush', 'NOT_ATTEMPTED')
        summary.data.update(collect_facts(day, a.manifest))
        summary.data['error'] = error
        summary.data['exitCode'] = code
        summary.data['finishedAt'] = _now()
        summary.data['status'] = classify(code, summary.data['stages'], error)
        summary.data['lastLogLines'] = log_path.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-5:]
        summary.save()
        print(f"EXIT CODE {code} STATUS {summary.data['status']}")
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__   # avoid Python's exit code 120 on flushing a closed log
        log.close()
    return code


if __name__ == '__main__':
    sys.exit(main())
