#!/usr/bin/env python3
"""
迈影AI获客 — Streamlit 界面

三步工作流：
  1. 获取/粘贴小红书 Cookie
  2. 搜索笔记并选择
  3. 获取选中笔记的评论

运行：
    uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

from obsidian_bridge import ObsidianVault

# 确保项目根在 sys.path 中，以便直接 import 同目录模块
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from xhs_new_search import (
    build_note_url,
    check_cookie_valid,
    cookie_str_to_dict,
    fetch_comments,
    print_results,
    search_notes,
)

# ── 页面配置 ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="🍠 迈影AI获客",
    page_icon="🍠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session State 初始化 ─────────────────────────────────────────────

load_dotenv()

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
    "llm_base_url": os.getenv("LLM_BASE_URL", "https://ai.liaobots1.work/v1"),
    "llm_api_key": os.getenv("LLM_API_KEY", "dGlKPVy2oOsnA"),
    "llm_model": os.getenv("LLM_MODEL", "gpt-4o-2024-11-20"),
    "obsidian_path": "/Users/tao/Documents/projects/huoke-app/vault",
    "ai_messages": [],          # AI 对话历史 [{role, content}]
    "ai_show_logs": False,      # 是否显示 LLM 执行日志
    "ai_last_exec_logs": None,   # 最近一次 LLM 执行日志
    "selected_note_path": None,  # 侧边栏选中的笔记路径
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
    st.title("🍠 迈影AI获客")
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
    st.markdown("**工作流**")
    wf_steps = {
        "cookie": "1️⃣ Cookie 获取",
        "search": "2️⃣ 搜索笔记",
        "comments": "3️⃣ 获取评论",
    }
    for step_id, label in wf_steps.items():
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
    st.markdown("**其他**")
    ai_btn_type = "primary" if st.session_state.page == "ai" else "secondary"
    if st.button("🤖 AI 查询", key="nav_ai", use_container_width=True, type=ai_btn_type):
        st.session_state.page = "ai"
        st.rerun()

    st.markdown("---")
    with st.expander("⚙️ 集成配置", expanded=False):
        st.markdown("**🤖 LLM 配置**")
        llm_url = st.text_input(
            "API Base URL",
            value=st.session_state.llm_base_url,
            placeholder="https://api.openai.com/v1",
            help="兼容 OpenAI API 的地址",
            key="input_llm_url",
        )
        llm_key = st.text_input(
            "API Key",
            value=st.session_state.llm_api_key,
            placeholder="sk-...",
            type="password",
            help="LLM API 密钥",
            key="input_llm_key",
        )
        llm_model = st.text_input(
            "模型名称",
            value=st.session_state.llm_model,
            placeholder="gpt-4o",
            help="模型标识（如 gpt-4o / claude-3-sonnet / deepseek-chat）",
            key="input_llm_model",
        )
        if llm_url != st.session_state.llm_base_url:
            st.session_state.llm_base_url = llm_url
        if llm_key != st.session_state.llm_api_key:
            st.session_state.llm_api_key = llm_key
        if llm_model != st.session_state.llm_model:
            st.session_state.llm_model = llm_model

        st.markdown("**📓 Obsidian 仓库**")
        obs_path = st.text_input(
            "仓库路径",
            value=st.session_state.obsidian_path,
            placeholder="/path/to/vault",
            help="Obsidian 仓库在本地的路径",
            key="input_obs_path",
        )
        if obs_path != st.session_state.obsidian_path:
            st.session_state.obsidian_path = obs_path
        if Path(st.session_state.obsidian_path).exists():
            st.caption(f"✅ 共 {len(list(Path(st.session_state.obsidian_path).glob('**/*.md')))} 篇笔记")
        else:
            st.caption("⚠️ 路径不存在")

    st.caption(f"项目路径: {_HERE}")


# ── 页面标题 ─────────────────────────────────────────────────────────

_pg_titles = {
    "cookie": "🍠 迈影AI获客 — 小红书笔记搜索 & 评论获取",
    "search": "🍠 迈影AI获客 — 小红书笔记搜索 & 评论获取",
    "comments": "🍠 迈影AI获客 — 小红书笔记搜索 & 评论获取",
    "ai": "🍠 迈影AI获客 — AI 笔记查询",
}
st.title(_pg_titles.get(st.session_state.page, "🍠 迈影AI获客"))

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

        col_a1, col_a2 = st.columns([1, 1])
        with col_a1:
            if st.button("📂 从 cookies.txt 读取", key="load_cookie_file", use_container_width=True):
                cookie_file = _HERE / "cookies.txt"
                if cookie_file.exists():
                    content = cookie_file.read_text(encoding="utf-8").strip()
                    if content:
                        st.session_state.cookie_str = content
                        st.success(f"✅ 已读取 cookies.txt（{len(content)} 字符）")
                        st.rerun()
                    else:
                        st.warning("cookies.txt 为空")
                else:
                    st.warning("cookies.txt 不存在，请先运行 xhs_cookie_grabber.py 获取 Cookie")
        with col_a2:
            if st.button("✅ 保存 Cookie", key="save_cookie", type="primary", use_container_width=True):
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

        # 校验 Cookie
        if st.session_state.cookie_str:
            validate_status = st.empty()
            if st.button("🔍 校验 Cookie", key="validate_cookie", use_container_width=True):
                with st.spinner("正在向小红书 API 发送校验请求..."):
                    try:
                        result = check_cookie_valid(
                            st.session_state.cookie_str,
                            proxy=st.session_state.proxy or None,
                        )
                        if result["valid"]:
                            validate_status.success(f"✅ Cookie 有效 — {result['reason']}")
                        else:
                            validate_status.error(f"❌ {result['reason']}")
                    except Exception as e:
                        validate_status.error(f"❌ 校验异常: {e}")

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
                    "链接": item["url"],
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
                    "链接": st.column_config.LinkColumn(
                        "链接",
                        width=100,
                        display_text="🔗 打开",
                    ),
                },
                hide_index=True,
                use_container_width=True,
                disabled=["#", "类型", "标题", "作者", "用户ID", "❤️", "⭐", "💬", "链接"],
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

            # 保存到 Obsidian
            obs_path_save = st.session_state.obsidian_path
            obs_dir = Path(obs_path_save)
            if obs_dir.exists():
                st.markdown("---")
                obs_col1, obs_col2 = st.columns([3, 1])
                with obs_col1:
                    if st.button("💾 保存到 Obsidian", type="primary", use_container_width=True):
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
                                c if c.isalnum() or c in " _-（()）" else "_"
                                for c in title
                            )[:40]

                            md_lines = []
                            md_lines.append("---")
                            md_lines.append(f'title: "💬 {title}"')
                            md_lines.append(f"source_url: {url}")
                            md_lines.append(f"source_keyword: {st.session_state.keyword}")
                            md_lines.append(f"comment_count: {count}")
                            md_lines.append(f"date: {date.today().isoformat()}")
                            md_lines.append("tags: [小红书, 评论]")
                            md_lines.append("---")
                            md_lines.append("")
                            md_lines.append(f"# 💬 评论: {title}")
                            md_lines.append("")
                            md_lines.append(f"**来源**: [{url}]({url})")
                            md_lines.append(f"**关键词**: {st.session_state.keyword}")
                            md_lines.append(f"**评论总数**: {count}")
                            md_lines.append("")
                            md_lines.append("---")
                            md_lines.append("")

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

                            md_content = "\n".join(md_lines)

                            note_path = target_dir / f"{idx:02d}_{safe_title}.md"
                            note_path.write_text(md_content, encoding="utf-8")
                            saved_count += 1

                        # 生成索引页
                        index_lines = []
                        index_lines.append("---")
                        index_lines.append(f'title: "评论汇总: {st.session_state.keyword}"')
                        index_lines.append(f"date: {date.today().isoformat()}")
                        index_lines.append("tags: [小红书, 评论汇总]")
                        index_lines.append("---")
                        index_lines.append("")
                        index_lines.append(f"# 📊 评论汇总: {st.session_state.keyword}")
                        index_lines.append("")
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
                                c if c.isalnum() or c in " _-（()）" else "_"
                                for c in data["title"]
                            )[:40]
                            url = item.get("url", "")
                            index_lines.append(
                                f"- [[{idx:02d}_{safe_title}]] — "
                                f"{data['title'][:50]} "
                                f"({data['total_comments']} 条评论)"
                            )

                        index_content = "\n".join(index_lines)
                        index_path = target_dir / "index.md"
                        index_path.write_text(index_content, encoding="utf-8")

                        st.success(
                            f"✅ 已保存 {saved_count} 篇笔记到 Obsidian\n\n"
                            f"📁 `{target_dir.relative_to(obs_dir)}`"
                        )
                with obs_col2:
                    vault_rel = Path(st.session_state.obsidian_path)
                    vault_name = vault_rel.name if vault_rel.exists() else "vault"
                    st.caption(f"目标: {vault_name}")

# ═══════════════════════════════════════════════════════════════════════
# 步骤 4: AI 查询
# ═══════════════════════════════════════════════════════════════════════

elif st.session_state.page == "ai":
    st.header("🤖 AI 笔记查询")

    # 检查配置
    llm_ready = all([
        st.session_state.llm_base_url,
        st.session_state.llm_api_key,
        st.session_state.llm_model,
    ])
    obs_ready = Path(st.session_state.obsidian_path).exists()
    obs_path = st.session_state.obsidian_path

    if not llm_ready:
        st.warning("⚠️ 请先在侧边栏「⚙️ 集成配置」中填写 LLM 参数（Base URL / API Key / 模型名称）")
    if not obs_ready:
        st.warning(f"⚠️ Obsidian 仓库路径不存在: `{obs_path}`")

    def _render_note_tree(paths: list[str], max_items: int = 80):
        tree: dict = {"dirs": {}, "files": []}
        for p in paths:
            parts = p.split("/")
            node = tree
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    node["files"].append(p)
                else:
                    node["dirs"].setdefault(part, {"dirs": {}, "files": []})
                    node = node["dirs"][part]

        rendered_count = 0

        def _render(node: dict):
            nonlocal rendered_count
            if rendered_count >= max_items:
                return
            for dir_name, dir_node in sorted(node["dirs"].items()):
                if rendered_count >= max_items:
                    return
                with st.expander(f"📁 {dir_name}", expanded=False):
                    _render(dir_node)
            for full_path in sorted(node["files"]):
                if rendered_count >= max_items:
                    return
                if st.button(
                    f"📄 {full_path.rsplit('/', 1)[-1]}",
                    key=f"note_{full_path}",
                    use_container_width=True,
                ):
                    st.session_state.selected_note_path = full_path
                    st.rerun()
                rendered_count += 1

        _render(tree)

    @st.dialog("📄 笔记预览", width="large")
    def show_note_dialog(note):
        st.markdown(note["content"])
        st.session_state.selected_note_path = None

    if llm_ready and obs_ready:
        vault = ObsidianVault(obs_path)

        # 侧边：笔记列表供引用
        with st.sidebar:
            st.markdown("---")
            st.markdown("**📓 仓库笔记**")
            all_notes = vault.list_notes()
            if all_notes:
                paths = [n["path"] for n in all_notes]
                _render_note_tree(paths)
                if len(paths) > 80:
                    st.caption(f"... 共 {len(paths)} 篇，显示前 80 篇")
            else:
                st.caption("(空仓库)")

        # 日志开关 + 日志显示区
        col_log_toggle, _ = st.columns([1, 5])
        with col_log_toggle:
            log_toggle = st.checkbox(
                "📋 显示执行日志",
                value=st.session_state.ai_show_logs,
                key="ai_log_checkbox",
            )
            if log_toggle != st.session_state.ai_show_logs:
                st.session_state.ai_show_logs = log_toggle
                st.rerun()

        log_placeholder = st.empty()

        # 渲染执行日志（从 session_state 读取，跨 rerun 保持）
        _logs = st.session_state.ai_last_exec_logs
        if st.session_state.ai_show_logs and _logs:
            with log_placeholder.container():
                with st.expander("📋 执行日志", expanded=True):
                    for entry in _logs:
                        t = entry.get("type")
                        if t == "llm_response":
                            tool_info = f", {entry['tool_call_count']} 个 tool calls" if entry["tool_call_count"] else ""
                            st.markdown(f"**🔄 LLM 响应** (第 {entry['turn']} 轮, {entry['duration']}s{tool_info})")
                            if entry["content_preview"]:
                                st.code(entry["content_preview"], language="text")
                        elif t == "tool_call":
                            st.markdown(
                                f"**🔧 工具调用** `{entry['tool']}`"
                                f"  ({entry['duration']}s, 返回 {entry['result_size']} 字符)"
                            )
                            st.code(json.dumps(entry["args"], ensure_ascii=False, indent=2), language="json")
                        elif t == "error":
                            st.error(f"❌ {entry['message']}")

        # 笔记预览（弹窗）
        if st.session_state.selected_note_path:
            note = vault.read_note(st.session_state.selected_note_path)
            if note:
                show_note_dialog(note)

        # 对话历史
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.ai_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # 输入
        if prompt := st.chat_input("输入问题，基于 Obsidian 笔记内容回答..."):
            # 清空上次执行日志
            st.session_state.ai_last_exec_logs = None
            # 添加用户消息
            st.session_state.ai_messages.append({"role": "user", "content": prompt})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(prompt)

            # 定义 MCP 工具（通过 ObsidianVault 直接执行）
            vault = ObsidianVault(obs_path)

            OBSIDIAN_TOOLS = [
                {
                    "type": "function",
                    "function": {
                        "name": "search_notes",
                        "description": "按关键词搜索笔记（全文/标题/标签）",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "搜索关键词"},
                                "field": {
                                    "type": "string",
                                    "enum": ["content", "title", "tags"],
                                    "description": "搜索范围：全文/标题/标签（默认全文）",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "read_note",
                        "description": "读取指定笔记的完整内容",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "笔记路径（相对 vault 根目录），如 小红书评论/index.md"},
                            },
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "list_notes",
                        "description": "列出仓库中所有笔记",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Glob 匹配模式（默认 **/*.md）"},
                            },
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_tags",
                        "description": "列出仓库中所有标签及其使用次数",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "write_note",
                        "description": "写入/覆盖一篇笔记（可含 YAML frontmatter），路径不存在时自动创建目录",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "笔记路径（相对 vault 根目录），如 小红书分析/竞品报告.md"},
                                "content": {"type": "string", "description": "Markdown 正文，可用 --- 包裹 YAML frontmatter"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "organize_notes",
                        "description": "一键整理归类所有小红书评论笔记：按客户等级(A/B/C/D)、标签、地域、时间线生成索引页和销售行动总表",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
            ]

            def _execute_obsidian_tool(name: str, args: dict) -> str:
                """执行 Obsidian 工具调用"""
                try:
                    if name == "search_notes":
                        results = vault.search_notes(args["query"], field=args.get("field", "content"))
                        # 也搜索标题和标签作为补充
                        if len(results) < 3:
                            seen = {r["path"] for r in results}
                            for extra_field in ("title", "tags"):
                                for r in vault.search_notes(args["query"], field=extra_field):
                                    if r["path"] not in seen:
                                        results.append(r)
                                        seen.add(r["path"])
                        return json.dumps({"total": len(results), "results": results}, ensure_ascii=False)
                    elif name == "read_note":
                        note = vault.read_note(args["path"])
                        if note is None:
                            return json.dumps({"error": f"笔记不存在: {args['path']}"})
                        return json.dumps({
                            "path": note["path"],
                            "title": note["title"],
                            "content": note["content"],
                            "tags": note["tags"],
                            "wikilinks": note["wikilinks"],
                        }, ensure_ascii=False)
                    elif name == "list_notes":
                        notes = vault.list_notes(args.get("pattern", "**/*.md"))
                        return json.dumps({"total": len(notes), "notes": [
                            {"path": n["path"], "title": n["title"], "tags": n["tags"],
                             "size": n["size"], "modified": n["modified"]} for n in notes
                        ]}, ensure_ascii=False)
                    elif name == "get_tags":
                        tags = vault.get_tags()
                        return json.dumps({"total": len(tags), "tags": tags}, ensure_ascii=False)
                    elif name == "write_note":
                        result = vault.write_note(args["path"], args["content"])
                        return json.dumps({"success": True, "note": result}, ensure_ascii=False)
                    elif name == "organize_notes":
                        from xhs_obsidian_organizer.xhs_obsidian_organizer import run_organizer
                        result = run_organizer(vault.root, verbose=False)
                        return json.dumps({"success": True, "result": result}, ensure_ascii=False)
                    return json.dumps({"error": f"未知工具: {name}"})
                except Exception as e:
                    return json.dumps({"error": str(e)}, ensure_ascii=False)

            # 调用 LLM（支持 function calling）
            system_prompt = """你是「迈影AI获客」的 AI 助手，专注小红书营销分析与知识管理。

