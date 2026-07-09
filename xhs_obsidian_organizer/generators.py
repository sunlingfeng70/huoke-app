from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Contact, UserRecord, _LEVEL_NAMES

OUTPUT_DIR = "小红书获客/索引"
CONTACT_DIR = "小红书联系人"


def _aggregate_contacts(users: list[UserRecord]) -> list[Contact]:
    grouped: dict[str, Contact] = {}
    for r in users:
        if r.nickname not in grouped:
            grouped[r.nickname] = Contact(r.nickname)
        grouped[r.nickname].add_record(r)
    return sorted(grouped.values(), key=lambda c: c.score, reverse=True)


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

    lines += ["", "---", "", "## 等级分布", ""]
    for lv in ("A", "B", "C", "D"):
        group = [c for c in contacts if c.level == lv]
        if group:
            top = ", ".join(c.nickname for c in group[:5])
            lines.append(f"- **{lv}类** ({len(group)} 人): {top}{'...' if len(group) > 5 else ''}")
    return "\n".join(lines)


def _generate_contact_note(contact: Contact, vault_root: Path) -> str | None:
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
        f"total_comments: {contact.total_comments}",
        f"total_likes: {contact.total_likes}",
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


def build_index_generators(users: list[UserRecord]) -> list[tuple[str, str]]:
    return [
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


def write_contact_notes(contacts: list[Contact], vault_root: Path, verbose: bool = False) -> list[str]:
    generated: list[str] = []
    contact_dir = vault_root / CONTACT_DIR

    index_content = _generate_contact_index(contacts)
    index_fp = contact_dir / "_索引.md"
    index_fp.parent.mkdir(parents=True, exist_ok=True)
    index_fp.write_text(index_content, encoding="utf-8")
    generated.append(str(index_fp.relative_to(vault_root)))
    if verbose:
        print(f"  ✅ 生成: {index_fp.relative_to(vault_root)}")

    for c in contacts:
        if c.level in ("A", "B"):
            rel = _generate_contact_note(c, vault_root)
            if rel:
                generated.append(rel)
                if verbose:
                    print(f"  ✅ 生成: {rel}")

    return generated
