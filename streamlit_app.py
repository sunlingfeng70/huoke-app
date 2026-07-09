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

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# 确保项目根在 sys.path 中
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app_pages import render_ai, render_comments, render_cookie, render_search

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
    "search_results": None,       # list[dict] | None
    "selected_indices": [],       # 勾选的笔记序号（1-based）
    "comments_data": {},          # {note_index: {title, comments, file}}
    "page": "cookie",             # 当前激活的 tab
    "llm_base_url": os.getenv("LLM_BASE_URL", "https://ai.liaobots1.work/v1"),
    "llm_api_key": os.getenv("LLM_API_KEY", "dGlKPVy2oOsnA"),
    "llm_model": os.getenv("LLM_MODEL", "gpt-4o-2024-11-20"),
    "obsidian_path": str(_HERE / "vault"),
    "ai_messages": [],            # AI 对话历史 [{role, content}]
    "ai_show_logs": False,        # 是否显示 LLM 执行日志
    "ai_last_exec_logs": None,    # 最近一次 LLM 执行日志
    "selected_note_path": None,   # 侧边栏选中的笔记路径
}

for k, v in _DEFAULT.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 侧边栏 ───────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🍠 迈影AI获客")
    st.markdown("---")

    # Cookie 状态指示
    if st.session_state.cookie_str:
        from xhs_new_search import cookie_str_to_dict

        missing = [k for k in ["a1", "web_session", "id_token"] if k not in cookie_str_to_dict(st.session_state.cookie_str)]
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
# 页面路由
# ═══════════════════════════════════════════════════════════════════════

if st.session_state.page == "cookie":
    render_cookie()
elif st.session_state.page == "search":
    render_search()
elif st.session_state.page == "comments":
    render_comments()
elif st.session_state.page == "ai":
    render_ai()
