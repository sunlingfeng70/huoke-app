from __future__ import annotations

import streamlit as st
import pandas as pd

from xhs_new_search import search_notes


def render() -> None:
    st.header("2️⃣ 搜索小红书笔记")

    if not st.session_state.cookie_str:
        st.warning("请先在「Cookie 获取」步骤设置 Cookie")
        if st.button("← 返回 Cookie 步骤"):
            st.session_state.page = "cookie"
            st.rerun()
        return

    with st.container(border=True):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            keyword = st.text_input(
                "搜索关键词",
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
            st.markdown("")
            st.markdown("")
            search_clicked = st.button(
                "搜索", type="primary", use_container_width=True
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
                    "搜索失败。可能原因：\n"
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
                st.success(f"找到 {len(results)} 条笔记")
                st.rerun()

    if not st.session_state.search_results:
        return

    results = st.session_state.search_results
    st.markdown("---")
    st.subheader(f"搜索结果（共 {len(results)} 条）")

    col_sel1, col_sel2, col_sel3 = st.columns([1, 1, 4])
    with col_sel1:
        if st.button("全选", use_container_width=True):
            st.session_state.selected_indices = list(range(1, len(results) + 1))
            st.rerun()
    with col_sel2:
        if st.button("取消全选", use_container_width=True):
            st.session_state.selected_indices = []
            st.rerun()
    with col_sel3:
        if st.session_state.selected_indices:
            st.info(f"已选择 {len(st.session_state.selected_indices)} 篇笔记")

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

    df = pd.DataFrame(data_rows)
    edited_df = st.data_editor(
        df,
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", help="勾选以获取评论", default=False),
            "#": st.column_config.NumberColumn("#", width=40),
            "类型": st.column_config.TextColumn("类型", width=50),
            "标题": st.column_config.TextColumn("标题", width=350),
            "作者": st.column_config.TextColumn("作者", width=120),
            "用户ID": st.column_config.TextColumn("用户ID", width=160),
            "❤️": st.column_config.NumberColumn("❤️", width=60),
            "⭐": st.column_config.NumberColumn("⭐", width=60),
            "💬": st.column_config.NumberColumn("💬", width=60),
            "链接": st.column_config.LinkColumn("链接", width=100, display_text="打开"),
        },
        hide_index=True,
        use_container_width=True,
        disabled=["#", "类型", "标题", "作者", "用户ID", "❤️", "⭐", "💬", "链接"],
        key="search_results_editor",
    )

    new_selected = [
        int(row["#"])
        for _, row in edited_df.iterrows()
        if row["选择"]
    ]
    if new_selected != st.session_state.selected_indices:
        st.session_state.selected_indices = new_selected
        st.rerun()

    if st.session_state.selected_indices:
        st.markdown("---")
        st.subheader(f"已选 {len(st.session_state.selected_indices)} 篇笔记")

        for idx in st.session_state.selected_indices:
            item = results[idx - 1]
            with st.expander(f"#{idx} {item['title'][:50]}", expanded=False):
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
        if st.button("下一步：获取评论", type="primary", use_container_width=True):
            st.session_state.page = "comments"
            st.rerun()
    else:
        st.info("在上方表格中勾选要获取评论的笔记")
