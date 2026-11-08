"""SQLite-Zugriff für den Trophäenschrank."""
import os
import sqlite3
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "trophaeenschrank.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,          -- steam | playstation | xbox | nintendo | other
    ext_id          TEXT NOT NULL,          -- AppID / npCommunicationId / titleId / uuid
    title           TEXT NOT NULL,
    sub_platform    TEXT DEFAULT '',        -- z.B. PS5, PS4, Switch
    status          TEXT DEFAULT 'none',    -- none | playing | finished | completed | backlog | shelved
    status_locked   INTEGER DEFAULT 0,      -- 1 = vom Nutzer gesetzt, Sync überschreibt nicht (außer 100 %)
    unlocked        INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0,
    platinum        INTEGER DEFAULT 0,
    playtime_min    INTEGER DEFAULT 0,
    playtime_2w     INTEGER DEFAULT 0,
    last_played     INTEGER DEFAULT 0,
    completed_at    INTEGER DEFAULT 0,
    completed_locked INTEGER DEFAULT 0,
    cover_src       TEXT DEFAULT '',        -- Cover/Icon, das die Plattform liefert
    cover_override  TEXT DEFAULT '',        -- vom Nutzer gewähltes Cover
    tags            TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    hidden          INTEGER DEFAULT 0,
    manual          INTEGER DEFAULT 0,
    ach_checked_lp  INTEGER DEFAULT -1,     -- last_played-Wert beim letzten Erfolge-Abruf
    created_at      INTEGER DEFAULT 0,
    updated_at      INTEGER DEFAULT 0,
    UNIQUE(platform, ext_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS cover_cache (
    game_id  INTEGER,
    source   TEXT,
    url      TEXT,
    file     TEXT,
    ts       INTEGER,
    PRIMARY KEY (game_id, source)
);
CREATE TABLE IF NOT EXISTS achievements (
    game_id      INTEGER NOT NULL,
    api_name     TEXT NOT NULL,          -- Steam-apiname / PSN-trophyId
    name         TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    icon         TEXT DEFAULT '',
    icon_gray    TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    trophy_type  TEXT DEFAULT '',        -- PSN: bronze/silver/gold/platinum
    unlocked     INTEGER DEFAULT 0,
    unlock_time  INTEGER DEFAULT 0,
    rarity       REAL,                   -- Anteil aller Spieler in %, NULL = unbekannt
    sort         INTEGER DEFAULT 0,
    PRIMARY KEY (game_id, api_name)
);
CREATE INDEX IF NOT EXISTS ach_time ON achievements(unlock_time);
CREATE TABLE IF NOT EXISTS ach_meta (
    game_id      INTEGER PRIMARY KEY,
    details_ts   INTEGER DEFAULT 0,      -- Namen/Icons geladen
    rarity_ts    INTEGER DEFAULT 0       -- Seltenheit geladen
);
CREATE TABLE IF NOT EXISTS sgdb_ids (
    game_id  INTEGER PRIMARY KEY,
    sgdb_id  INTEGER
);
"""


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    # Fehlgeschlagene Cover-Suchen beim Start vergessen, damit neue Quellen greifen
    c.execute("DELETE FROM cover_cache WHERE file='' OR file IS NULL")
    c.commit()


def now():
    return int(time.time())


def get_setting(key, default=""):
    row = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    c = conn()
    c.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    c.commit()


def all_settings():
    return {r["key"]: r["value"] for r in conn().execute("SELECT key,value FROM settings")}
