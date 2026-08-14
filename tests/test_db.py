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


class TestUpsertXtgal:
    def test_noop_when_empty(self, db_path):
        db.upsert_xtgal([], db_path=db_path)
        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM xtgal_watchlist').fetchone()[0]
        conn.close()
        assert count == 0

    def test_inserts_new_row(self, db_path):
        db.upsert_xtgal(['1111111111111111111'], db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute('SELECT atlas_id, active, date_added FROM xtgal_watchlist').fetchone()
        conn.close()
        assert row[0] == 1111111111111111111
        assert row[1] == 1
        assert row[2] is not None

    def test_does_not_create_duplicate(self, db_path):
        db.upsert_xtgal(['1111111111111111111'], db_path=db_path)
        db.upsert_xtgal(['1111111111111111111'], db_path=db_path)
        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM xtgal_watchlist').fetchone()[0]
        conn.close()
        assert count == 1


class TestDeactivateBefore:
    def test_deactivates_old_entries(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO xtgal_watchlist (atlas_id, date_added, active) VALUES (1111111111111111111, '2026-01-01', 1)")
        conn.commit()
        conn.close()
        db.deactivate_old_alerts('2026-06-01', db_path=db_path)
        conn = sqlite3.connect(db_path)
        active = conn.execute('SELECT active FROM xtgal_watchlist').fetchone()[0]
        conn.close()
        assert active == 0

    def test_leaves_recent_entries_active(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO xtgal_watchlist (atlas_id, date_added, active) VALUES (1111111111111111111, '2026-07-01', 1)")
        conn.commit()
        conn.close()
        db.deactivate_old_alerts('2026-06-01', db_path=db_path)
        conn = sqlite3.connect(db_path)
        active = conn.execute('SELECT active FROM xtgal_watchlist').fetchone()[0]
        conn.close()
        assert active == 1


class TestGetActiveXtgalIds:
    def test_returns_empty_when_no_entries(self, db_path):
        assert db.get_active_xtgal_ids(db_path=db_path) == []

    def test_returns_only_active_ids(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO xtgal_watchlist (atlas_id, active) VALUES (1111111111111111111, 1)")
        conn.execute("INSERT INTO xtgal_watchlist (atlas_id, active) VALUES (2222222222222222222, 0)")
        conn.commit()
        conn.close()
        ids = db.get_active_xtgal_ids(db_path=db_path)
        assert ids == [1111111111111111111]


class TestLogSlackMessage:
    def test_inserts_row(self, db_path):
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                              telescope='SALT', atlas_id=1120650750361606600,
                              db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_id, sender_name, telescope, atlas_id FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row == ('B123', 'ATLAS SALT Triggers', 'SALT', 1120650750361606600)

    def test_duplicate_slack_ts_is_noop(self, db_path):
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                              atlas_id=1120650750361606600, db_path=db_path)
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                              atlas_id=1120650750361606600, db_path=db_path)
        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM slack_messages').fetchone()[0]
        conn.close()
        assert count == 1

    def test_duplicate_slack_ts_with_null_atlas_id_is_not_deduped(self, db_path):
        # Claude wrote this for issue #37 (2026-08-14): UNIQUE(slack_ts, atlas_id)
        # doesn't catch this because SQL treats every NULL as distinct - see #37 discussion.
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM slack_messages').fetchone()[0]
        conn.close()
        assert count == 2

    def test_successful_insert_logs_at_info(self, db_path, caplog):
        # Claude wrote this for the logging review (2026-08-14)
        with caplog.at_level('INFO'):
            db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                                  atlas_id=1120650750361606600, status='Triggered', db_path=db_path)
        assert 'Logged slack message' in caplog.text
        assert '1120650750361606600' in caplog.text

    def test_ignored_duplicate_does_not_log_at_info(self, db_path, caplog):
        # Claude wrote this for the logging review (2026-08-14)
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                              atlas_id=1120650750361606600, db_path=db_path)
        with caplog.at_level('INFO'):
            db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                                  atlas_id=1120650750361606600, db_path=db_path)
        assert 'Logged slack message' not in caplog.text


class TestGetLastSlackTs:
    def test_returns_none_when_empty(self, db_path):
        assert db.get_last_slack_ts(db_path=db_path) is None

    def test_returns_max_ts(self, db_path):
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        db.log_slack_message('1690834000.000100', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        assert db.get_last_slack_ts(db_path=db_path) == '1690834000.000100'
