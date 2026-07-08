# 🍠 小红书工具 (huoke-app)

小红书笔记搜索 & 评论获取工具。提供三步工作流：

1. **获取 Cookie** — 浏览器扫码登录，自动提取小红书 API 需要的登录态 Cookie
2. **搜索笔记** — 输入热词搜索，可勾选感兴趣的笔记
3. **获取评论** — 循环获取选中笔记的全部评论（含子评论），支持导出

---

## 目录

- [快速开始](#快速开始)
- [工作流详解](#工作流详解)
  - [第一步：Cookie 获取](#第一步-cookie-获取)
  - [第二步：搜索笔记](#第二步-搜索笔记)
  - [第三步：获取评论](#第三步-获取评论)
- [文件说明](#文件说明)
- [网络故障排查](#网络故障排查)
  - [DNS 解析超时 (curl: (28))](#dns-解析超时-curl-28)
  - [配置 HTTP 代理](#配置-http-代理)
  - [PyPI 镜像配置](#pypi-镜像配置)
- [高级用法](#高级用法)
  - [命令行直接运行](#命令行直接运行)
  - [配置持久化镜像源](#配置持久化镜像源)

---

## 快速开始

```bash
# 1. 安装依赖
cd huoke-app
uv sync

# 2. 启动 Streamlit 界面
uv run streamlit run streamlit_app.py

# 3. 浏览器打开 http://localhost:8501
```

### 前置条件

- **Python ≥ 3.12**
- **uv** (包管理器)：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Chrome/Chromium**：用于 Cookie 获取（Playwright 自动管理）

### 所需依赖

| 依赖 | 用途 | 安装方式 |
|---|---|---|
| `playwright` | 浏览器自动化（Cookie 获取） | `uv add playwright` |
| `xhshow` | 小红书 API 签名生成 | `uv add xhshow` |
| `curl-cffi` | HTTP 请求（TLS 指纹模拟） | `uv add curl-cffi` |
| `streamlit` | Web 界面 | `uv add streamlit` |

---

## 工作流详解

### 第一步：Cookie 获取

小红书 API 需要登录态 Cookie 才能访问。提供两种方式：

#### 方式 A：粘贴已有 Cookie

在文本框中直接粘贴 Cookie 字符串（`key=value; key=value` 格式），点击保存。

#### 方式 B：浏览器自动获取

点击「启动浏览器」，会自动打开一个 Chrome 窗口导航到小红书登录页。用手机小红书 App 扫码登录后，Cookie 会自动填入文本框。

**要求浏览器支持图形界面**（macOS/Windows 桌面环境）。服务器环境请使用方式 A，或在命令行中运行：

```bash
uv run python xhs_cookie_grabber.py --headless
```

**关键 Cookie 字段**：

| 字段 | 说明 | 是否必需 |
|---|---|---|
| `a1` | 匿名/用户标识，用于签名 | ✅ 必需 |
| `web_session` | 会话 Token | ✅ 必需 |
| `id_token` | 身份 Token | ✅ 必需 |
| `gid` | 设备标识 | 建议 |

### 第二步：搜索笔记

配置参数后点击搜索：

| 参数 | 说明 |
|---|---|
| **搜索关键词** | 热词/话题 |
| **排序方式** | 综合排序 / 最新发布 / 最热排序 |
| **返回数量** | 1-100 条 |
| **笔记类型** | 全部 / 图文 / 视频 |

搜索结果以表格形式展示，可通过「选择」列勾选感兴趣的笔记（支持全选/取消全选），然后进入下一步获取评论。

### 第三步：获取评论

对第二步勾选的笔记逐一获取评论：

- 支持翻页获取全部评论
- 支持子评论（回复）展开
- 实时进度条显示
- 每篇笔记的评论自动保存为 JSON 文件
- 完成后可下载合并 JSON（所有笔记的评论汇总）

---

## 文件说明

| 文件 | 说明 |
|---|---|
| `xhs_cookie_grabber.py` | Cookie 获取工具（CLI）。启动浏览器 → 扫码登录 → 保存 Cookie |
| `xhs_new_search.py` | 搜索 & 评论核心库。提供 `search_notes()`、`fetch_comments()` 等函数 |
| `streamlit_app.py` | Streamlit Web 界面。三步工作流的可视化操作 |
| `cookies.txt` | （自动生成）浏览器获取的 Cookie 字符串 |
| `.browser-data/` | （自动生成）Playwright 浏览器持久化数据，下次可复用登录态 |
| `pyproject.toml` | uv 项目配置与依赖声明 |

### 输出文件

获取评论后会在项目目录生成以下文件：

```
YYYY-MM-DD_关键词_comments_N.json   # 单篇笔记的评论
YYYY-MM-DD_关键词_all_comments.json  # 所有笔记的合并评论（通过界面下载）
```

JSON 格式：

```json
{
  "keyword": "搜索热词",
  "note_id": "64abc...",
  "note_title": "笔记标题",
  "total_comments": 42,
  "comments": [
    {
      "评论ID": "123...",
      "用户昵称": "用户",
      "用户ID": "abc...",
      "评论内容": "评论正文",
      "发布时间": "2026-07-08 12:00:00",
      "点赞数量": "5",
      "回复数量": "2",
      "子评论": [
        {
          "评论ID": "124...",
          "用户昵称": "回复者",
          "评论内容": "回复正文",
          "点赞数量": "1"
        }
      ]
    }
  ]
}
```

---

## 网络故障排查

### DNS 解析超时 (curl: (28))

**错误信息**：

```
第 1 页请求异常(尝试 1/3): Failed to perform, curl: (28) Resolving timed out after 15001 milliseconds
```

**原因**：`curl-cffi` 无法解析域名 `edith.xiaohongshu.com`。通常在以下情况出现：

- 在中国大陆网络环境，DNS 解析不稳定
- 使用了不稳定的 DNS 服务器
- 防火墙/运营商限制

**解决方案**（任选其一）：

#### 方案 1：配置 HTTP 代理（推荐）

在 Streamlit 界面左侧栏的 **🌐 网络代理** 输入框中填入代理地址，例如：

```
http://127.0.0.1:7890       # Clash/Shadowrocket 等代理工具
http://192.168.1.100:10809  # 局域网代理
socks5://127.0.0.1:1080     # SOCKS5 代理（如支持）
```

#### 方案 2：修改系统 DNS

将系统 DNS 改为稳定可靠的公共 DNS：

| DNS 服务商 | 地址 |
|---|---|
| 阿里 DNS | `223.5.5.5` / `223.6.6.6` |
| 腾讯 DNSPod | `119.29.29.29` |
| 114 DNS | `114.114.114.114` / `114.114.115.115` |
| Google DNS | `8.8.8.8` / `8.8.4.4` |
| Cloudflare | `1.1.1.1` / `1.0.0.1` |

macOS 修改路径：**系统设置 → 网络 → 高级 → DNS**。

#### 方案 3：命令行使用代理

```bash
# 临时设置代理后运行
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
uv run streamlit run streamlit_app.py
```

### PyPI 镜像配置

首次安装依赖时若遇到 PyPI 连接问题（`tls handshake eof`、`Connection timeout`），可使用国内镜像：

```bash
# 临时使用清华镜像安装
uv add <包名> --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 或者永久配置（推荐）
uv add --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

> ⚠️ `--index-url` 只对单次命令生效，`--default-index` 会写入 `pyproject.toml` 持久化。

---

## 高级用法

### 命令行直接运行

Cookie 获取（不通过 Streamlit）：

```bash
uv run python xhs_cookie_grabcher.py
uv run python xhs_cookie_grabcher.py --headless          # 无头模式
uv run python xhs_cookie_grabcher.py --timeout 300       # 5分钟超时
uv run python xhs_cookie_grabcher.py -o ~/cookies.txt    # 指定输出路径
```

搜索笔记（不通过 Streamlit）：

```bash
uv run python xhs_new_search.py "热词" "a1=xxx; web_session=yyy"
uv run python xhs_new_search.py "热词" "cookie.." -n 20 -s popularity_descending
uv run python xhs_new_search.py "热词" "cookie.." -o results.json -c all
uv run python xhs_new_search.py "" "cookie.." -l 结果文件.md -c 1,3,5
```

### 配置持久化镜像源

```bash
uv add --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

这会修改 `pyproject.toml`，后续所有 `uv add` / `uv sync` 都会使用该镜像。

---

## 技术说明

- **签名机制**：小红书 API 需要 `X-s`、`X-t`、`X-s-common` 签名头，由 `xhshow` 库根据 `a1` Cookie 和时间戳生成
- **TLS 指纹**：`curl-cffi` 模拟 Chrome 131 的 TLS 指纹（`impersonate="chrome131"`），绕过反爬检测
- **持久化登录**：Playwright 浏览器上下文保存在 `.browser-data/` 目录，下次可复用登录态，无需重复扫码
