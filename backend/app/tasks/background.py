from __future__ import annotations

import atexit
import json
import logging
import math
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models.task import BackgroundTask

logger = logging.getLogger(__name__)
TERMINAL_STATES = {"completed", "failed", "interrupted", "cancelled"}
OWNER_ID = f"{os.getpid()}-{uuid.uuid4()}"
HEARTBEAT_SECONDS = 5
STALE_SECONDS = max(30, int(os.getenv("TASK_STALE_SECONDS", "120")))
RETENTION_DAYS = max(1, int(os.getenv("TASK_RETENTION_DAYS", "30")))
MEMORY_LIMIT = max(10, int(os.getenv("TASK_MEMORY_LIMIT", "1000")))


@dataclass
class TaskStatus:
    id: str
    type: str
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    result: dict | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    _persist_lock: object = field(default_factory=threading.RLock, repr=False, compare=False)


executor = ThreadPoolExecutor(max_workers=2)
task_registry: dict[str, TaskStatus] = {}
_monitor_lock = threading.Lock()
_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()
atexit.register(_monitor_stop.set)


def _json_value(value):
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _persist(task: TaskStatus, *, create: bool = False, heartbeat: bool = False) -> None:
    # Serialize the complete read/write/commit boundary, not only dict access.
    # The callback may mutate its object while a heartbeat is awaiting I/O, so
    # capture status before the other fields and never persist terminal state
    # from a heartbeat/query. Only the executor's finalizer owns that transition.
    with task._persist_lock:
        state = task.status
        if heartbeat and state in TERMINAL_STATES:
            return
        now = datetime.utcnow()
        task.updated_at = now
        if state in TERMINAL_STATES and task.completed_at is None:
            task.completed_at = now
        values = {"type": task.type, "status": state, "progress": task.progress,
                  "message": task.message,
                  "result": json.loads(json.dumps(_json_value(task.result), default=str)),
                  "updated_at": now, "heartbeat_at": now, "completed_at": task.completed_at}
        with SessionLocal() as db:
            row = db.get(BackgroundTask, task.id)
            if row is None:
                if not create:
                    raise RuntimeError("任务持久记录不存在")
                row = BackgroundTask(id=task.id, owner_id=OWNER_ID, created_at=task.created_at)
                db.add(row)
                for key, value in values.items():
                    setattr(row, key, value)
            elif row.owner_id != OWNER_ID:
                raise RuntimeError("当前进程不能更新其他执行进程的任务")
            elif row.status in TERMINAL_STATES:
                # Late heartbeats/stale local objects cannot resurrect a task or
                # replace the result of any completed, failed or interrupted run.
                for key in ("status", "progress", "message", "result", "updated_at", "completed_at"):
                    setattr(task, key, getattr(row, key))
                return
            else:
                # Recovery can run in another web process between our SELECT
                # and UPDATE. Keep the terminal-state predicate in the SQL write.
                changed = db.query(BackgroundTask).filter(
                    BackgroundTask.id == task.id, BackgroundTask.owner_id == OWNER_ID,
                    BackgroundTask.status.in_(["pending", "running"]),
                ).update(values, synchronize_session=False)
                if not changed:
                    db.expire_all()
                    durable = db.get(BackgroundTask, task.id)
                    if durable is None:
                        raise RuntimeError("任务持久记录不存在")
                    for key in ("status", "progress", "message", "result", "updated_at", "completed_at"):
                        setattr(task, key, getattr(durable, key))
                    return
            db.commit()


def recover_interrupted_tasks(*, now: datetime | None = None) -> int:
    """Fail stale work without replaying side effects; live workers renew a heartbeat."""
    now = now or datetime.utcnow()
    with SessionLocal() as db:
        count = db.query(BackgroundTask).filter(
            BackgroundTask.status.in_(["pending", "running"]),
            BackgroundTask.heartbeat_at < now - timedelta(seconds=STALE_SECONDS),
        ).update({"status": "interrupted", "message": "执行进程心跳已过期；任务已中断，请核查结果后手动重试",
                  "updated_at": now, "completed_at": now}, synchronize_session=False)
        db.commit()
        return count


def prune_tasks(*, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    with SessionLocal() as db:
        count = db.query(BackgroundTask).filter(
            BackgroundTask.status.in_(TERMINAL_STATES),
            BackgroundTask.completed_at < now - timedelta(days=RETENTION_DAYS),
        ).delete(synchronize_session=False)
        db.commit()
    terminal = sorted((t for t in list(task_registry.values()) if t.status in TERMINAL_STATES),
                      key=lambda t: t.updated_at)
    remove = max(0, len(task_registry) - MEMORY_LIMIT)
    for index, task in enumerate(terminal):
        if index < remove or task.updated_at < now - timedelta(days=RETENTION_DAYS):
            task_registry.pop(task.id, None)
    return count


def _monitor_loop():
    while not _monitor_stop.wait(HEARTBEAT_SECONDS):
        for task in list(task_registry.values()):
            if task.status in {"pending", "running"}:
                try:
                    _persist(task, heartbeat=True)
                except Exception:
                    logger.exception("Could not persist heartbeat for task %s", task.id)


def _ensure_monitor():
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_stop.clear()
            _monitor_thread = threading.Thread(target=_monitor_loop, name="task-heartbeat", daemon=True)
            _monitor_thread.start()


def submit_task(task_type: str, fn, *args, **kwargs) -> str:
    # Missing migrations fail before executing a callable or modifying business data.
    recover_interrupted_tasks()
    prune_tasks()
    task_id = str(uuid.uuid4())
    task = TaskStatus(id=task_id, type=task_type, message="任务已提交，等待后台执行")
    _persist(task, create=True)
    task_registry[task_id] = task
    _ensure_monitor()

    def wrapper():
        task.status = "running"
        try:
            _persist(task)
            fn(task_id, *args, **kwargs)
            if task.status not in TERMINAL_STATES:
                task.status = "completed"
            if task.status == "completed":
                task.progress = 1.0
        except Exception as exc:
            task.status = "failed"
            task.message = str(exc)
        finally:
            try:
                _persist(task)
            except Exception:
                task.status = "failed"
                task.message = "任务终态持久化失败，请核查执行结果后再重试"
                logger.exception("Could not persist final task state %s", task_id)

    try:
        executor.submit(wrapper)
    except Exception as exc:
        task.status, task.message = "failed", str(exc)
        _persist(task)
        raise
    return task_id


def get_task_status(task_id: str) -> TaskStatus | None:
    local = task_registry.get(task_id)
    if local is not None:
        _persist(local, create=True, heartbeat=True)
    recover_interrupted_tasks()
    with SessionLocal() as db:
        row = db.get(BackgroundTask, task_id)
        if row is None:
            return None
        if local is not None:
            if row.status == "interrupted":
                local.status, local.message, local.completed_at = row.status, row.message, row.completed_at
            return local
        return TaskStatus(id=row.id, type=row.type, status=row.status, progress=row.progress,
                          message=row.message, result=row.result, created_at=row.created_at,
                          updated_at=row.updated_at, completed_at=row.completed_at)
