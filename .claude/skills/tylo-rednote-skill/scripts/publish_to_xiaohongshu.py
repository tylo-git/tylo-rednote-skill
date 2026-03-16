#!/usr/bin/env python3
"""
小红书 MCP 自动发布脚本
通过 HTTP 直接与 xiaohongshu-mcp 服务通信，支持超时重试和错误处理。
"""

import argparse
import io
import json
import os
import re
import sys
import time
import requests

# 修复 Windows 控制台中文编码问题（cp1252 无法输出中文）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


MCP_URL = os.environ.get("XHS_MCP_URL", "http://localhost:18060/mcp")
MAX_RETRIES = 3
PUBLISH_TIMEOUT = 1200  # 发布超时 20 分钟
LOGIN_CHECK_TIMEOUT = 30
INIT_TIMEOUT = 15

# Docker 容器内图片目录前缀
DOCKER_IMAGE_PREFIX = "/app/images/"

# Git Bash 路径转换的典型特征（/app/ 被转成 C:/Program Files/Git/app/）
GIT_BASH_MANGLED_PATTERN = re.compile(r"^[A-Za-z]:[/\\].*[/\\]Git[/\\]app[/\\]images[/\\]", re.IGNORECASE)

# Windows 绝对路径特征
WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:[/\\]")


def log(msg):
    print(f"[xiaohongshu] {msg}", flush=True)


def log_error(msg):
    print(f"[xiaohongshu] ERROR: {msg}", file=sys.stderr, flush=True)


def fix_image_path(path):
    """
    修复图片路径，确保是 Docker 容器内路径（/app/images/xxx.png）。

    处理以下情况：
    1. Git Bash 路径转换：/app/images/a.png → C:/Program Files/Git/app/images/a.png
    2. Windows 本地绝对路径：E:/LLMproject/.../images/a.png
    3. 已经是正确的 Docker 路径：/app/images/a.png → 不变
    """
    original = path

    # 情况 1：Git Bash 自动路径转换（/app/ → C:/Program Files/Git/app/）
    if GIT_BASH_MANGLED_PATTERN.match(path):
        filename = os.path.basename(path)
        fixed = DOCKER_IMAGE_PREFIX + filename
        log(f"  路径修复 (Git Bash 转换): {original} -> {fixed}")
        return fixed

    # 情况 2：Windows 绝对路径
    if WINDOWS_PATH_PATTERN.match(path):
        filename = os.path.basename(path)
        fixed = DOCKER_IMAGE_PREFIX + filename
        log(f"  路径修复 (Windows 路径): {original} -> {fixed}")
        return fixed

    # 情况 3：已经是 Docker 容器内路径，无需修复
    return path


def check_mcp_server():
    """检查 MCP 服务是否可达"""
    try:
        resp = requests.get(MCP_URL, timeout=5)
        return True
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        # 有些 MCP 服务器对 GET 返回错误，但说明服务是通的
        return True


def init_session():
    """初始化 MCP 会话，返回 session 和 headers"""
    session = requests.Session()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "tylo-rednote-publisher", "version": "1.0"},
        },
        "id": 1,
    }

    resp = session.post(MCP_URL, json=init_payload, headers=headers, timeout=INIT_TIMEOUT)
    resp.raise_for_status()

    session_id = resp.headers.get("mcp-session-id", "")
    if not session_id:
        # 尝试从响应体获取
        try:
            data = resp.json()
            session_id = data.get("result", {}).get("sessionId", "")
        except Exception:
            pass

    if not session_id:
        log("WARNING: 未获取到 mcp-session-id，继续尝试...")

    headers_with_session = {**headers}
    if session_id:
        headers_with_session["mcp-session-id"] = session_id

    # 发送初始化通知
    session.post(
        MCP_URL,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers=headers_with_session,
        timeout=INIT_TIMEOUT,
    )

    return session, headers_with_session


