# 迈影AI获客 — 小红书工具

3 个 Python 文件，单包结构。Streamlit Web 界面 + CLI 双入口，操作小红书 API 搜索笔记和获取评论。

## 运行命令

```bash
uv run streamlit run streamlit_app.py   # Web 界面（主要入口）
uv run python xhs_cookie_grabber.py     # CLI 获取 Cookie
uv run python xhs_new_search.py "热词" "a1=...; web_session=..."  # CLI 搜索+评论
```

## 架构

- `xhs_new_search.py` — 核心库（`search_notes` / `fetch_comments`），也是 CLI
- `streamlit_app.py` — Streamlit 前端，三步工作流：Cookie → 搜索 → 评论
- `xhs_cookie_grabber.py` — 独立工具，Playwright 浏览器自动获取 Cookie

`xhs_new_search.py` 被 `streamlit_app.py` import 作为后端；`xhs_cookie_grabber.py` 也可被 streamlit 运行时 import 调用。

## 关键约定

- **包管理**: `uv`（不是 pip），Python 3.12，依赖在 `pyproject.toml`
- **API 签名**: `xhshow` 库 — search 用 `sign_xs()`（POST），comment 用 `sign_headers_get()`（GET）
- **HTTP 层**: `curl-cffi` 模拟 Chrome 131 TLS 指纹
- **搜索分页**: API 要求 `page_size >= 20`，即使请求更少条数
- **代理**: 所有 API 调用（search + comments）透传 `proxy` 参数，通过 `requests` 的 `proxies=` 传入
- **Cookie**: 需要 `a1` + `web_session` + `id_token`；缺少任一字段 API 返回失败
- **数据格式**: 评论输出 JSON 使用中文键名（`评论ID`、`用户昵称`、`评论内容` 等）
- **Git**: semantic commit style（`feat:` / `docs:` / `chore:`），macOS Keychain 管理 GitHub 凭据
- **自举**: `xhs_new_search.py` 模块级调用 `_bootstrap()`（65行），导入 xhshow 前自动建 venv 装依赖

## 注意事项

- 没有测试、没有 linter/formatter 配置、没有 CI
- `search_notes` 返回的每条笔记包含 `user.nickname` + `user.user_id`，表格展示需手动加入
- `load_items_from_markdown()` 从 Markdown 恢复笔记时会丢失统计数据（stats 点零）、user_id 置空
- Streamlit session state 的 `search_results` 是 `list[dict]`（即 `search_notes` 返回的原始结构）
- 评论获取最大 50 页翻页限制（`max_pages=50`），每页间隔 0.3s
- Git 已推送到 `github.com/sunlingfeng70/huoke-app`，origin 已建立 upstream 追踪
