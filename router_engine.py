"""
Router Engine - Task decomposition and intelligent routing for the AI Swarm Orchestrator.
Uses9Router to break down complex tasks and assign optimal models.
"""
import json
from typing import List, Dict, Any
from openai import AsyncOpenAI

from config import (
    ROUTER_BASE_URL,
    ROUTER_API_KEY,
    MODEL_COORDINATOR,
    AGENT_MODEL_MAP,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)
from agent_types import classify_task_type, AgentType
from logging_config import get_logger

logger = get_logger(__name__)


class NineRouterCoordinator:
    """
    Coordinates task decomposition and model routing.
    Uses the 'plan' model for intelligent task analysis.
    """

    def __init__(self):
        api_key = ROUTER_API_KEY if ROUTER_API_KEY else "sk-dummy"
        self.client = AsyncOpenAI(
            base_url=ROUTER_BASE_URL,
            api_key=api_key,
            timeout=30.0,
            max_retries=1,
        )
        self.router_model = MODEL_COORDINATOR
        logger.info(
            f"NineRouterCoordinator initialized",
            extra={"base_url": ROUTER_BASE_URL, "router_model": self.router_model},
        )

    async def decompose_and_route(
        self,
        prompt: str,
        agent_count: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Decompose a user prompt into sub-tasks and route to appropriate models.

        Args:
            prompt: User's original request
            agent_count: Number of agents to spawn

        Returns:
            List of task definitions with model assignments
        """
        logger.info(
            f"Decomposing prompt into {agent_count} tasks",
            extra={"prompt_length": len(prompt)},
        )

        available_models = ", ".join(AGENT_MODEL_MAP.values())
        agent_types = [t.value for t in AgentType]

        system_instruction = f"""You are an AI Task Coordinator. Decompose tasks into EXACTLY {agent_count} parallel sub-tasks.

OUTPUT: ONLY a JSON array with EXACTLY {agent_count} items. Nothing else. No markdown, no explanation.

AGENT TYPES: coding, debugging, researching, analyzing, architecture, writing, translating, simple

DECISION RULE:
- SIMPLE QUESTION (math, facts, definitions, translations): Give ALL agents the SAME core question but from DIFFERENT angles. Example for "What is 2+2?": agent 1 (coding) writes code, agent 2 (researching) explains math, agent 3 (simple) gives direct answer.
- COMPLEX TASK (code, systems, analysis): Split into non-overlapping sub-tasks with specific deliverables.

OUTPUT FORMAT:
[
    {{"agent_id": 1, "task_type": "coding", "instruction": "..."}},
    {{"agent_id": 2, "task_type": "researching", "instruction": "..."}}
]

RULES:
- CRITICAL: Each task MUST BE UNIQUE. No two agents should work on the same topic or deliverable.
- Each instruction is SELF-CONTAINED. Agent has no context except this instruction.
- Keep instructions SHORT and FOCUSED. 1-2 sentences per task. Specific deliverable.
- DO NOT include the full original prompt in each task. Reference it briefly.
- Each task should produce a CONCISE output (100-200 words or 50-100 lines of code).
- Output EXACTLY {agent_count} items, numbered 1 to {agent_count}.
- CRITICAL: Tasks must be completable within 30 seconds by the agent model.
- AVOID DUPLICATION: If assigning multiple coding tasks, make each one tackle a DIFFERENT component or aspect.
- CODING TASKS: ONE file only, max 30-40 lines. No multi-file projects. Keep examples minimal.
- RESEARCH/ANALYSIS: Max 200 words. Focus on key points only. No lengthy essays."""

        try:
            response = await self.client.chat.completions.create(
                model=self.router_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
                stream=False,
            )
            raw = response.choices[0].message.content
            logger.debug(f"Raw coordinator response: {raw[:500]}...")

            # Parse JSON - handle various formats
            tasks = self._parse_tasks_response(raw)

            # Validate and normalize tasks
            tasks = self._validate_tasks(tasks, agent_count)

            logger.info(
                f"Task decomposition complete",
                extra={"task_count": len(tasks)},
            )

            return tasks

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse coordinator response: {e}", exc_info=True)
            return self._fallback_tasks(prompt, agent_count)
        except Exception as e:
            logger.error(f"Task decomposition failed: {e}", exc_info=True)
            return self._fallback_tasks(prompt, agent_count)

    def _parse_tasks_response(self, raw: str) -> List[Dict[str, Any]]:
        """Parse tasks from various response formats."""
        # Try direct JSON parse
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data.get("tasks", data.get("task_list", []))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON array in text
        array_match = re.search(r'\[[\s\S]*\]', raw)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError("No valid JSON found in response", raw, 0)

    def _validate_tasks(
        self,
        tasks: List[Dict[str, Any]],
        expected_count: int,
    ) -> List[Dict[str, Any]]:
        """Validate and normalize task definitions."""
        valid_models = set(AGENT_MODEL_MAP.values())
        valid_types = set(AGENT_MODEL_MAP.keys())

        validated = []
        for i, task in enumerate(tasks):
            # Ensure required fields
            task.setdefault("agent_id", i + 1)
            task.setdefault("task_type", "simple")
            task.setdefault("assigned_model", MODEL_COORDINATOR)
            task.setdefault("instruction", "")

            # Validate model
            if task["assigned_model"] not in valid_models:
                task_type = task.get("task_type", "default")
                task["assigned_model"] = AGENT_MODEL_MAP.get(
                    task_type, MODEL_COORDINATOR
                )

            # Validate task type
            if task["task_type"] not in valid_types:
                task["task_type"] = "simple"
                task["assigned_model"] = AGENT_MODEL_MAP["simple"]

            # Auto-classify if type seems wrong
            classified = classify_task_type(task["instruction"])
            if classified.value != task["task_type"]:
                # Use classification if original seems generic
                if task["task_type"] == "simple" and classified != AgentType.SIMPLE:
                    task["task_type"] = classified.value
                    task["assigned_model"] = AGENT_MODEL_MAP.get(
                        classified.value, MODEL_COORDINATOR
                    )

            validated.append(task)

        # Pad or trim to expected count
        while len(validated) < expected_count:
            validated.append({
                "agent_id": len(validated) + 1,
                "task_type": "simple",
                "assigned_model": AGENT_MODEL_MAP["simple"],
                "instruction": f"Additional analysis or support task #{len(validated) + 1}",
            })

        return validated[:expected_count]

    def _fallback_tasks(
        self,
        prompt: str,
        agent_count: int,
    ) -> List[Dict[str, Any]]:
        """Generate fallback tasks when decomposition fails."""
        logger.warning(f"Using fallback task generation for {agent_count} agents")

        tasks = []
        for i in range(agent_count):
            tasks.append({
                "agent_id": i + 1,
                "task_type": "simple",
                "assigned_model": AGENT_MODEL_MAP["simple"],
                "instruction": f"Analyze and contribute to: {prompt}",
            })

        return tasks

    async def health_check(self) -> bool:
        """Check if9Router is accessible."""
        try:
            response = await self.client.chat.completions.create(
                model=MODEL_COORDINATOR,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
