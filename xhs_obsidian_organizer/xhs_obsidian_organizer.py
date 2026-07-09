#!/usr/bin/env python3
"""
xhs_obsidian_organizer.py — Obsidian 获客文档整理归类工具

扫描 vault 中小红书评论笔记，提取用户数据，按等级/标签/地域/时间归类，
生成索引页和销售行动总表。

用法:
    uv run python xhs-obsidian-organizer/xhs_obsidian_organizer.py <vault_path>
    uv run python xhs-obsidian-organizer/xhs_obsidian_organizer.py ./vault --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 常量 ──────────────────────────────────────────────────────────────

COMMENT_DIR = "小红书评论"        # 源数据目录
OUTPUT_DIR = "小红书获客/索引"    # 索引页输出目录
CONTACT_DIR = "小红书联系人"      # 联系人笔记输出目录

# 评论行正则：### 昵称 — ❤️ 点赞数 — 🕐 时间戳
COMMENT_RE = re.compile(
    r"^###\s+(.+?)\s+—\s+❤️\s+(\d+)\s+—\s+🕐\s+(\d+)",
    re.MULTILINE,
)

# 回复行正则：> **回复者**: 内容
REPLY_RE = re.compile(r"^>\s*\*\*(.+?)\*\*:\s*(.+)")

# YAML frontmatter 正则
FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)

# 标签正则
TAG_RE = re.compile(r"(?<!\w)#([\u4e00-\u4fff\w/-]+)")


# ── 数据模型 ──────────────────────────────────────────────────────────


class UserRecord:
    """一个用户记录"""

    def __init__(
        self,
        nickname: str,
        comment: str,
        likes: int,
        timestamp: int,
        source_note: str,
        source_keyword: str,
        source_date: str,
        tags: list[str],
    ):
        self.nickname = nickname
        self.comment = comment
        self.likes = likes
        self.timestamp = timestamp
        self.source_note = source_note      # 来源笔记标题
        self.source_keyword = source_keyword  # 搜索关键词
        self.source_date = source_date        # 笔记日期
        self.tags = tags
        self.replies: list[dict] = []        # 回复列表

        # 推导属性
        self.comment_length = len(comment)
        self.has_question = any(kw in comment for kw in ("?", "？", "怎么", "如何", "求", "有没"))
        self.has_request = any(kw in comment for kw in ("求资料", "求教程", "求分享", "求推荐"))
        self.is_meaningful = self.comment_length > 30 and not self.has_request

    @property
    def level(self) -> str:
        """客户等级：
        A — 高质量（长评论 / 有观点 / 互动多）
        B — 有需求（中长度评论，含意图）
        C — 低意向（短评论，仅求资料/打招呼）
        D — 待培育（极小互动，仅表情/单词）
        """
        if self.likes >= 5 or self.is_meaningful:
            return "A"
        if self.comment_length > 20 or (self.has_question and not self.has_request):
            return "B"
        if self.has_request or self.comment_length > 5:
            return "C"
        return "D"

    @property
    def date_str(self) -> str:
        ts = self.timestamp / 1000 if self.timestamp > 1e11 else self.timestamp
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    @property
    def location(self) -> str:
        # 目前评论格式不含 IP 属地，留空待后续扩展
        return "未知"

    def to_dict(self) -> dict:
        return {
            "昵称": self.nickname,
            "评论": self.comment[:80],
            "评论长度": self.comment_length,
            "点赞": self.likes,
            "等级": self.level,
            "日期": self.date_str,
            "地域": self.location,
            "来源笔记": self.source_note,
            "来源关键词": self.source_keyword,
            "互动": len(self.replies),
        }


class Contact:
    """按昵称聚合后的联系人"""

    def __init__(self, nickname: str):
        self.nickname = nickname
        self.records: list[UserRecord] = []

    def add_record(self, r: UserRecord):
        self.records.append(r)

    @property
    def keywords(self) -> list[str]:
        return list(dict.fromkeys(r.source_keyword for r in self.records if r.source_keyword))

    @property
    def total_comments(self) -> int:
        return len(self.records)

    @property
    def total_likes(self) -> int:
        return sum(r.likes for r in self.records)

    @property
    def avg_length(self) -> float:
        return sum(r.comment_length for r in self.records) / max(len(self.records), 1)

    @property
    def first_date(self) -> str:
        return min(r.date_str for r in self.records)

    @property
    def last_date(self) -> str:
        return max(r.date_str for r in self.records)

    @property
    def signal_keywords(self) -> list[str]:
        signals: list[str] = []
        for r in self.records:
            if r.has_request:
                signals.append("有索取行为")
            if r.is_meaningful:
                signals.append("有质量评论")
            if r.likes >= 3:
                signals.append("高赞")
        return list(dict.fromkeys(signals))

    @property
    def score(self) -> int:
        """加权评分 0-100"""
        if not self.records:
            return 0

        avg_len = self.avg_length
        unique_keywords = len(self.keywords)
        total_likes = self.total_likes
        has_reply = any(len(r.replies) > 0 for r in self.records)
        days_since = (datetime.now() - datetime.strptime(self.last_date, "%Y-%m-%d")).days

        # 1. 评论质量分 (15%)
        len_score = min(100, avg_len * 2)

        # 2. 互动分 (15%)
        like_score = min(100, total_likes * 8)

        # 3. 跨关键词分 (25%) — 同一人在多个关键词下出现 → 高意向
        keyword_score = min(100, unique_keywords * 25)

        # 4. 需求信号分 (20%)
        signal_score = 0
        if any(r.is_meaningful for r in self.records):
            signal_score += 40
        if any(r.has_request for r in self.records):
            signal_score += 25
        if total_likes >= 5:
            signal_score += 20
        if has_reply:
            signal_score += 15

        # 5. 回复互动分 (15%)
        reply_score = 30 if has_reply else 10

        # 6. 时效分 (10%)
        recency_score = max(0, 100 - days_since)

        score = (
            len_score * 0.15
            + like_score * 0.15
            + keyword_score * 0.25
            + signal_score * 0.20
            + reply_score * 0.15
            + recency_score * 0.10
        )
        return round(min(100, max(0, score)))

    @property
    def level(self) -> str:
        s = self.score
        if s >= 65:
            return "A"
        if s >= 45:
            return "B"
        if s >= 20:
            return "C"
        return "D"

    @property
    def best_comment(self) -> str:
        best = max(self.records, key=lambda r: (r.likes, r.comment_length))
        return best.comment[:120]

    def comment_summary(self) -> list[dict]:
        return [
            {"keyword": r.source_keyword, "note": r.source_note,
             "comment": r.comment[:80], "likes": r.likes, "date": r.date_str,
             "replies": len(r.replies)}
            for r in sorted(self.records, key=lambda x: x.timestamp, reverse=True)
        ]


# ── 解析 ──────────────────────────────────────────────────────────────


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


def scan_vault(vault_path: str | Path, verbose: bool = False) -> list[UserRecord]:
    """扫描 vault 中所有评论笔记，提取用户记录"""
    root = Path(vault_path).resolve()
    comment_root = root / COMMENT_DIR
    if not comment_root.exists():
        print(f"❌ 未找到目录: {comment_root}")
        return []

    users: list[UserRecord] = []
    seen: set[str] = set()  # 去重 (nickname + comment)

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

            # 提取回复
            replies = _extract_replies(raw, m.end())
            record.replies = replies

            users.append(record)

    return users


def _extract_comment_text(raw: str, start: int) -> str:
    """提取评论正文（从 ### 行后到下一个 --- 或 ### 或文件尾）"""
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
    """提取评论下的回复"""
    replies: list[dict] = []
    remaining = raw[start:]
    for m in REPLY_RE.finditer(remaining):
        if m.start() > 0 and remaining[m.start() - 1] != '\n':
            continue
        replies.append({
            "reply_to": m.group(1).strip(),
            "content": m.group(2).strip(),
        })
    return replies


