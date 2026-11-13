import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import run_daily_unattended as rdu  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def st(self, **kw):
        s = {k: 'PENDING' for k in rdu.STAGES}
        s.update(kw)
        return s

    def test_partial_is_withheld_not_completed(self):
        self.assertEqual(rdu.classify(0, self.st(publicationApproval='WITHHELD', githubPush='NOT_ATTEMPTED')), 'COMPLETED_WITHHELD')

    def test_quality_breach_is_withheld(self):
        self.assertEqual(rdu.classify(1, self.st(publicationApproval='WITHHELD')), 'COMPLETED_WITHHELD')

    def test_push_without_pages_is_not_published(self):
        self.assertEqual(rdu.classify(0, self.st(githubPush='DONE', pagesDeploy='UNCONFIRMED')), 'PUBLISH_UNCONFIRMED')
        self.assertEqual(rdu.classify(0, self.st(githubPush='DONE', pagesDeploy='FAILED')), 'FAILED')

    def test_published_requires_push_and_pages(self):
        self.assertEqual(rdu.classify(0, self.st(githubPush='DONE', pagesDeploy='DONE')), 'PUBLISHED')

    def test_exception_or_deploy_failure_is_failed(self):
        self.assertEqual(rdu.classify(3, self.st(), error='RuntimeError: x'), 'FAILED')
        self.assertEqual(rdu.classify(2, self.st(githubPush='FAILED')), 'FAILED')


class StageTrackingTest(unittest.TestCase):
    def test_markers_update_summary_during_run(self):
        with tempfile.TemporaryDirectory() as d:
            s = rdu.Summary(Path(d) / 's.json', {'status': 'RUNNING'})
            log = open(Path(d) / 'l.log', 'w', encoding='utf-8')
            t = rdu.TeeTracker(log, s)
            t.write('[Step 1] Starting supervised Naver collection\n')
            self.assertEqual(json.loads((Path(d) / 's.json').read_text(encoding='utf-8'))['stages']['collection'], 'RUNNING')
            t.write("[Quality] {'valid': 1}\n  판정 상태:                 PARTIAL_SUCCESS\n")
            t.write('[Step 8] Skipping public GitHub deployment (Status: PARTIAL_SUCCESS).\n')
            saved = json.loads((Path(d) / 's.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['stages']['quality'], 'DONE')
            self.assertEqual(saved['gateStatus'], 'PARTIAL_SUCCESS')
            self.assertEqual(saved['stages']['publicationApproval'], 'WITHHELD')
            log.close()


class StaleRunTest(unittest.TestCase):
    def test_running_summary_is_reclassified(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'unattended_a.log').write_text('[Step 1] Starting\n', encoding='utf-8')
            (d / 'unattended_a.summary.json').write_text(json.dumps({'status': 'RUNNING', 'log': str(d / 'unattended_a.log')}), encoding='utf-8')
            (d / 'unattended_b.summary.json').write_text(json.dumps({'status': 'RUNNING', 'log': str(d / 'missing.log')}), encoding='utf-8')
            rdu.mark_stale_runs(d)
            self.assertEqual(json.loads((d / 'unattended_a.summary.json').read_text(encoding='utf-8'))['status'], 'INTERRUPTED')
            self.assertEqual(json.loads((d / 'unattended_b.summary.json').read_text(encoding='utf-8'))['status'], 'UNKNOWN_TERMINATION')


if __name__ == '__main__':
    unittest.main()
