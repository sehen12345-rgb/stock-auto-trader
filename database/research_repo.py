from datetime import datetime
from typing import Any

from database.db import Database, get_db


class ResearchRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or get_db()

    def save(self, note: dict) -> int:
        """새 리서치 노트 저장. 저장된 행의 id를 반환한다."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        INSERT INTO research_notes
            (ticker, source, rating, target_price, current_price,
             summary, content, catalyst, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.db.insert(
            sql,
            (
                note.get("ticker", "").upper(),
                note.get("source", ""),
                note.get("rating", ""),
                float(note.get("target_price", 0) or 0),
                float(note.get("current_price", 0) or 0),
                note.get("summary", ""),
                note.get("content", ""),
                note.get("catalyst", ""),
                now,
                now,
            ),
        )

    def find_by_ticker(self, ticker: str, limit: int = 10) -> list[dict]:
        """특정 종목의 최근 리서치를 limit개 반환한다."""
        rows = self.db.execute(
            "SELECT * FROM research_notes WHERE ticker=? ORDER BY created_at DESC LIMIT ?",
            (ticker.upper(), limit),
        )
        return [self._row_to_dict(r) for r in rows]

    def find_all(self, limit: int = 50) -> list[dict]:
        """전체 리서치 목록을 최신 순으로 반환한다."""
        rows = self.db.execute(
            "SELECT * FROM research_notes ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_dict(r) for r in rows]

    def delete(self, note_id: int) -> None:
        """id로 리서치 노트를 삭제한다."""
        self.db.execute("DELETE FROM research_notes WHERE id=?", (note_id,))

    @staticmethod
    def _row_to_dict(row: Any) -> dict:
        return {
            "id": row["id"],
            "ticker": row["ticker"],
            "source": row["source"],
            "rating": row["rating"],
            "target_price": row["target_price"],
            "current_price": row["current_price"],
            "summary": row["summary"],
            "content": row["content"],
            "catalyst": row["catalyst"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


_instance: ResearchRepository | None = None


def get_research_repo() -> ResearchRepository:
    """싱글톤 ResearchRepository 인스턴스를 반환한다."""
    global _instance
    if _instance is None:
        _instance = ResearchRepository()
    return _instance
