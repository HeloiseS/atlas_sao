CREATE TABLE xtgal_3mnths (
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
