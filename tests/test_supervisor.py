import asyncio
import sys

import pytest
from fastapi import HTTPException

from deploy import supervisor


@pytest.mark.parametrize("action", ["startup", "reset"])
async def test_failed_start_terminates_owned_child(monkeypatch, action):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(60)", start_new_session=True,
    )

    async def failed_spawn():
        supervisor.child = process
        raise TimeoutError("readiness failed")

    monkeypatch.setattr(supervisor, "child", None)
    monkeypatch.setattr(supervisor, "spawn", failed_spawn)
    try:
        if action == "startup":
            with pytest.raises(TimeoutError):
                async with supervisor.lifespan(supervisor.app):
                    pytest.fail("An unready child must not finish startup")
        else:
            with pytest.raises(HTTPException) as error:
                await supervisor.reset()
            assert error.value.status_code == 503
        assert process.returncode is not None
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
