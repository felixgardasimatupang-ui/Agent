"""
AI Swarm Orchestrator - CLI Entry Point
Main command-line interface for the swarm system.
"""
import asyncio
import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt
from rich.live import Live
from rich.spinner import Spinner

from router_engine import NineRouterCoordinator
from swarm_manager import SwarmManager
from result_aggregator import AggregationStrategy
from dashboard_server import broadcast_status
from config import (
    DEFAULT_AGENT_COUNT,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    NINEROUTER_URL,
    NINEROUTER_KEY,
    LOG_LEVEL,
    JSON_LOG_FORMAT,
    LOG_FILE,
)
from logging_config import setup_logging, get_logger, generate_correlation_id

console = Console()
logger = get_logger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="AI Swarm Orchestrator - Execute tasks with multiple AI agents"
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        help="Task prompt (if not provided, enters interactive mode)",
    )
    parser.add_argument(
        "-n", "--agents",
        type=int,
        default=DEFAULT_AGENT_COUNT,
        help=f"Number of agents to spawn (default: {DEFAULT_AGENT_COUNT})",
    )
    parser.add_argument(
        "-s", "--strategy",
        choices=["merge", "concatenate", "vote", "best"],
        default="merge",
        help="Result aggregation strategy (default: merge)",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start dashboard server only",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=DASHBOARD_PORT,
        help=f"Dashboard port (default: {DASHBOARD_PORT})",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show swarm statistics",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=LOG_LEVEL,
        help=f"Log level (default: {LOG_LEVEL})",
    )
    return parser.parse_args()


async def run_interactive(swarm: SwarmManager):
    """Run in interactive mode."""
    console.print(
        Panel.fit(
            "[bold cyan]AI Swarm Orchestrator[/bold cyan]\n"
            "[dim]Interactive Mode - Type 'quit' to exit[/dim]"
        )
    )

    while True:
        try:
            prompt = Prompt.ask("\n[bold green]Enter task")

            if prompt.lower() in ("quit", "exit", "q"):
                console.print("[yellow]Goodbye![/yellow]")
                break

            if not prompt.strip():
                continue

            agent_count = IntPrompt.ask(
                "[bold yellow]Number of agents",
                default=DEFAULT_AGENT_COUNT,
            )

            strategy_str = Prompt.ask(
                "[bold yellow]Aggregation strategy",
                choices=["merge", "concatenate", "vote", "best"],
                default="merge",
            )
            strategy = AggregationStrategy(strategy_str)

            console.print(
                f"\n[bold blue]Starting swarm with {agent_count} agents...[/bold blue]"
            )

            with Live(Spinner("dots", text="Executing swarm..."), console=console):
                result = await swarm.execute_swarm(
                    prompt,
                    agent_count=agent_count,
                    aggregation_strategy=strategy,
                )

            # Display results
            display_result(result)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type 'quit' to exit.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            logger.error(f"Interactive mode error: {e}", exc_info=True)


def display_result(result):
    """Display aggregated result."""
    table = Table(title="Swarm Execution Result", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Task ID", result.task_id[:12])
    table.add_row("Strategy", result.strategy.value)
    table.add_row("Success", str(result.success_count))
    table.add_row("Failed", str(result.failure_count))
    table.add_row("Total Time", f"{result.total_execution_time:.2f}s")
    table.add_row("Total Tokens", str(result.total_tokens))

    console.print(table)

    console.print(
        Panel(
            result.final_output,
            title="[bold green]Final Output[/bold green]",
            border_style="green",
        )
    )


async def show_stats(swarm: SwarmManager):
    """Display swarm statistics."""
    stats = swarm.get_stats()

    table = Table(title="Swarm Statistics", show_header=True)
    table.add_column("Category", style="cyan")
    table.add_column("Value", style="green")

    for category, values in stats.items():
        if isinstance(values, dict):
            for key, value in values.items():
                table.add_row(f"{category}.{key}", str(value))
        else:
            table.add_row(category, str(values))

    console.print(table)


async def run_dashboard(port: int):
    """Run dashboard server only."""
    import uvicorn
    from dashboard_server import app

    console.print(
        Panel.fit(
            f"[bold cyan]Starting Dashboard Server[/bold cyan]\n"
            f"[dim]URL: http://{DASHBOARD_HOST}:{port}[/dim]"
        )
    )

    config = uvicorn.Config(
        app,
        host=DASHBOARD_HOST,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Main entry point."""
    args = parse_args()

    # Setup logging
    setup_logging(
        level=args.log_level,
        json_format=JSON_LOG_FORMAT,
        log_file=LOG_FILE,
    )

    logger.info("AI Swarm Orchestrator starting")

    # Dashboard only mode — skip9Router check
    if args.dashboard:
        await run_dashboard(args.dashboard_port)
        return

    # Validate9Router connectivity
    import urllib.request
    try:
        req = urllib.request.Request(f"{NINEROUTER_URL}/api/health")
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"9Router reachable at {NINEROUTER_URL}")
    except Exception as e:
        console.print(f"[red]Cannot reach 9Router at {NINEROUTER_URL}: {e}[/red]")
        console.print("[dim]Start 9Router first: 9router --port 20128 --no-browser --tray[/dim]")
        sys.exit(1)

    if not NINEROUTER_KEY:
        console.print("[yellow]⚠ NINEROUTER_KEY not set. API calls may fail.[/yellow]")

    # Initialize swarm
    coordinator = NineRouterCoordinator()
    swarm = SwarmManager(
        router_engine=coordinator,
        telemetry_cb=broadcast_status,
    )

    # Stats mode
    if args.stats:
        await show_stats(swarm)
        return

    # Direct execution mode
    if args.prompt:
        strategy = AggregationStrategy(args.strategy)
        console.print(
            f"[bold blue]Executing with {args.agents} agents...[/bold blue]"
        )

        with Live(Spinner("dots", text="Running swarm..."), console=console):
            result = await swarm.execute_swarm(
                args.prompt,
                agent_count=args.agents,
                aggregation_strategy=strategy,
            )

        display_result(result)
        return

    # Interactive mode
    await run_interactive(swarm)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
        sys.exit(0)
