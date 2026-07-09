from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import streamlit as st

from xhs_new_search import check_cookie_valid, cookie_str_to_dict


def _cookie_short_display(cookie_str: str, max_len: int = 80) -> str:
    if len(cookie_str) <= max_len:
        return cookie_str
    return cookie_str[:max_len] + "..."


def _validate_cookie(cookie_str: str) -> list[str]:
    d = cookie_str_to_dict(cookie_str)
    required = ["a1", "web_session", "id_token"]
    return [k for k in required if k not in d]


def _launch_cookie_grabber_direct(headless: bool = False, timeout_val: int = 180) -> str | None:
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
            result["error"] = "超时或用户中断"
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
            status.info(f"浏览器已打开，请用手机小红书 App 扫码登录... ({elapsed}s)")
        else:
            status.warning("即将超时...")
        progress.progress(min(elapsed / (timeout_val + 30), 0.95))
        time.sleep(1)

    progress.progress(1.0)

    if result["error"]:
        status.error(result["error"])
        return None
    if result["cookie"]:
        status.success("Cookie 获取成功！")
        time.sleep(0.5)
        status.empty()
        progress.empty()
        return result["cookie"]

    status.error("未获取到 Cookie")
    return None


def render() -> None:
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
            if st.button("从 cookies.txt 读取", key="load_cookie_file", use_container_width=True):
                _HERE = Path(__file__).parent.parent
                cookie_file = _HERE / "cookies.txt"
                if cookie_file.exists():
                    content = cookie_file.read_text(encoding="utf-8").strip()
                    if content:
                        st.session_state.cookie_str = content
                        st.success(f"已读取 cookies.txt（{len(content)} 字符）")
                        st.rerun()
                    else:
                        st.warning("cookies.txt 为空")
                else:
                    st.warning("cookies.txt 不存在，请先运行 xhs_cookie_grabber.py 获取 Cookie")
        with col_a2:
            if st.button("保存 Cookie", key="save_cookie", type="primary", use_container_width=True):
                cookie_input = cookie_input.strip()
                if not cookie_input:
                    st.warning("请输入 Cookie 字符串")
                else:
                    missing = _validate_cookie(cookie_input)
                    if missing:
                        st.warning(f"Cookie 缺少必要字段: {', '.join(missing)}，搜索可能失败")
                    st.session_state.cookie_str = cookie_input
                    st.success(f"Cookie 已保存（{len(cookie_input)} 字符）")
                    st.rerun()

        if st.session_state.cookie_str:
            if st.button("校验 Cookie", key="validate_cookie", use_container_width=True):
                with st.spinner("正在向小红书 API 发送校验请求..."):
                    try:
                        result = check_cookie_valid(
                            st.session_state.cookie_str,
                            proxy=st.session_state.proxy or None,
                        )
                        if result["valid"]:
                            st.success(f"Cookie 有效 — {result['reason']}")
                        else:
                            st.error(f"❌ {result['reason']}")
                    except Exception as e:
                        st.error(f"校验异常: {e}")

    with col_b:
        st.subheader("方式 B: 浏览器获取")
        st.markdown("点击下方按钮，自动启动浏览器打开小红书登录页。")
        st.markdown("请用手机小红书 App 扫描二维码完成登录。")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            launch = st.button("启动浏览器", key="launch_browser", type="primary")
        with col_b2:
            launch_headless = st.button("无头模式", key="launch_headless")

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
            "uv run python xhs_cookie_grabber.py\n"
            "```\n\n"
            "然后将输出的 Cookie 粘贴到「方式 A」中。"
        )

    if st.session_state.cookie_str:
        st.markdown("---")
        st.subheader("当前 Cookie")
        missing = _validate_cookie(st.session_state.cookie_str)
        if missing:
            st.warning(f"缺失字段: {', '.join(missing)}")
        else:
            st.success("关键字段齐全")
        st.code(_cookie_short_display(st.session_state.cookie_str, 120))

        if st.button("下一步：搜索笔记", key="goto_search", type="primary"):
            st.session_state.page = "search"
            st.rerun()
