#!/usr/bin/env python3
"""
xhs_new_search.py — 独立的小红书笔记搜索 + 评论获取工具（零外部依赖）

无需 XHS-Downloader 项目、无需手动安装依赖。首次运行自动创建虚拟环境并安装依赖。

功能：
  - 搜索小红书笔记（支持翻页、排序、类型筛选）
  - 获取笔记的全部评论（翻页 + 子评论）
  - 从已保存的 Markdown 结果加载，跳过重复搜索
  - 输出 Markdown（默认）或 JSON

用法：
    python xhs_new_search.py <关键词> <Cookie字符串>
    python xhs_new_search.py <关键词> <Cookie字符串> -n 20
    python xhs_new_search.py <关键词> <Cookie字符串> -s popularity_descending
    python xhs_new_search.py "" <Cookie> -l 结果文件.md -c 1,3,5

示例：
    python xhs_new_search.py "AIGC" "a1=...; web_session=..."
    python xhs_new_search.py "" "a1=..." -l 2026-07-08_智能体教学_result.md -c all
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════
# 自举：检查依赖 → 自动创建 venv + 安装 → 重新执行
# ═══════════════════════════════════════════════════════════

import importlib.util as _importlib
import subprocess as _subprocess
import sys as _sys
import os as _os

_SKILL_DIR = _os.path.dirname(_os.path.abspath(__file__))
_VENV_DIR = _os.path.join(_SKILL_DIR, ".venv")
_REQUIREMENTS = ["xhshow>=0.2.0", "curl-cffi"]


def _ensure_venv() -> str:
    """确保 venv 存在且依赖已安装，返回 python 可执行路径"""
    venv_python = _os.path.join(_VENV_DIR, "bin", "python3")
    if _os.path.exists(venv_python):
        return venv_python
    print("📦 首次运行，正在创建虚拟环境...")
    _subprocess.check_call([_sys.executable, "-m", "venv", _VENV_DIR])
    print(f"📦 安装依赖: {', '.join(_REQUIREMENTS)}")
    _subprocess.check_call(
        [venv_python, "-m", "pip", "install", "--quiet"] + _REQUIREMENTS
    )
    print("✅ 环境就绪\n")
    return venv_python


def _bootstrap() -> None:
    """如果 xhshow 无法导入，自动进入 venv 并重新执行"""
    if _importlib.find_spec("xhshow") is not None:
        return
    venv_python = _ensure_venv()
    if _sys.executable != venv_python:
        print("🔄 切换到 venv 环境执行...")
        _os.execv(venv_python, [venv_python] + _sys.argv)


_bootstrap()
# ═══════════════════════════════════════════════════════════

import argparse
import json
import logging
import re
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("xhs_new_search")

# ── 常量 ──────────────────────────────────────────────────────────────

SEARCH_API = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
EXPLORE_BASE = "https://www.xiaohongshu.com/explore"

SORT_OPTIONS = {
    "general": "general",
    "time_descending": "time_descending",
    "popularity_descending": "popularity_descending",
}

NOTE_TYPE_OPTIONS = {
    "all": 0,
    "video": 1,    # 视频
    "normal": 2,   # 图文
}

# ── 评论 API 常量 ───────────────────────────────────────────────────────

COMMENT_API = "https://edith.xiaohongshu.com/api/sns/web/v2/comment/page"
REPLY_API = "https://edith.xiaohongshu.com/api/sns/web/v1/comment/post"

# API → SSR 键名映射
_COMMENT_KEY_MAP: dict[str, str] = {
    "user_info": "user", "like_count": "likedCount",
    "create_time": "createTime", "sub_comment_count": "subCommentCount",
    "sub_comment_cursor": "subCommentCursor",
    "sub_comment_has_more": "subCommentHasMore",
    "sub_comments": "subComments", "target_comment": "targetComment",
}
_USER_KEY_MAP: dict[str, str] = {"user_id": "userId"}

# ── 工具函数 ──────────────────────────────────────────────────────────


def cookie_str_to_dict(cookie_str: str) -> dict[str, str]:
    """将 'key=value; key=value' 格式的 Cookie 字符串解析为字典"""
    result: dict[str, str] = {}
    if not cookie_str:
        return result
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def build_note_url(note_id: str, xsec_token: str) -> str:
    """构建完整的小红书笔记链接"""
    return f"{EXPLORE_BASE}/{note_id}?xsec_token={xsec_token}"


# ── API 调用层 ────────────────────────────────────────────────────────


def check_cookie_valid(
    cookie_str: str,
    proxy: str | None = None,
) -> dict[str, Any]:
    """验证 Cookie 是否有效（向搜索 API 发一次试探请求）

    返回:
        {"valid": True} 或 {"valid": False, "reason": "..."}
    """
    from xhshow import Xhshow
    from curl_cffi import requests as curl_requests

    cookies = cookie_str_to_dict(cookie_str)
    a1 = cookies.get("a1")
    if not a1:
        return {"valid": False, "reason": "缺少 a1 字段，无法生成签名"}

    if not cookies.get("web_session"):
        return {"valid": False, "reason": "缺少 web_session 字段"}

    if not cookies.get("id_token"):
        return {"valid": False, "reason": "缺少 id_token 字段"}

    xh = Xhshow()
    payload = {
        "keyword": "校验",
        "page": 1,
        "page_size": 20,
        "sort": "general",
        "note_type": 0,
        "image_formats": ["jpg", "webp", "avif"],
        "ext_flags": [],
        "search_id": f"xhs_verify_{int(time.time())}",
    }
    xs = xh.sign_xs("POST", SEARCH_API, a1_value=a1)
    xsc = xh.sign_xs_common(cookies)
    xt = str(xh.get_x_t())
    headers = {
        "sec-ch-ua-platform": "macOS",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "x-s": xs, "x-t": xt, "x-s-common": xsc,
    }
    try:
        resp = curl_requests.post(
            SEARCH_API, json=payload, headers=headers, cookies=cookies,
            impersonate="chrome131", timeout=15, proxies=proxy,
        )
    except Exception as e:
        return {"valid": False, "reason": f"网络请求异常: {e}"}

    if resp.status_code != 200:
        if resp.status_code == 401:
            return {"valid": False, "reason": "Cookie 已过期（API 返回 401）"}
        if resp.status_code == 403:
            return {"valid": False, "reason": "Cookie 被拒绝（API 返回 403），可能触发了风控"}
        return {"valid": False, "reason": f"API 返回状态码 {resp.status_code}"}

    data = resp.json()
    if not data.get("success"):
        msg = data.get("msg", "未知错误")
        if "登录" in str(msg) or "未登录" in str(msg) or "token" in str(msg).lower():
            return {"valid": False, "reason": f"Cookie 已失效: {msg}"}
        return {"valid": False, "reason": f"API 返回失败: {msg}"}

    return {"valid": True, "reason": "Cookie 有效"}


def search_notes(
    keyword: str,
    cookie_str: str,
    page_size: int = 10,
    sort: str = "general",
    note_type: int = 0,
    max_retries: int = 3,
    proxy: str | None = None,
) -> list[dict[str, Any]] | None:
    """
    通过小红书搜索 API 搜索笔记。

    参数:
        keyword:     搜索关键词
        cookie_str:  Cookie 字符串（需要 a1 / web_session / id_token 等）
        page_size:   返回笔记数量（默认 10）
        sort:        排序方式（general / time_descending / popularity_descending）
        note_type:   笔记类型（0=全部, 1=视频, 2=图文）
        max_retries: 重试次数
        proxy:       HTTP 代理地址（如 http://127.0.0.1:7890），DNS 解析失败时使用

    返回:
        标准化笔记列表，失败返回 None
    """
    from xhshow import Xhshow
    from curl_cffi import requests as curl_requests

    cookies = cookie_str_to_dict(cookie_str)
    a1 = cookies.get("a1")
    if not a1:
        logger.error("Cookie 缺少 a1 字段，无法生成签名")
        return None

    xh = Xhshow()
    all_items: list[dict[str, Any]] = []
    page = 1
    fetched = 0

    base_headers = {
        "sec-ch-ua-platform": "macOS",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
    }

    while fetched < page_size:
        payload = {
            "keyword": keyword,
            "page": page,
            "page_size": 20,  # API 要求 page_size >= 20 才返回 items
            "sort": sort,
            "note_type": note_type,
            "image_formats": ["jpg", "webp", "avif"],
            "ext_flags": [],
            "search_id": f"xhs_search_{int(time.time())}",
        }

        # 手动生成签名，sign_headers 会引入 x-rap-param 导致搜索返回空
        xs = xh.sign_xs("POST", SEARCH_API, a1_value=a1)
        xsc = xh.sign_xs_common(cookies)
        xt = str(xh.get_x_t())

        headers = {
            **base_headers,
            "x-s": xs,
            "x-t": xt,
            "x-s-common": xsc,
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = curl_requests.post(
                    SEARCH_API, json=payload, headers=headers, cookies=cookies,
                    impersonate="chrome131", timeout=30, proxies=proxy,
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning("第 %d 页请求异常(尝试 %d/%d): %s", page, attempt + 1, max_retries, e)
                time.sleep(1)

        if last_error is not None:
            logger.error("第 %d 页请求失败，已达最大重试次数", page)
            break

        if resp.status_code != 200:
            if page == 1:
                logger.warning("API 返回状态码 %d（Cookie 可能无效）", resp.status_code)
                return None
            logger.warning("第 %d 页返回状态码 %d，停止翻页", page, resp.status_code)
            break

        data = resp.json()
        if not data.get("success"):
            if page == 1:
                logger.warning("API 返回失败: %s", data.get("msg", "未知错误"))
                return None
            break

        items = data.get("data", {}).get("items", [])
        if not items:
            break

        for item in items:
            if fetched >= page_size:
                break
            note_card = item.get("note_card", {})
            note_id = item.get("id", "")
            xsec_token = item.get("xsec_token", "")

            # 过滤推广内容（UUID 格式 ID 非真实笔记）
            if not note_id or "-" in note_id or not xsec_token:
                continue

            # 提取关键信息
            display_title = (note_card.get("display_title") or note_card.get("title") or "").strip()
            if not display_title:
                continue  # 无标题的跳过
            interact_info = note_card.get("interact_info", {})
            user_info = note_card.get("user", {})
            note_type_val = note_card.get("type", "")
            # 标准化类型标签
            type_label = "video" if "video" in str(note_type_val) else "normal"

            note_data = {
                "id": note_id,
                "title": display_title,
                "url": build_note_url(note_id, xsec_token) if note_id and xsec_token else "",
                "user": {
                    "nickname": (user_info.get("nickname") or user_info.get("nick_name") or ""),
                    "user_id": user_info.get("user_id", ""),
                },
                "stats": {
                    "liked_count": interact_info.get("liked_count", "0"),
                    "collected_count": interact_info.get("collected_count", "0"),
                    "comment_count": interact_info.get("comment_count", "0"),
                    "shared_count": interact_info.get("shared_count", "0"),
                },
                "note_type": type_label,
            }
            all_items.append(note_data)
            fetched += 1

        if fetched < page_size:
            has_more = data.get("data", {}).get("has_more", False)
            if not has_more:
                break
            page += 1
            time.sleep(0.3)  # 页间隔

    return all_items


# ── 输出 ──────────────────────────────────────────────────────────────


def print_results(items: list[dict[str, Any]], keyword: str) -> None:
    """在终端友好地输出搜索结果"""
    print(f"\n🔍 搜索关键词: {keyword}")
    print(f"📊 找到 {len(items)} 条笔记\n")

    for i, item in enumerate(items, 1):
        title = item["title"] or "(无标题)"
        url = item["url"]
        user = item["user"]["nickname"] or "(未知用户)"
        stats = item["stats"]
        note_type = "📷 图文" if item["note_type"] == "normal" else "🎬 视频" if item["note_type"] == "video" else "📝 笔记"

        print(f"{'─' * 60}")
        print(f"  #{i}  {note_type}")
        print(f"  📌 标题: {title}")
        print(f"  👤 作者: {user}")
        print(f"  ❤️ {stats['liked_count']}  ⭐ {stats['collected_count']}  💬 {stats['comment_count']}  🔄 {stats['shared_count']}")
        if url:
            print(f"  🔗 链接: {url}")
        print()

    print(f"{'═' * 60}")
    print(f"✅ 共 {len(items)} 条结果")


def dump_json(
    items: list[dict[str, Any]],
    keyword: str,
    output_path: str | None = None,
) -> str:
    """将搜索结果写入 JSON 文件，返回文件路径"""
    payload = {
        "keyword": keyword,
        "total": len(items),
        "items": items,
    }
    if output_path is None:
        safe_keyword = "".join(c if c.isalnum() or c in " _-" else "_" for c in keyword)[:30]
        output_path = f"{date.today().isoformat()}_{safe_keyword}_result.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return output_path


def dump_markdown(
    items: list[dict[str, Any]],
    keyword: str,
    output_path: str | None = None,
) -> str:
    """将搜索结果写入 Markdown 文件，返回文件路径"""
    if output_path is None:
        safe_keyword = "".join(c if c.isalnum() or c in " _-" else "_" for c in keyword)[:30]
        output_path = f"{date.today().isoformat()}_{safe_keyword}_result.md"

    type_icons = {"normal": "📷", "video": "🎬"}
    lines: list[str] = []
    lines.append(f"# 小红书搜索：{keyword}")
    lines.append("")
    lines.append(f"共找到 **{len(items)}** 条笔记\n")
    lines.append("")

    for i, item in enumerate(items, 1):
        title = item["title"] or "(无标题)"
        url = item["url"]
        user = item["user"]["nickname"] or "(未知用户)"
        stats = item["stats"]
        icon = type_icons.get(item["note_type"], "📝")
        note_type_str = {"normal": "图文", "video": "视频"}.get(item["note_type"], "笔记")

        lines.append(f"## {i}. {icon} {title}")
        lines.append("")
        lines.append(f"- **作者**：{user}")
        lines.append(f"- **类型**：{note_type_str}")
        lines.append(f"- ❤️ {stats['liked_count']}　⭐ {stats['collected_count']}　💬 {stats['comment_count']}　🔄 {stats['shared_count']}")
        if url:
            lines.append(f"- **链接**：[查看笔记]({url})")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_path


# ── 评论获取层 ─────────────────────────────────────────────────────────


def _rename_keys(d: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """原地重命名字典键"""
    for old, new in mapping.items():
        if old in d and old != new:
            d[new] = d.pop(old)
    return d


def _normalize_comment(c: dict[str, Any]) -> dict[str, Any]:
    """将单条 API 评论归一化为 SSR 格式"""
    _rename_keys(c, _COMMENT_KEY_MAP)
    user = c.get("user")
    if isinstance(user, dict):
        _rename_keys(user, _USER_KEY_MAP)
    subs = c.get("subComments")
    if isinstance(subs, list):
        for s in subs:
            if isinstance(s, dict):
                _normalize_comment(s)
    return c


def _ts_to_cst(ts: str | int | float) -> str:
    """将毫秒级时间戳转换为中国标准时间 (UTC+8)，如 '2026-07-10 19:30:00'"""
    if not ts and ts != 0:
        return ""
    try:
        seconds = int(ts) / 1000
        if seconds == 0:
            return ""
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc) + timedelta(hours=8)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _format_comment(c: dict[str, Any]) -> dict[str, Any]:
    """将 SSR 格式评论转为中文键名"""
    user = c.get("user", {})
    nick = (user.get("nickName") or user.get("nickname") or user.get("nick_name") or "") if isinstance(user, dict) else ""
    uid = (user.get("userId") or user.get("user_id") or "") if isinstance(user, dict) else ""
    subs_raw = c.get("subComments", [])
    return {
        "评论ID": c.get("id", ""),
        "用户昵称": nick,
        "用户ID": uid,
        "评论内容": c.get("content", ""),
        "发布时间": _ts_to_cst(c.get("createTime", "")),
        "点赞数量": str(c.get("likedCount", "0")),
        "回复数量": str(c.get("subCommentCount", "0")),
        "ip_location": c.get("ip_location", ""),
        "子评论": [_format_comment(s) for s in subs_raw if isinstance(s, dict)] if isinstance(subs_raw, list) else [],
    }


def fetch_comments(
    note_id: str,
    xsec_token: str,
    cookie_str: str,
    max_pages: int = 50,
    proxy: str | None = None,
) -> list[dict[str, Any]] | None:
    """获取笔记全部评论（翻页），返回中文格式化后的列表"""
    from xhshow import Xhshow
    from curl_cffi import requests as curl_requests

    cookies = cookie_str_to_dict(cookie_str)
    a1 = cookies.get("a1")
    if not a1:
        logger.error("Cookie 缺少 a1 字段")
        return None
    xh = Xhshow()
    all_comments: list[dict[str, Any]] = []
    cursor = ""
    page = 0
    base_headers = {
        "sec-ch-ua-platform": "macOS",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "accept": "application/json, text/plain, */*",
    }
    while page < max_pages:
        api_path = "/api/sns/web/v2/comment/page"
        url = f"https://edith.xiaohongshu.com{api_path}"
        params = {"note_id": note_id, "cursor": cursor, "top_comment_id": "", "image_formats": "jpg,webp,avif", "xsec_token": xsec_token}
        headers = {
            **base_headers,
            **xh.sign_headers_get(uri=api_path, cookies=cookies, params=params),
        }
        try:
            resp = curl_requests.get(url, headers=headers, cookies=cookies, params=params, impersonate="chrome131", timeout=15, proxies=proxy)
        except Exception as e:
            logger.warning("评论第 %d 页请求异常: %s", page + 1, e)
            break
        if resp.status_code != 200:
            if page == 0:
                logger.warning("评论 API 返回 %d（Cookie 可能无效）", resp.status_code)
                return None
            break
        data = resp.json()
        if not data.get("success"):
            if page == 0:
                logger.warning("评论 API 返回失败: %s", data.get("msg"))
                return None
            break
        comments = data["data"].get("comments", [])
        if not comments:
            break
        for c in comments:
            if isinstance(c, dict):
                _normalize_comment(c)
                all_comments.append(_format_comment(c))
        has_more = data["data"].get("has_more", False)
        cursor = data["data"].get("cursor", "")
        page += 1
        if not has_more or not cursor:
            break
        time.sleep(0.3)
    return all_comments


# ── 评论回复层 ────────────────────────────────────────────────────────────


def reply_comment(
    note_id: str,
    content: str,
    target_comment_id: str = "",
    cookie_str: str = "",
    proxy: str | None = None,
) -> dict | None:
    """回复小红书笔记的评论（或回复子评论）。

    参数:
        note_id:             笔记 ID
        content:             回复内容
        target_comment_id:   目标评论 ID（回复子评论时也填其 comment_id）
        cookie_str:          Cookie 字符串
        proxy:               HTTP 代理地址

    返回:
        API 响应 dict（含 success/msg 等字段），网络或签名异常返回 None
    """
    from xhshow import Xhshow
    from curl_cffi import requests as curl_requests

    cookies = cookie_str_to_dict(cookie_str)
    a1 = cookies.get("a1")
    if not a1:
        logger.error("reply_comment: Cookie 缺少 a1 字段")
        return None

    xh = Xhshow()
    uri_path = "/api/sns/web/v1/comment/post"
    url = f"https://edith.xiaohongshu.com{uri_path}"

    payload: dict[str, Any] = {
        "note_id": note_id,
        "content": content,
        "at_users": [],
    }
    if target_comment_id:
        payload["target_comment_id"] = target_comment_id

    # sign_headers_post 返回 x-s / x-t / x-s-common / x-b3-traceid / x-xray-traceid
    signed = xh.sign_headers_post(uri=uri_path, cookies=cookies, payload=payload)
    headers = {
        "referer": "https://www.xiaohongshu.com/",
        "content-type": "application/json;charset=UTF-8",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        **signed,
    }

    try:
        resp = curl_requests.post(
            url, json=payload, headers=headers, cookies=cookies,
            impersonate="chrome131", timeout=15, proxies=proxy,
        )
    except Exception as e:
        logger.error("reply_comment: 请求异常: %s", e)
        return None

    if resp.status_code != 200:
        logger.warning("reply_comment: API 返回 %d", resp.status_code)
        return None

    try:
        return resp.json()
    except Exception:
        return None


# ── 笔记选择层 ──────────────────────────────────────────────────────────


def load_items_from_markdown(filepath: str) -> list[dict[str, Any]] | None:
    """从已保存的 Markdown 结果文件加载笔记列表，跳过重新搜索"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        logger.error("文件不存在: %s", filepath)
        return None

    items: list[dict[str, Any]] = []
    # 解析每个 ## N. 段落
    blocks = re.split(r"\n## \d+\. ", content)[1:]  # 跳过标题行
    for block in blocks:
        lines = block.strip().split("\n")
        title = lines[0].strip() if lines else ""
        # 移除开头的图标（🎬 📷 📝 等）
        title = re.sub(r"^[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u2600-\u27BF\uFE00-\uFE0F]+\s*", "", title)
        url = ""
        nickname = ""
        for line in lines:
            if "https://" in line:
                m = re.search(r"\(https://([^)]+)\)", line)
                if m:
                    url = "https://" + m.group(1)
            if "**作者**" in line:
                sep = "：" if "：" in line else ":"
                nickname = line.split(sep)[-1].strip()
        if not url:
            continue
        parsed = urlparse(url)
        note_id = parsed.path.rstrip("/").split("/")[-1]
        qs = parse_qs(parsed.query)
        xsec_token = (qs.get("xsec_token") or [""])[0]
        if not note_id or not xsec_token:
            continue
        items.append({
            "id": note_id,
            "title": title,
            "url": url,
            "user": {"nickname": nickname, "user_id": ""},
            "stats": {"liked_count": "0", "collected_count": "0", "comment_count": "0", "shared_count": "0"},
            "note_type": "video",
        })
    return items if items else None


