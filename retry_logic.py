"""
Retry logic with exponential backoff for the AI Swarm Orchestrator.
Handles transient failures and rate limits gracefully.
"""
import asyncio
import random
from typing import Callable, Any, Optional, Type
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class RetryExhaustedException(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, last_error: Exception, attempts: int):
        self.last_error = last_error
        self.attempts = attempts
        super().__init__(
            f"Failed after {attempts} attempts. Last error: {last_error}"
        )


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (Exception,),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay with exponential backoff and optional jitter."""
    delay = min(
        config.base_delay * (config.exponential_base ** attempt),
        config.max_delay,
    )

    if config.jitter:
        delay = delay * (0.5 + random.random())

    return delay


async def retry_async(
    func: Callable,
    config: Optional[RetryConfig] = None,
    *args,
    **kwargs,
) -> Any:
    """
    Execute an async function with retry logic.

    Args:
        func: Async function to execute
        config: Retry configuration
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result of func execution

    Raises:
        RetryExhaustedException: If all retries fail
    """
    if config is None:
        config = RetryConfig()

    last_error = None

    for attempt in range(config.max_retries):
        try:
            return await func(*args, **kwargs)
        except config.retryable_exceptions as e:
            last_error = e
            logger.warning(
                f"Attempt {attempt + 1}/{config.max_retries} failed: {e}"
            )

            if attempt < config.max_retries - 1:
                delay = calculate_delay(attempt, config)
                logger.info(f"Retrying in {delay:.2f} seconds...")
                await asyncio.sleep(delay)

    raise RetryExhaustedException(last_error, config.max_retries)


def with_retry(
    config: Optional[RetryConfig] = None,
):
    """
    Decorator for adding retry logic to async functions.

    Usage:
        @with_retry(RetryConfig(max_retries=3))
        async def my_function():
            # function body
            pass
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(func, config, *args, **kwargs)

        wrapper.retry_config = config
        return wrapper

    return decorator


class CircuitBreaker:
    """Circuit breaker pattern for preventing cascade failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = "closed"  # closed = normal, open = blocking, half-open = testing

    @property
    def state(self) -> str:
        """Get current circuit state."""
        if self._state == "open" and self._last_failure_time:
            import time
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "half-open"
        return self._state

    def record_success(self):
        """Record a successful call."""
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self):
        """Record a failed call."""
        import time
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                f"Circuit breaker '{self.name}' opened after "
                f"{self._failure_count} failures"
            )

    def is_available(self) -> bool:
        """Check if the circuit allows requests."""
        state = self.state
        return state in ("closed", "half-open")

    def reset(self):
        """Manually reset the circuit breaker."""
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = None


async def call_with_circuit_breaker(
    func: Callable,
    circuit_breaker: CircuitBreaker,
    *args,
    **kwargs,
) -> Any:
    """
    Execute a function with circuit breaker protection.

    Args:
        func: Async function to execute
        circuit_breaker: Circuit breaker instance
        *args: Positional arguments
        **kwargs: Keyword arguments

    Returns:
        Result of func execution

    Raises:
        RuntimeError: If circuit is open
    """
    if not circuit_breaker.is_available():
        raise RuntimeError(
            f"Circuit breaker '{circuit_breaker.name}' is open. "
            f"Service unavailable."
        )

    try:
        result = await func(*args, **kwargs)
        circuit_breaker.record_success()
        return result
    except Exception as e:
        circuit_breaker.record_failure()
        raise
