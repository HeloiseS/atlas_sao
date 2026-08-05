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
            'INSERT OR IGNORE INTO xtgal_watchlist (atlas_id, date_added) VALUES (?, CURRENT_TIMESTAMP)',
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
            'UPDATE xtgal_watchlist SET active = 0 WHERE date_added < ?',
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
        rows = conn.execute('SELECT atlas_id FROM xtgal_watchlist WHERE active = 1').fetchall()
    
    conn.close() # technically not needed because GC would do it, but adding anyways

    return [row[0] for row in rows]


def log_slack_message(slack_ts: str,
                       sender_id: str,
                       sender_name: str,
                       telescope: str = None,
                       related_list: str = None,
                       raw_text: str = None,
                       raw_blocks: str = None,
                       atlas_id: int = None,
                       ra: float = None,
                       dec: float = None,
                       latest_mag: float = None,
                       message_time: str = None,
                       db_path: str = None) -> None:
    """Adds a new slack message to the slack_messages table.

    Note
    ---- 
    This needs a parser in order to extract the ra, dec, latest_mag etc 
    which are contained within the text fields of the raw_message. 
    """
    with get_connection(db_path) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO slack_messages '
            '(slack_ts, sender_id, sender_name, telescope, related_list, '
            'raw_text, raw_blocks, atlas_id, ra, dec, latest_mag, message_time) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (slack_ts, sender_id, sender_name, telescope, related_list,
             raw_text, raw_blocks, atlas_id, ra, dec, latest_mag, message_time)
        )

    conn.close() # technically not needed because GC would do it, but adding anyways


def get_last_slack_ts(db_path: str = None) -> str:
    """Get the latest slack timemstamp from the slack_messages table. 

    Note
    ----
    This is NOT the same as the timestamp added automatically by the table when filling a row
    it's the timestamp on slack in Unix epoch seconds. Because it has microseconds precision
    it is unique and slack uses it as a unique key and polling cursor (like a group_id in kafka, 
    its like our place in the thread so we can poll from slack only recent messages without 
    missing any!)
    """
    with get_connection(db_path) as conn:
        row = conn.execute('SELECT MAX(slack_ts) FROM slack_messages').fetchone()

    conn.close() 
    return row[0]

