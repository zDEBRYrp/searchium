"""
MCP (Model Context Protocol) Server for Searchium

Exposes file search, indexing, and chat as MCP tools
for use by AI agents (Claude, GPT, etc.).
"""

import json
import os
import sys
from typing import Any, Dict, List

MCP_PORT = int(os.getenv("MCP_PORT", "8275"))
API_BASE = os.getenv("SEARCHIUM_API", "http://127.0.0.1:8274")


def get_tools() -> List[Dict[str, Any]]:
    """Return MCP tool definitions"""
    return [
        {
            "name": "search_files",
            "description": "Search indexed files by text query. Supports fuzzy matching and semantic search.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                    "semantic": {"type": "boolean", "description": "Use semantic/vector search", "default": False},
                },
                "required": ["query"],
            },
        },
        {
            "name": "find_similar",
            "description": "Find files similar to a given file path using semantic embeddings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path of the file to find similar to"},
                    "limit": {"type": "integer", "description": "Max results (default 5)", "default": 5},
                },
                "required": ["file_path"],
            },
        },
        {
            "name": "chat_with_files",
            "description": "Ask a question about your indexed files. Uses RAG to find relevant context.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Question to ask"},
                },
                "required": ["message"],
            },
        },
        {
            "name": "get_index_status",
            "description": "Get current indexing status: files discovered, indexed, queue size.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "start_indexing",
            "description": "Start the file indexer for all configured watch paths.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "stop_indexing",
            "description": "Stop the file indexer.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_recent_files",
            "description": "Get recently indexed files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of files (default 10)", "default": 10},
                },
            },
        },
        {
            "name": "add_watch_path",
            "description": "Add a directory to watch for file changes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to watch"},
                    "include_subdirs": {"type": "boolean", "description": "Include subdirectories", "default": True},
                },
                "required": ["path"],
            },
        },
    ]


def call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute an MCP tool by calling the Searchium API"""
    import httpx

    with httpx.Client(timeout=30) as client:
        if name == "search_files":
            resp = client.post(f"{API_BASE}/api/v1/search", json={
                "query": arguments["query"],
                "per_page": arguments.get("limit", 10),
                "semantic": arguments.get("semantic", False),
            })
            return resp.json()

        elif name == "find_similar":
            resp = client.post(f"{API_BASE}/api/v1/chat/similar", json={
                "file_path": arguments["file_path"],
                "limit": arguments.get("limit", 5),
            })
            return resp.json()

        elif name == "chat_with_files":
            resp = client.post(f"{API_BASE}/api/v1/chat", json={
                "message": arguments["message"],
            })
            return resp.json()

        elif name == "get_index_status":
            resp = client.get(f"{API_BASE}/api/v1/crawler/status")
            return resp.json()

        elif name == "start_indexing":
            resp = client.post(f"{API_BASE}/api/v1/crawler/start")
            return resp.json()

        elif name == "stop_indexing":
            resp = client.post(f"{API_BASE}/api/v1/crawler/stop")
            return resp.json()

        elif name == "get_recent_files":
            resp = client.get(f"{API_BASE}/api/v1/stats/recent-files", params={
                "limit": arguments.get("limit", 10),
            })
            return resp.json()

        elif name == "add_watch_path":
            resp = client.post(f"{API_BASE}/api/v1/config/watch-paths", json={
                "path": arguments["path"],
                "include_subdirectories": arguments.get("include_subdirs", True),
            })
            return resp.json()

        else:
            return {"error": f"Unknown tool: {name}"}


def run_mcp_stdio():
    """Run MCP server over stdio (for Claude Desktop, etc.)"""
    tools = get_tools()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "searchium", "version": "1.0.0"},
                },
            }
        elif method == "tools/list":
            response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = call_tool(tool_name, arguments)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                    },
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True,
                    },
                }
        elif method == "notifications/initialized":
            continue
        else:
            response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}

        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        run_mcp_stdio()
    else:
        print(f"Searchium MCP Server v1.0.0")
        print(f"API: {API_BASE}")
        print(f"Tools: {len(get_tools())}")
        print("Usage: python mcp_server.py --stdio")
