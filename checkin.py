#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DZZI.AI (New API) 自动签到脚本

支持功能：
- 多账号批量签到
- 飞书/Lark/Server 酱/Telegram/Bark 推送结果
- 签到前先查询状态，已签到则跳过
- GitHub Actions / 本地 / 任意 Linux cron 通用

API 路径（参考 QuantumNous/new-api controller/checkin.go）：
- 登录:    POST /api/user/login
- 状态:    GET  /api/user/checkin
- 执行:    POST /api/user/checkin
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_BASE_URL = "https://api.dzzi.ai"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def log(level: str, msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}", flush=True)


def quota_to_yuan(quota: int) -> float:
    """new-api 内 1 元 = 500000 quota。"""
    if quota is None:
        return 0.0
    return round(quota / 500000, 5)


def parse_accounts(raw: str) -> List[Dict[str, str]]:
    """
    支持两种账号配置方式：
    1. JSON 数组：   '[{"username":"a","password":"b"}]'
    2. 换行/分号分隔： user1|pwd1\\nuser2|pwd2  或  user1:pwd1;user2:pwd2
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        data = json.loads(raw)
        accounts: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("username") and item.get("password"):
                accounts.append({
                    "username": str(item["username"]).strip(),
                    "password": str(item["password"]).strip(),
                    "base_url": str(item.get("base_url") or DEFAULT_BASE_URL).strip(),
                })
        return accounts

    accounts = []
    for line in raw.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 同时支持 : 与 | 分隔
        sep = "|" if "|" in line else (":" if ":" in line else None)
        if not sep:
            continue
        user, pwd = line.split(sep, 1)
        accounts.append({
            "username": user.strip(),
            "password": pwd.strip(),
            "base_url": DEFAULT_BASE_URL,
        })
    return accounts


# ---------------------------------------------------------------------------
# 签到核心
# ---------------------------------------------------------------------------
class DzziClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self.user_id: Optional[int] = None
        self.display_name: Optional[str] = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        url = self._url(path)
        try:
            resp = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            return {"success": False, "message": f"网络异常: {exc}"}, -1
        try:
            data = resp.json()
        except ValueError:
            data = {"success": False, "message": f"非 JSON 响应 (HTTP {resp.status_code})"}
        return data, resp.status_code

    def login(self) -> bool:
        """登录拿 session。turnstile 留空即可（dzzi 未启用）。"""
        data, code = self._request(
            "POST",
            "/api/user/login",
            params={"turnstile": ""},
            json_body={"username": self.username, "password": self.password},
        )
        if not data.get("success"):
            log("ERROR", f"[{self.username}] 登录失败: {data.get('message')}")
            return False
        payload = data.get("data") or {}
        self.user_id = payload.get("id")
        self.display_name = payload.get("display_name") or self.username
        log("INFO", f"[{self.username}] 登录成功 (id={self.user_id}, name={self.display_name})")
        return True

    def get_status(self) -> Optional[Dict[str, Any]]:
        if not self.user_id:
            return None
        data, _ = self._request(
            "GET",
            "/api/user/checkin",
        )
        # 兼容 GET 自动带上 New-Api-User
        if not data.get("success") and "header not provided" in str(data.get("message")):
            self.session.headers["New-Api-User"] = str(self.user_id)
            data, _ = self._request("GET", "/api/user/checkin")
        if not data.get("success"):
            log("ERROR", f"[{self.username}] 查询签到状态失败: {data.get('message')}")
            return None
        return data.get("data") or {}

    def do_checkin(self) -> Dict[str, Any]:
        if not self.user_id:
            return {"success": False, "message": "未登录"}
        self.session.headers.setdefault("New-Api-User", str(self.user_id))
        data, _ = self._request("POST", "/api/user/checkin", params={"turnstile": ""})
        return data


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
def send_notifier(kind: str, token: str, title: str, content: str) -> None:
    if not token:
        return
    try:
        if kind in ("feishu", "lark", "飞书"):
            send_feishu(token, title, content)
        elif kind in ("serverchan", "server", "sct"):
            send_serverchan(token, title, content)
        elif kind == "telegram":
            send_telegram(token, title, content)
        elif kind == "bark":
            send_bark(token, title, content)
        else:
            log("WARN", f"未知的推送方式: {kind}")
    except Exception as exc:  # noqa: BLE001
        log("ERROR", f"推送失败 ({kind}): {exc}")


def send_feishu(token: str, title: str, content: str) -> None:
    """飞书自定义机器人。token 形如 https://open.feishu.cn/... 或纯 webhook url。"""
    url = token if token.startswith("http") else f"https://open.feishu.cn/open-apis/bot/v2/hook/{token}"
    body = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": content}],
        },
    }
    r = requests.post(url, json=body, timeout=15)
    log("INFO", f"飞书推送: HTTP {r.status_code}")