def call_tool(session, headers, tool_name, arguments, timeout=30, request_id=2):
    """调用 MCP 工具"""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": request_id,
    }

    resp = session.post(MCP_URL, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()

    data = resp.json()

    # 检查 JSON-RPC 错误
    if "error" in data:
        error = data["error"]
        raise Exception(f"MCP 工具调用失败: {error.get('message', str(error))}")

    # 提取结果文本
    result = data.get("result", {})
    content_list = result.get("content", [])
    texts = []
    for item in content_list:
        if item.get("type") == "text":
            texts.append(item.get("text", ""))

    return "\n".join(texts), result


def check_login(session, headers):
    """检查小红书登录状态"""
    log("检查登录状态...")
    text, result = call_tool(
        session, headers, "check_login_status", {}, timeout=LOGIN_CHECK_TIMEOUT
    )
    log(f"登录状态: {text[:200]}")

    # 判断是否已登录
    is_logged_in = "已登录" in text or "logged in" in text.lower() or "login" not in text.lower()
    return is_logged_in, text


def publish(session, headers, title, content, images, tags=None):
    """发布笔记到小红书"""
    # 修复所有图片路径，确保是 Docker 容器内路径
    fixed_images = [fix_image_path(img) for img in images]

    # 校验：所有路径必须以 /app/images/ 开头
    for img in fixed_images:
        if not img.startswith(DOCKER_IMAGE_PREFIX):
            log_error(f"图片路径无效（必须是 Docker 容器内路径 /app/images/xxx.png）: {img}")
            raise ValueError(f"无效的图片路径: {img}")

    arguments = {
        "title": title,
        "content": content,
        "images": fixed_images,
    }
    if tags:
        arguments["tags"] = tags

    log(f"正在发布笔记...")
    log(f"  标题: {title}")
    log(f"  正文长度: {len(content)} 字")
    log(f"  图片数量: {len(fixed_images)}")
    log(f"  图片路径: {fixed_images}")

    text, result = call_tool(
        session, headers, "publish_content", arguments, timeout=PUBLISH_TIMEOUT, request_id=5
    )

    return text, result


def main():
    parser = argparse.ArgumentParser(description="发布笔记到小红书")
    parser.add_argument("--title", required=True, help="笔记标题")
    parser.add_argument("--content", required=True, help="笔记正文（含话题标签）")
    parser.add_argument("--images", required=True, nargs="+", help="Docker 容器内图片路径列表，如 /app/images/fig1.png")
    parser.add_argument("--tags", nargs="*", default=None, help="话题标签列表（可选）")
    parser.add_argument("--mcp-url", default=None, help="MCP 服务 URL（默认 http://localhost:18060/mcp）")
    parser.add_argument("--dry-run", action="store_true", help="仅检查登录状态，不实际发布")

    args = parser.parse_args()

    if args.mcp_url:
        global MCP_URL
        MCP_URL = args.mcp_url

    # Step 1: 检查 MCP 服务
    log(f"检查 MCP 服务: {MCP_URL}")
    if not check_mcp_server():
        log_error(f"无法连接到 MCP 服务 ({MCP_URL})")
        log_error("请确保 Docker 容器已启动: docker compose up -d")
        sys.exit(1)
    log("MCP 服务可达 ✓")

    # Step 2: 初始化会话（带重试）
    session = None
    headers = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log(f"初始化 MCP 会话（尝试 {attempt}/{MAX_RETRIES}）...")
            session, headers = init_session()
            log("MCP 会话初始化成功 ✓")
            break
        except Exception as e:
            log_error(f"会话初始化失败: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2)
            else:
                log_error("会话初始化重试次数已用完，退出")
                sys.exit(1)

    # Step 3: 检查登录
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            is_logged_in, login_text = check_login(session, headers)
            break
        except Exception as e:
            log_error(f"登录检查失败: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2)
                try:
                    session, headers = init_session()
                except Exception:
                    pass
            else:
                log_error("登录检查重试次数已用完，退出")
                sys.exit(1)

    if not is_logged_in:
        log_error("未登录小红书！请先完成登录：")
        log_error("1. 运行 xiaohongshu-login 工具扫码登录")
        log_error("2. 或检查 data/cookies.json 是否有效")
        sys.exit(2)

    log("已登录小红书 ✓")

    if args.dry_run:
        log("dry-run 模式，跳过发布")
        sys.exit(0)

    # Step 4: 发布（带重试）
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            text, result = publish(session, headers, args.title, args.content, args.images, args.tags)
            log(f"发布结果: {text[:500]}")

            # 检查是否成功
            is_error = result.get("isError", False)
            if is_error:
                log_error(f"发布返回错误: {text}")
                if attempt < MAX_RETRIES:
                    log(f"等待后重试...")
                    time.sleep(5)
                    session, headers = init_session()
                    continue
                else:
                    sys.exit(1)

            log("发布成功！✓")
            sys.exit(0)

        except requests.exceptions.Timeout:
            log_error(f"发布超时（尝试 {attempt}/{MAX_RETRIES}）")
            if attempt < MAX_RETRIES:
                log("等待后重试...")
                time.sleep(5)
                try:
                    session, headers = init_session()
                except Exception:
                    pass
            else:
                log_error("发布超时，重试次数已用完")
                sys.exit(1)

        except requests.exceptions.ConnectionError:
            log_error(f"连接断开（尝试 {attempt}/{MAX_RETRIES}）")
            if attempt < MAX_RETRIES:
                log("等待后重试...")
                time.sleep(5)
                try:
                    session, headers = init_session()
                except Exception:
                    pass
            else:
                log_error("连接失败，重试次数已用完")
                sys.exit(1)

        except Exception as e:
            log_error(f"发布失败: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(3)
                try:
                    session, headers = init_session()
                except Exception:
                    pass
            else:
                sys.exit(1)


if __name__ == "__main__":
    main()
