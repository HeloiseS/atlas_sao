CREATE TABLE IF NOT EXISTS xtgal_watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id    INTEGER NOT NULL UNIQUE,
    active      INTEGER NOT NULL DEFAULT 1,
    date_added  TEXT,
    last_mag     REAL,
    last_mag_err REAL,
    last_mag_filt TEXT,
    timestamp   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bk_young_fast_track (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id     INTEGER NOT NULL,
    date_added   TEXT,
    date_removed TEXT,
    vra_score_when_added REAL,
    version      TEXT,
    timestamp    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bk_young_not_fast_track (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id     INTEGER NOT NULL,
    date_added   TEXT,
    date_removed TEXT,
    vra_score_when_added REAL,
    version      TEXT,
    timestamp    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bk_peak (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id     INTEGER NOT NULL,
    date_added   TEXT,
    date_removed TEXT,
    vra_score_when_added REAL,
    version      TEXT,
    timestamp    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS slack_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slack_ts      TEXT NOT NULL,
    sender_id     TEXT NOT NULL,
    sender_name   TEXT NOT NULL,
    telescope     TEXT,
    related_list  TEXT,
    atlas_id      INTEGER,
    atlas_name    TEXT,
    ra            REAL,
    dec           REAL,
    latest_mag    REAL,
    status        TEXT,
    note          TEXT,
    message_time  TEXT,
    timestamp     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    list_removed_at TEXT,  -- CLAUDE EDIT - PLEASE REVIEW: added, was referenced by db.py but missing here
    -- HFS: slack timestamp can correspond to several atlas IDs when 
    --      Nic reports several in a row. ATLAS ID also not unique
    --      because a same ID will have status evolution. 
    --      If atlas_id is NULL then one message with a unique slack_ts
    --      can have DUPLICATE rows because every instance of NULL is unique
    --      That is a weird edge case if 1) our cursor is in the wrong spot and
    --      2) a message doesn't have an ATLAS ID after that wrong cursor location
    --      No action taken to fix this as overly complicates indexes for a rare
    --      edge case that may never occur. 
    UNIQUE(slack_ts, atlas_id)
);