def parse_selection(text: str, max_index: int) -> list[int]:
    """解析用户输入的编号选择，返回 1-based 索引列表

    支持: "1,3,5" "1-5" "1,3-5,7" "all"
    """
    text = text.strip().lower()
    if text == "all":
        return list(range(1, max_index + 1))
    selected: set[int] = set()
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                start, end = int(a.strip()), int(b.strip())
                selected.update(range(max(1, start), min(max_index, end) + 1))
            except ValueError:
                continue
        else:
            try:
                n = int(part)
                if 1 <= n <= max_index:
                    selected.add(n)
            except ValueError:
                continue
    return sorted(selected)


def prompt_select_note(max_index: int) -> list[int] | None:
    """交互式提示用户选择笔记编号，返回选择列表，None 表示跳过"""
    try:
        text = input(f"\n👉 要查询哪些笔记的评论？\n"
                     f"   输入编号（如 1,3,5 或 1-5 或 all），按回车跳过：").strip()
        if not text:
            return None
        return parse_selection(text, max_index)
    except (EOFError, KeyboardInterrupt):
        return None


def run_comment_pipeline(
    items: list[dict[str, Any]],
    selected: list[int],
    keyword: str,
    cookie_str: str,
) -> None:
    """对选中的笔记逐一获取评论并保存"""
    print(f"\n{'=' * 60}")
    print(f"📝 开始获取 {len(selected)} 篇笔记的评论...")
    print(f"{'=' * 60}")

    all_comments_data = {}
    total_comments = 0
    for idx, note_index in enumerate(selected, 1):
        item = items[note_index - 1]
        title = item["title"]
        note_id = item["id"]
        xsec_token = item["url"].split("xsec_token=")[-1] if "xsec_token=" in item["url"] else ""

        print(f"\n[{idx}/{len(selected)}] 📌 {title[:40]}")
        print(f"   正在获取评论...")

        comments = fetch_comments(note_id, xsec_token, cookie_str)
        if comments is None:
            print(f"   ❌ 获取失败（Cookie 可能无效或网络异常）")
            continue
        count = len(comments)
        total_comments += count
        print(f"   ✅ 共 {count} 条评论")

        _os.makedirs("comment", exist_ok=True)
        note_file = f"comment/{date.today().isoformat()}_{keyword}_comments_{note_index}.json"
        with open(note_file, "w", encoding="utf-8") as f:
            json.dump({
                "keyword": keyword,
                "note_id": note_id,
                "note_title": title,
                "total_comments": count,
                "comments": comments,
            }, f, ensure_ascii=False, indent=2)
        print(f"   📁 已保存: {note_file}")
        all_comments_data[str(note_index)] = {
            "title": title,
            "total_comments": count,
            "file": note_file,
        }
        time.sleep(0.5)

    print(f"\n{'═' * 60}")
    print(f"✅ 评论获取完成！共 {total_comments} 条评论")
    print(f"📁 文件列表:")
    for idx_str, info in all_comments_data.items():
        print(f"   #{idx_str} {info['title'][:30]}... → {info['file']} ({info['total_comments']} 条)")
    print()


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="搜索小红书笔记并返回笔记名称和链接",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            '  %(prog)s "AIGC" "a1=...; web_session=..."\n'
            '  %(prog)s "AI绘画" "a1=...; web_session=..." -n 20\n'
            '  %(prog)s "人工智能" "a1=..." -s popularity_descending -o results.json\n'
        ),
    )
    parser.add_argument("keyword", nargs="?", default="", help="搜索热词（--load 模式可选）")
    parser.add_argument("cookie", nargs="?", default="", help="Cookie 字符串（登录态，含 a1/web_session/id_token 等）")
    parser.add_argument("-n", "--number", type=int, default=10, help="返回笔记数量（默认 10）")
    parser.add_argument(
        "-s", "--sort", choices=list(SORT_OPTIONS.keys()), default="general",
        help="排序方式: general=综合, time_descending=最新, popularity_descending=最热（默认 general）",
    )
    parser.add_argument(
        "-t", "--type", type=int, choices=list(NOTE_TYPE_OPTIONS.values()), default=0,
        help="笔记类型: 0=全部, 1=视频, 2=图文（默认 0）",
    )
    parser.add_argument("-o", "--output", help="输出路径（指定时用 JSON 格式）")
    parser.add_argument("-c", "--comments", nargs="?", const="interactive", default=None,
                        help="获取评论: 不加值进入交互模式；加值如 '1,3,5' 或 'all' 直接选择")
    parser.add_argument("-l", "--load", help="从已保存的 Markdown 结果文件加载，跳过重新搜索")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # ── 模式 A: 从文件加载（跳过搜索） ──
    if args.load:
        if not args.cookie.strip():
            logger.error("获取评论需要提供 Cookie")
            _sys.exit(1)
        logger.info("从文件加载: %s", args.load)
        items = load_items_from_markdown(args.load)
        if items is None:
            _sys.exit(1)
        keyword = args.keyword
        if not keyword:
            try:
                with open(args.load, encoding="utf-8") as _f:
                    _first = _f.readline()
                _m = re.search(r"搜索[：:]\s*(.+)", _first)
                if _m:
                    keyword = _m.group(1).strip()
            except Exception:
                pass
            if not keyword:
                keyword = _os.path.splitext(_os.path.basename(args.load))[0].replace("_result", "")
        logger.info("加载到 %d 条笔记", len(items))
        print_results(items, keyword)

    # ── 模式 B: 正常搜索 ──
    else:
        if not args.keyword.strip():
            logger.error("关键词不能为空")
            _sys.exit(1)
        if not args.cookie.strip():
            logger.error("Cookie 为空，请提供登录态 Cookie")
            _sys.exit(1)
        if args.number < 1 or args.number > 100:
            logger.error("笔记数量必须在 1-100 之间")
            _sys.exit(1)

        logger.info("搜索关键词: %s", args.keyword)
        logger.info("排序方式: %s", args.sort)
        logger.info("返回数量: %d", args.number)
        logger.info("开始搜索...")

        items = search_notes(
            keyword=args.keyword,
            cookie_str=args.cookie,
            page_size=args.number,
            sort=args.sort,
            note_type=args.type,
        )

        if items is None:
            logger.error("搜索失败（xhshow 未安装 / Cookie 无效 / 网络异常）")
            _sys.exit(1)

        if not items:
            logger.warning("未找到相关笔记")
            print(f"\n🔍 搜索关键词: {args.keyword}")
            print("❌ 未找到相关笔记")
            _sys.exit(0)

        # 终端输出
        print_results(items, args.keyword)

        # 保存结果
        if args.output and args.output.endswith(".json"):
            out_path = dump_json(items, args.keyword, args.output)
            fmt = "JSON"
        else:
            out_path = dump_markdown(items, args.keyword, args.output)
            fmt = "Markdown"
        print(f"📁 {fmt} 已保存至: {_os.path.abspath(out_path)}")

    # ── 评论获取管道（两种模式共享） ──
    if args.comments is not None:
        if args.comments == "interactive":
            selected = prompt_select_note(len(items))
        else:
            selected = parse_selection(args.comments, len(items))

        if selected:
            run_comment_pipeline(items, selected, args.keyword or "result", args.cookie)
        else:
            print("\n⏭ 跳过评论获取")
    print()


if __name__ == "__main__":
    main()
