import os
import time

from mcp.server import MCPServer

server = MCPServer("stub")


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return text


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("intentional failure")


@server.tool()
def sleep(seconds: float) -> str:
    """Sleep for the given number of seconds."""
    time.sleep(seconds)
    return "done"


@server.tool()
def die() -> str:
    """Kill the server process."""
    os._exit(1)


if __name__ == "__main__":
    server.run()
