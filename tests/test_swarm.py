"""
Tests for the AI Swarm Orchestrator.
"""
import pytest
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_types import (
    AgentType,
    AgentProfile,
    get_agent_profile,
    classify_task_type,
    AGENT_PROMPTS,
    MODEL_PREFERENCES,
)
from task_queue import TaskQueue, Task, TaskStatus
from result_aggregator import (
    ResultAggregator,
    AgentResult,
    AggregatedResult,
    AggregationStrategy,
)
from retry_logic import (
    RetryConfig,
    retry_async,
    calculate_delay,
    CircuitBreaker,
    RetryExhaustedException,
)


# ============================================================================
# Agent Types Tests
# ============================================================================
class TestAgentTypes:
    """Tests for agent type classification and profiles."""

    def test_all_agent_types_have_prompts(self):
        """Every agent type should have a system prompt."""
        for agent_type in AgentType:
            profile = get_agent_profile(agent_type)
            assert profile.system_prompt, f"Missing prompt for {agent_type}"
            assert len(profile.system_prompt) > 50, f"Prompt too short for {agent_type}"

    def test_all_agent_types_have_models(self):
        """Every agent type should have a preferred model."""
        for agent_type in AgentType:
            assert agent_type in MODEL_PREFERENCES, f"Missing model for {agent_type}"

    def test_classify_coding_tasks(self):
        """Should classify coding-related tasks."""
        assert classify_task_type("Write a Python function") == AgentType.CODER
        assert classify_task_type("Implement a class for user management") == AgentType.CODER
        assert classify_task_type("Create a new module") == AgentType.CODER

    def test_classify_debug_tasks(self):
        """Should classify debugging tasks."""
        assert classify_task_type("Debug this error") == AgentType.DEBUGGER
        assert classify_task_type("Fix the bug in auth module") == AgentType.DEBUGGER
        assert classify_task_type("Why is this crashing?") == AgentType.DEBUGGER

    def test_classify_research_tasks(self):
        """Should classify research tasks."""
        assert classify_task_type("Research best practices for REST APIs") == AgentType.RESEARCHER
        assert classify_task_type("Find information about Docker networking") == AgentType.RESEARCHER

    def test_classify_simple_tasks(self):
        """Should classify simple tasks."""
        assert classify_task_type("What is 2+2?") == AgentType.SIMPLE
        assert classify_task_type("Hello world") == AgentType.SIMPLE


# ============================================================================
# Task Queue Tests
# ============================================================================
class TestTaskQueue:
    """Tests for SQLite task queue."""

    @pytest.fixture
    def queue(self, tmp_path):
        """Create a temporary task queue."""
        db_path = str(tmp_path / "test_tasks.db")
        return TaskQueue(db_path)

    def test_create_task(self, queue):
        """Should create a task with correct status."""
        task = queue.create_task(
            agent_id=1,
            agent_type="coding",
            instruction="Write code",
            model="power",
        )
        assert task.task_id is not None
        assert task.status == TaskStatus.QUEUED
        assert task.agent_id == 1

    def test_get_task(self, queue):
        """Should retrieve a task by ID."""
        created = queue.create_task(
            agent_id=2,
            agent_type="simple",
            instruction="Test",
            model="murah",
        )
        retrieved = queue.get_task(created.task_id)
        assert retrieved is not None
        assert retrieved.instruction == "Test"

    def test_update_task_status(self, queue):
        """Should update task status."""
        task = queue.create_task(
            agent_id=3,
            agent_type="coding",
            instruction="Update me",
            model="power",
        )
        success = queue.update_task_status(
            task.task_id,
            TaskStatus.RUNNING,
        )
        assert success

        updated = queue.get_task(task.task_id)
        assert updated.status == TaskStatus.RUNNING
        assert updated.started_at is not None

    def test_increment_retry(self, queue):
        """Should increment retry count."""
        task = queue.create_task(
            agent_id=4,
            agent_type="simple",
            instruction="Retry test",
            model="murah",
        )
        success = queue.increment_retry(task.task_id)
        assert success

        updated = queue.get_task(task.task_id)
        assert updated.retry_count == 1

    def test_get_pending_tasks(self, queue):
        """Should get pending tasks."""
        for i in range(3):
            queue.create_task(
                agent_id=i,
                agent_type="simple",
                instruction=f"Task {i}",
                model="murah",
            )
        pending = queue.get_pending_tasks()
        assert len(pending) == 3

    def test_get_task_stats(self, queue):
        """Should return task statistics."""
        queue.create_task(1, "simple", "T1", "murah")
        queue.create_task(2, "simple", "T2", "murah")
        stats = queue.get_task_stats()
        assert "queued" in stats
        assert stats["queued"] == 2

    def test_delete_task(self, queue):
        """Should delete a task."""
        task = queue.create_task(1, "simple", "Delete me", "murah")
        success = queue.delete_task(task.task_id)
        assert success
        assert queue.get_task(task.task_id) is None


