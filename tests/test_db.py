import os
import sqlite3
import pytest
import atlas_sao.db as db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / 'test.db')
    conn = sqlite3.connect(path)
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'log.sql')
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.close()
    return path


class TestLogAdded:
    def test_noop_when_empty(self, db_path):
        db.log_added([], 'bk_peak', db_path=db_path)
        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM bk_peak').fetchone()[0]
        conn.close()
        assert count == 0

    def test_inserts_rows(self, db_path):
        db.log_added(['1111111111111111111', '2222222222222222222'], 'bk_peak', db_path=db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute('SELECT atlas_id, date_removed, date_added FROM bk_peak ORDER BY atlas_id').fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0][0] == 1111111111111111111
        assert rows[0][1] is None
        assert rows[0][2] is not None

    def test_inserts_vra_score(self, db_path):
        db.log_added(['1111111111111111111'], 'bk_peak',
                     vra_scores={'1111111111111111111': 9.5}, db_path=db_path)
        conn = sqlite3.connect(db_path)
        score = conn.execute('SELECT vra_score_when_added FROM bk_peak').fetchone()[0]
        conn.close()
        assert score == 9.5

    def test_null_vra_score_when_not_provided(self, db_path):
        db.log_added(['1111111111111111111'], 'bk_peak', db_path=db_path)
        conn = sqlite3.connect(db_path)
        score = conn.execute('SELECT vra_score_when_added FROM bk_peak').fetchone()[0]
        conn.close()
        assert score is None


class TestLogRemoved:
    def test_noop_when_empty(self, db_path):
        db.log_added(['1111111111111111111'], 'bk_peak', db_path=db_path)
        db.log_removed([], 'bk_peak', db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute('SELECT date_removed FROM bk_peak').fetchone()
        conn.close()
        assert row[0] is None

    def test_sets_date_removed_and_updates_timestamp(self, db_path):
        db.log_added(['1111111111111111111'], 'bk_peak', db_path=db_path)
        db.log_removed(['1111111111111111111'], 'bk_peak', db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute('SELECT date_removed, timestamp FROM bk_peak').fetchone()
        conn.close()
        assert row[0] is not None
        assert row[1] is not None

    def test_only_updates_open_row(self, db_path):
        db.log_added(['1111111111111111111'], 'bk_peak', db_path=db_path)
        db.log_removed(['1111111111111111111'], 'bk_peak', db_path=db_path)
        db.log_added(['1111111111111111111'], 'bk_peak', db_path=db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute('SELECT date_removed FROM bk_peak ORDER BY id').fetchall()
        conn.close()
        assert rows[0][0] is not None
        assert rows[1][0] is None