# ── 归类与生成 ────────────────────────────────────────────────────────


def _generate_overview(users: list[UserRecord]) -> str:
    total = len(users)
    level_counts = defaultdict(int)
    tag_counter = Counter[str]()
    location_counter = Counter[str]()
    dates = sorted(set(u.date_str for u in users))

    for u in users:
        level_counts[u.level] += 1
        for t in u.tags:
            tag_counter[t] += 1
        location_counter[u.location] += 1

    top_tags = tag_counter.most_common(15)
    top_locations = location_counter.most_common(10)
    a_users = [u for u in users if u.level == "A"]
    a_preview = a_users[:10]

    lines = [
        "---",
        'title: "📊 获客总览"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        "tags: [获客总览, 索引]",
        "---",
        "",
        "# 📊 获客总览",
        "",
        f"**更新日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 数据概览",
        "",
        f"- **总评论用户数**: {total}",
        f"- **时间跨度**: {dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'}",
        f"- **A 类高意向**: {level_counts.get('A', 0)}",
        f"- **B 类中意向**: {level_counts.get('B', 0)}",
        f"- **C 类低意向**: {level_counts.get('C', 0)}",
        f"- **D 类待培育**: {level_counts.get('D', 0)}",
        "",
        "---",
        "",
        "## 热门标签",
        "",
    ]
    for tag, count in top_tags:
        lines.append(f"- #{tag} ({count} 人)")
    lines += [
        "",
        "---",
        "",
        "## 地域分布",
        "",
    ]
    for loc, count in top_locations:
        lines.append(f"- {loc}: {count} 人")
    lines += [
        "",
        "---",
        "",
        "## A 类客户预览",
        "",
    ]
    for u in a_preview:
        lines.append(f"- [[{u.nickname}]] — {u.comment[:50]}")
    if len(a_users) > 10:
        lines.append(f"\n... 共 {len(a_users)} 位 A 类客户")
    lines += [
        "",
        "---",
        "",
        "## 日报列表",
        "",
    ]
    for d in reversed(sorted(dates)):
        day_users = [u for u in users if u.date_str == d]
        a_count = sum(1 for u in day_users if u.level == "A")
        lines.append(f"- {d} ({len(day_users)} 人, A类 {a_count} 人)")
    return "\n".join(lines)


