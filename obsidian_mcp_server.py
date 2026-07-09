#!/usr/bin/env python3
"""
obsidian_mcp_server.py — MCP server for Obsidian vault access.

Provides tools for AI assistants (Claude Desktop, Cursor, etc.) and the
Streamlit app to interact with the Obsidian vault via the Model Context Protocol.

Usage:
    # Run as stdio MCP server (for Claude Desktop / Cursor)
    python obsidian_mcp_server.py

    # Specify vault path
    python obsidian_mcp_server.py --vault /path/to/vault

Environment:
    OBSIDIAN_VAULT_PATH: path to vault (overrides --vault)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from obsidian_bridge import ObsidianVault

# ── MCP imports ──────────────────────────────────────────────────────

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool


# ── Server setup ─────────────────────────────────────────────────────

VAULT_PATH = Path(
    os.environ.get("OBSIDIAN_VAULT_PATH")
    or (sys.argv[sys.argv.index("--vault") + 1] if "--vault" in sys.argv else None)
    or (Path(__file__).parent / "vault")
).resolve()

server = Server("obsidian-vault")


# ── Tool definitions ─────────────────────────────────────────────────

def _get_vault() -> ObsidianVault:
    return ObsidianVault(str(VAULT_PATH))


_TOOL_LIST = [
    Tool(
        name="list_notes",
        description="列出仓库中所有笔记",
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob 匹配模式，默认 **/*.md",
                }
            },
        },
    ),
    Tool(
        name="read_note",
        description="读取指定笔记的完整内容（含 frontmatter）",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "笔记路径（相对仓库根目录），如 日记/2026-07-08.md",
                }
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="search_notes",
        description="按关键词搜索笔记（全文/标题/标签）",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "field": {
                    "type": "string",
                    "enum": ["content", "title", "tags"],
                    "description": "搜索范围：全文 / 标题 / 标签（默认全文）",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_tags",
        description="列出仓库中所有标签及其使用次数",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="get_note_links",
        description="提取笔记中的所有 [[ 内部链接 ]]",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "笔记路径（相对仓库根目录）",
                }
            },
            "required": ["path"],
        },
    ),
]


# ── Tool handlers ────────────────────────────────────────────────────


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return _TOOL_LIST


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    vault = _get_vault()
    try:
        if name == "list_notes":
            pattern = arguments.get("pattern", "**/*.md")
            notes = vault.list_notes(pattern)
            result = {
                "total": len(notes),
                "notes": [
                    {
                        "path": n["path"],
                        "title": n["title"],
                        "tags": n["tags"],
                        "size": n["size"],
                        "modified": n["modified"],
                    }
                    for n in notes
                ],
            }

        elif name == "read_note":
            path = arguments["path"]
            note = vault.read_note(path)
            if note is None:
                result = {"error": f"笔记不存在: {path}"}
            else:
                result = {
                    "path": note["path"],
                    "title": note["title"],
                    "content": note["content"],
                    "tags": note["tags"],
                    "wikilinks": note["wikilinks"],
                }

        elif name == "search_notes":
            query = arguments["query"]
            field = arguments.get("field", "content")
            results = vault.search_notes(query, field=field)
            result = {
                "total": len(results),
                "results": [
                    {
                        "path": r["path"],
                        "title": r["title"],
                        "snippet": r["snippet"],
                        "match_count": r["match_count"],
                    }
                    for r in results
                ],
            }

        elif name == "get_tags":
            tags = vault.get_tags()
            result = {
                "total": len(tags),
                "tags": tags,
            }

        elif name == "get_note_links":
            path = arguments["path"]
            links = vault.get_wikilinks(path)
            if links is None:
                result = {"error": f"笔记不存在: {path}"}
            else:
                result = {
                    "path": path,
                    "wikilinks": links,
                }

        else:
            result = {"error": f"未知工具: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


# ── Entry point ──────────────────────────────────────────────────────


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
