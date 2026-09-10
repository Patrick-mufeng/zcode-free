"""通知:Windows Toast(免第三方依赖,经 PowerShell WinRT)+ 可选 webhook。"""
from __future__ import annotations

import base64
import subprocess

import httpx
from loguru import logger

from core.config import ConfigStore

_PS_TEMPLATE = """
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode('{title}')) | Out-Null
$texts.Item(1).AppendChild($template.CreateTextNode('{message}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ZCode福利助手').Show($toast)
"""


def _escape_ps(text: str) -> str:
    return str(text).replace("'", "''")


def desktop(title: str, message: str, timeout: float = 15.0) -> bool:
    """发 Windows 桌面通知(PowerShell -EncodedCommand,规避中文编码问题)。"""
    script = _PS_TEMPLATE.format(title=_escape_ps(title), message=_escape_ps(message))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            errors="replace",   # PowerShell 可能回 GBK 文本,避免 UTF-8 模式下解码报错
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            logger.debug(f"桌面通知发送失败:{result.stderr.strip()[:200]}")
            return False
        return True
    except Exception as exc:
        logger.debug(f"桌面通知异常:{exc}")
        return False


def webhook(url: str, title: str, message: str, timeout: float = 10.0) -> bool:
    """通用 webhook(Server酱/企业微信机器人等均接受 JSON POST)。"""
    if not url:
        return False
    try:
        resp = httpx.post(
            url,
            json={"title": title, "text": message, "content": message, "desp": message},
            timeout=timeout,
        )
        return resp.status_code < 400
    except Exception as exc:
        logger.debug(f"webhook 通知失败:{exc}")
        return False


def notify(cfg: ConfigStore, title: str, message: str) -> None:
    if cfg.get("app", "dry_run"):
        logger.info(f"[演练模式] 跳过通知:{title} | {message}")
        return
    if cfg.get("notify", "desktop"):
        desktop(title, message)
    url = (cfg.get("notify", "webhook_url") or "").strip()
    if url:
        webhook(url, title, message)
