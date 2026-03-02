import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TaskStatus:
    id: str
    type: str
    status: str = "running"
    progress: float = 0.0
    message: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

executor = ThreadPoolExecutor(max_workers=2)
task_registry: dict[str, TaskStatus] = {}

def submit_task(task_type: str, fn, *args, **kwargs) -> str:
    task_id = str(uuid.uuid4())
    task_registry[task_id] = TaskStatus(id=task_id, type=task_type)

    def wrapper():
        try:
            fn(task_id, *args, **kwargs)
            task_registry[task_id].status = "completed"
            task_registry[task_id].progress = 1.0
        except Exception as e:
            task_registry[task_id].status = "failed"
            task_registry[task_id].message = str(e)

    executor.submit(wrapper)
    return task_id

def get_task_status(task_id: str) -> TaskStatus | None:
    return task_registry.get(task_id)