def _generate_level_page(level: str, label: str, emoji: str, users: list[UserRecord], intro: str) -> str:
    target = [u for u in users if u.level == level]
    target.sort(key=lambda u: (-u.likes, -u.comment_length))

    lines = [
        "---",
        f'title: "{emoji}{label}"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        f"tags: [{label}, {level}类, 索引]",
        "---",
        "",
        f"# {emoji}{label}",
        "",
        intro,
        "",
        f"共 {len(target)} 人",
        "",
        "---",
        "",
    ]
    for i, u in enumerate(target, 1):
        lines.append(f"### {i}. {u.nickname}")
        lines.append(f"- **等级**: {u.level}")
        lines.append(f"- **点赞**: {u.likes}")
        lines.append(f"- **日期**: {u.date_str}")
        lines.append(f"- **来源**: [[{u.source_note}]]")
        lines.append(f"- **评论**: {u.comment[:100]}")
        if level == "A":
            greeting = f"您好，看到您在{u.source_note}下留言，想进一步和您聊聊相关需求～"
            lines.append(f"- **建议开场**: {greeting}")
        elif level == "B":
            greeting = f"您好，看到您对{u.source_keyword}感兴趣，有什么可以帮您的吗？"
            lines.append(f"- **建议开场**: {greeting}")
        lines.append("")
    return "\n".join(lines)


