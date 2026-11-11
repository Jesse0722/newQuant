from __future__ import annotations

from datetime import datetime, timedelta

from app.models.task import BackgroundTask
from app.tasks import background


class ImmediateExecutor:
    def submit(self, fn):
        fn()


def test_failure_status_and_result_survive_registry_loss(monkeypatch, background_storage_factory):
    monkeypatch.setattr(background, "executor", ImmediateExecutor())
    def fail(task_id):
        task = background.task_registry[task_id]
        task.status, task.message = "failed", "供应商返回错误"
        task.result = {"outcome": "provider_failed", "count": 0}
    task_id = background.submit_task("strategy", fail)
    assert background.get_task_status(task_id).status == "failed"
    monkeypatch.delitem(background.task_registry, task_id)
    restored = background.get_task_status(task_id)
    assert restored.status == "failed"
    assert restored.message == "供应商返回错误"
    assert restored.result == {"outcome": "provider_failed", "count": 0}
    assert restored.completed_at is not None


def test_thrown_failure_is_persisted(monkeypatch):
    monkeypatch.setattr(background, "executor", ImmediateExecutor())
    def fail(task_id):
        raise RuntimeError("database is locked")
    task_id = background.submit_task("sync", fail)
    monkeypatch.delitem(background.task_registry, task_id)
    assert background.get_task_status(task_id).status == "failed"


def test_success_keeps_result_and_sanitizes_nonfinite_json(monkeypatch):
    monkeypatch.setattr(background, "executor", ImmediateExecutor())
    def succeed(task_id):
        background.task_registry[task_id].result = {"rows": [1, float("nan")]}
    task_id = background.submit_task("sync", succeed)
    monkeypatch.delitem(background.task_registry, task_id)
    restored = background.get_task_status(task_id)
    assert restored.status == "completed" and restored.progress == 1
    assert restored.result == {"rows": [1, None]}


def test_recover_stale_pending_and_running_without_replaying(background_storage_factory):
    now = datetime.utcnow()
    with background_storage_factory() as db:
        for identifier, status, heartbeat in [
            ("stale-running", "running", now - timedelta(seconds=background.STALE_SECONDS + 1)),
            ("stale-pending", "pending", now - timedelta(seconds=background.STALE_SECONDS + 1)),
            ("live-other-worker", "running", now),
        ]:
            db.add(BackgroundTask(id=identifier, type="sync", status=status, progress=.3,
                                  message="", owner_id="other-process", created_at=now,
                                  updated_at=now, heartbeat_at=heartbeat))
        db.commit()
    background.recover_interrupted_tasks(now=now)
    assert background.get_task_status("stale-running").status == "interrupted"
    assert background.get_task_status("stale-pending").status == "interrupted"
    assert background.get_task_status("live-other-worker").status == "running"


def test_retention_removes_only_old_terminal_tasks(background_storage_factory):
    now = datetime.utcnow()
    old = now - timedelta(days=background.RETENTION_DAYS + 1)
    with background_storage_factory() as db:
        for identifier, status in [("expired-finished", "completed"), ("old-still-running", "running")]:
            db.add(BackgroundTask(id=identifier, type="sync", status=status, progress=0, message="",
                                  owner_id="other", created_at=old, updated_at=old, heartbeat_at=now,
                                  completed_at=old if status == "completed" else None))
        db.commit()
    background.prune_tasks(now=now)
    assert background.get_task_status("expired-finished") is None
    assert background.get_task_status("old-still-running").status == "running"


