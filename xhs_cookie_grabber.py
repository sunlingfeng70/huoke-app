#!/usr/bin/env python3
"""
xhs_cookie_grabber.py — 小红书 Cookie 自动获取工具

启动浏览器打开小红书登录页，用户手机扫码登录后自动提取完整 Cookie，
保存为 xhs-search 可直接使用的格式。

依赖（首次运行自动安装）：
    playwright

用法：
    python xhs_cookie_grabber.py
    python xhs_cookie_grabber.py --output ~/my_cookies.txt
    python xhs_cookie_grabber.py --force-login   # 忽略已有登录态，强制重新登录
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════
# 自举：检查依赖 → 自动安装 → 重新执行
# ═══════════════════════════════════════════════════════════

import importlib.util as _importlib
import subprocess as _subprocess
import sys as _sys
import os as _os

_SKILL_DIR = _os.path.dirname(_os.path.abspath(__file__))
_VENV_DIR = _os.path.join(_SKILL_DIR, ".venv")


def _ensure_venv(with_browser: bool = False) -> str:
    venv_python = _os.path.join(_VENV_DIR, "bin", "python3")
    if _os.path.exists(venv_python):
        return venv_python
    print("📦 首次运行，正在创建虚拟环境...")
    _subprocess.check_call([_sys.executable, "-m", "venv", _VENV_DIR])
    reqs = ["playwright"]
    print(f"📦 安装依赖: {', '.join(reqs)}")
    _subprocess.check_call([venv_python, "-m", "pip", "install", "--quiet"] + reqs)
    if with_browser:
        print("📦 安装 Chromium 浏览器...")
        _subprocess.check_call([venv_python, "-m", "playwright", "install", "chromium"])
    print("✅ 环境就绪\n")
    return venv_python


def _bootstrap() -> None:
    if _importlib.find_spec("playwright") is not None:
        return
    venv_python = _ensure_venv(with_browser=True)
    if _sys.executable != venv_python:
        _os.execv(venv_python, [venv_python] + _sys.argv)


# 不在模块层级执行 bootstrap，推迟到 main() 中

import argparse
import json
import sys
import time as _time
from pathlib import Path

_COOKIE_FILE = Path(_SKILL_DIR) / "cookies.txt"
_USER_DATA_DIR = Path(_SKILL_DIR) / ".browser-data"

# 目标 Cookie 字段（xhs-search 所需）
_REQUIRED_COOKIES = [
    "a1", "web_session", "id_token", "gid",
    "webBuild", "webId", "loadts", "xsecappid",
    "acw_tc", "abRequestId",
]


def _extract_cookie_string(cookies: list[dict]) -> str:
    """从 Playwright cookies 列表生成 'key=value; key=value' 格式字符串"""
    cookie_map: dict[str, str] = {}
    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        if name and value:
            cookie_map[name] = value
    # 按所需字段顺序排列，优先保证重要字段
    parts: list[str] = []
    seen: set[str] = set()
    for key in _REQUIRED_COOKIES:
        if key in cookie_map and key not in seen:
            parts.append(f"{key}={cookie_map[key]}")
            seen.add(key)
    for key, val in cookie_map.items():
        if key not in seen:
            parts.append(f"{key}={val}")
            seen.add(key)
    return "; ".join(parts)


_LOGIN_FEED_PATHS = ("/explore", "/channel", "/profile", "/feed")


def _check_logged_in(page) -> bool:
    """检查是否已登录

    核心标准：
      1. URL 已离开登录页（不在 /login）
      2. 且当前 URL 是小红书主站 feed 页面
      3. 且 id_token Cookie 存在
    """
    current_url = page.url
    try:
        path = _os.path.basename(current_url.rstrip("/"))
        # 不在 /login 页 + 在 feed 页 = 登录成功
        if "/login" in current_url:
            return False
        if any(p in current_url for p in _LOGIN_FEED_PATHS):
            cookies = page.context.cookies()
            cookie_map = {c["name"]: c.get("value", "") for c in cookies}
            return bool(cookie_map.get("web_session")) and bool(cookie_map.get("id_token"))
    except Exception:
        pass
    return False


def _wait_for_login(
    page,
    poll_interval: float = 2.0,
    timeout: float = 300.0,
) -> str | None:
    """轮询等待用户扫码登录

    登录成功判定（三者缺一不可）：
      1. URL 离开 /login 页
      2. URL 进入 feed 页面（/explore /channel /profile /feed）
      3. id_token + web_session Cookie 都存在

    返回 Cookie 字符串，超时返回 None
    """
    start = _time.time()
    notified_scan = False
    notified_verify = False
    while _time.time() - start < timeout:
        _time.sleep(poll_interval)
        try:
            current_url = page.url
        except Exception:
            continue

        # 仍在 /login 页 → 等待扫码
        if "/login" in current_url:
            continue

        # 已离开 /login 但还没到 feed → 安全验证中
        if not any(p in current_url for p in _LOGIN_FEED_PATHS):
            if not notified_verify:
                print("   📱 扫码成功，等待安全验证...")
                notified_verify = True
                if not notified_scan:
                    notified_scan = True  # 防止重复
            continue

        # 已在 feed 页 → 检查关键 Cookie
        if not notified_scan:
            print("   ✅ 安全验证通过")
            notified_scan = True
        cookies = page.context.cookies()
        cookie_map = {c["name"]: c.get("value", "") for c in cookies}
        if cookie_map.get("web_session") and cookie_map.get("id_token"):
            return _extract_cookie_string(cookies)
    return None


def grab_cookie(
    output_path: str | None = None,
    force_login: bool = False,
    headless: bool = False,
    timeout: int = 30,
) -> str:
    """
    打开小红书，等待用户登录，获取 Cookie。

    返回 Cookie 字符串。
    """
    _ensure_playwright()
    from playwright.sync_api import sync_playwright

    cookie_str = ""

    with sync_playwright() as p:
        # 使用持久化上下文，下次可复用登录态
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(_USER_DATA_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        page = context.pages[0] if context.pages else context.new_page()

        # 先检查是否已有登录态
        if not force_login and _check_logged_in(page):
            print("🔑 检测到已有登录态（来自上次会话）")
            cookies = context.cookies()
            cookie_str = _extract_cookie_string(cookies)

            # 验证关键字段
            missing = [k for k in ["a1", "web_session", "id_token"]
                       if k not in {c["name"]: c["value"] for c in cookies}]
            if missing:
                print(f"⚠️  关键 Cookie 缺失 ({', '.join(missing)})，需要重新登录")
                force_login = True
            else:
                print("✅ 直接使用现有登录态\n")
                # 仍打开页面确认登录有效
                page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
                _time.sleep(1)
                if not _check_logged_in(page):
                    print("⚠️  登录态已过期，需要重新登录")
                    force_login = True
                else:
                    print(f"📋 Cookie 长度: {len(cookie_str)} 字符")
                    print(f"   a1={cookies.get('a1', '')[:20]}...")
                    print(f"   web_session={cookies.get('web_session', '')[:20]}...")
                    print(f"   id_token={cookies.get('id_token', '')[:20]}...")

        if force_login or not cookie_str:
            # 导航到小红书首页（会显示登录弹窗 / 二维码）
            print(f"\n{'=' * 60}")
            print("📱 正在打开小红书登录页...")
            print("   请用手机小红书 App 扫描二维码登录")
            print(f"{'=' * 60}\n")

            page.goto("https://www.xiaohongshu.com/login", wait_until="domcontentloaded")
            _time.sleep(2)

            # 等待用户扫码登录
            print(f"⏳ 等待扫码登录（最长 {timeout} 秒）...")
            print(f"   流程：手机扫码 → 确认登录 → 完成安全验证 → 自动跳转")
            cookie_str = _wait_for_login(page, timeout=float(timeout))

            if cookie_str is None:
                print(f"\n⏰ 等待超时（{timeout} 秒），未检测到登录完成")
                print("💡 请重新运行本 skill 再次尝试：")
                print("   python xhs_cookie_grabber.py")
                context.close()
                sys.exit(1)

            print("\n✅ 扫码登录成功！")
            print(f"📋 Cookie 长度: {len(cookie_str)} 字符")
            # 显示关键字段前 20 位
            parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in cookie_str.split("; ") if "=" in p}
            for k in ["a1", "web_session", "id_token", "gid"]:
                if k in parts:
                    print(f"   {k}={parts[k][:20]}...")

        # 保存 Cookie
        save_path = output_path or str(_COOKIE_FILE)
        Path(save_path).write_text(cookie_str, encoding="utf-8")
        print(f"\n💾 Cookie 已保存至: {save_path}")

        # 保留浏览器 3 秒让用户看到结果
        if not headless and (force_login or cookie_str):
            print("\n🔚 浏览器将在 3 秒后自动关闭...")
            _time.sleep(3)

        context.close()

    return cookie_str


def _ensure_playwright() -> None:
    """确保 playwright 可用，不可用时 bootstrap 后重新执行"""
    if _importlib.find_spec("playwright") is not None:
        return
    venv_python = _ensure_venv(with_browser=True)
    if _sys.executable != venv_python:
        _os.execv(venv_python, [venv_python] + _sys.argv)
    print("❌ playwright 自举失败")
    sys.exit(1)


def main():
    # 先解析 --help / -h（不依赖 playwright）
    parser = argparse.ArgumentParser(
        description="小红书 Cookie 自动获取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s                          # 启动浏览器获取 Cookie\n"
            "  %(prog)s -o ~/xhs_cookies.txt    # 指定保存路径\n"
            "  %(prog)s --force-login           # 强制重新扫码登录\n"
        ),
    )
    parser.add_argument(
        "-o", "--output",
        help="Cookie 保存路径（默认 skill 目录下的 cookies.txt）",
    )
    parser.add_argument(
        "-f", "--force-login", action="store_true",
        help="忽略已有登录态，强制扫码重新登录",
    )
    parser.add_argument(
        "-t", "--timeout", type=int, default=120,
        help="扫码等待超时秒数（默认 120，含安全验证）",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="无头模式（不显示浏览器窗口，适合服务器环境）",
    )

    args = parser.parse_args()

    print(f"{'=' * 60}")
    print("🍠 小红书 Cookie 获取器")
    print(f"{'=' * 60}\n")

    try:
        cookie_str = grab_cookie(
            output_path=args.output,
            force_login=args.force_login,
            headless=args.headless,
            timeout=args.timeout,
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("✅ Cookie 获取完成！")
    print(f"   可直接用于 xhs-search:")
    print(f'   python xhs_new_search.py "热词" "{cookie_str[:60]}..."')
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
