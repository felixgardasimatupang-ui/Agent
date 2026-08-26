"""
Result aggregation and synthesis for the AI Swarm Orchestrator.
Collects results from multiple agents and produces coherent summaries.
"""
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class AggregationStrategy(Enum):
    """Different strategies for combining results."""
    CONCATENATE = "concatenate"      # Simple join
    MERGE = "merge"                  # Intelligent merge
    SUMMARIZE = "summarize"          # AI-powered summary
    VOTE = "vote"                    # Majority voting
    BEST = "best"                    # Select best result


@dataclass
class AgentResult:
    """Result from a single agent execution."""
    agent_id: int
    agent_type: str
    model: str
    instruction: str
    output: Optional[str] = None
    error: Optional[str] = None
    status: str = "pending"
    execution_time: float = 0.0
    tokens_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AggregatedResult:
    """Final aggregated result from the swarm."""
    task_id: str
    original_prompt: str
    strategy: AggregationStrategy
    final_output: str
    agent_results: List[AgentResult]
    success_count: int
    failure_count: int
    total_execution_time: float
    total_tokens: int
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResultAggregator:
    """Aggregates results from multiple agents into a coherent output."""

    def __init__(self, strategy: AggregationStrategy = AggregationStrategy.MERGE):
        self.strategy = strategy
        self.results: List[AgentResult] = []

    def add_result(self, result: AgentResult):
        """Add an agent result to the aggregator."""
        self.results.append(result)

    def clear(self):
        """Clear all stored results."""
        self.results.clear()

    def get_successful_results(self) -> List[AgentResult]:
        """Get only successful results."""
        return [r for r in self.results if r.status == "SUCCESS"]

    def get_failed_results(self) -> List[AgentResult]:
        """Get only failed results."""
        return [r for r in self.results if r.status == "ERROR"]

    def calculate_stats(self) -> Dict[str, Any]:
        """Calculate aggregation statistics."""
        successful = self.get_successful_results()
        failed = self.get_failed_results()

        return {
            "total": len(self.results),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / len(self.results) if self.results else 0,
            "total_tokens": sum(r.tokens_used for r in self.results),
            "total_time": sum(r.execution_time for r in self.results),
            "avg_time": (
                sum(r.execution_time for r in self.results) / len(self.results)
                if self.results
                else 0
            ),
        }

    def aggregate(self, task_id: str, original_prompt: str) -> AggregatedResult:
        """Aggregate results based on the configured strategy."""
        if self.strategy == AggregationStrategy.CONCATENATE:
            output = self._concatenate()
        elif self.strategy == AggregationStrategy.MERGE:
            output = self._merge()
        elif self.strategy == AggregationStrategy.VOTE:
            output = self._vote()
        elif self.strategy == AggregationStrategy.BEST:
            output = self._best()
        else:
            output = self._concatenate()

        stats = self.calculate_stats()

        return AggregatedResult(
            task_id=task_id,
            original_prompt=original_prompt,
            strategy=self.strategy,
            final_output=output,
            agent_results=self.results.copy(),
            success_count=stats["successful"],
            failure_count=stats["failed"],
            total_execution_time=stats["total_time"],
            total_tokens=stats["total_tokens"],
        )

    def _concatenate(self) -> str:
        """Simple concatenation of all results."""
        successful = self.get_successful_results()
        if not successful:
            return "No successful results to aggregate."

        parts = []
        for r in successful:
            parts.append(f"**Agent {r.agent_id} ({r.agent_type}):**\n{r.output}")

        return "\n\n---\n\n".join(parts)

    def _merge(self) -> str:
        """Intelligent merge of results by agent type."""
        successful = self.get_successful_results()
        if not successful:
            return "No successful results to aggregate."

        # Group by agent type
        by_type: Dict[str, List[AgentResult]] = {}
        for r in successful:
            by_type.setdefault(r.agent_type, []).append(r)

        sections = []
        for agent_type, results in by_type.items():
            if len(results) == 1:
                sections.append(
                    f"**{agent_type.title()} Output:**\n{results[0].output}"
                )
            else:
                combined = "\n\n".join(
                    f"- Agent {r.agent_id}: {r.output}" for r in results
                )
                sections.append(
                    f"**{agent_type.title()} Outputs ({len(results)} agents):**\n{combined}"
                )

        return "\n\n---\n\n".join(sections)

    def _vote(self) -> str:
        """Majority voting for consensus answers."""
        successful = self.get_successful_results()
        if not successful:
            return "No successful results to aggregate."

        # Simple voting: most common output wins
        output_counts: Dict[str, int] = {}
        output_map: Dict[str, AgentResult] = {}

        for r in successful:
            normalized = r.output.strip().lower()
            output_counts[normalized] = output_counts.get(normalized, 0) + 1
            output_map[normalized] = r

        if not output_counts:
            return "No results to vote on."

        winner = max(output_counts, key=output_counts.get)
        winning_result = output_map[winner]
        vote_count = output_counts[winner]

        return (
            f"**Consensus Result ({vote_count}/{len(successful)} agreement):**\n"
            f"{winning_result.output}"
        )

    def _best(self) -> str:
        """Select the best result based on heuristics."""
        successful = self.get_successful_results()
        if not successful:
            return "No successful results to aggregate."

        # Score based on: length (completeness), execution time (efficiency)
        def score(r: AgentResult) -> float:
            length_score = min(len(r.output) / 100, 10)  # Cap at 10
            time_score = max(10 - r.execution_time, 0)   # Faster is better
            return length_score + time_score

        best = max(successful, key=score)
        return (
            f"**Best Result (Agent {best.agent_id}, {best.agent_type}):**\n"
            f"{best.output}"
        )

    def to_json(self, result: AggregatedResult) -> str:
        """Serialize aggregated result to JSON."""
        return json.dumps(
            {
                "task_id": result.task_id,
                "original_prompt": result.original_prompt,
                "strategy": result.strategy.value,
                "final_output": result.final_output,
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "total_execution_time": result.total_execution_time,
                "total_tokens": result.total_tokens,
                "created_at": result.created_at,
                "agent_results": [
                    {
                        "agent_id": r.agent_id,
                        "agent_type": r.agent_type,
                        "model": r.model,
                        "status": r.status,
                        "output": r.output,
                        "error": r.error,
                        "execution_time": r.execution_time,
                        "tokens_used": r.tokens_used,
                    }
                    for r in result.agent_results
                ],
            },
            indent=2,
        )
