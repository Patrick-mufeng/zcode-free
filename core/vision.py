"""DeepSeek 视觉模型封装(OpenAI 兼容 /chat/completions)。

设计要点(见技术方案 §3.1 / §6.4):
- 只发裁剪后的窗口图,坐标要求归一化 0~1;
- 结构化输出三重保障:prompt 含 json + response_format + 本地 JSON 修复;
- 网络错误退避重试,失败返回 {"error": ...},"unknown 不瞎点"。
"""
from __future__ import annotations

import base64
import json
import re
import time
from io import BytesIO

import httpx
from loguru import logger
from PIL import Image

from core.config import ConfigStore

LOCATE_PROMPT = """你是桌面软件自动化助手。图片是 ZCode 客户端窗口的截图。
任务:在图中找到「领取」按钮并判断页面状态。

先认清目标:福利入口不是独立页面,而是一张**浮在界面上方的推广卡片**,位置固定在
**窗口左下角**(通常在侧边栏底部、用户头像上方)。卡片特征:
- 含 "ZCODE" 与 "Weekend Build"(或类似的期次名)字样;
- 有大号数字如 "300,000,000 Tokens";
- 右下角有一个**小圆形/胶囊形的「领取」按钮**(可能更小,文字也可能是 领取/立即领取/收下)。
这张卡片可能出现在任意页面上,不要只在"福利页"里找,也不要因为当前是对话主页就判定没有。

规则:
1. 忽略窗口标题栏与无关元素。
2. 领取按钮特征:可点击按钮,文字含 领取/领/收下/立即领取/签到领取 之一;
   若按钮置灰不可点,或文字为 已领取/明日再来/已签到/次数已用完,视为不可领。
3. 结果弹窗会遮挡领取按钮:若画面中出现弹窗(含 领取成功/开始体验 或 领取失败/知道了),
   说明上一次操作的弹窗还没关闭 —— 此时 button_found 设为 false、button_box 设为 null、
   claimable 设为 false,并把弹窗上的文字原样写进 ocr_texts。
4. button_box 输出相对整张图片的归一化坐标(0~1 小数,左上角为 0,0),不要输出像素值。
   按钮很小,框要紧贴按钮本身,不要框住整张卡片。
5. card_visible:上述推广卡片此刻是否在画面上(在=true,不在=false)。
   卡片不在画面上时,button_found 必须为 false。
6. ocr_texts 里把卡片上看到的文字(如 "300,000,000 Tokens"、"领取")原样写上,
   便于下游判断卡片是否出现过。
7. 只输出 json,不要输出任何其他文字。

输出示例:
{"scene":"welfare","claimable":true,"already_claimed":false,"card_visible":true,
 "button_found":true,"button_label":"领取","button_box":[0.089,0.909,0.106,0.93],
 "ocr_texts":["ZCODE Weekend Build","300,000,000 Tokens","领取"],
 "confidence":0.92,"notes":"左下角推广卡片内右下角有可点击的领取按钮"}
"""

VERIFY_PROMPT = """你是桌面软件自动化助手。图片是点击「领取」按钮之后 ZCode 客户端窗口的截图。
任务:判断这次领取的结果。结果可能以弹窗形式给出,也可能还在加载中。

先认清要观察的「福利卡片」:通常在窗口左下角,是一张推广卡片,含 "ZCODE / Weekend Build"
"300,000,000 Tokens" 等字样,右下角有一个「领取」胶囊按钮。

判断:
- 成功弹窗:含「领取成功」文字,并带有一个「开始体验」按钮。
- 失败弹窗:含「领取失败」文字,并带有一个「知道了」按钮。
- 加载中:卡片仍在,但「领取」按钮变成转圈的加载图标,或出现「领取中 / 处理中 / 请稍候 /
  发放中」等字样,页面其他内容与点击前一致——这表示请求已提交、服务端还在处理。
- 卡片消失:整个福利卡片(含 Tokens 字样)从画面上不见了,且没有成功/失败弹窗。
规则:
1. 看到「领取成功」或「开始体验」→ success 为 true,failed 为 false,popup 为 "success"。
2. 看到「领取失败」或「知道了」→ failed 为 true,success 为 false,popup 为 "failure"。
3. 处于加载中(如上)→ pending 为 true,popup 为 "pending",success 与 failed 都为 false;
   并把看到的加载文案原样写进 keywords。注意:加载中不等于失败,不要报 failed。
   实测这个加载过程可能持续数十秒,只要还在转圈就一律算 pending。
4. 既没有弹窗、也不在加载中时:文案含 已领取/今日已领/明天再来/今日份已领完 → claimed 为 true;
   页面与点击前无明显变化 → success、failed 都为 false,popup 为 null。
5. card_visible:福利卡片此刻是否还在画面上(在=true,不在=false)。即使卡片在弹窗后面
   或只露出一点,也算 true;整张卡片确实没了才填 false。
6. keywords 只填图上真实出现的关键词,例如 ["领取成功","开始体验"]。
7. 只输出 json,不要输出任何其他文字。

输出示例:
{"success":true,"failed":false,"claimed":false,"pending":false,"card_visible":false,
 "popup":"success","keywords":["领取成功","开始体验"],"confidence":0.95,
 "notes":"弹出领取成功弹窗,含开始体验按钮"}
"""

