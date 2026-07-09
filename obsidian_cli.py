#!/usr/bin/env python3
"""
obsidian_cli.py — Obsidian 仓库交互命令行工具

用法:
    python obsidian_cli.py list                          # 列出所有笔记
    python obsidian_cli.py read <路径>                    # 读取笔记内容
    python obsidian_cli.py search <关键词>                 # 按内容搜索
    python obsidian_cli.py tags                           # 列出所有标签
    python obsidian_cli.py links <路径>                    # 提取笔记中的 [[ 链接 ]]
    python obsidian_cli.py write <路径> <内容>             # 写入/覆盖笔记

    python obsidian_cli.py --vault /path/to/vault list   # 指定仓库路径
    python obsidian_cli.py --json tags                    # JSON 格式输出
"""

from __future__ import annotations

import argparse
import json
import sys

from obsidian_bridge import ObsidianVault


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Obsidian 仓库交互工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s list                          # 列出所有笔记\n"
            "  %(prog)s read 日记/今天.md             # 读取笔记\n"
            "  %(prog)s search AI                     # 搜索内容\n"
            "  %(prog)s tags                          # 查看标签\n"
            "  %(prog)s links 项目/需求.md             # 查看内部链接\n"
            "  %(prog)s --vault /path/to/vault list   # 指定仓库路径\n"
        ),
    )
    parser.add_argument("--vault", default=None, help="Obsidian 仓库路径（默认 ./vault）")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出所有笔记")
    p_list.add_argument("-p", "--pattern", default="**/*.md", help="glob 匹配模式")

    p_read = sub.add_parser("read", help="读取笔记内容")
    p_read.add_argument("path", help="笔记路径（相对仓库根目录）")

    p_search = sub.add_parser("search", help="搜索笔记")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("-f", "--field", choices=["content", "title", "tags"], default="content")
    p_search.add_argument("-i", "--ignore-case", action="store_true", help="忽略大小写")

    sub.add_parser("tags", help="列出所有标签")

    p_links = sub.add_parser("links", help="提取笔记中的 [[ 内部链接 ]]")
    p_links.add_argument("path", help="笔记路径（相对仓库根目录）")

    p_write = sub.add_parser("write", help="写入/覆盖笔记")
    p_write.add_argument("path", help="笔记路径（相对仓库根目录）")
    p_write.add_argument("content", help="Markdown 内容（可含 frontmatter）")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    vault = ObsidianVault(args.vault)

    if args.command == "list":
        notes = vault.list_notes(args.pattern)
        if args.json:
            print(json.dumps(notes, ensure_ascii=False, indent=2))
        else:
            print(f"📚 共 {len(notes)} 篇笔记\n")
            for n in notes:
                tags = f"  {' '.join('#' + t for t in n['tags'][:5])}" if n["tags"] else ""
                print(f"  📄 {n['path']}{tags}")

    elif args.command == "read":
        note = vault.read_note(args.path)
        if note is None:
            print(f"❌ 笔记不存在: {args.path}")
            sys.exit(1)
        if args.json:
            print(json.dumps(note, ensure_ascii=False, indent=2))
        else:
            print(f"📄 {note['path']}")
            print(f"  标题: {note['title']}")
            if note["tags"]:
                print(f"  标签: {' '.join('#' + t for t in note['tags'])}")
            if note["wikilinks"]:
                print(f"  链接: {', '.join(note['wikilinks'])}")
            print(f"  大小: {note['size']} bytes")
            print(f"  ── 内容 ──")
            print(note["content"][:3000])
            if len(note["content"]) > 3000:
                print("...（内容过长已截断）")

    elif args.command == "search":
        results = vault.search_notes(args.query, args.field, not args.ignore_case)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"🔍 搜索「{args.query}」共 {len(results)} 条结果\n")
            for r in results:
                print(f"  📄 {r['path']} — 匹配 {r['match_count']} 处")
                print(f"     {r['snippet'][:100]}")
                print()

    elif args.command == "tags":
        tags = vault.get_tags()
        if args.json:
            print(json.dumps(tags, ensure_ascii=False, indent=2))
        else:
            print(f"🏷️ 共 {len(tags)} 个标签\n")
            for t in tags:
                print(f"  #{t['tag']}  ({t['count']} 篇笔记)")

    elif args.command == "links":
        links = vault.get_wikilinks(args.path)
        if links is None:
            print(f"❌ 笔记不存在: {args.path}")
            sys.exit(1)
        if args.json:
            print(json.dumps(links, ensure_ascii=False, indent=2))
        else:
            print(f"🔗 {args.path} 中的内部链接:\n")
            for l in links:
                print(f"  [[{l}]]")

    elif args.command == "write":
        result = vault.write_note(args.path, args.content)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"✅ 已保存: {result['path']} ({result['size']} bytes)")


if __name__ == "__main__":
    main()
