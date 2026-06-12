import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent


def default_db_path():
    data_dir = Path(os.getenv("CONTROL_HORARIO_DATA_DIR", APP_DIR / "data"))
    return data_dir / "control_horario.sqlite3"


@contextmanager
def connect(db_path=None):
    db_path = Path(db_path or default_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path=None):
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT,
                pin_hash TEXT,
                role TEXT NOT NULL CHECK(role IN ('admin', 'worker')),
                weekly_hours REAL NOT NULL DEFAULT 40,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS centers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                radius_meters REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                worker_id TEXT NOT NULL REFERENCES users(id),
                event_type TEXT NOT NULL CHECK(event_type IN ('entrada', 'pausa', 'reanudacion', 'salida')),
                happened_at TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('mobile', 'kiosk', 'admin')),
                lat REAL,
                lon REAL,
                accuracy_meters REAL,
                geo_status TEXT NOT NULL,
                center_id TEXT REFERENCES centers(id),
                distance_meters REAL,
                inside_radius INTEGER,
                note TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS correction_requests (
                id TEXT PRIMARY KEY,
                worker_id TEXT NOT NULL REFERENCES users(id),
                work_date TEXT NOT NULL,
                description TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pendiente', 'aprobada', 'rechazada')),
                admin_comment TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                actor_id TEXT REFERENCES users(id),
                action TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                before_data TEXT,
                after_data TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def row_to_dict(row):
    if row is None:
        return None
    data = dict(row)
    for key in ("active", "inside_radius"):
        if key in data and data[key] is not None:
            data[key] = bool(data[key])
    return data