_STRICT_SUFFIX = "\n注意:只输出一个 json 对象,不要输出任何解释文字。"


def parse_json(text: str) -> dict | None:
    """从模型输出中抽取 JSON:去代码围栏 → 直接解析 → 平衡括号截取。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(t)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                frag = t[start : i + 1]
                for candidate in (frag, frag.replace("'", '"')):
                    try:
                        parsed = json.loads(candidate)
                        return parsed if isinstance(parsed, dict) else None
                    except Exception:
                        continue
                return None
    return None


class VisionClient:
    def __init__(self, cfg: ConfigStore):
        self.cfg = cfg

    # ---------- 对外 ----------

    def locate(self, png: bytes) -> dict:
        res = self.chat(LOCATE_PROMPT, png)
        logger.debug(f"定位结果:{json.dumps(res, ensure_ascii=False)}")
        return res

    def verify(self, png: bytes) -> dict:
        res = self.chat(VERIFY_PROMPT, png)
        logger.debug(f"校验结果:{json.dumps(res, ensure_ascii=False)}")
        return res

    def test_connection(self) -> dict:
        vision = self.cfg.get("vision") or {}
        if not (vision.get("api_key") or "").strip():
            return {"ok": False, "message": "未配置 API Key"}
        buf = BytesIO()
        Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, "PNG")
        start = time.time()
        res = self.chat('这是一张测试图片。只输出 json:{"ok": true}', buf.getvalue())
        ms = int((time.time() - start) * 1000)
        if res.get("error"):
            return {"ok": False, "ms": ms, "message": str(res["error"])}
        return {"ok": True, "ms": ms, "message": f"连接正常,耗时 {ms} ms,模型已返回:{json.dumps(res, ensure_ascii=False)[:120]}"}

    # ---------- 核心请求 ----------

    def chat(self, prompt: str, png: bytes) -> dict:
        vision = self.cfg.get("vision") or {}
        api_key = (vision.get("api_key") or "").strip()
        if not api_key:
            return {"error": "未配置 API Key", "confidence": 0}

        b64 = base64.b64encode(png).decode("ascii")
        url = (vision.get("base_url") or "https://api.deepseek.com").rstrip("/") + "/chat/completions"
        timeout = float(vision.get("timeout_s") or 20)
        body = {
            "model": vision.get("model") or "deepseek-v4-flash-vision-exp",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": vision.get("detail") or "auto",
                            },
                        },
                    ],
                }
            ],
            "temperature": float(vision.get("temperature") or 0.2),
            "max_tokens": int(vision.get("max_tokens") or 800),
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        last_error = "未知错误"
        strict = False
        for attempt in range(3):
            if strict:
                body["messages"][0]["content"][0]["text"] = prompt + _STRICT_SUFFIX
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
            except Exception as exc:
                last_error = f"网络错误:{exc}"
                logger.warning(f"视觉 API 请求失败({attempt + 1}/3):{exc}")
                time.sleep(1.2)
                continue

            # 模型不支持 response_format 时自动去掉重试
            if resp.status_code == 400 and "response_format" in body and "response_format" in resp.text:
                logger.warning("接口不支持 response_format 参数,已去掉后重试")
                body.pop("response_format", None)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code}"
                logger.warning(f"视觉 API 暂时不可用({resp.status_code}),稍后重试")
                time.sleep(1.5)
                continue
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}:{resp.text[:200]}"
                logger.error(f"视觉 API 报错:{last_error}")
                break

            try:
                content = resp.json()["choices"][0]["message"].get("content") or ""
            except Exception as exc:
                last_error = f"响应解析失败:{exc}"
                logger.warning(last_error)
                continue

            parsed = parse_json(content)
            if parsed is None:
                last_error = "模型未返回有效 json"
                logger.warning(f"JSON 解析失败,严格模式重试;原文:{content[:120]!r}")
                strict = True
                continue
            parsed.setdefault("confidence", 0)
            return parsed

        return {"error": last_error, "confidence": 0}
