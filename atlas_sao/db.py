# Claude wrote this for BK_ provenance tracking (2026-06-30)
import os
import sqlite3


def get_connection(db_path: str = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = os.environ.get(
            'ATLAS_SAO_DB_PATH',
            os.path.join(os.path.dirname(__file__), '..', 'db', 'log.db')
        )
    return sqlite3.connect(db_path)


def log_added(atlas_ids: list, bk_table: str, vra_scores: dict = None, db_path: str = None) -> None:
    if not atlas_ids:
        return
    rows = [
        (int(aid), vra_scores.get(str(aid)) if vra_scores else None)
        for aid in atlas_ids
    ]
    with get_connection(db_path) as conn:
        conn.executemany(
            f'INSERT INTO {bk_table} (atlas_id, date_added, vra_score_when_added) '
            f'VALUES (?, CURRENT_TIMESTAMP, ?)',
            rows
        )


def log_removed(atlas_ids: list, bk_table: str, db_path: str = None) -> None:
    if not atlas_ids:
        return
    with get_connection(db_path) as conn:
        conn.executemany(
            f'UPDATE {bk_table} '
            f'SET date_removed = CURRENT_TIMESTAMP, timestamp = CURRENT_TIMESTAMP '
            f'WHERE atlas_id = ? AND date_removed IS NULL',
            [(int(aid),) for aid in atlas_ids]
        )


def upsert_xtgal(entries: list, db_path: str = None) -> None:
    if not entries:
        return
    rows = [(int(aid), score, score) for aid, score in entries]
    with get_connection(db_path) as conn:
        conn.executemany(
            'INSERT OR IGNORE INTO xtgal_3mnths (atlas_id, date_added, vra_score_when_added, vra_score_now) '
            'VALUES (?, CURRENT_TIMESTAMP, ?, ?)',
            rows
        )
        conn.executemany(
            'UPDATE xtgal_3mnths SET vra_score_now = ?, timestamp = CURRENT_TIMESTAMP WHERE atlas_id = ?',
            [(score, int(aid)) for aid, score in entries]
        )


def deactivate_before(cutoff_date: str, db_path: str = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            'UPDATE xtgal_3mnths SET active = 0 WHERE date_added < ?',
            (cutoff_date,)
        )


def get_active_xtgal_ids(db_path: str = None) -> list:
    with get_connection(db_path) as conn:
        rows = conn.execute('SELECT atlas_id FROM xtgal_3mnths WHERE active = 1').fetchall()
    return [row[0] for row in rows]
