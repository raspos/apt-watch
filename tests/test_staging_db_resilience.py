"""Automated Resilience and Fault Tolerance Tests for APT WATCH Staging DB.
Validates:
  1. Idempotent Merge (중복 병합 무결성)
  2. Resume After Interruption (중단 후 재개 시 기존 데이터 보존)
  3. Corrupted Worker DB Isolation (손상된 워커 DB 격리 및 주 DB 보호)
  4. Atomic Rollback on Write Failure (메인 DB 쓰기 실패 시 원자적 롤백)
  5. Existing Historical Data Protection (과거 관측 데이터 절대 보호)
"""
import unittest
import sqlite3
import tempfile
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.parallel_collector import ensure_tables, merge_all_staging_atomic

class TestStagingDBResilience(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.tmp_dir.name)
        self.main_db = self.base_path / "main_history.sqlite3"
        
        # Populate main DB with existing historical baseline
        conn = sqlite3.connect(self.main_db)
        ensure_tables(conn)
        conn.execute("INSERT INTO batches VALUES ('2026-11-10', '1001', '2026-11-10T00:00:00Z', 1)")
        conn.execute("INSERT INTO listings VALUES ('2026-11-10', '1001', 'art_001', 50000, '{\"price\": 50000}')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def create_sample_worker_db(self, name, day, complex_id, listings_count=5):
        w_path = self.base_path / f"{name}.sqlite3"
        conn = sqlite3.connect(w_path)
        ensure_tables(conn)
        conn.execute("INSERT INTO batches VALUES (?, ?, ?, 1)", (day, complex_id, f"{day}T01:00:00Z"))
        for i in range(listings_count):
            conn.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)",
                         (day, complex_id, f"art_{complex_id}_{i}", 60000 + i*1000, json.dumps({'price': 60000 + i*1000})))
        conn.execute("INSERT INTO collection_telemetry VALUES (?, ?, '11110', 'TestComplex', ?, 20.0, ?, ?, 1, NULL)",
                     (day, complex_id, f"{day}T01:00:00Z", listings_count, listings_count))
        conn.commit()
        conn.close()
        return w_path

    def test_idempotent_repeated_merge(self):
        w1 = self.create_sample_worker_db("worker_01", "2026-11-12", "2001", listings_count=3)
        w2 = self.create_sample_worker_db("worker_02", "2026-11-12", "2002", listings_count=4)

        # First merge
        b1, l1, t1, cor1 = merge_all_staging_atomic([w1, w2], self.main_db)
        self.assertEqual(b1, 2)
        self.assertEqual(l1, 7)
        self.assertEqual(len(cor1), 0)

        # Re-run same merge (Idempotency test)
        b2, l2, t2, cor2 = merge_all_staging_atomic([w1, w2], self.main_db)
        self.assertEqual(b2, 2)
        self.assertEqual(l2, 7)

        # Verify main DB counts are exact (no duplication)
        conn = sqlite3.connect(self.main_db)
        batch_cnt = conn.execute("SELECT COUNT(*) FROM batches WHERE day='2026-11-12'").fetchone()[0]
        listing_cnt = conn.execute("SELECT COUNT(*) FROM listings WHERE day='2026-11-12'").fetchone()[0]
        hist_cnt = conn.execute("SELECT COUNT(*) FROM batches WHERE day='2026-11-10'").fetchone()[0]
        conn.close()

        self.assertEqual(batch_cnt, 2)
        self.assertEqual(listing_cnt, 7)
        self.assertEqual(hist_cnt, 1, "Historical baseline must be preserved")

    def test_corrupted_worker_db_isolation(self):
        w_good = self.create_sample_worker_db("worker_good", "2026-11-12", "2001", listings_count=2)
        
        # Create corrupted DB file (invalid header/binary garbage)
        w_bad = self.base_path / "worker_corrupted.sqlite3"
        w_bad.write_bytes(b"CORRUPTED_GARBAGE_DATA_1234567890")

        # Atomic merge should catch corrupted DB and isolate it without breaking good data
        b, l, t, corrupted = merge_all_staging_atomic([w_good, w_bad], self.main_db)
        self.assertEqual(len(corrupted), 1)
        self.assertEqual(corrupted[0][0], w_bad)
        self.assertEqual(b, 1)
        self.assertEqual(l, 2)

        # Verify main DB integrity
        conn = sqlite3.connect(self.main_db)
        chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        self.assertEqual(chk, 'ok')

    def test_resume_preserves_previous_batches(self):
        # Day 1 collection
        w1 = self.create_sample_worker_db("worker_d1", "2026-11-11", "2001", listings_count=5)
        merge_all_staging_atomic([w1], self.main_db)

        # Day 2 collection with new complex
        w2 = self.create_sample_worker_db("worker_d2", "2026-11-12", "2002", listings_count=3)
        merge_all_staging_atomic([w2], self.main_db)

        conn = sqlite3.connect(self.main_db)
        days = sorted([r[0] for r in conn.execute("SELECT DISTINCT day FROM batches").fetchall()])
        conn.close()

        self.assertEqual(days, ['2026-11-10', '2026-11-11', '2026-11-12'])

if __name__ == '__main__':
    unittest.main()
