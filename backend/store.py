"""SQLite persistence for evaluation runs."""
import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("EVAL_DB_PATH", Path(__file__).resolve().parent.parent / "runs.db"))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _init_sync() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            file_name TEXT,
            count INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
        """)


async def init_db() -> None:
    await asyncio.to_thread(_init_sync)


def _save_sync(file_name: str | None, payload: dict) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    count = payload.get("count", 0)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO runs(created_at, file_name, count, payload_json) VALUES (?,?,?,?)",
            (now, file_name, count, json.dumps(payload)),
        )
        return cur.lastrowid


async def save_run(file_name: str | None, payload: dict) -> int:
    return await asyncio.to_thread(_save_sync, file_name, payload)


def _list_sync() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created_at, file_name, count FROM runs ORDER BY id DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]


async def list_runs() -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_sync)


def _get_sync(run_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, created_at, file_name, count, payload_json FROM runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "file_name": row["file_name"],
            "count": row["count"],
            **payload,
        }


async def get_run(run_id: int) -> dict | None:
    return await asyncio.to_thread(_get_sync, run_id)


def _delete_sync(run_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM runs WHERE id=?", (run_id,))
        return cur.rowcount > 0


async def delete_run(run_id: int) -> bool:
    return await asyncio.to_thread(_delete_sync, run_id)


def _leaderboard_sync(limit: int = 100) -> list[dict[str, Any]]:
    """Flatten every app across every run, sorted by final_score desc."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created_at, payload_json FROM runs ORDER BY id DESC"
        ).fetchall()
    flat: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        for r in payload.get("results", []):
            s = r.get("submission") or {}
            ctx = r.get("app_context") or {}
            flat.append({
                "run_id": row["id"],
                "created_at": row["created_at"],
                "rank_in_run": r.get("rank"),
                "team_name": s.get("team_name") or "",
                "project_title": s.get("project_title") or "",
                "app_id": s.get("app_id") or "",
                "app_name": ctx.get("app_name") or "",
                "final_score": r.get("final_score", 0),
                "raw_total": r.get("raw_total", 0),
                "fetch_error": r.get("fetch_error"),
            })
    flat.sort(key=lambda x: x["final_score"], reverse=True)
    return flat[:limit]


async def apps_leaderboard(limit: int = 100) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_leaderboard_sync, limit)