# ============================================================================
# Result Aggregator Tests
# ============================================================================
class TestResultAggregator:
    """Tests for result aggregation."""

    def _make_result(self, agent_id: int, agent_type: str, output: str, status: str = "SUCCESS"):
        """Helper to create test results."""
        return AgentResult(
            agent_id=agent_id,
            agent_type=agent_type,
            model="murah",
            instruction="Test",
            output=output,
            status=status,
            execution_time=1.0,
            tokens_used=100,
        )

    def test_concatenate_strategy(self):
        """Should concatenate results."""
        agg = ResultAggregator(AggregationStrategy.CONCATENATE)
        agg.add_result(self._make_result(1, "coder", "Code output"))
        agg.add_result(self._make_result(2, "writer", "Written output"))

        result = agg.aggregate("task-1", "Test prompt")
        assert "Code output" in result.final_output
        assert "Written output" in result.final_output

    def test_vote_strategy(self):
        """Should select majority vote."""
        agg = ResultAggregator(AggregationStrategy.VOTE)
        agg.add_result(self._make_result(1, "coder", "Same answer"))
        agg.add_result(self._make_result(2, "writer", "Same answer"))
        agg.add_result(self._make_result(3, "analyst", "Different answer"))

        result = agg.aggregate("task-1", "Test prompt")
        assert "Same answer" in result.final_output
        assert "Consensus" in result.final_output

    def test_best_strategy(self):
        """Should select best result (prefers coder for code tasks, concise for simple)."""
        agg = ResultAggregator(AggregationStrategy.BEST)
        agg.add_result(self._make_result(1, "coder", "Short"))
        agg.add_result(self._make_result(2, "writer", "This is a much longer and more detailed output"))

        result = agg.aggregate("task-1", "Write a Python function")
        # For code tasks, coder agent gets type_bonus, so "Short" wins
        assert "Short" in result.final_output

    def test_calculate_stats(self):
        """Should calculate correct statistics."""
        agg = ResultAggregator()
        agg.add_result(self._make_result(1, "coder", "OK", "SUCCESS"))
        agg.add_result(self._make_result(2, "writer", "ERR", "ERROR"))

        stats = agg.calculate_stats()
        assert stats["total"] == 2
        assert stats["successful"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == 0.5

    def test_empty_aggregation(self):
        """Should handle empty results."""
        agg = ResultAggregator()
        result = agg.aggregate("task-1", "Test prompt")
        assert "No successful results" in result.final_output


# ============================================================================
# Retry Logic Tests
# ============================================================================
class TestRetryLogic:
    """Tests for retry and circuit breaker."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failure(self):
        """Should succeed after transient failure."""
        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Transient error")
            return "success"

        config = RetryConfig(max_retries=3, base_delay=0.01, jitter=False)
        result = await retry_async(failing_func, config)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Should raise exception after all retries."""
        async def always_fail():
            raise ValueError("Permanent error")

        config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        with pytest.raises(RetryExhaustedException):
            await retry_async(always_fail, config)

    def test_circuit_breaker_opens(self):
        """Should open after threshold failures."""
        cb = CircuitBreaker(failure_threshold=3, name="test")
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"

    def test_circuit_breaker_half_open(self):
        """Should transition to half-open after timeout."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        import time
        time.sleep(0.15)
        assert cb.state == "half-open"

    def test_circuit_breaker_closes_on_success(self):
        """Should close after successful call."""
        cb = CircuitBreaker(failure_threshold=3, name="test")
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"


# ============================================================================
# Integration Tests
# ============================================================================
class TestIntegration:
    """Integration tests for the swarm system."""

    def test_task_to_result_flow(self):
        """Test flow from task creation to result aggregation."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = TaskQueue(os.path.join(tmpdir, "test.db"))
            aggregator = ResultAggregator(AggregationStrategy.CONCATENATE)

            # Create task
            task = queue.create_task(
                agent_id=1,
                agent_type="coding",
                instruction="Write code",
                model="power",
            )
            assert task.status == TaskStatus.QUEUED

            # Simulate execution
            queue.update_task_status(task.task_id, TaskStatus.RUNNING)

            # Create result
            result = AgentResult(
                agent_id=1,
                agent_type="coding",
                model="power",
                instruction="Write code",
                output="def hello(): pass",
                status="SUCCESS",
                execution_time=0.5,
                tokens_used=50,
            )
            aggregator.add_result(result)

            # Aggregate
            agg_result = aggregator.aggregate(task.task_id, "Write code")
            assert agg_result.success_count == 1
            assert "hello" in agg_result.final_output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
