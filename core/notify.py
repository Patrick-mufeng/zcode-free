"""通知:Windows Toast(免第三方依赖,经 PowerShell WinRT)+ 可选 webhook。"""
from __future__ import annotations

import base64
import json
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


def _is_feishu(url: str) -> bool:
    """飞书 / Lark 自定义机器人 webhook(两家域名都认)。"""
    lowered = (url or "").lower()
    return "open.feishu.cn" in lowered or "open.larksuite.com" in lowered


def _feishu_payload(title: str, message: str) -> dict:
    """飞书要求显式 msg_type,缺了会直接报 19002 params error。

    用 post 富文本:标题与正文分开,和桌面通知的观感一致。
    """
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": str(title),
                    "content": [[{"tag": "text", "text": str(message)}]],
                }
            }
        },
    }


def _generic_payload(title: str, message: str) -> dict:
    """Server 酱 / 企业微信机器人等:它们各自认其中一个字段,一次都带上即可。"""
    return {"title": title, "text": message, "content": message, "desp": message}


def _response_error(text: str) -> str | None:
    """从响应体里提取错误信息,正常时返回 None。

    必须查响应体,不能只看 HTTP 状态码:飞书出错时(如密钥失效、内容为空)
    依然返回 200,只有 body 里的 code 非 0 才是真的失败。
    """
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # 飞书/Lark:code 为 0 表示成功;企业微信:errcode 为 0
    for key in ("code", "errcode", "StatusCode"):
        if key in data:
            try:
                code = int(data[key])
            except (TypeError, ValueError):
                continue
            if code != 0:
                return str(data.get("msg") or data.get("errmsg") or data.get("StatusMessage") or data)
            return None
    if data.get("ok") is False:
        return str(data.get("message") or data)
    return None


def webhook(url: str, title: str, message: str, timeout: float = 10.0) -> tuple[bool, str]:
    """通用 webhook 推送,返回 (是否成功, 说明)。

    按目标站点选格式:飞书/Lark 走它自己的 post 结构,其余按通用 JSON 发。
    失败原因带回给调用方,便于在面板上直接看到"为什么没收到通知"。
    """
    if not url:
        return False, "未配置 webhook 地址"
    payload = _feishu_payload(title, message) if _is_feishu(url) else _generic_payload(title, message)
    try:
        resp = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        logger.debug(f"webhook 通知失败:{exc}")
        return False, f"请求失败:{exc}"

    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}:{resp.text[:200]}"
    error = _response_error(resp.text)
    if error:
        return False, f"服务端拒绝:{error}"
    return True, "推送成功"


def send(cfg: ConfigStore, title: str, message: str) -> dict:
    """按配置发通知,返回各渠道的执行结果(供「发送测试通知」直接展示)。"""
    results = {"desktop": None, "webhook": None}
    if cfg.get("notify", "desktop"):
        results["desktop"] = desktop(title, message)
    url = (cfg.get("notify", "webhook_url") or "").strip()
    if url:
        ok, detail = webhook(url, title, message)
        results["webhook"] = {"ok": ok, "message": detail}
    return results


def notify(cfg: ConfigStore, title: str, message: str) -> None:
    if cfg.get("app", "dry_run"):
        logger.info(f"[演练模式] 跳过通知:{title} | {message}")
        return
    if cfg.get("notify", "desktop"):
        desktop(title, message)
    url = (cfg.get("notify", "webhook_url") or "").strip()
    if url:
        ok, detail = webhook(url, title, message)
        if ok:
            logger.info(f"webhook 已推送:{title}")
        else:
            logger.warning(f"webhook 推送失败:{detail}")
