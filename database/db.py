import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from loguru import logger

from config.settings import DB_PATH


class Database:
    """SQLite 데이터베이스 연결 및 초기화 관리."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"[DB] 초기화 완료: {self.db_path.resolve()}")

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(_SCHEMA_SQL)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connection() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall()

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        with self.connection() as conn:
            conn.executemany(sql, params_list)

    def execute_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connection() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchone()

    def insert(self, sql: str, params: tuple = ()) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid or 0


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL CHECK(side IN ('BUY', 'SELL')),
    order_type  TEXT    NOT NULL CHECK(order_type IN ('MARKET', 'LIMIT')),
    quantity    INTEGER NOT NULL,
    price       REAL    NOT NULL,
    filled_qty  INTEGER NOT NULL DEFAULT 0,
    filled_price REAL   NOT NULL DEFAULT 0.0,
    order_id    TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'PENDING',
    market      TEXT    NOT NULL DEFAULT '',
    strategy    TEXT    NOT NULL DEFAULT '',
    pnl         REAL    NOT NULL DEFAULT 0.0,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL UNIQUE,
    quantity    INTEGER NOT NULL,
    avg_price   REAL    NOT NULL,
    stop_price  REAL    NOT NULL DEFAULT 0.0,
    target_price REAL   NOT NULL DEFAULT 0.0,
    market      TEXT    NOT NULL DEFAULT '',
    strategy    TEXT    NOT NULL DEFAULT '',
    opened_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,
    signal_type   TEXT    NOT NULL CHECK(signal_type IN ('BUY', 'SELL', 'HOLD')),
    strategy_name TEXT    NOT NULL,
    price         REAL    NOT NULL,
    score         REAL    NOT NULL DEFAULT 0.0,
    reason        TEXT    NOT NULL DEFAULT '',
    metadata      TEXT    NOT NULL DEFAULT '{}',
    acted         INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol    ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_created   ON trades(created_at);
CREATE INDEX IF NOT EXISTS idx_signals_symbol   ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created  ON signals(created_at);
"""


_instance: Database | None = None


def get_db(db_path: str = DB_PATH) -> Database:
    """싱글톤 DB 인스턴스를 반환한다."""
    global _instance
    if _instance is None:
        _instance = Database(db_path)
    return _instance