## 核心能力
1. **知识问答** — 通过 search_notes / read_note 工具查询 Obsidian 知识库回答问题
2. **小红书数据分析** — 分析笔记、评论中蕴含的用户需求、痛点和趋势
3. **内容策略** — 根据已收集的素材给出选题建议、文案优化方案
4. **笔记撰写** — 使用 write_note 工具将分析结果、竞品报告、选题方案等保存为笔记
5. **文档归类** — 使用 organize_notes 工具一键扫描所有小红书评论，按客户等级/标签/地域/时间线自动生成索引页
6. **竞品洞察** — 从评论和笔记中提炼竞品信息和用户偏好

## 回答规范
- **基于笔记**：所有回答必须通过工具查询笔记内容，标注来源（笔记文件名）
- **不确定时告知**：如果笔记内容不足以回答问题，明确说「笔记中没有相关记录」
- **结构化输出**：使用标题、列表、表格等方式组织答案，便于阅读
- **中文优先**：默认使用中文回答
- **具体可执行**：给出 actionable 的建议，而非空泛的描述
- **主动查询**：收到问题后，先调用 search_notes 搜索相关笔记，再根据需要调用 read_note 读取具体内容，最后综合分析回答
- **善用 write_note**：分析完成后，如需长期保存结果，使用 write_note 写入仓库，并告知用户保存路径
- **定期归类**：评论笔记较多时，主动建议使用 organize_notes 生成索引页"""

            # 收集执行日志
            exec_logs: list[dict] = []

            def _log(entry: dict):
                exec_logs.append(entry)

            with st.spinner("🤖 AI 思考中..."):
                try:
                    messages = [{"role": "system", "content": system_prompt}]
                    for msg in st.session_state.ai_messages[-30:]:
                        messages.append({"role": msg["role"], "content": msg["content"]})

                    payload = {
                        "model": st.session_state.llm_model,
                        "messages": messages,
                        "tools": OBSIDIAN_TOOLS,
                        "tool_choice": "auto",
                        "temperature": 0.7,
                        "max_tokens": 8192,
                    }

                    t0 = time.time()
                    resp = requests.post(
                        f"{st.session_state.llm_base_url.rstrip('/')}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {st.session_state.llm_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=180,
                        proxies={"http": st.session_state.proxy or None, "https": st.session_state.proxy or None} if st.session_state.proxy else None,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data["choices"][0]["message"]
                    _log({"turn": 0, "type": "llm_response", "duration": round(time.time() - t0, 2),
                          "content_preview": (msg.get("content") or "")[:200],
                          "tool_call_count": len(msg.get("tool_calls") or [])})

                    # 处理 tool calls 循环（最多 5 轮）
                    max_turns = 5
                    turn = 0
                    while msg.get("tool_calls") and turn < max_turns:
                        turn += 1
                        messages.append({
                            "role": "assistant",
                            "content": msg.get("content") or None,
                            "tool_calls": msg["tool_calls"],
                        })
                        for tc in msg["tool_calls"]:
                            func_name = tc["function"]["name"]
                            func_args = json.loads(tc["function"]["arguments"])
                            t1 = time.time()
                            result = _execute_obsidian_tool(func_name, func_args)
                            elapsed = round(time.time() - t1, 3)
                            _log({"turn": turn, "type": "tool_call", "tool": func_name,
                                  "args": func_args, "duration": elapsed,
                                  "result_size": len(result)})
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result,
                            })

                        # 继续调用 LLM
                        payload["messages"] = messages
                        t2 = time.time()
                        resp = requests.post(
                            f"{st.session_state.llm_base_url.rstrip('/')}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {st.session_state.llm_api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                            timeout=180,
                            proxies={"http": st.session_state.proxy or None, "https": st.session_state.proxy or None} if st.session_state.proxy else None,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        msg = data["choices"][0]["message"]
                        _log({"turn": turn, "type": "llm_response", "duration": round(time.time() - t2, 2),
                              "content_preview": (msg.get("content") or "")[:200],
                              "tool_call_count": len(msg.get("tool_calls") or [])})

                    answer = msg.get("content") or "(无文本回复)"
                except Exception as e:
                    answer = f"❌ LLM 调用失败: {e}"
                    _log({"type": "error", "message": str(e)})

                # 保存执行日志到 session_state
                st.session_state.ai_last_exec_logs = exec_logs if st.session_state.ai_show_logs else None

            # 添加 AI 回复
            st.session_state.ai_messages.append({"role": "assistant", "content": answer})
            with chat_container:
                with st.chat_message("assistant"):
                    st.markdown(answer)

            st.rerun()

        # 清空对话按钮
        if st.session_state.ai_messages:
            if st.button("🗑️ 清空对话"):
                st.session_state.ai_messages = []
                st.rerun()