def send_serverchan(token: str, title: str, content: str) -> None:
    """Server 酱 (sct.ftqq.com / sct.dev)。token 支持 'SCTxxxxxx' 或完整 url。"""
    if token.startswith("http"):
        url = token
    else:
        url = f"https://sctapi.ftqq.com/{token}.send"
    r = requests.post(url, data={"title": title, "desp": content}, timeout=15)
    log("INFO", f"Server 酱推送: HTTP {r.status_code}")


def send_telegram(token: str, title: str, content: str) -> None:
    """token 形如 'BOT_TOKEN|CHAT_ID'。"""
    if "|" not in token:
        log("ERROR", "Telegram 推送需 BOT_TOKEN|CHAT_ID 格式")
        return
    bot_token, chat_id = token.split("|", 1)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": chat_id, "text": f"*{title}*\n\n{content}", "parse_mode": "Markdown"},
        timeout=15,
    )
    log("INFO", f"Telegram 推送: HTTP {r.status_code}")


def send_bark(token: str, title: str, content: str) -> None:
    """Bark：token 形如 'https://api.day.app/yourkey/' 或 'https://api.day.app/yourkey'。"""
    base = token.rstrip("/")
    url = f"{base}/{title}"
    r = requests.get(url, params={"body": content}, timeout=15)
    log("INFO", f"Bark 推送: HTTP {r.status_code}")


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------
def run_one(client: DzziClient) -> Dict[str, Any]:
    if not client.login():
        return {"ok": False, "msg": "登录失败"}

    status = client.get_status() or {}
    already = bool(status.get("stats", {}).get("checked_in_today"))

    if already:
        last = (status.get("stats", {}).get("records") or [{}])[0]
        msg = (
            f"账号 {client.display_name} 今日已签到，"
            f"上次奖励 {quota_to_yuan(last.get('quota_awarded', 0))} 元"
        )
        log("INFO", msg)
        return {"ok": True, "msg": msg, "quota_awarded": 0, "skipped": True}

    result = client.do_checkin()
    if not result.get("success"):
        msg = f"账号 {client.display_name} 签到失败：{result.get('message')}"
        log("ERROR", msg)
        return {"ok": False, "msg": msg}

    quota_awarded = (result.get("data") or {}).get("quota_awarded", 0)
    msg = f"账号 {client.display_name} 签到成功，获得 {quota_to_yuan(quota_awarded)} 元"
    log("INFO", msg)
    return {"ok": True, "msg": msg, "quota_awarded": quota_awarded, "skipped": False}


def main() -> int:
    raw_accounts = (
        os.environ.get("DZZI_ACCOUNTS")
        or os.environ.get("ACCOUNTS")
        or os.environ.get("DZZI")
        or ""
    )
    notifier_kind = os.environ.get("NOTIFIER", "").strip()
    notifier_token = os.environ.get("NOTIFIER_TOKEN", "").strip()

    accounts = parse_accounts(raw_accounts)
    if not accounts:
        log("ERROR", "未找到账号配置。请设置 DZZI_ACCOUNTS 环境变量。")
        return 1

    log("INFO", f"共加载 {len(accounts)} 个账号，开始签到…")

    results: List[Dict[str, Any]] = []
    for acc in accounts:
        client = DzziClient(
            base_url=acc.get("base_url", DEFAULT_BASE_URL),
            username=acc["username"],
            password=acc["password"],
        )
        try:
            results.append(run_one(client))
        except Exception as exc:  # noqa: BLE001
            log("ERROR", f"账号 {acc.get('username')} 异常: {exc}")
            results.append({"ok": False, "msg": str(exc)})
        time.sleep(2)  # 防止风控

    success_n = sum(1 for r in results if r["ok"])
    fail_n = len(results) - success_n

    summary_lines = [
        "## DZZI.AI 自动签到结果",
        f"- 总账号：{len(results)}",
        f"- 成功：{success_n}",
        f"- 失败：{fail_n}",
        "",
    ]
    for idx, r in enumerate(results, 1):
        summary_lines.append(f"{idx}. {'✅' if r['ok'] else '❌'} {r['msg']}")

    summary = "\n".join(summary_lines)
    print()
    print(summary)

    if notifier_kind and notifier_token:
        title = "DZZI.AI 签到" + (" 成功" if fail_n == 0 else f" {fail_n} 失败")
        send_notifier(notifier_kind, notifier_token, title, summary)

    return 0 if fail_n == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
