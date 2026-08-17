from __future__ import annotations
from database.db import get_db


class AlertRepository:
    def __init__(self, db=None):
        self.db = db or get_db()

    def save(self, ticker: str, name: str, alert_type: str,
             target_price: float = 0, change_pct: float = 0, memo: str = "") -> int:
        return self.db.insert(
            """INSERT INTO price_alerts
               (ticker, name, alert_type, target_price, change_pct, memo)
               VALUES (?,?,?,?,?,?)""",
            (ticker.upper(), name, alert_type, target_price, change_pct, memo),
        )

    def find_all(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM price_alerts ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def find_active(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM price_alerts WHERE active=1 AND triggered=0 ORDER BY created_at"
        )
        return [dict(r) for r in rows]

    def mark_triggered(self, alert_id: int) -> None:
        self.db.execute(
            "UPDATE price_alerts SET triggered=1, triggered_at=datetime('now','localtime') WHERE id=?",
            (alert_id,),
        )

    def deactivate(self, alert_id: int) -> None:
        self.db.execute("UPDATE price_alerts SET active=0 WHERE id=?", (alert_id,))

    def reactivate(self, alert_id: int) -> None:
        self.db.execute(
            "UPDATE price_alerts SET active=1, triggered=0, triggered_at=NULL WHERE id=?",
            (alert_id,),
        )

    def delete(self, alert_id: int) -> None:
        self.db.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))

    def reset_daily(self) -> None:
        """매일 자정 triggered 리셋 (반복 알림 허용)."""
        self.db.execute("UPDATE price_alerts SET triggered=0, triggered_at=NULL WHERE active=1")


def get_alert_repo() -> AlertRepository:
    return AlertRepository()
