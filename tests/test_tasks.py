import asyncio
import logging
import pytest

from utils.tasks import create_task


async def failing_coroutine():
    await asyncio.sleep(0)
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_create_task_logs_exception(caplog):
    caplog.set_level(logging.ERROR, logger="utils.tasks")
    task = create_task(failing_coroutine())
    while not task.done():
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert any("Unhandled task exception" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_create_task_logs_exception_with_taskgroup(caplog):
    caplog.set_level(logging.ERROR, logger="utils.tasks")
    with pytest.raises(ExceptionGroup):
        async with asyncio.TaskGroup() as tg:
            create_task(failing_coroutine(), task_group=tg)
    assert any("Unhandled task exception" in r.message for r in caplog.records)
