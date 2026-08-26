"""
Swarm Manager - Core orchestration engine for the AI Swarm Orchestrator.
Manages agent lifecycle, task execution, and result aggregation.
"""
import asyncio
from typing import List, Optional, Dict, Any
from openai import AsyncOpenAI

from agent_types import (
    AgentType,
    AgentProfile,
    get_agent_profile,
    classify_task_type,
    MODEL_PREFERENCES,
)

# Map coordinator task_type strings to AgentType enum values
TASK_TYPE_TO_AGENT = {
    "coding": AgentType.CODER,
    "code": AgentType.CODER,
    "debugging": AgentType.DEBUGGER,
    "debug": AgentType.DEBUGGER,
    "researching": AgentType.RESEARCHER,
    "research": AgentType.RESEARCHER,
    "analyzing": AgentType.ANALYST,
    "analysis": AgentType.ANALYST,
    "architecture": AgentType.ARCHITECT,
    "architect": AgentType.ARCHITECT,
    "writing": AgentType.WRITER,
    "writer": AgentType.WRITER,
    "translating": AgentType.TRANSLATOR,
    "translate": AgentType.TRANSLATOR,
    "simple": AgentType.SIMPLE,
}


def resolve_agent_type(task_type_str: str) -> AgentType:
    """Resolve coordinator task_type string to AgentType enum."""
    return TASK_TYPE_TO_AGENT.get(task_type_str.lower(), AgentType.SIMPLE)
from task_queue import TaskQueue, Task, TaskStatus
from result_aggregator import (
    ResultAggregator,
    AgentResult,
    AggregatedResult,
    AggregationStrategy,
)
from retry_logic import RetryConfig, retry_async, CircuitBreaker, call_with_circuit_breaker
from logging_config import get_logger, generate_correlation_id, set_correlation_id

logger = get_logger(__name__)


class AgentWorker:
    """Executes individual tasks with retry and monitoring."""

    def __init__(
        self,
        task: Task,
        client: AsyncOpenAI,
        retry_config: Optional[RetryConfig] = None,
        telemetry_cb=None,
    ):
        self.task = task
        self.client = client
        self.retry_config = retry_config or RetryConfig(max_retries=3)
        self.telemetry_cb = telemetry_cb
        self.profile = get_agent_profile(resolve_agent_type(task.agent_type))

    async def run(self) -> AgentResult:
        """Execute the task with retry logic."""
        set_correlation_id(generate_correlation_id())
        logger.info(
            f"Agent {self.task.agent_id} starting task",
            extra={"task_id": self.task.task_id, "model": self.task.model},
        )

        if self.telemetry_cb:
            await self.telemetry_cb(
                self.task.agent_id,
                "INITIALIZING",
                f"Model: {self.task.model}",
            )

        result = AgentResult(
            agent_id=self.task.agent_id,
            agent_type=self.task.agent_type,
            model=self.task.model,
            instruction=self.task.instruction,
        )

        start_time = asyncio.get_event_loop().time()

        try:
            # Execute with retry
            response = await retry_async(
                self._execute_call,
                self.retry_config,
            )

            result.output = response
            result.status = "SUCCESS"
            result.execution_time = asyncio.get_event_loop().time() - start_time

            if self.telemetry_cb:
                await self.telemetry_cb(
                    self.task.agent_id,
                    "COMPLETE",
                    f"Done in {result.execution_time:.2f}s",
                )

            logger.info(
                f"Agent {self.task.agent_id} completed successfully",
                extra={
                    "task_id": self.task.task_id,
                    "execution_time": result.execution_time,
                },
            )

        except Exception as e:
            result.error = str(e)
            result.status = "ERROR"
            result.execution_time = asyncio.get_event_loop().time() - start_time

            if self.telemetry_cb:
                await self.telemetry_cb(
                    self.task.agent_id,
                    "FAILED",
                    str(e),
                )

            logger.error(
                f"Agent {self.task.agent_id} failed: {e}",
                extra={"task_id": self.task.task_id, "error": str(e)},
                exc_info=True,
            )

        return result

    async def _execute_call(self) -> str:
        """Make the actual API call to the LLM."""
        messages = [
            {"role": "system", "content": self.profile.system_prompt},
            {"role": "user", "content": self.task.instruction},
        ]

        response = await self.client.chat.completions.create(
            model=self.task.model,
            messages=messages,
            max_tokens=self.profile.max_tokens,
            temperature=self.profile.temperature,
        )

        if response.usage:
            logger.debug(
                f"Token usage: {response.usage.total_tokens}",
                extra={"task_id": self.task.task_id},
            )

        return response.choices[0].message.content


