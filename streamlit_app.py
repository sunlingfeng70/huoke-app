#!/usr/bin/env python3
"""
huoke-app Streamlit 界面

三步工作流：
  1. 获取/粘贴小红书 Cookie
  2. 搜索笔记并选择
  3. 获取选中笔记的评论

运行：
    uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

# 确保项目根在 sys.path 中，以便直接 import 同目录模块
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from xhs_new_search import (
    build_note_url,
    cookie_str_to_dict,
    fetch_comments,
    print_results,
    search_notes,
)

# ── 页面配置 ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="🍠 小红书工具",
    page_icon="🍠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session State 初始化 ─────────────────────────────────────────────

_DEFAULT = {
    "cookie_str": "",
    "proxy": "",
    "keyword": "",
    "search_sort": "general",
    "search_note_type": 0,
    "search_number": 10,
    "search_results": None,  # list[dict] | None
    "selected_indices": [],  # 勾选的笔记序号（1-based）
    "comments_data": {},     # {note_index: {title, comments, file}}
    "page": "cookie",        # 当前激活的 tab
}

for k, v in _DEFAULT.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── 辅助函数 ─────────────────────────────────────────────────────────


def _cookie_short_display(cookie_str: str, max_len: int = 80) -> str:
    """截断显示 Cookie 字符串"""
    if len(cookie_str) <= max_len:
        return cookie_str
    return cookie_str[:max_len] + "..."


def _validate_cookie(cookie_str: str) -> list[str]:
    """检查 Cookie 中是否包含必要字段，返回缺失字段列表"""
    d = cookie_str_to_dict(cookie_str)
    required = ["a1", "web_session", "id_token"]
    return [k for k in required if k not in d]


def _launch_cookie_grabber_direct(headless: bool = False, timeout_val: int = 180) -> str | None:
    """直接调用 xhs_cookie_grabber.grab_cookie() 获取 Cookie

    与 subprocess 方案相比，本方式：
    - 避免 capture_output 阻塞浏览器 GUI
    - 可直接捕获 grab_cookie 返回值（不依赖文件读写）
    - 支持实时进度反馈
    """
    try:
        from xhs_cookie_grabber import grab_cookie
    except ImportError as e:
        st.error(f"无法导入 xhs_cookie_grabber: {e}")
        return None

    import threading

    result: dict[str, Any] = {"cookie": None, "error": None}

    def _run() -> None:
        try:
            cookie = grab_cookie(headless=headless, timeout=timeout_val)
            result["cookie"] = cookie
        except SystemExit:
            result["error"] = "⏰ 超时或用户中断"
        except Exception as e:
            result["error"] = f"❌ {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    status = st.empty()
    progress = st.progress(0, text="启动浏览器...")

    start = time.time()
    while thread.is_alive():
        elapsed = int(time.time() - start)
        if elapsed < timeout_val:
            status.info(
                f"⏳ 浏览器已打开，请用手机小红书 App 扫码登录... ({elapsed}s)"
            )
        else:
            status.warning("⏰ 即将超时...")
        progress.progress(min(elapsed / (timeout_val + 30), 0.95))
        time.sleep(1)

    progress.progress(1.0)

    if result["error"]:
        status.error(result["error"])
        return None
    if result["cookie"]:
        status.success("✅ Cookie 获取成功！")
        time.sleep(0.5)
        status.empty()
        progress.empty()
        return result["cookie"]

    status.error("❌ 未获取到 Cookie")
    return None


# ── 侧边栏 ───────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🍠 小红书工具")
    st.markdown("---")

    # Cookie 状态指示
    if st.session_state.cookie_str:
        missing = _validate_cookie(st.session_state.cookie_str)
        if missing:
            st.warning(f"⚠️ Cookie 缺失字段: {', '.join(missing)}")
        else:
            st.success("✅ Cookie 已就绪")
    else:
        st.info("⏳ 请先在「Cookie」步骤获取 Cookie")

    st.markdown("---")
    st.markdown("**🌐 网络代理**")
    proxy_input = st.text_input(
        "HTTP 代理地址",
        value=st.session_state.proxy,
        placeholder="http://127.0.0.1:7890",
        help="DNS 解析失败（curl: (28) Resolving timed out）时，配置 HTTP 代理可解决网络问题。留空=直连。",
    )
    if proxy_input != st.session_state.proxy:
        st.session_state.proxy = proxy_input
        st.rerun()

    st.markdown("---")
    st.markdown("**工作流**")
    steps = {
        "cookie": "1️⃣ Cookie 获取",
        "search": "2️⃣ 搜索笔记",
        "comments": "3️⃣ 获取评论",
    }
    for step_id, label in steps.items():
        disabled = False
        if step_id == "search" and not st.session_state.cookie_str:
            disabled = True
        if step_id == "comments" and not st.session_state.search_results:
            disabled = True

        if st.button(
            label,
            key=f"nav_{step_id}",
            use_container_width=True,
            disabled=disabled,
            type="primary" if st.session_state.page == step_id else "secondary",
        ):
            st.session_state.page = step_id
            st.rerun()

    st.markdown("---")
    st.caption(f"项目路径: {_HERE}")


# ── 页面标题 ─────────────────────────────────────────────────────────

st.title("🍠 小红书笔记搜索 & 评论获取工具")

# ═══════════════════════════════════════════════════════════════════════
# 步骤 1: Cookie 获取
# ═══════════════════════════════════════════════════════════════════════

if st.session_state.page == "cookie":
    st.header("1️⃣ Cookie 获取")
    st.markdown(
        """
        小红书 API 需要登录态 Cookie 才能访问。你有两种方式获取：
        - **方式 A**: 手动运行脚本获取 → 粘贴 Cookie 字符串
        - **方式 B**: 直接在浏览器中启动获取流程
        """
    )

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("方式 A: 粘贴 Cookie")
        cookie_input = st.text_area(
            "Cookie 字符串",
            value=st.session_state.cookie_str,
            height=150,
            placeholder="a1=xxx; web_session=yyy; id_token=zzz; ...",
            help="从 xhs_cookie_grabber.py 获取的 Cookie 字符串",
        )
        if st.button("✅ 保存 Cookie", key="save_cookie", type="primary"):
            cookie_input = cookie_input.strip()
            if not cookie_input:
                st.warning("请输入 Cookie 字符串")
            else:
                missing = _validate_cookie(cookie_input)
                if missing:
                    st.warning(f"⚠️ Cookie 缺少必要字段: {', '.join(missing)}，搜索可能失败")
                st.session_state.cookie_str = cookie_input
                st.success(f"✅ Cookie 已保存（{len(cookie_input)} 字符）")
                st.rerun()

    with col_b:
        st.subheader("方式 B: 浏览器获取")
        st.markdown("点击下方按钮，自动启动浏览器打开小红书登录页。")
        st.markdown("请用手机小红书 App 扫描二维码完成登录。")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            launch = st.button("🚀 启动浏览器", key="launch_browser", type="primary")
        with col_b2:
            launch_headless = st.button("🖥️ 无头模式", key="launch_headless")

        if launch:
            cookie = _launch_cookie_grabber_direct(headless=False)
            if cookie:
                st.session_state.cookie_str = cookie
                st.rerun()

        if launch_headless:
            cookie = _launch_cookie_grabber_direct(headless=True)
            if cookie:
                st.session_state.cookie_str = cookie
                st.rerun()

        st.info(
            "💡 浏览器获取失败？请手动运行:\n\n"
            "```\n"
            f"uv run python xhs_cookie_grabber.py\n"
            "```\n\n"
            "然后将输出的 Cookie 粘贴到「方式 A」中。"
        )

    # 显示当前 Cookie 状态
    if st.session_state.cookie_str:
        st.markdown("---")
        st.subheader("📋 当前 Cookie")
        missing = _validate_cookie(st.session_state.cookie_str)
        if missing:
            st.warning(f"⚠️ 缺失字段: {', '.join(missing)}")
        else:
            st.success("✅ 关键字段齐全")
        st.code(_cookie_short_display(st.session_state.cookie_str, 120))

        if st.button("➡️ 下一步：搜索笔记", key="goto_search", type="primary"):
            st.session_state.page = "search"
            st.rerun()

# ═══════════════════════════════════════════════════════════════════════
# 步骤 2: 搜索笔记
# ═══════════════════════════════════════════════════════════════════════

elif st.session_state.page == "search":
    st.header("2️⃣ 搜索小红书笔记")

    if not st.session_state.cookie_str:
        st.warning("⚠️ 请先在「Cookie 获取」步骤设置 Cookie")
        if st.button("← 返回 Cookie 步骤"):
            st.session_state.page = "cookie"
            st.rerun()
    else:
        # 搜索参数
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                keyword = st.text_input(
                    "🔍 搜索关键词",
                    value=st.session_state.keyword,
                    placeholder="输入要搜索的热词...",
                )
            with col2:
                sort_option = st.selectbox(
                    "排序方式",
                    options=["general", "time_descending", "popularity_descending"],
                    format_func=lambda x: {
                        "general": "综合排序",
                        "time_descending": "最新发布",
                        "popularity_descending": "最热排序",
                    }[x],
                    index=["general", "time_descending", "popularity_descending"].index(
                        st.session_state.search_sort
                    ),
                )
            with col3:
                number = st.number_input(
                    "返回数量",
                    min_value=1,
                    max_value=100,
                    value=st.session_state.search_number,
                )

            col4, col5 = st.columns([1, 3])
            with col4:
                note_type = st.selectbox(
                    "笔记类型",
                    options=[0, 1, 2],
                    format_func=lambda x: {0: "全部", 1: "图文", 2: "视频"}[x],
                    index=[0, 1, 2].index(st.session_state.search_note_type),
                )
            with col5:
                st.markdown("")  # 占位
                st.markdown("")  # 占位
                search_clicked = st.button(
                    "🔍 搜索", type="primary", use_container_width=True
                )

        if search_clicked:
            if not keyword.strip():
                st.warning("请输入搜索关键词")
            else:
                st.session_state.keyword = keyword
                st.session_state.search_sort = sort_option
                st.session_state.search_note_type = note_type
                st.session_state.search_number = number
                st.session_state.selected_indices = []
                st.session_state.comments_data = {}

                with st.spinner(f"正在搜索「{keyword}」..."):
                    try:
                        results = search_notes(
                            keyword=keyword,
                            cookie_str=st.session_state.cookie_str,
                            page_size=number,
                            sort=sort_option,
                            note_type=note_type,
                            proxy=st.session_state.proxy or None,
                        )
                    except Exception as e:
                        st.error(f"搜索失败: {e}")
                        results = None

                if results is None:
                    st.error(
                        "❌ 搜索失败。可能原因：\n"
                        "1. Cookie 已过期，请重新获取\n"
                        "2. DNS 解析失败（域名 edith.xiaohongshu.com 无法解析），\n"
                        "   请检查网络连接或切换 DNS（如 8.8.8.8 / 114.114.114.114）\n"
                        "3. 网络连接问题（防火墙 / 代理 / VPN）\n"
                        "4. a1 签名参数异常"
                    )
                elif not results:
                    st.warning(f"未找到「{keyword}」相关笔记")
                else:
                    st.session_state.search_results = results
                    st.success(f"✅ 找到 {len(results)} 条笔记")
                    st.rerun()

        # 显示搜索结果
        if st.session_state.search_results:
            results = st.session_state.search_results
            st.markdown("---")
            st.subheader(f"📋 搜索结果（共 {len(results)} 条）")

            # 全选/取消
            col_sel1, col_sel2, col_sel3 = st.columns([1, 1, 4])
            with col_sel1:
                if st.button("✅ 全选", use_container_width=True):
                    st.session_state.selected_indices = list(range(1, len(results) + 1))
                    st.rerun()
            with col_sel2:
                if st.button("❌ 取消全选", use_container_width=True):
                    st.session_state.selected_indices = []
                    st.rerun()
            with col_sel3:
                if st.session_state.selected_indices:
                    st.info(
                        f"已选择 {len(st.session_state.selected_indices)} 篇笔记"
                    )

            # 结果表格
            data_rows = []
            for i, item in enumerate(results, 1):
                note_type_icon = "🎬" if item["note_type"] == "video" else "📷"
                stats = item["stats"]
                data_rows.append({
                    "选择": i in st.session_state.selected_indices,
                    "#": i,
                    "类型": note_type_icon,
                    "标题": item["title"][:60],
                    "作者": item["user"]["nickname"],
                    "用户ID": item["user"]["user_id"],
                    "❤️": stats["liked_count"],
                    "⭐": stats["collected_count"],
                    "💬": stats["comment_count"],
                })

            import pandas as pd

            df = pd.DataFrame(data_rows)
            edited_df = st.data_editor(
                df,
                column_config={
                    "选择": st.column_config.CheckboxColumn(
                        "选择",
                        help="勾选以获取评论",
                        default=False,
                    ),
                    "#": st.column_config.NumberColumn("#", width=40),
                    "类型": st.column_config.TextColumn("类型", width=50),
                    "标题": st.column_config.TextColumn("标题", width=350),
                    "作者": st.column_config.TextColumn("作者", width=120),
                    "用户ID": st.column_config.TextColumn("用户ID", width=160),
                    "❤️": st.column_config.NumberColumn("❤️", width=60),
                    "⭐": st.column_config.NumberColumn("⭐", width=60),
                    "💬": st.column_config.NumberColumn("💬", width=60),
                },
                hide_index=True,
                use_container_width=True,
                disabled=["#", "类型", "标题", "作者", "用户ID", "❤️", "⭐", "💬"],
                key="search_results_editor",
            )

            # 同步勾选状态
            new_selected = [
                int(row["#"])
                for _, row in edited_df.iterrows()
                if row["选择"]
            ]
            if new_selected != st.session_state.selected_indices:
                st.session_state.selected_indices = new_selected
                st.rerun()

            # 显示选中笔记详情
            if st.session_state.selected_indices:
                st.markdown("---")
                st.subheader(f"📌 已选 {len(st.session_state.selected_indices)} 篇笔记")

                for idx in st.session_state.selected_indices:
                    item = results[idx - 1]
                    with st.expander(
                        f"#{idx} {item['title'][:50]}", expanded=False
                    ):
                        st.markdown(f"**标题**: {item['title']}")
                        st.markdown(f"**作者**: {item['user']['nickname']}")
                        st.markdown(f"**类型**: {'🎬 视频' if item['note_type'] == 'video' else '📷 图文'}")
                        stats = item["stats"]
                        st.markdown(
                            f"❤️ {stats['liked_count']}　"
                            f"⭐ {stats['collected_count']}　"
                            f"💬 {stats['comment_count']}　"
                            f"🔄 {stats['shared_count']}"
                        )
                        if item["url"]:
                            st.markdown(f"**链接**: {item['url']}")

                st.markdown("---")
                if st.button(
                    "➡️ 下一步：获取评论",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state.page = "comments"
                    st.rerun()
            else:
                st.info("👆 在上方表格中勾选要获取评论的笔记")

# ═══════════════════════════════════════════════════════════════════════
# 步骤 3: 获取评论
# ═══════════════════════════════════════════════════════════════════════

elif st.session_state.page == "comments":
    st.header("3️⃣ 获取笔记评论")

    if not st.session_state.search_results or not st.session_state.selected_indices:
        st.warning("⚠️ 请先在「搜索笔记」步骤选择要获取评论的笔记")
        if st.button("← 返回搜索步骤"):
            st.session_state.page = "search"
            st.rerun()
    else:
        results = st.session_state.search_results
        selected = st.session_state.selected_indices

        st.subheader(f"📌 将获取 {len(selected)} 篇笔记的评论")

        # 显示选中的笔记列表
        for idx in selected:
            item = results[idx - 1]
            has_comments = idx in st.session_state.comments_data
            status = "✅ 已完成" if has_comments else "⏳ 待获取"
            st.markdown(f"- **#{idx}** {item['title'][:50]} — {status}")

        st.markdown("---")

        # 获取评论按钮
        col_go, col_reset = st.columns([3, 1])
        with col_go:
            fetch_all = st.button(
                "🚀 开始获取评论",
                type="primary",
                use_container_width=True,
            )
        with col_reset:
            if st.session_state.comments_data:
                if st.button("🔄 重新获取", use_container_width=True):
                    st.session_state.comments_data = {}
                    st.rerun()

        if fetch_all:
            st.session_state.comments_data = {}
            progress_bar = st.progress(0, text="准备获取评论...")
            status_text = st.empty()

            total = len(selected)
            all_comments_data: dict[int, dict[str, Any]] = {}
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

                status_text.info(
                    f"[{i + 1}/{total}] 正在获取: {title[:40]}..."
                )
                progress_bar.progress(
                    (i) / total,
                    text=f"[{i + 1}/{total}] {title[:40]}",
                )

                try:
                    comments = fetch_comments(
                        note_id, xsec_token, st.session_state.cookie_str,
                        proxy=st.session_state.proxy or None,
                    )
                except Exception as e:
                    st.warning(f"   ❌ #{idx} 获取失败: {e}")
                    comments = None

                if comments is None:
                    st.warning(f"   ❌ #{idx} 《{title[:30]}》获取失败")
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

                st.success(
                    f"   ✅ #{idx} 《{title[:30]}》— {count} 条评论"
                )

                all_comments_data[idx] = {
                    "title": title,
                    "total_comments": count,
                    "file": note_file,
                    "comments": comments,
                }

                time.sleep(0.3)

            st.session_state.comments_data = all_comments_data

            progress_bar.progress(
                1.0, text=f"✅ 完成！共 {total_comment_count} 条评论"
            )
            status_text.empty()

            if all_comments_data:
                st.success(
                    f"✅ 全部完成！共获取 {total_comment_count} 条评论，"
                    f"涉及 {len(all_comments_data)} 篇笔记"
                )
            st.rerun()

        # 显示已获取的评论
        if st.session_state.comments_data:
            st.markdown("---")
            st.subheader("📊 评论结果")

            for idx in sorted(st.session_state.comments_data.keys()):
                data = st.session_state.comments_data[idx]
                item = results[idx - 1]
                title = data["title"]
                count = data["total_comments"]
                comments = data["comments"]
                note_file = data["file"]

                with st.expander(
                    f"#{idx} {title[:50]} — 💬 {count} 条评论",
                    expanded=False,
                ):
                    st.markdown(f"**标题**: {title}")
                    st.markdown(f"**链接**: {item['url']}")
                    st.markdown(f"**文件**: `{note_file}`")

                    if count == 0:
                        st.info("暂无评论")
                    else:
                        for j, c in enumerate(comments, 1):
                            with st.container(border=True):
                                st.markdown(
                                    f"**{c.get('用户昵称', '匿名')}** "
                                    f"— ❤️ {c.get('点赞数量', '0')} "
                                    f"— 🕐 {c.get('发布时间', '')}"
                                )
                                st.markdown(c.get("评论内容", ""))

                                sub_comments = c.get("子评论", [])
                                if sub_comments:
                                    with st.expander(
                                        f"💬 {len(sub_comments)} 条回复",
                                        expanded=False,
                                    ):
                                        for s in sub_comments:
                                            st.markdown(
                                                f"> **{s.get('用户昵称', '匿名')}**: "
                                                f"{s.get('评论内容', '')}"
                                            )

            # 批量下载
            st.markdown("---")
            st.subheader("📦 导出结果")

            col_export1, col_export2 = st.columns(2)

            with col_export1:
                # 合并所有评论为单个 JSON
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
                safe_kw = "".join(
                    c if c.isalnum() or c in "_-" else "_"
                    for c in st.session_state.keyword
                )[:20]
                merged_filename = f"{date.today().isoformat()}_{safe_kw}_all_comments.json"

                st.download_button(
                    label=f"📥 下载合并 JSON ({total_all} 条评论)",
                    data=merged_json,
                    file_name=merged_filename,
                    mime="application/json",
                    use_container_width=True,
                )

            with col_export2:
                if st.button("🔄 返回搜索", use_container_width=True):
                    st.session_state.page = "search"
                    st.rerun()
