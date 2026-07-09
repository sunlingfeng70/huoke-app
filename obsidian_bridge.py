#!/usr/bin/env python3
"""
obsidian_bridge.py — Obsidian 仓库交互模块

通过 LLM 可调用的函数接口，实现对 Obsidian 仓库中文档的读取、搜索和管理。

用法（CLI）:
    python obsidian_bridge.py list                          # 列出所有笔记
    python obsidian_bridge.py read <路径>                    # 读取笔记内容
    python obsidian_bridge.py search <关键词>                 # 按内容搜索
    python obsidian_bridge.py tags                           # 列出所有标签
    python obsidian_bridge.py links <路径>                    # 提取笔记中的 [[ 链接 ]]

用法（Python）:
    from obsidian_bridge import ObsidianVault
    vault = ObsidianVault("vault")
    notes = vault.list_notes()
    note = vault.read_note("日记/2026-07-08.md")
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ── 常量 ──────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
_DEFAULT_VAULT = _HERE / "vault"  # 默认仓库目录，可在初始化时覆盖

_YAML_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_TAG_RE = re.compile(r"(?<!\w)#([\u4e00-\u9fff\w/-]+)")


# ── 核心类 ────────────────────────────────────────────────────────────


class ObsidianVault:
    """Obsidian 仓库操作接口"""

    def __init__(self, vault_path: str | Path | None = None):
        self.root = Path(vault_path or _DEFAULT_VAULT).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)

    # ── 查询 ──────────────────────────────────────────────────────

    def list_notes(self, pattern: str = "**/*.md") -> list[dict[str, Any]]:
        """列出仓库中所有 Markdown 笔记

        参数:
            pattern: glob 匹配模式，默认递归所有 .md 文件

        返回:
            [{path, title, tags, created, modified, size}]
        """
        notes: list[dict[str, Any]] = []
        for fp in sorted(self.root.glob(pattern)):
            if not fp.is_file():
                continue
            rel = fp.relative_to(self.root)
            stat = fp.stat()
            frontmatter = self._parse_frontmatter(fp)
            notes.append({
                "path": str(rel),
                "title": frontmatter.get("title") or fp.stem,
                "tags": self._extract_tags_from_content(fp, frontmatter),
                "created": datetime.fromtimestamp(stat.st_birthtime).isoformat() if hasattr(stat, "st_birthtime") else "",
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size,
            })
        return notes

    def read_note(self, path: str) -> dict[str, Any] | None:
        """读取指定笔记的内容

        参数:
            path: 笔记路径（相对仓库根目录），如 "日记/2026-07-08.md"

        返回:
            {path, title, content, frontmatter, tags, wikilinks} 或 None
        """
        fp = (self.root / path).resolve()
        if not fp.exists() or not fp.is_file():
            return None
        try:
            rel = fp.relative_to(self.root)
        except ValueError:
            return None  # 路径在仓库外

        raw = fp.read_text(encoding="utf-8")
        frontmatter, content = self._split_frontmatter(raw)
        return {
            "path": str(rel),
            "title": frontmatter.get("title") or fp.stem,
            "content": content.strip(),
            "frontmatter": frontmatter,
            "tags": self._extract_tags(content, frontmatter),
            "wikilinks": self._extract_wikilinks(content),
            "modified": datetime.fromtimestamp(fp.stat().st_mtime).isoformat(),
            "size": fp.stat().st_size,
        }

    def write_note(self, path: str, content: str) -> dict[str, Any]:
        """写入/覆盖笔记

        参数:
            path:    笔记路径（相对仓库根目录），如 "小红书分析/竞品.md"
            content: Markdown 正文（可含 YAML frontmatter）

        返回:
            {path, title, size}
        """
        fp = (self.root / path).resolve()
        try:
            fp.relative_to(self.root)
        except ValueError:
            raise ValueError(f"路径在仓库外: {path}")
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        frontmatter, _ = self._split_frontmatter(content)
        return {
            "path": str(fp.relative_to(self.root)),
            "title": frontmatter.get("title") or fp.stem,
            "size": fp.stat().st_size,
        }

    def search_notes(
        self,
        query: str,
        field: str = "content",
        case_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """按关键词搜索笔记

        参数:
            query:        搜索关键词
            field:        搜索范围 — "content" 全文 / "title" 标题 / "tags" 标签
            case_sensitive: 是否区分大小写

        返回:
            [{path, title, snippet, match_count}]
        """
        results: list[dict[str, Any]] = []
        q = query if case_sensitive else query.lower()

        for fp in self.root.glob("**/*.md"):
            if not fp.is_file():
                continue
            try:
                rel = fp.relative_to(self.root)
            except ValueError:
                continue

            raw = fp.read_text(encoding="utf-8")
            frontmatter, content = self._split_frontmatter(raw)

            if field == "title":
                title = frontmatter.get("title") or fp.stem
                check = title if case_sensitive else title.lower()
                if q in check:
                    results.append({
                        "path": str(rel),
                        "title": title,
                        "snippet": f"标题匹配: {title}",
                        "match_count": 1,
                    })
                continue

            if field == "tags":
                tags = self._extract_tags(content, frontmatter)
                matched = [t for t in tags if q in (t if case_sensitive else t.lower())]
                if matched:
                    results.append({
                        "path": str(rel),
                        "title": frontmatter.get("title") or fp.stem,
                        "snippet": f"标签匹配: {', '.join(matched)}",
                        "match_count": len(matched),
                    })
                continue

            # 全文搜索
            check = raw if case_sensitive else raw.lower()
            count = check.count(q)
            if count > 0:
                # 截取首次匹配附近片段
                idx = check.find(q)
                start = max(0, idx - 40)
                end = min(len(raw), idx + len(q) + 60)
                snippet = raw[start:end].replace("\n", " ").strip()
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."
                results.append({
                    "path": str(rel),
                    "title": frontmatter.get("title") or fp.stem,
                    "snippet": snippet,
                    "match_count": count,
                })

        return sorted(results, key=lambda r: r["match_count"], reverse=True)

    def get_tags(self) -> list[dict[str, Any]]:
        """列出仓库中所有标签及其使用次数

        返回:
            [{tag, count, notes: [path, ...]}]
        """
        tag_map: dict[str, dict[str, Any]] = {}
        for fp in self.root.glob("**/*.md"):
            if not fp.is_file():
                continue
            try:
                rel = str(fp.relative_to(self.root))
            except ValueError:
                continue
            raw = fp.read_text(encoding="utf-8")
            frontmatter, content = self._split_frontmatter(raw)
            tags = self._extract_tags(content, frontmatter)
            for tag in tags:
                if tag not in tag_map:
                    tag_map[tag] = {"tag": tag, "count": 0, "notes": []}
                tag_map[tag]["count"] += 1
                if rel not in tag_map[tag]["notes"]:
                    tag_map[tag]["notes"].append(rel)
        return sorted(tag_map.values(), key=lambda r: r["count"], reverse=True)

    def get_wikilinks(self, path: str) -> list[str] | None:
        """提取笔记中的所有 [[ 内部链接 ]]

        参数:
            path: 笔记路径（相对仓库根目录）

        返回:
            [链接目标标题, ...] 或 None
        """
        note = self.read_note(path)
        if note is None:
            return None
        return note["wikilinks"]

    # ── 内部方法 ──────────────────────────────────────────────────

    def _parse_frontmatter(self, fp: Path) -> dict[str, Any]:
        """解析笔记的 YAML frontmatter"""
        raw = fp.read_text(encoding="utf-8")
        fm, _ = self._split_frontmatter(raw)
        return fm

    def _split_frontmatter(self, raw: str) -> tuple[dict[str, Any], str]:
        """将原始内容拆分为 frontmatter dict 和正文"""
        m = _YAML_FRONT_MATTER_RE.match(raw)
        if not m:
            return {}, raw
        fm: dict[str, Any] = {}
        for line in m.group(1).split("\n"):
            line = line.strip()
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                fm[k] = v
        return fm, raw[m.end():]

    def _extract_tags(self, content: str, frontmatter: dict[str, Any]) -> list[str]:
        """从正文和 frontmatter 中提取标签"""
        tags: list[str] = []
        # 正文行内标签 #tag
        tags.extend(_TAG_RE.findall(content))
        # frontmatter 中的 tags 字段
        for key in ("tags", "tag"):
            val = frontmatter.get(key, "")
            if isinstance(val, str):
                for t in val.replace("[", "").replace("]", "").split(","):
                    t = t.strip().strip('"').strip("'")
                    if t:
                        tags.append(t)
        # 去重
        seen: set[str] = set()
        return [t for t in tags if not (t in seen or seen.add(t))]

    def _extract_tags_from_content(self, fp: Path, frontmatter: dict[str, Any]) -> list[str]:
        """从文件中提取标签（用于 list_notes 避免重复读文件）"""
        raw = fp.read_text(encoding="utf-8")
        _, content = self._split_frontmatter(raw)
        return self._extract_tags(content, frontmatter)

    def _extract_wikilinks(self, content: str) -> list[str]:
        """提取 [[ 内部链接 ]] 的目标标题"""
        return [m for m in _WIKILINK_RE.findall(content) if m]


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    import argparse

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