def _generate_tag_index(users: list[UserRecord]) -> str:
    tag_users: dict[str, list[UserRecord]] = defaultdict(list)
    for u in users:
        for t in u.tags:
            tag_users[t].append(u)

    lines = [
        "---",
        'title: "🏷️ 按标签归类"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        "tags: [按标签归类, 索引]",
        "---",
        "",
        "# 🏷️ 按标签归类",
        "",
        "按需求标签分组，快速定位目标用户。",
        "",
        "---",
        "",
    ]
    for tag in sorted(tag_users.keys()):
        group = sorted(tag_users[tag], key=lambda u: u.level)
        lines.append(f"## #{tag} ({len(group)} 人)")
        for u in group:
            lines.append(f"- {u.nickname} — {u.level}级 — {u.comment[:40]}")
        lines.append("")
    return "\n".join(lines)


def _generate_location_index(users: list[UserRecord]) -> str:
    loc_users: dict[str, list[UserRecord]] = defaultdict(list)
    for u in users:
        loc_users[u.location].append(u)

    lines = [
        "---",
        'title: "📍 按地域归类"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        "tags: [按地域归类, 索引]",
        "---",
        "",
        "# 📍 按地域归类",
        "",
        "按用户 IP 属地分组。",
        "",
        "---",
        "",
    ]
    for loc in sorted(loc_users.keys()):
        group = sorted(loc_users[loc], key=lambda u: u.level)
        lines.append(f"## {loc} ({len(group)} 人)")
        for u in group:
            lines.append(f"- {u.nickname} — {u.level}级 — {u.source_keyword}")
        lines.append("")
    return "\n".join(lines)


def _generate_timeline(users: list[UserRecord]) -> str:
    date_users: dict[str, list[UserRecord]] = defaultdict(list)
    for u in users:
        date_users[u.date_str].append(u)

    lines = [
        "---",
        'title: "📅 时间线"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        "tags: [时间线, 索引]",
        "---",
        "",
        "# 📅 时间线",
        "",
        "按日期排列，追踪获客趋势。",
        "",
        "---",
        "",
    ]
    for date in sorted(date_users.keys(), reverse=True):
        group = date_users[date]
        a_users = [u for u in group if u.level == "A"]
        a_mark = " 🔴" if a_users else ""
        lines.append(f"## {date} ({len(group)} 人){a_mark}")
        for u in sorted(group, key=lambda x: x.level):
            a_tag = " ⭐" if u.level == "A" else ""
            lines.append(f"- {u.nickname} — {u.level}级{a_tag} — {u.comment[:50]}")
        lines.append("")
    return "\n".join(lines)


def _generate_action_table(users: list[UserRecord]) -> str:
    targets = [u for u in users if u.level in ("A", "B")]
    targets.sort(key=lambda u: (0 if u.level == "A" else 1, -u.likes, -u.comment_length))

    lines = [
        "---",
        'title: "🎯 销售行动总表"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        "tags: [销售行动, A类, B类, 索引]",
        "---",
        "",
        "# 🎯 销售行动总表",
        "",
        "A+B 类合并，按优先级排序，直接作为销售每日工作清单。",
        "",
        f"共 {len(targets)} 条待跟进",
        "",
        "---",
        "",
        "| 优先级 | 昵称 | 等级 | 点赞 | 来源笔记 | 建议开场白 |",
        "|--------|------|------|------|----------|------------|",
    ]
    for i, u in enumerate(targets, 1):
        if u.level == "A":
            greeting = f"您好，看到您在{u.source_note}下留言，想进一步和您聊聊相关需求～"
        else:
            greeting = f"您好，看到您对{u.source_keyword}感兴趣，有什么可以帮您的吗？"
        lines.append(f"| {i}. | {u.nickname} | {u.level} | {u.likes} | {u.source_note} | {greeting} |")
    return "\n".join(lines)


# ── 联系人聚合 ────────────────────────────────────────────────────────


def _aggregate_contacts(users: list[UserRecord]) -> list[Contact]:
    """按昵称将 UserRecord 聚合为 Contact"""
    grouped: dict[str, Contact] = {}
    for r in users:
        if r.nickname not in grouped:
            grouped[r.nickname] = Contact(r.nickname)
        grouped[r.nickname].add_record(r)
    return sorted(grouped.values(), key=lambda c: c.score, reverse=True)