class SwarmManager:
    """
    Orchestrates multiple agents to execute tasks in parallel.
    Manages task lifecycle, retry, and result aggregation.
    """

    def __init__(
        self,
        router_engine,
        telemetry_cb=None,
        aggregation_strategy: AggregationStrategy = AggregationStrategy.MERGE,
        max_concurrent_agents: int = 10,
    ):
        self.router_engine = router_engine
        self.telemetry_cb = telemetry_cb
        self.max_concurrent_agents = max_concurrent_agents

        # Initialize components
        self.task_queue = TaskQueue()
        self.aggregator = ResultAggregator(strategy=aggregation_strategy)
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            name="swarm_executor",
        )

        # Semaphore for limiting concurrency
        self._semaphore = asyncio.Semaphore(max_concurrent_agents)

    async def execute_swarm(
        self,
        prompt: str,
        agent_count: int = 10,
        aggregation_strategy: Optional[AggregationStrategy] = None,
        telemetry_cb=None,
    ) -> AggregatedResult:
        """
        Execute a swarm of agents for the given prompt.

        Args:
            prompt: User's original request
            agent_count: Number of agents to spawn
            aggregation_strategy: Override default aggregation strategy

        Returns:
            AggregatedResult with combined outputs
        """
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)

        logger.info(
            f"Starting swarm execution",
            extra={
                "prompt_length": len(prompt),
                "agent_count": agent_count,
                "correlation_id": correlation_id,
            },
        )

        if not self.circuit_breaker.is_available():
            raise RuntimeError("Swarm circuit breaker is open. Service degraded.")

        # Step 1: Decompose and route
        try:
            task_definitions = await self.router_engine.decompose_and_route(
                prompt, agent_count
            )
        except Exception as e:
            logger.error(f"Task decomposition failed: {e}", exc_info=True)
            raise

        # Step 2: Create tasks in queue
        tasks = []
        for task_def in task_definitions:
            agent_type = task_def.get("task_type", "simple")
            model = task_def.get("assigned_model", "murah")

            # Include original prompt as context for the agent
            original_instruction = task_def["instruction"]
            full_instruction = f"""ORIGINAL USER REQUEST:\n\"\"\"\n{prompt}\n\"\"\"\n\nYOUR SPECIFIC TASK:\n{original_instruction}\n\nProduce the complete output directly. Do NOT ask questions or say you need to check files."""

            task = self.task_queue.create_task(
                agent_id=task_def["agent_id"],
                agent_type=agent_type,
                instruction=full_instruction,
                model=model,
                metadata={"correlation_id": correlation_id},
            )
            tasks.append(task)

            logger.info(
                f"Created task {task.task_id}",
                extra={
                    "agent_id": task.agent_id,
                    "agent_type": agent_type,
                    "model": model,
                },
            )

        # Step 3: Execute tasks in parallel
        if aggregation_strategy:
            self.aggregator.strategy = aggregation_strategy
        self.aggregator.clear()

        results = await self._execute_tasks_parallel(tasks, telemetry_cb=telemetry_cb)

        # Step 4: Aggregate results
        aggregated = self.aggregator.aggregate(
            task_id=correlation_id,
            original_prompt=prompt,
        )

        # Update task queue with final statuses
        for result in results:
            status = TaskStatus.COMPLETED if result.status == "SUCCESS" else TaskStatus.FAILED
            self.task_queue.update_task_status(
                task_id=str(result.agent_id),
                status=status,
                result=result.output,
                error=result.error,
            )

        logger.info(
            f"Swarm execution completed",
            extra={
                "success_count": aggregated.success_count,
                "failure_count": aggregated.failure_count,
                "total_time": aggregated.total_execution_time,
            },
        )

        self.circuit_breaker.record_success()
        return aggregated

    async def _execute_tasks_parallel(
        self,
        tasks: List[Task],
        telemetry_cb=None,
    ) -> List[AgentResult]:
        """Execute tasks in parallel with concurrency limiting."""
        results = []

        async def execute_with_semaphore(task: Task) -> AgentResult:
            async with self._semaphore:
                worker = AgentWorker(
                    task=task,
                    client=self.router_engine.client,
                    telemetry_cb=telemetry_cb or self.telemetry_cb,
                )
                result = await worker.run()
                self.aggregator.add_result(result)
                return result

        # Create all tasks
        coros = [execute_with_semaphore(task) for task in tasks]

        # Execute with gather (handles exceptions)
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Handle any exceptions from gather
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Task {tasks[i].task_id} raised exception: {result}")
                # Create error result
                error_result = AgentResult(
                    agent_id=tasks[i].agent_id,
                    agent_type=tasks[i].agent_type,
                    model=tasks[i].model,
                    instruction=tasks[i].instruction,
                    error=str(result),
                    status="ERROR",
                )
                final_results.append(error_result)
            else:
                final_results.append(result)

        return final_results

    def get_stats(self) -> Dict[str, Any]:
        """Get swarm execution statistics."""
        queue_stats = self.task_queue.get_task_stats()
        return {
            "queue": queue_stats,
            "circuit_breaker": {
                "state": self.circuit_breaker.state,
                "failure_count": self.circuit_breaker._failure_count,
            },
            "max_concurrent": self.max_concurrent_agents,
        }

    def clear_completed_tasks(self) -> int:
        """Clear completed tasks from queue."""
        return self.task_queue.clear_completed()
