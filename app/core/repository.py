"""Persistent, multi-worker-safe storage for work-item state.

State that used to live in per-process dictionaries (and a single pickle file)
now lives in the database, so every worker process reads and writes the same
source of truth. Each state object is stored as a JSON blob keyed by
``(kind, id)``; a few fields are duplicated into indexed columns for filtering
by user and for the cleanup job.

All functions open a short-lived session and are safe to call from the event
loop or from worker threads.
"""
import json
import time
from typing import Any, Dict, List, Optional, Type

from app.core.database import SessionLocal
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


def put(kind: str, state: Any) -> None:
    """Insert or update a work item."""
    db = SessionLocal()
    try:
        row = db.get(WorkItem, state.id)
        if row is None:
            row = WorkItem(id=state.id, kind=kind)
            db.add(row)
        row.kind = kind
        row.user_id = getattr(state, "user_id", None)
        row.uploaded_at = getattr(state, "uploaded_at", 0.0) or 0.0
        row.status = getattr(state, "status", None)
        row.data = _dump(state)
        db.commit()
    finally:
        db.close()


def get(kind: str, state_id: str) -> Optional[Any]:
    """Fetch a single work item, or None if it is missing/for another kind."""
    db = SessionLocal()
    try:
        row = db.get(WorkItem, state_id)
        if row is None or row.kind != kind:
            return None
        return _load(kind, row.data)
    finally:
        db.close()


def list_for_user(kind: str, user_id: int) -> List[Any]:
    """All work items of a kind belonging to one user, newest first."""
    db = SessionLocal()
    try:
        rows = (
            db.query(WorkItem)
            .filter(WorkItem.kind == kind, WorkItem.user_id == user_id)
            .order_by(WorkItem.uploaded_at.asc())
            .all()
        )
        return [_load(kind, row.data) for row in rows]
    finally:
        db.close()


def delete(kind: str, state_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(WorkItem, state_id)
        if row is not None and row.kind == kind:
            db.delete(row)
            db.commit()
    finally:
        db.close()


# --- background tasks ------------------------------------------------------


def set_task(
    task_id: str, file_id: str, user_id: Optional[int], status: str, message: str
) -> None:
    db = SessionLocal()
    try:
        row = db.get(Task, task_id)
        if row is None:
            row = Task(id=task_id)
            db.add(row)
        row.file_id = file_id
        row.user_id = user_id
        row.status = status
        row.message = message
        row.updated_at = time.time()
        db.commit()
    finally:
        db.close()


def update_task(
    task_id: str, *, message: Optional[str] = None, status: Optional[str] = None
) -> None:
    db = SessionLocal()
    try:
        row = db.get(Task, task_id)
        if row is None:
            return
        if message is not None:
            row.message = message
        if status is not None:
            row.status = status
        row.updated_at = time.time()
        db.commit()
    finally:
        db.close()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        row = db.get(Task, task_id)
        if row is None:
            return None
        return {
            "status": row.status,
            "file_id": row.file_id,
            "user_id": row.user_id,
            "message": row.message,
        }
    finally:
        db.close()


# --- maintenance -----------------------------------------------------------


def purge_older_than(cutoff: float) -> int:
    """Delete work items and tasks older than ``cutoff`` (epoch seconds)."""
    db = SessionLocal()
    try:
        deleted = db.query(WorkItem).filter(
            WorkItem.uploaded_at < cutoff
        ).delete(synchronize_session=False)
        deleted += db.query(Task).filter(
            Task.updated_at < cutoff
        ).delete(synchronize_session=False)
        db.commit()
        return deleted
    finally:
        db.close()