def test_recent_history_merges_background_sync_and_scheduled(monkeypatch, background_storage_factory):
    from app.models.sync_log import SyncLog
    from app.models.task import ScheduledJobRun
    from app.routers.sync import recent_tasks
    # Dedicated business DB; the metadata fixture stays independently isolated.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    SyncLog.__table__.create(engine)
    with sessionmaker(bind=engine)() as business:
        now = datetime.utcnow()
        business.add(SyncLog(id="recent-shared", task_type="stock", status="failed",
                             started_at=now, completed_at=now, result='{"message":"network error"}'))
        business.commit()
        with background_storage_factory() as storage:
            storage.add(BackgroundTask(id="recent-shared", type="sync", status="failed", progress=.2,
                message="source failed", result={"ts_code": "000001.SZ"}, owner_id="other",
                created_at=now, updated_at=now, heartbeat_at=now, completed_at=now))
            storage.add(ScheduledJobRun(id="recent-scheduled", job_key="message_pipeline_preopen_0815",
                slot="202611110815", status="failed", started_at=now, completed_at=now, error="pipeline failed"))
            storage.commit()
        rows = recent_tasks(100, business)["items"]
        shared = [r for r in rows if r["id"] == "recent-shared"]
        assert len(shared) == 1 and shared[0]["source"] == "background"
        assert shared[0]["message"] == "source failed"
        assert shared[0]["link"] == "/stocks/000001.SZ"
        scheduled = next(r for r in rows if r["id"] == "scheduled:recent-scheduled")
        assert scheduled["status"] == "failed" and scheduled["link"] == "/messages"
        assert scheduled["updated_at"].endswith("Z")
    engine.dispose()


def test_heartbeat_cannot_commit_after_final_state(monkeypatch, background_storage_factory):
    import threading
    from sqlalchemy.orm import Session, sessionmaker
    paused, resume, finalized = threading.Event(), threading.Event(), threading.Event()
    class BlockingSession(Session):
        def commit(self):
            if threading.current_thread().name == "review-heartbeat":
                paused.set()
                assert resume.wait(5)
            return super().commit()
    factory = sessionmaker(bind=background_storage_factory.kw["bind"], class_=BlockingSession)
    monkeypatch.setattr(background, "SessionLocal", factory)
    task = background.TaskStatus(id="ordered-heartbeat", type="sync", status="running", result={"phase": 0})
    background._persist(task, create=True)
    task.progress, task.result = .5, {"phase": 1}
    heartbeat = threading.Thread(target=lambda: background._persist(task, heartbeat=True), name="review-heartbeat")
    heartbeat.start()
    assert paused.wait(5)
    task.status, task.progress, task.result = "completed", 1, {"phase": 2}
    def finish():
        background._persist(task)
        finalized.set()
    finalizer = threading.Thread(target=finish, name="review-finalizer")
    finalizer.start()
    assert not finalized.wait(.05)
    resume.set()
    heartbeat.join(5)
    finalizer.join(5)
    assert not heartbeat.is_alive() and not finalizer.is_alive() and finalized.is_set()
    with factory() as db:
        row = db.get(BackgroundTask, task.id)
        assert row.status == "completed" and row.progress == 1 and row.result == {"phase": 2}
    stale = background.TaskStatus(id=task.id, type="sync", status="running", progress=.2, result={"phase": -1})
    background._persist(stale)
    assert stale.status == "completed" and stale.result == {"phase": 2}
    with factory() as db:
        row = db.get(BackgroundTask, task.id)
        assert row.status == "completed" and row.progress == 1 and row.result == {"phase": 2}


def test_recovery_between_heartbeat_read_and_write_cannot_be_undone(monkeypatch, background_storage_factory):
    import threading
    from sqlalchemy.orm import Session, sessionmaker
    paused, resume = threading.Event(), threading.Event()
    task = background.TaskStatus(id="cas-recovery", type="sync", status="running", result={"phase": 0})
    background._persist(task, create=True)
    class PausedReadSession(Session):
        def get(self, entity, identifier, *args, **kwargs):
            row = super().get(entity, identifier, *args, **kwargs)
            if threading.current_thread().name == "cas-heartbeat" and not paused.is_set():
                paused.set()
                assert resume.wait(5)
            return row
    factory = sessionmaker(bind=background_storage_factory.kw["bind"], class_=PausedReadSession)
    monkeypatch.setattr(background, "SessionLocal", factory)
    thread = threading.Thread(target=lambda: background._persist(task, heartbeat=True), name="cas-heartbeat")
    thread.start()
    assert paused.wait(5)
    with background_storage_factory() as db:
        db.query(BackgroundTask).filter_by(id=task.id).update({"status": "interrupted",
            "message": "worker lease expired", "completed_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
    resume.set()
    thread.join(5)
    assert not thread.is_alive()
    with background_storage_factory() as db:
        row = db.get(BackgroundTask, task.id)
        assert row.status == "interrupted" and row.message == "worker lease expired"
    assert task.status == "interrupted"
