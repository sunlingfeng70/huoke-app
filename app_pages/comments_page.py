from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import streamlit as st

from xhs_new_search import fetch_comments


def render() -> None:
    st.header("3️⃣ 获取笔记评论")

    if not st.session_state.search_results or not st.session_state.selected_indices:
        st.warning("请先在「搜索笔记」步骤选择要获取评论的笔记")
        if st.button("← 返回搜索步骤"):
            st.session_state.page = "search"
            st.rerun()
        return

    results = st.session_state.search_results
    selected = st.session_state.selected_indices

    st.subheader(f"将获取 {len(selected)} 篇笔记的评论")

    for idx in selected:
        item = results[idx - 1]
        has_comments = idx in st.session_state.comments_data
        status = "已完成" if has_comments else "待获取"
        st.markdown(f"- **#{idx}** {item['title'][:50]} — {status}")

    st.markdown("---")

    col_go, col_reset = st.columns([3, 1])
    with col_go:
        fetch_all = st.button("开始获取评论", type="primary", use_container_width=True)
    with col_reset:
        if st.session_state.comments_data:
            if st.button("重新获取", use_container_width=True):
                st.session_state.comments_data = {}
                st.rerun()

    if fetch_all:
        st.session_state.comments_data = {}
        progress_bar = st.progress(0, text="准备获取评论...")
        status_text = st.empty()

        total = len(selected)
        all_comments_data: dict[int, dict] = {}
        total_comment_count = 0

        for i, idx in enumerate(selected):
            item = results[idx - 1]
            title = item["title"]
            note_id = item["id"]
            xsec_token = (
                item["url"].split("xsec_token=")[-1]
                if "xsec_token=" in item["url"]
                else ""
            )

            status_text.info(f"[{i + 1}/{total}] 正在获取: {title[:40]}...")
            progress_bar.progress((i) / total, text=f"[{i + 1}/{total}] {title[:40]}")

            try:
                comments = fetch_comments(
                    note_id, xsec_token, st.session_state.cookie_str,
                    proxy=st.session_state.proxy or None,
                )
            except Exception as e:
                st.warning(f"   #{idx} 获取失败: {e}")
                comments = None

            if comments is None:
                st.warning(f"   #{idx} 《{title[:30]}》获取失败")
                continue

            count = len(comments)
            total_comment_count += count

            safe_keyword = "".join(
                c if c.isalnum() or c in " _-" else "_"
                for c in st.session_state.keyword
            )[:20]
            note_file = (
                f"{date.today().isoformat()}_{safe_keyword}"
                f"_comments_{idx}.json"
            )
            with open(note_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "keyword": st.session_state.keyword,
                        "note_id": note_id,
                        "note_title": title,
                        "total_comments": count,
                        "comments": comments,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            st.success(f"   #{idx} 《{title[:30]}》— {count} 条评论")

            all_comments_data[idx] = {
                "title": title,
                "total_comments": count,
                "file": note_file,
                "comments": comments,
            }

            time.sleep(0.3)

        st.session_state.comments_data = all_comments_data

        progress_bar.progress(1.0, text=f"完成！共 {total_comment_count} 条评论")
        status_text.empty()

        if all_comments_data:
            st.success(
                f"全部完成！共获取 {total_comment_count} 条评论，"
                f"涉及 {len(all_comments_data)} 篇笔记"
            )
        st.rerun()

    if not st.session_state.comments_data:
        return

    st.markdown("---")
    st.subheader("评论结果")

    for idx in sorted(st.session_state.comments_data.keys()):
        data = st.session_state.comments_data[idx]
        item = results[idx - 1]
        title = data["title"]
        count = data["total_comments"]
        comments = data["comments"]
        note_file = data["file"]

        with st.expander(f"#{idx} {title[:50]} — 💬 {count} 条评论", expanded=False):
            st.markdown(f"**标题**: {title}")
            st.markdown(f"**链接**: {item['url']}")
            st.markdown(f"**文件**: `{note_file}`")

            if count == 0:
                st.info("暂无评论")
            else:
                for c in comments:
                    with st.container(border=True):
                        st.markdown(
                            f"**{c.get('用户昵称', '匿名')}** "
                            f"— ❤️ {c.get('点赞数量', '0')} "
                            f"— 🕐 {c.get('发布时间', '')}"
                        )
                        st.markdown(c.get("评论内容", ""))

                        sub_comments = c.get("子评论", [])
                        if sub_comments:
                            with st.expander(f"💬 {len(sub_comments)} 条回复", expanded=False):
                                for s in sub_comments:
                                    st.markdown(
                                        f"> **{s.get('用户昵称', '匿名')}**: "
                                        f"{s.get('评论内容', '')}"
                                    )

    st.markdown("---")
    st.subheader("导出结果")

    col_export1, col_export2 = st.columns(2)

    with col_export1:
        merged = {
            "keyword": st.session_state.keyword,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": {},
        }
        total_all = 0
        for idx, data in st.session_state.comments_data.items():
            merged["notes"][str(idx)] = {
                "title": data["title"],
                "total_comments": data["total_comments"],
                "comments": data["comments"],
            }
            total_all += data["total_comments"]
        merged["total_comments_all"] = total_all

        merged_json = json.dumps(merged, ensure_ascii=False, indent=2)
        safe_kw = "".join(c if c.isalnum() or c in "_-" else "_" for c in st.session_state.keyword)[:20]
        merged_filename = f"{date.today().isoformat()}_{safe_kw}_all_comments.json"

        st.download_button(
            label=f"下载合并 JSON ({total_all} 条评论)",
            data=merged_json,
            file_name=merged_filename,
            mime="application/json",
            use_container_width=True,
        )

    with col_export2:
        if st.button("返回搜索", use_container_width=True):
            st.session_state.page = "search"
            st.rerun()

    obs_path_save = st.session_state.obsidian_path
    obs_dir = Path(obs_path_save)
    if obs_dir.exists():
        st.markdown("---")
        obs_col1, obs_col2 = st.columns([3, 1])
        with obs_col1:
            if st.button("保存到 Obsidian", type="primary", use_container_width=True):
                safe_kw = "".join(
                    c if c.isalnum() or c in " _-" else "_"
                    for c in st.session_state.keyword
                )[:20]
                target_dir = obs_dir / "小红书评论" / f"{date.today().isoformat()}_{safe_kw}"
                target_dir.mkdir(parents=True, exist_ok=True)
                saved_count = 0

                for idx, data in st.session_state.comments_data.items():
                    item = results[idx - 1]
                    title = data["title"]
                    url = item.get("url", "")
                    comments = data["comments"]
                    count = data["total_comments"]

                    safe_title = "".join(
                        c if c.isalnum() or c in " _-（）()" else "_"
                        for c in title
                    )[:40]

                    md_lines = [
                        "---",
                        f'title: "💬 {title}"',
                        f"source_url: {url}",
                        f"source_keyword: {st.session_state.keyword}",
                        f"comment_count: {count}",
                        f"date: {date.today().isoformat()}",
                        "tags: [小红书, 评论]",
                        "---",
                        "",
                        f"# 💬 评论: {title}",
                        "",
                        f"**来源**: [{url}]({url})",
                        f"**关键词**: {st.session_state.keyword}",
                        f"**评论总数**: {count}",
                        "",
                        "---",
                        "",
                    ]

                    for c in comments:
                        nickname = c.get("用户昵称", "匿名")
                        likes = c.get("点赞数量", "0")
                        time_str = c.get("发布时间", "")
                        content = c.get("评论内容", "")
                        md_lines.append(f"### {nickname} — ❤️ {likes} — 🕐 {time_str}")
                        md_lines.append("")
                        md_lines.append(content)
                        md_lines.append("")

                        sub_comments = c.get("子评论", [])
                        if sub_comments:
                            for s in sub_comments:
                                s_nick = s.get("用户昵称", "匿名")
                                s_content = s.get("评论内容", "")
                                md_lines.append(f"> **{s_nick}**: {s_content}")
                            md_lines.append("")

                        md_lines.append("---")
                        md_lines.append("")

                    note_path = target_dir / f"{idx:02d}_{safe_title}.md"
                    note_path.write_text("\n".join(md_lines), encoding="utf-8")
                    saved_count += 1

                index_lines = [
                    "---",
                    f'title: "评论汇总: {st.session_state.keyword}"',
                    f"date: {date.today().isoformat()}",
                    "tags: [小红书, 评论汇总]",
                    "---",
                    "",
                    f"# 📊 评论汇总: {st.session_state.keyword}",
                    "",
                ]
                total_all_comments = sum(
                    d["total_comments"] for d in st.session_state.comments_data.values()
                )
                index_lines.append(f"- **搜索关键词**: {st.session_state.keyword}")
                index_lines.append(f"- **笔记数**: {saved_count}")
                index_lines.append(f"- **评论总数**: {total_all_comments}")
                index_lines.append(f"- **导出时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                index_lines.append("")
                index_lines.append("## 笔记列表")
                index_lines.append("")

                for idx, data in st.session_state.comments_data.items():
                    item = results[idx - 1]
                    safe_title = "".join(
                        c if c.isalnum() or c in " _-（）()" else "_"
                        for c in data["title"]
                    )[:40]
                    index_lines.append(
                        f"- [[{idx:02d}_{safe_title}]] — "
                        f"{data['title'][:50]} "
                        f"({data['total_comments']} 条评论)"
                    )

                index_path = target_dir / "index.md"
                index_path.write_text("\n".join(index_lines), encoding="utf-8")

                st.success(
                    f"已保存 {saved_count} 篇笔记到 Obsidian\n\n"
                    f"📁 `{target_dir.relative_to(obs_dir)}`"
                )
        with obs_col2:
            vault_rel = Path(st.session_state.obsidian_path)
            vault_name = vault_rel.name if vault_rel.exists() else "vault"
            st.caption(f"目标: {vault_name}")
