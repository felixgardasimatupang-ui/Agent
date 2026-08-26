"""
Swarm Manager - Core orchestration engine for the AI Swarm Orchestrator.
Manages agent lifecycle, task execution, and result aggregation.
"""
import asyncio
import httpx
from typing import List, Optional, Dict, Any
from openai import AsyncOpenAI

from agent_types import (
    AgentType,
    AgentProfile,
    get_agent_profile,
    classify_task_type,
    MODEL_PREFERENCES,
    WEB_SEARCH_TOOL,
)
from config import (
    ROUTER_BASE_URL,
    ROUTER_API_KEY,
    TASK_TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    MODEL_FALLBACK_CHAIN,
    NINEROUTER_URL,
    MODEL_WEB_SEARCH,
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
    "web_search": AgentType.WEB_SEARCHER,
    "search": AgentType.WEB_SEARCHER,
    "web_searcher": AgentType.WEB_SEARCHER,
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
        shared_context: Optional[Dict[str, Any]] = None,
    ):
        self.task = task
        self.client = client
        self.retry_config = retry_config or RetryConfig(
            max_retries=MAX_RETRIES,
            base_delay=RETRY_BASE_DELAY,
        )
        self.telemetry_cb = telemetry_cb
        self.shared_context = shared_context or {}
        self.profile = get_agent_profile(resolve_agent_type(task.agent_type))
        self._tokens_used = 0

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
            result.tokens_used = self._tokens_used
            result.status = "SUCCESS"
            result.execution_time = asyncio.get_event_loop().time() - start_time

            # Store in shared context for other agents
            self.shared_context[f"agent_{self.task.agent_id}"] = {
                "type": self.task.agent_type,
                "output": response[:500] if response else "",
                "status": "SUCCESS",
            }

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
        ]

        # Inject shared context from previous agents (brief summaries only)
        if self.shared_context:
            context_parts = []
            for key, val in self.shared_context.items():
                if key.startswith("agent_") and val.get("status") == "SUCCESS":
                    context_parts.append(
                        f"[{val['type']}]: {val['output'][:100]}"
                    )
            if context_parts:
                context_str = "\n".join(context_parts)
                messages.append({
                    "role": "system",
                    "content": f"Prior outputs:\n{context_str}",
                })

        messages.append({"role": "user", "content": self.task.instruction})

        # Add web search tool for web_searcher agents
        tools = None
        if self.task.agent_type in ("web_searcher", "web_search"):
            tools = [WEB_SEARCH_TOOL]

        try:
            if tools:
                response = await self.client.chat.completions.create(
                    model=self.task.model,
                    messages=messages,
                    max_tokens=self.profile.max_tokens,
                    temperature=self.profile.temperature,
                    tools=tools,
                )
            else:
                response = await self.client.chat.completions.create(
                    model=self.task.model,
                    messages=messages,
                    max_tokens=self.profile.max_tokens,
                    temperature=self.profile.temperature,
                )
        except Exception as e:
            # Multi-provider failover: try fallback models
            if "model" in str(e).lower() or "unavailable" in str(e).lower():
                for fallback_model in MODEL_FALLBACK_CHAIN:
                    if fallback_model != self.task.model:
                        try:
                            logger.warning(f"Falling back to {fallback_model} for agent {self.task.agent_id}")
                            response = await self.client.chat.completions.create(
                                model=fallback_model,
                                messages=messages,
                                max_tokens=self.profile.max_tokens,
                                temperature=self.profile.temperature,
                            )
                            break
                        except Exception:
                            continue
                else:
                    raise
            else:
                raise

        if response.usage:
            self._tokens_used = response.usage.total_tokens
            logger.debug(
                f"Token usage: {self._tokens_used}",
                extra={"task_id": self.task.task_id},
            )

        # Handle tool calls for web search
        choice = response.choices[0]
        if choice.message.tool_calls:
            return await self._handle_tool_calls(choice.message.tool_calls, messages)

        return choice.message.content

    async def _handle_tool_calls(self, tool_calls, messages: list) -> str:
        """Handle tool calls (e.g., web search) and continue conversation."""
        import json
        import httpx as httpx_mod

        messages.append(messages[-1])  # assistant message with tool_calls

        for tool_call in tool_calls:
            func = tool_call.function
            if func.name == "web_search":
                args = json.loads(func.arguments)
                query = args.get("query", "")

                # Call 9Router tavily/search
                try:
                    async with httpx_mod.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            f"{NINEROUTER_URL}/v1/chat/completions",
                            json={
                                "model": MODEL_WEB_SEARCH,
                                "messages": [{"role": "user", "content": query}],
                            },
                        )
                        if resp.status_code == 200:
                            search_result = resp.json()
                            content = search_result.get("choices", [{}])[0].get("message", {}).get("content", "No results found.")
                        else:
                            content = f"Search failed: HTTP {resp.status_code}"
                except Exception as e:
                    content = f"Search error: {str(e)}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": content,
                })

        # Get final response with search results
        final_response = await self.client.chat.completions.create(
            model=self.task.model,
            messages=messages,
            max_tokens=self.profile.max_tokens,
            temperature=self.profile.temperature,
        )

        if final_response.usage:
            self._tokens_used += final_response.usage.total_tokens

        return final_response.choices[0].message.content


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

        # Shared context between agents (memory)
        self._shared_context: Dict[str, Any] = {}

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

        # Clear shared context for new swarm execution
        self._shared_context.clear()

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

            # Include original prompt as context for the agent (keep it short)
            original_instruction = task_def["instruction"]
            # Only include first 500 chars of original prompt to avoid token bloat
            prompt_preview = prompt[:500] + ("..." if len(prompt) > 500 else "")
            full_instruction = f"""ORIGINAL REQUEST: {prompt_preview}

YOUR TASK: {original_instruction}

Output directly. No preamble, no questions. Be concise and focused."""

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
        """Execute tasks in parallel with per-worker httpx clients."""
        api_key = ROUTER_API_KEY if ROUTER_API_KEY else "sk-dummy"

        async def execute_with_semaphore(task: Task) -> AgentResult:
            async with self._semaphore:
                # Per-agent httpx client to avoid connection pool serialization
                http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(TASK_TIMEOUT_SECONDS, connect=10.0),
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=10,
                        keepalive_expiry=30,
                    ),
                )
                client = AsyncOpenAI(
                    base_url=ROUTER_BASE_URL,
                    api_key=api_key,
                    timeout=TASK_TIMEOUT_SECONDS,
                    max_retries=0,
                    http_client=http_client,
                )
                try:
                    worker = AgentWorker(
                        task=task,
                        client=client,
                        telemetry_cb=telemetry_cb or self.telemetry_cb,
                        shared_context=self._shared_context,
                    )
                    result = await worker.run()
                    self.aggregator.add_result(result)
                    return result
                finally:
                    await http_client.aclose()

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
