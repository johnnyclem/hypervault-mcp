"""Vercel serverless entrypoint for the HyperVault MCP server.

Exposes FastMCP's streamable-HTTP ASGI app at /mcp. Stateless mode + JSON
responses suit Vercel's serverless model: each invocation is self-contained,
with no long-lived SSE session held between requests.
"""

import os
import sys

# The package lives under ../src (src layout); make it importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hypervault_mcp.server import build_http_app

# /mcp with a key header, or /k/<key>/mcp for clients that can't set headers.
app = build_http_app(path="/mcp")
