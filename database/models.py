import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from database.db import Database, get_db


# ── Trade ────────────────────────────────────────────────────────────────────


@dataclass
class Trade:
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: float
    filled_qty: int = 0
    filled_price: float = 0.0
    order_id: str = ""
    status: str = "PENDING"
    market: str = ""
    strategy: str = ""
    pnl: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: int = 0


class TradeRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or get_db()

    def save(self, trade: Trade) -> int:
        sql = """
        INSERT INTO trades
            (symbol, side, order_type, quantity, price,
             filled_qty, filled_price, order_id, status,
             market, strategy, pnl, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        row_id = self.db.insert(
            sql,
            (
                trade.symbol, trade.side, trade.order_type, trade.quantity, trade.price,
                trade.filled_qty, trade.filled_price, trade.order_id, trade.status,
                trade.market, trade.strategy, trade.pnl,
                trade.created_at, trade.updated_at,
            ),
        )
        trade.id = row_id
        return row_id

    def update_status(self, trade_id: int, status: str,
                      filled_qty: int = 0, filled_price: float = 0.0, pnl: float = 0.0) -> None:
        sql = """
        UPDATE trades
        SET status=?, filled_qty=?, filled_price=?, pnl=?,
            updated_at=strftime('%Y-%m-%dT%H:%M:%S', 'now')
        WHERE id=?
        """
        self.db.execute(sql, (status, filled_qty, filled_price, pnl, trade_id))

    def find_by_symbol(self, symbol: str, limit: int = 100) -> list[Trade]:
        rows = self.db.execute(
            "SELECT * FROM trades WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
            (symbol, limit),
        )
        return [self._row_to_trade(r) for r in rows]

    def find_by_date(self, date_str: str) -> list[Trade]:
        """date_str 예시: '2024-01-15'"""
        rows = self.db.execute(
            "SELECT * FROM trades WHERE created_at LIKE ? ORDER BY created_at DESC",
            (f"{date_str}%",),
        )
        return [self._row_to_trade(r) for r in rows]

    def find_all(self, limit: int = 500) -> list[Trade]:
        rows = self.db.execute(
            "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_trade(r) for r in rows]

    def daily_pnl(self, date_str: str) -> float:
        row = self.db.execute_one(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE created_at LIKE ?",
            (f"{date_str}%",),
        )
        return float(row["total"]) if row else 0.0

    @staticmethod
    def _row_to_trade(row: Any) -> Trade:
        return Trade(
            id=row["id"],
            symbol=row["symbol"],
            side=row["side"],
            order_type=row["order_type"],
            quantity=row["quantity"],
            price=row["price"],
            filled_qty=row["filled_qty"],
            filled_price=row["filled_price"],
            order_id=row["order_id"],
            status=row["status"],
            market=row["market"],
            strategy=row["strategy"],
            pnl=row["pnl"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ── Position ─────────────────────────────────────────────────────────────────


@dataclass
class PositionRecord:
    symbol: str
    quantity: int
    avg_price: float
    stop_price: float = 0.0
    target_price: float = 0.0
    market: str = ""
    strategy: str = ""
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: int = 0


class PositionRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or get_db()

    def upsert(self, pos: PositionRecord) -> None:
        sql = """
        INSERT INTO positions
            (symbol, quantity, avg_price, stop_price, target_price, market, strategy, opened_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            quantity=excluded.quantity,
            avg_price=excluded.avg_price,
            stop_price=excluded.stop_price,
            target_price=excluded.target_price,
            updated_at=excluded.updated_at
        """
        self.db.execute(
            sql,
            (
                pos.symbol, pos.quantity, pos.avg_price,
                pos.stop_price, pos.target_price,
                pos.market, pos.strategy,
                pos.opened_at, pos.updated_at,
            ),
        )

    def delete(self, symbol: str) -> None:
        self.db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))

    def find_all(self) -> list[PositionRecord]:
        rows = self.db.execute("SELECT * FROM positions ORDER BY opened_at DESC")
        return [self._row_to_pos(r) for r in rows]

    def find_by_symbol(self, symbol: str) -> PositionRecord | None:
        row = self.db.execute_one("SELECT * FROM positions WHERE symbol=?", (symbol,))
        return self._row_to_pos(row) if row else None

    @staticmethod
    def _row_to_pos(row: Any) -> PositionRecord:
        return PositionRecord(
            id=row["id"],
            symbol=row["symbol"],
            quantity=row["quantity"],
            avg_price=row["avg_price"],
            stop_price=row["stop_price"],
            target_price=row["target_price"],
            market=row["market"],
            strategy=row["strategy"],
            opened_at=row["opened_at"],
            updated_at=row["updated_at"],
        )


# ── Signal ────────────────────────────────────────────────────────────────────


@dataclass
class SignalRecord:
    symbol: str
    signal_type: str
    strategy_name: str
    price: float
    score: float = 0.0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    acted: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: int = 0


class SignalRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or get_db()

    def save(self, sig: SignalRecord) -> int:
        sql = """
        INSERT INTO signals
            (symbol, signal_type, strategy_name, price, score, reason, metadata, acted, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.db.insert(
            sql,
            (
                sig.symbol, sig.signal_type, sig.strategy_name,
                sig.price, sig.score, sig.reason,
                json.dumps(sig.metadata, ensure_ascii=False),
                int(sig.acted), sig.created_at,
            ),
        )

    def mark_acted(self, signal_id: int) -> None:
        self.db.execute("UPDATE signals SET acted=1 WHERE id=?", (signal_id,))

    def find_recent(self, limit: int = 100) -> list[SignalRecord]:
        rows = self.db.execute(
            "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_signal(r) for r in rows]

    def find_by_symbol(self, symbol: str, limit: int = 50) -> list[SignalRecord]:
        rows = self.db.execute(
            "SELECT * FROM signals WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
            (symbol, limit),
        )
        return [self._row_to_signal(r) for r in rows]

    def find_unacted(self) -> list[SignalRecord]:
        rows = self.db.execute(
            "SELECT * FROM signals WHERE acted=0 ORDER BY created_at DESC"
        )
        return [self._row_to_signal(r) for r in rows]

    def find_by_date(self, date_str: str) -> list[SignalRecord]:
        rows = self.db.execute(
            "SELECT * FROM signals WHERE created_at LIKE ? ORDER BY created_at DESC",
            (f"{date_str}%",),
        )
        return [self._row_to_signal(r) for r in rows]

    @staticmethod
    def _row_to_signal(row: Any) -> SignalRecord:
        try:
            meta = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return SignalRecord(
            id=row["id"],
            symbol=row["symbol"],
            signal_type=row["signal_type"],
            strategy_name=row["strategy_name"],
            price=row["price"],
            score=row["score"],
            reason=row["reason"],
            metadata=meta,
            acted=bool(row["acted"]),
            created_at=row["created_at"],
        )
