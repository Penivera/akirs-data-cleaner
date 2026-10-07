"""Persistent, multi-worker-safe storage for work-item state.

State that used to live in per-process dictionaries (and a single pickle file)
now lives in the database, so every worker process reads and writes the same
source of truth. Each state object is stored as a JSON blob keyed by
``(kind, id)``; a few fields are duplicated into indexed columns for filtering
by user and for the cleanup job.

All functions open a short-lived async session and are safe to call from the
event loop.
"""
import json
import time
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.models import Task, WorkItem
from app.core.state import AnalysisState, FileState, IntelSyncState, NubanState

KIND_FILE = "file"
KIND_ANALYSIS = "analysis"
KIND_NUBAN = "nuban"
KIND_INTEL = "intel"

_KIND_TO_CLASS: Dict[str, Type[Any]] = {
    KIND_FILE: FileState,
    KIND_ANALYSIS: AnalysisState,
    KIND_NUBAN: NubanState,
    KIND_INTEL: IntelSyncState,
}


def _dump(state: Any) -> str:
    # default=str guards against any value type that is not natively JSON
    # serialisable, so a single odd field never fails the whole save.
    return json.dumps(state.__dict__, default=str)


def _load(kind: str, raw: str) -> Any:
    state = _KIND_TO_CLASS[kind]()
    state.__dict__.update(json.loads(raw))
    return state


# --- work items ------------------------------------------------------------


async def put(kind: str, state: Any) -> None:
    """Insert or update a work item."""
    async with AsyncSessionLocal() as db:
        row = await db.get(WorkItem, state.id)
        if row is None:
            row = WorkItem(id=state.id, kind=kind)
            db.add(row)
        row.kind = kind
        row.user_id = getattr(state, "user_id", None)
        row.uploaded_at = getattr(state, "uploaded_at", 0.0) or 0.0
        row.status = getattr(state, "status", None)
        row.data = _dump(state)
        await db.commit()


async def get(kind: str, state_id: str) -> Optional[Any]:
    """Fetch a single work item, or None if it is missing/for another kind."""
    async with AsyncSessionLocal() as db:
        row = await db.get(WorkItem, state_id)
        if row is None or row.kind != kind:
            return None
        return _load(kind, row.data)


async def list_for_user(kind: str, user_id: int) -> List[Any]:
    """All work items of a kind belonging to one user, newest first."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkItem)
            .where(WorkItem.kind == kind, WorkItem.user_id == user_id)
            .order_by(WorkItem.uploaded_at.asc())
        )
        rows = result.scalars().all()
        return [_load(kind, row.data) for row in rows]


async def delete(kind: str, state_id: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(WorkItem, state_id)
        if row is not None and row.kind == kind:
            await db.delete(row)
            await db.commit()


# --- background tasks ------------------------------------------------------


async def set_task(
    task_id: str, file_id: str, user_id: Optional[int], status: str, message: str
) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(Task, task_id)
        if row is None:
            row = Task(id=task_id)
            db.add(row)
        row.file_id = file_id
        row.user_id = user_id
        row.status = status
        row.message = message
        row.updated_at = time.time()
        await db.commit()


async def update_task(
    task_id: str, *, message: Optional[str] = None, status: Optional[str] = None
) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(Task, task_id)
        if row is None:
            return
        if message is not None:
            row.message = message
        if status is not None:
            row.status = status
        row.updated_at = time.time()
        await db.commit()


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        row = await db.get(Task, task_id)
        if row is None:
            return None
        return {
            "status": row.status,
            "file_id": row.file_id,
            "user_id": row.user_id,
            "message": row.message,
        }


# --- maintenance -----------------------------------------------------------


async def purge_older_than(cutoff: float) -> int:
    """Delete work items and tasks older than ``cutoff`` (epoch seconds)."""
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(WorkItem).where(WorkItem.uploaded_at < cutoff)
        )
        deleted = result.rowcount
        result = await db.execute(delete(Task).where(Task.updated_at < cutoff))
        deleted += result.rowcount
        await db.commit()
        return deleted
