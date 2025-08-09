import asyncio
import logging
from typing import Awaitable, Optional

logger = logging.getLogger(__name__)


def create_task(coro: Awaitable, *, task_group: Optional[asyncio.TaskGroup] = None,
                 logger: logging.Logger = logger) -> asyncio.Task:
    """Create an asyncio task and log exceptions once finished.

    If *task_group* is provided (Python ≥3.11), the task is created via the
    group, allowing collective cancellation and error propagation.
    """
    if task_group is not None:
        task = task_group.create_task(coro)
    else:
        task = asyncio.create_task(coro)

    def _log_result(task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            logger.error("Unhandled task exception", exc_info=exc)

    task.add_done_callback(_log_result)
    return task
