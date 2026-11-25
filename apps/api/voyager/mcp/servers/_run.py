"""Shared CLI for running one MCP server standalone over stdio or streamable HTTP."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer


def run_cli(build: Callable[[], MCPServer], default_port: int) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()
    server = build()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