def _generate_contact_index(contacts: list[Contact]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "---",
        'title: "📇 联系人总览"',
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        "tags: [联系人, 总览, 索引]",
        "---",
        "",
        "# 📇 联系人总览",
        "",
        f"**更新日期**: {now}",
        "",
        "按加权评分降序排列。评分基于：评论质量、点赞数、跨关键词覆盖、需求信号、回复互动、时效。",
        "",
        "---",
        "",
        "| # | 昵称 | 评分 | 等级 | 评论数 | 关键词数 | 总点赞 | 最近互动 | 信号 |",
        "|---|------|------|------|--------|----------|--------|----------|------|",
    ]
    for i, c in enumerate(contacts, 1):
        signals = " ".join(c.signal_keywords[:2]) if c.signal_keywords else "-"
        lines.append(
            f"| {i}. | [[{c.nickname}]] | {c.score} | {c.level} |"
            f" {c.total_comments} | {len(c.keywords)} | {c.total_likes} |"
            f" {c.last_date} | {signals} |"
        )

    # 按等级汇总
    lines += ["", "---", "", "## 等级分布", ""]
    for lv in ("A", "B", "C", "D"):
        group = [c for c in contacts if c.level == lv]
        if group:
            top = ", ".join(c.nickname for c in group[:5])
            lines.append(f"- **{lv}类** ({len(group)} 人): {top}{'...' if len(group) > 5 else ''}")
    return "\n".join(lines)


def _generate_contact_note(contact: Contact, vault_root: Path) -> str | None:
    """为 A/B 类联系人生成独立笔记，返回相对路径"""
    if not contact.records:
        return None

    summaries = contact.comment_summary()
    signals = ", ".join(contact.signal_keywords) if contact.signal_keywords else "无明确信号"
    keywords = ", ".join(contact.keywords)
    greeting = (
        f"您好，看到您在{contact.keywords[0] if contact.keywords else '小红书'}相关笔记下留言，"
        f"想进一步和您聊聊相关需求～"
    )

    content = [
        "---",
        f'nickname: "{contact.nickname}"',
        f"score: {contact.score}",
        f'level: "{contact.level}"',
        f'status: "待联系"',
        f'total_comments: {contact.total_comments}',
        f'total_likes: {contact.total_likes}',
        f'keywords: [{", ".join(f"\"{k}\"" for k in contact.keywords)}]',
        f'signals: [{", ".join(f"\"{s}\"" for s in contact.signal_keywords)}]',
        f'first_interaction: "{contact.first_date}"',
        f'last_interaction: "{contact.last_date}"',
        "---",
        "",
        f"# 📇 {contact.nickname}",
        "",
        "## 概览",
        "",
        f"- **意向评分**: {contact.score}/100",
        f"- **客户等级**: {contact.level}",
        f"- **跟进状态**: 待联系",
        f"- **互动次数**: {contact.total_comments} 条评论",
        f"- **涉及关键词**: {keywords}",
        f"- **总点赞**: {contact.total_likes}",
        f"- **首次互动**: {contact.first_date}",
        f"- **最近互动**: {contact.last_date}",
        f"- **需求信号**: {signals}",
        "",
        "## 建议开场白",
        "",
        f"> {greeting}",
        "",
        "## 互动记录",
        "",
    ]
    for s in summaries:
        kw = s["keyword"] or "(无关键词)"
        content.append(f"### {s['date']} — {kw}")
        content.append(f"- **来源**: [[{s['note']}]]")
        content.append(f"- **评论**: {s['comment']}")
        content.append(f"- **点赞**: {s['likes']}  |  **回复**: {s['replies']} 条")
        content.append("")

    level_dir = f"{contact.level}-{_LEVEL_NAMES[contact.level]}"
    rel_path = f"{CONTACT_DIR}/{level_dir}/{contact.nickname}.md"
    full_path = vault_root / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text("\n".join(content), encoding="utf-8")
    return rel_path


