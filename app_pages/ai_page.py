from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from obsidian_bridge import ObsidianVault

_OBSIDIAN_TOOL_DEFS = [
    {
        "icon": "🔍",
        "name": "search_notes",
        "label": "搜索笔记",
        "description": "按关键词搜索笔记，支持全文/标题/标签三种搜索范围",
    },
    {
        "icon": "📖",
        "name": "read_note",
        "label": "读取笔记",
        "description": "读取指定笔记的完整 Markdown 内容",
    },
    {
        "icon": "📋",
        "name": "list_notes",
        "label": "列出笔记",
        "description": "列出仓库中所有笔记，可按 Glob 模式筛选",
    },
    {
        "icon": "🏷️",
        "name": "get_tags",
        "label": "查看标签",
        "description": "列出仓库中所有标签及其使用次数",
    },
    {
        "icon": "✍️",
        "name": "write_note",
        "label": "写入笔记",
        "description": "写入/覆盖一篇笔记（含 YAML frontmatter），自动创建目录",
    },
    {
        "icon": "📊",
        "name": "organize_notes",
        "label": "一键归类",
        "description": "扫描所有小红书评论，按客户等级/标签/地域/时间线生成索引页",
    },
]


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
            with st.expander(f"{dir_name}", expanded=False):
                _render(dir_node)
        for full_path in sorted(node["files"]):
            if rendered_count >= max_items:
                return
            if st.button(
                full_path.rsplit("/", 1)[-1],
                key=f"note_{full_path}",
                use_container_width=True,
            ):
                st.session_state.selected_note_path = full_path
                st.rerun()
            rendered_count += 1

    _render(tree)


@st.dialog("笔记预览", width="large")
def show_note_dialog(note: dict):
    st.markdown(note["content"])
    st.session_state.selected_note_path = None


def render() -> None:
    st.header("🤖 AI 笔记查询")

    llm_ready = all([
        st.session_state.llm_base_url,
        st.session_state.llm_api_key,
        st.session_state.llm_model,
    ])
    obs_ready = Path(st.session_state.obsidian_path).exists()
    obs_path = st.session_state.obsidian_path

    if not llm_ready:
        st.warning("请先在侧边栏「集成配置」中填写 LLM 参数（Base URL / API Key / 模型名称）")
    if not obs_ready:
        st.warning(f"Obsidian 仓库路径不存在: `{obs_path}`")

    if not (llm_ready and obs_ready):
        return

    vault = ObsidianVault(obs_path)

    with st.sidebar:
        st.markdown("---")
        st.markdown("**仓库笔记**")
        all_notes = vault.list_notes()
        if all_notes:
            paths = [n["path"] for n in all_notes]
            _render_note_tree(paths)
            if len(paths) > 80:
                st.caption(f"... 共 {len(paths)} 篇，显示前 80 篇")
        else:
            st.caption("(空仓库)")

    col_log_toggle, _ = st.columns([1, 5])
    with col_log_toggle:
        log_toggle = st.checkbox(
            "显示执行日志",
            value=st.session_state.ai_show_logs,
            key="ai_log_checkbox",
        )
        if log_toggle != st.session_state.ai_show_logs:
            st.session_state.ai_show_logs = log_toggle
            st.rerun()

    log_placeholder = st.empty()
    _logs = st.session_state.ai_last_exec_logs
    if st.session_state.ai_show_logs and _logs:
        with log_placeholder.container():
            with st.expander("执行日志", expanded=True):
                for entry in _logs:
                    t = entry.get("type")
                    if t == "llm_response":
                        tool_info = f", {entry['tool_call_count']} 个 tool calls" if entry["tool_call_count"] else ""
                        st.markdown(f"**LLM 响应** (第 {entry['turn']} 轮, {entry['duration']}s{tool_info})")
                        if entry["content_preview"]:
                            st.code(entry["content_preview"], language="text")
                    elif t == "tool_call":
                        st.markdown(
                            f"**工具调用** `{entry['tool']}`"
                            f"  ({entry['duration']}s, 返回 {entry['result_size']} 字符)"
                        )
                        st.code(json.dumps(entry["args"], ensure_ascii=False, indent=2), language="json")
                    elif t == "error":
                        st.error(f"❌ {entry['message']}")

    if st.session_state.selected_note_path:
        note = vault.read_note(st.session_state.selected_note_path)
        if note:
            show_note_dialog(note)

    with st.expander("🤖 AI 可用能力", expanded=False):
        cols = st.columns(3)
        for i, tool in enumerate(_OBSIDIAN_TOOL_DEFS):
            with cols[i % 3]:
                st.markdown(
                    f"<div style='padding:6px 0'>"
                    f"<span style='font-size:1.1rem'>{tool['icon']}</span> "
                    f"<code>{tool['name']}</code><br>"
                    f"<span style='font-size:0.85rem;color:#666'>{tool['description']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.ai_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if prompt := st.chat_input("输入问题，基于 Obsidian 笔记内容回答..."):
        st.session_state.ai_last_exec_logs = None
        st.session_state.ai_messages.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

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
            try:
                if name == "search_notes":
                    results = vault.search_notes(args["query"], field=args.get("field", "content"))
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
                        "path": note["path"], "title": note["title"],
                        "content": note["content"], "tags": note["tags"],
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
                    from xhs_obsidian_organizer import run_organizer
                    result = run_organizer(vault.root, verbose=False)
                    return json.dumps({"success": True, "result": result}, ensure_ascii=False)
                return json.dumps({"error": f"未知工具: {name}"})
            except Exception as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)

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
                    proxies={"http": st.session_state.proxy or None, "https": st.session_state.proxy or None}
                    if st.session_state.proxy else None,
                )
                resp.raise_for_status()
                data = resp.json()
                msg = data["choices"][0]["message"]
                _log({"turn": 0, "type": "llm_response", "duration": round(time.time() - t0, 2),
                      "content_preview": (msg.get("content") or "")[:200],
                      "tool_call_count": len(msg.get("tool_calls") or [])})

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
                              "args": func_args, "duration": elapsed, "result_size": len(result)})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })

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
                        proxies={"http": st.session_state.proxy or None, "https": st.session_state.proxy or None}
                        if st.session_state.proxy else None,
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

            st.session_state.ai_last_exec_logs = exec_logs if st.session_state.ai_show_logs else None

        st.session_state.ai_messages.append({"role": "assistant", "content": answer})
        with chat_container:
            with st.chat_message("assistant"):
                st.markdown(answer)

        st.rerun()

    if st.session_state.ai_messages:
        if st.button("清空对话"):
            st.session_state.ai_messages = []
            st.rerun()
