import asyncio
import logging
import os
import signal
import socket
import sys
from pathlib import Path

import uvicorn

from server.server import app

__all__ = ["app"]


def _resolve_listen_port() -> int:
    """Use PORT env or 8000; if that address is in use, bind to an ephemeral port."""
    preferred = int(os.environ.get("PORT", "8000"))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", preferred))  # noqa: S104
    except OSError:
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 0))  # noqa: S104
        chosen: int = s.getsockname()[1]
        s.close()
        logging.warning(
            "Port %s is in use; listening on OS-assigned port %s",
            preferred,
            chosen,
        )
        return chosen
    else:
        port: int = s.getsockname()[1]
        s.close()
        return port


async def main() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(message)s",
        )
    module = Path(__file__).stem
    port = _resolve_listen_port()
    logging.info("Uvicorn listening on port %s", port)
    config = uvicorn.Config(
        f"{module}:app",
        host="0.0.0.0",  # noqa: S104
        port=port,
        access_log=True,
        workers=1,
    )
    server = uvicorn.Server(config)

    # Setup graceful shutdown
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def shutdown(sig: int) -> None:
        logging.info("Received stop signal %d. Initiating graceful shutdown...", sig)
        stop_event.set()
        server.handle_exit(sig=sig, frame=None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown, sig)

    # Start server in background
    server_task = asyncio.create_task(server.serve())

    # Wait for signal
    await stop_event.wait()

    # Now gracefully shutdown server
    logging.info("Shutdown complete.")

    # Optional: wait for server task to finish if needed
    server_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        logging.exception("Unexpected exception occurred")
        sys.exit(1)
