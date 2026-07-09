"""
obsidian_bridge.py — Obsidian 仓库交互模块

通过 LLM 可调用的函数接口，实现对 Obsidian 仓库中文档的读取、搜索和管理。

用法（Python）:
    from obsidian_bridge import ObsidianVault
    vault = ObsidianVault("vault")
    notes = vault.list_notes()
    note = vault.read_note("日记/2026-07-08.md")

CLI 用法见 obsidian_cli.py。
"""

from __future__ import annotations

import re
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



