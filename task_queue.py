"""
SQLite-based task queue for persistence and reliability.
Ensures tasks survive crashes and can be retried.
"""
import sqlite3
import json
import uuid
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from contextlib import contextmanager


class TaskStatus(Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Task:
    """Represents a unit of work in the swarm."""
    task_id: str
    agent_id: int
    agent_type: str
    instruction: str
    model: str
    status: TaskStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        d = asdict(self)
        d['status'] = self.status.value
        d['metadata'] = json.dumps(self.metadata) if self.metadata else None
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Task':
        """Create task from database row."""
        return cls(
            task_id=row['task_id'],
            agent_id=row['agent_id'],
            agent_type=row['agent_type'],
            instruction=row['instruction'],
            model=row['model'],
            status=TaskStatus(row['status']),
            created_at=row['created_at'],
            started_at=row['started_at'],
            completed_at=row['completed_at'],
            result=row['result'],
            error=row['error'],
            retry_count=row['retry_count'],
            max_retries=row['max_retries'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None,
        )


class TaskQueue:
    """SQLite-backed task queue with retry support."""

    def __init__(self, db_path: str = "swarm_tasks.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    agent_id INTEGER NOT NULL,
                    agent_type TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status 
                ON tasks(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_agent_id 
                ON tasks(agent_id)
            """)

    @contextmanager
    def _get_conn(self):
        """Get database connection with auto-commit."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_task(
        self,
        agent_id: int,
        agent_type: str,
        instruction: str,
        model: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Create a new task and add to queue."""
        task = Task(
            task_id=str(uuid.uuid4()),
            agent_id=agent_id,
            agent_type=agent_type,
            instruction=instruction,
            model=model,
            status=TaskStatus.QUEUED,
            created_at=datetime.utcnow().isoformat(),
            metadata=metadata,
        )

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO tasks 
                   (task_id, agent_id, agent_type, instruction, model, 
                    status, created_at, retry_count, max_retries, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.task_id,
                    task.agent_id,
                    task.agent_type,
                    task.instruction,
                    task.model,
                    task.status.value,
                    task.created_at,
                    task.retry_count,
                    task.max_retries,
                    json.dumps(task.metadata) if task.metadata else None,
                ),
            )

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return Task.from_row(row) if row else None

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update task status and result."""
        updates = {"status": status.value}
        
        if status == TaskStatus.RUNNING:
            updates["started_at"] = datetime.utcnow().isoformat()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            updates["completed_at"] = datetime.utcnow().isoformat()
        
        if result is not None:
            updates["result"] = result
        if error is not None:
            updates["error"] = error

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]

        with self._get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE task_id = ?",
                values,
            )
            return cursor.rowcount > 0

    def increment_retry(self, task_id: str) -> bool:
        """Increment retry count and check if retries available."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT retry_count, max_retries FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            
            if not row:
                return False
            
            if row['retry_count'] >= row['max_retries']:
                return False
            
            conn.execute(
                """UPDATE tasks 
                   SET retry_count = retry_count + 1, 
                       status = ? 
                   WHERE task_id = ?""",
                (TaskStatus.RETRYING.value, task_id),
            )
            return True

    def get_pending_tasks(self, limit: int = 100) -> List[Task]:
        """Get queued tasks ready for execution."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM tasks 
                   WHERE status = ? 
                   ORDER BY created_at ASC 
                   LIMIT ?""",
                (TaskStatus.QUEUED.value, limit),
            ).fetchall()
            return [Task.from_row(row) for row in rows]

    def get_failed_tasks(self) -> List[Task]:
        """Get failed tasks that can be retried."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM tasks 
                   WHERE status = ? AND retry_count < max_retries
                   ORDER BY created_at ASC"""
            ).fetchall()
            return [Task.from_row(row) for row in rows]

    def get_task_stats(self) -> Dict[str, int]:
        """Get task statistics by status."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM tasks GROUP BY status"
            ).fetchall()
            return {row['status']: row['count'] for row in rows}

    def clear_completed(self) -> int:
        """Clear completed tasks and return count."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status = ?",
                (TaskStatus.COMPLETED.value,),
            )
            return cursor.rowcount

    def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE task_id = ?", (task_id,)
            )
            return cursor.rowcount > 0
