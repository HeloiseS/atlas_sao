# Claude wrote this for BK_ provenance tracking (2026-06-30)
# HFS Reviewed 2026-07-01 - docstrings comments and refactor 
# to make functions parse a connection instead of all calling 
# get_connection

import os
import sqlite3

# NOTE: Need to add a little bit of logging - could be set to debug so can turn
# off most of it in prod, but we'll at least want to know when the db has been updated



def get_connection(db_path: str = None) -> sqlite3.Connection:
    """Makes connection to sqlite db and returns it.
    Expects that the data base is under the atlas_sao/db/log.db file 
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'log.db')
    return sqlite3.connect(db_path)


def log_added(atlas_ids: list, 
              bk_table: str, 
              vra_scores: dict = None, 
              db_path: str = None) -> None:
    """Log when ATLAS_ID added to a list - this requires VRA score at time of adding"""
    
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

    conn.close() # technically not needed because GC would do it, but adding anyways


def log_removed(atlas_ids: list, 
                bk_table: str, 
                db_path: str = None) -> None:
    """Log when ATLAS ID removed from a list"""
    if not atlas_ids:
        return
    
    with get_connection(db_path) as conn:
        conn.executemany(
            f'UPDATE {bk_table} '
            f'SET date_removed = CURRENT_TIMESTAMP, timestamp = CURRENT_TIMESTAMP '
            f'WHERE atlas_id = ? AND date_removed IS NULL',
            [(int(aid),) for aid in atlas_ids]
        )

    conn.close() # technically not needed because GC would do it, but adding anyways


def upsert_xtgal(atlas_ids: list,
                 db_path: str = None) -> None:
    """Adds a row to XTGAL table if it doesn't already exist.

    Returns
    -------
    None
    """
    if not atlas_ids:
        return

    with get_connection(db_path) as conn:
        conn.executemany(
            'INSERT OR IGNORE INTO xtgal_3mnths (atlas_id, date_added) VALUES (?, CURRENT_TIMESTAMP)',
            [(int(aid),) for aid in atlas_ids]
        )

    conn.close() # technically not needed because GC would do it, but adding anyways


def deactivate_old_alerts(cutoff_date: str, db_path: str = None) -> None:
    """Sets status ACTIVE = 0 for alerts with date_added < cutoff_date
    
    Parameters
    ----------
    cutoff_date: str
        Date in UTC format before which all alerts are stale and should be set to ACTIVE=0
    """
    with get_connection(db_path) as conn:
        conn.execute(
            'UPDATE xtgal_3mnths SET active = 0 WHERE date_added < ?',
            (cutoff_date,)
        )

    conn.close() # technically not needed because GC would do it, but adding anyways


def get_active_xtgal_ids(db_path: str = None) -> list:
    """Utility function to know which alerts are set to active
    
    Returns
    -------
    list of ATLAS_IDs for which ACTIVE=1
    """ 
    with get_connection(db_path) as conn:
        rows = conn.execute('SELECT atlas_id FROM xtgal_3mnths WHERE active = 1').fetchall()
    
    conn.close() # technically not needed because GC would do it, but adding anyways
    
    return [row[0] for row in rows]

