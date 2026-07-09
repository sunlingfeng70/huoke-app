from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import UserRecord

COMMENT_RE = re.compile(
    r"^###\s+(.+?)\s+—\s+❤️\s+(\d+)\s+—\s+🕐\s+(\d+)",
    re.MULTILINE,
)
REPLY_RE = re.compile(r"^>\s*\*\*(.+?)\*\*:\s*(.+)")
FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
TAG_RE = re.compile(r"(?<!\w)#([\u4e00-\u4fff\w/-]+)")


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    m = FM_RE.match(raw)
    if not m:
        return {}
    fm: dict[str, Any] = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def _extract_tags(raw: str) -> list[str]:
    return list(dict.fromkeys(TAG_RE.findall(raw)))


def _extract_comment_text(raw: str, start: int) -> str:
    lines = raw[start:].split("\n")
    text_parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") or stripped == "---" or stripped.startswith("> **"):
            if stripped.startswith("> **"):
                continue
            break
        if stripped:
            text_parts.append(stripped)
    return "\n".join(text_parts).strip()


def _extract_replies(raw: str, start: int) -> list[dict]:
    replies: list[dict] = []
    remaining = raw[start:]
    for m in REPLY_RE.finditer(remaining):
        if m.start() > 0 and remaining[m.start() - 1] != "\n":
            continue
        replies.append({
            "reply_to": m.group(1).strip(),
            "content": m.group(2).strip(),
        })
    return replies


def scan_vault(vault_path: str | Path, verbose: bool = False) -> list[UserRecord]:
    root = Path(vault_path).resolve()
    comment_root = root / "小红书评论"
    if not comment_root.exists():
        print(f"❌ 未找到目录: {comment_root}")
        return []

    users: list[UserRecord] = []
    seen: set[str] = set()

    for fp in sorted(comment_root.glob("**/*.md")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(root)
        if verbose:
            print(f"  扫描: {rel}")

        raw = fp.read_text(encoding="utf-8")
        fm = _parse_frontmatter(raw)
        src_keyword = fm.get("source_keyword", "")
        src_date = fm.get("date", "")
        note_title = fm.get("title", fp.stem)
        tags = _extract_tags(raw)

        for m in COMMENT_RE.finditer(raw):
            nickname = m.group(1).strip()
            likes = int(m.group(2))
            timestamp = int(m.group(3))
            comment_text = _extract_comment_text(raw, m.end())

            dedup_key = f"{nickname}|{comment_text[:40]}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            record = UserRecord(
                nickname=nickname,
                comment=comment_text,
                likes=likes,
                timestamp=timestamp,
                source_note=note_title,
                source_keyword=src_keyword,
                source_date=src_date,
                tags=tags,
            )
            record.replies = _extract_replies(raw, m.end())
            users.append(record)

    return users
