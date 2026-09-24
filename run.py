"""Start the API with settings from .env - works the same on Windows, macOS, Linux.

    python run.py

On Windows, Playwright needs a Proactor event loop to launch the browser
subprocess; some uvicorn setups (notably with --reload) end up on a Selector
loop and fail with NotImplementedError. This sets the right policy first and
never uses --reload.
"""
import asyncio
import sys

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False, loop="asyncio")