_LEVEL_NAMES = {"A": "高意向", "B": "中意向", "C": "低意向", "D": "暂不跟进"}


# ── 主流程 ────────────────────────────────────────────────────────────


def run_organizer(vault_path: str | Path, verbose: bool = False) -> dict[str, Any]:
    """执行完整整理流程，返回生成的文件列表"""
    root = Path(vault_path).resolve()
    out_dir = root / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"📂 仓库路径: {root}")
        print(f"📥 扫描源目录: {COMMENT_DIR}/")
        print(f"📤 输出目录: {OUTPUT_DIR}/")
        print()

    # 扫描
    users = scan_vault(root, verbose=verbose)
    if not users:
        print("⚠️ 未找到用户数据")
        return {"total_users": 0, "generated_files": []}

    if verbose:
        levels = defaultdict(int)
        for u in users:
            levels[u.level] += 1
        print(f"\n📊 用户统计: 共 {len(users)} 人")
        for lv in "ABCD":
            print(f"   {lv}类: {levels.get(lv, 0)}")
        print()

    # 生成索引页
    generators = [
        ("📊获客总览.md", _generate_overview(users)),
        ("🟢A类高意向客户.md", _generate_level_page("A", "A类高意向客户", "🟢", users,
            "高意向客户 — 评论质量高、点赞多、有明确需求。优先联系。")),
        ("🟡B类中意向客户.md", _generate_level_page("B", "B类中意向客户", "🟡", users,
            "中意向客户 — 有需求意向，但互动深度不足。需要培育跟进。")),
        ("🔵C类低意向客户.md", _generate_level_page("C", "C类低意向客户", "🔵", users,
            "低意向客户 — 互动较浅，仍在内容培育池中。")),
        ("🏷️按标签归类.md", _generate_tag_index(users)),
        ("📍按地域归类.md", _generate_location_index(users)),
        ("📅时间线.md", _generate_timeline(users)),
        ("🎯销售行动总表.md", _generate_action_table(users)),
    ]

    generated: list[str] = []
    for filename, content in generators:
        fp = out_dir / filename
        fp.write_text(content, encoding="utf-8")
        generated.append(str(fp.relative_to(root)))
        if verbose:
            print(f"  ✅ 生成: {fp.relative_to(root)}")

    # 联系人聚合
    contacts = _aggregate_contacts(users)
    contact_dir = root / CONTACT_DIR

    # 联系人总览索引
    index_content = _generate_contact_index(contacts)
    index_fp = contact_dir / "_索引.md"
    index_fp.parent.mkdir(parents=True, exist_ok=True)
    index_fp.write_text(index_content, encoding="utf-8")
    generated.append(str(index_fp.relative_to(root)))
    if verbose:
        print(f"  ✅ 生成: {index_fp.relative_to(root)}")

    # A/B 类联系人独立笔记
    contact_notes = 0
    for c in contacts:
        if c.level in ("A", "B"):
            rel = _generate_contact_note(c, root)
            if rel:
                contact_notes += 1
                generated.append(rel)
                if verbose:
                    print(f"  ✅ 生成: {rel}")

    if verbose:
        print(f"\n👤 联系人: 共 {len(contacts)} 人 (A+B 笔记 {contact_notes} 篇)")

    return {
        "total_users": len(users),
        "generated_files": generated,
        "output_dir": str(out_dir.relative_to(root)),
    }


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Obsidian 获客文档整理归类工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("vault", help="Obsidian 仓库路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出结果")
    args = parser.parse_args()

    result = run_organizer(args.vault, verbose=args.verbose)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n✅ 整理完成")
        print(f"   用户数: {result['total_users']}")
        print(f"   生成文件: {len(result['generated_files'])} 篇")
        for f in result["generated_files"]:
            print(f"     - {f}")


if __name__ == "__main__":
    main()
