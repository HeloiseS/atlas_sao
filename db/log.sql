CREATE TABLE xtgal_watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id    INTEGER NOT NULL UNIQUE,
    active      INTEGER NOT NULL DEFAULT 1,
    date_added  TEXT,
    last_mag     REAL,
    last_mag_err REAL,
    last_mag_filt TEXT,
    timestamp   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bk_young_fast_track (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id     INTEGER NOT NULL,
    date_added   TEXT,
    date_removed TEXT,
    vra_score_when_added REAL,
    version      TEXT,
    timestamp    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bk_young_not_fast_track (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id     INTEGER NOT NULL,
    date_added   TEXT,
    date_removed TEXT,
    vra_score_when_added REAL,
    version      TEXT,
    timestamp    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bk_peak (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    atlas_id     INTEGER NOT NULL,
    date_added   TEXT,
    date_removed TEXT,
    vra_score_when_added REAL,
    version      TEXT,
    timestamp    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE slack_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slack_ts      TEXT NOT NULL UNIQUE,
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
    timestamp     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
