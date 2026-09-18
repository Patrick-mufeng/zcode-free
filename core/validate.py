"""判定逻辑:把视觉模型的返回转成明确的动作决策。

词表匹配只扫描模型给出的结构化字段(keywords / ocr_texts / button_label),
不扫描 notes —— notes 是模型自己的解释性文字,极易误命中("没有出现+X")。

配置读取约定:执行器传入的是 **普通 dict**(`cfg.all()`),而面板侧可能是
ConfigStore,因此统一走下面的 `_cfg()` 兼容读取,避免两种签名互相踩坑。
"""
from __future__ import annotations

# 判定结果
RETRY = "retry"        # 本次未成功,走重开重试
CLAIM = "claim"        # 可以点击领取
ALREADY = "claimed"    # 已领取过,按成功收尾
SUCCESS = "success"    # 领取成功
FAILED = "failed"      # 明确失败(弹窗提示"领取失败 / 知道了")
MANUAL = "manual"      # 需人工处理(登录页/验证码等),停止本场
PENDING = "pending"    # 已提交、界面仍在加载:继续等结果,不算失败
NO_CARD = "no_card"    # 福利卡片不在画面上:需复查确认后再收敛,不直接重开客户端

# 结果弹窗:模型用 popup 字段给出的明确结论
POPUP_SUCCESS = ("success", "succeeded", "ok", "成功")
POPUP_FAILURE = ("failure", "failed", "fail", "error", "失败")
POPUP_PENDING = ("pending", "loading", "processing", "等待", "加载中")


def _cfg(cfg, key: str, default=None):
    """兼容读取:普通 dict 与 ConfigStore(多键 get)都能用。"""
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    getter = getattr(cfg, "get", None)
    if callable(getter):
        try:
            value = getter(key, default=default)
        except TypeError:      # 某些实现的 get 不接受 default 关键字
            value = getter(key)
        return default if value is None else value
    return default


def normalize_box(box, img_w: int, img_h: int) -> tuple[float, float, float, float] | None:
    """把模型返回的框统一成归一化 (x1,y1,x2,y2)。

    容错:模型可能返回 0~1 归一化值、0~100 百分比或像素值,这里逐一识别。
    """
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        vals = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if any(v != v for v in vals):  # NaN
        return None

    peak = max(vals)
    if peak <= 1.01:                                   # 已经是归一化
        norm = vals
    elif peak <= 100.01:                               # 百分比
        norm = [v / 100.0 for v in vals]
    elif img_w > 0 and img_h > 0:                      # 像素值(按发送图片尺寸换算)
        norm = [vals[0] / img_w, vals[1] / img_h, vals[2] / img_w, vals[3] / img_h]
    else:
        return None

    x1, y1, x2, y2 = norm
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    x1, x2 = max(0.0, min(x1, 1.0)), max(0.0, min(x2, 1.0))
    y1, y2 = max(0.0, min(y1, 1.0)), max(0.0, min(y2, 1.0))
    if x2 - x1 <= 0 or y2 - y1 <= 0:
        return None
    return (x1, y1, x2, y2)


def _blob(res: dict) -> str:
    parts: list[str] = []
    for key in ("keywords", "ocr_texts"):
        value = res.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
    for key in ("button_label", "text", "label"):
        value = res.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts)


def _confidence(res: dict) -> float:
    try:
        return float(res.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_any(blob: str, keywords) -> bool:
    return any(k and k in blob for k in (keywords or []))


def judge_locate(res: dict, cfg) -> str:
    """点击前:判断页面状态与是否可点。cfg 为普通 dict 或 ConfigStore。"""
    if not res or res.get("error"):
        return RETRY

    scene = str(res.get("scene") or "").lower()
    blob = _blob(res)

    if scene in ("login", "captcha", "verify", "risk"):
        return MANUAL
    if res.get("already_claimed") is True:
        return ALREADY
    if _has_any(blob, _cfg(cfg, "claimed_keywords") or []):
        return ALREADY

    vision = _cfg(cfg, "vision") or {}
    min_conf = float(vision.get("locate_confidence_min", 0.7) or 0.7)
    if (
        res.get("button_found") is True
        and res.get("claimable") is not False
        and res.get("button_box")
        and _confidence(res) >= min_conf
    ):
        return CLAIM

    # 卡片明确不在画面上:当前没有可领的福利(本期已领完 / 活动结束 / 卡片被关掉)。
    # 再关客户端重开也变不出卡片,只会白跑一串重试并反复杀客户端。但卡片有可能比
    # 主界面晚渲染,所以不直接下结论,交给调用方复查一次再收敛(见 runner)。
    # 只在模型明确回答 False 时采信(字段缺失/为 None 都不算),避免把"没看到"当"不存在"。
    if res.get("card_visible") is False:
        return NO_CARD
    return RETRY


def judge_verify(res: dict, cfg, clicked: bool = False) -> str:
    """点击后:判断领取结果。cfg 为普通 dict 或 ConfigStore。

    主证据是结果弹窗(成功含「领取成功 + 开始体验」,失败含「领取失败 + 知道了」),
    其次是结构化字段与词表。词表只扫 keywords / ocr_texts 等字段,不扫 notes。

    注意 PENDING:点击后服务端要走一段发放流程(实测约 40 秒),这期间界面停在
    加载动画上、关键字也认不出——它是"还没出结果"而不是"失败",调用方应继续等,
    不能据此判定未成功去关客户端重试。

    clicked 表示本次确实点过按钮(演练模式不点)。点过之后福利卡片整张消失,是
    "该次领取已被消费"的旁证:实测领取后卡片会被移除,而此时也没有任何结果弹窗
    可读——没有这个旁证就只能记成失败并白跑一轮重试。
    """
    if not res or res.get("error"):
        return RETRY

    blob = _blob(res)
    popup = str(res.get("popup") or "").strip().lower()

    # ① 弹窗/字段给出的明确结论优先
    if res.get("success") is True or popup in POPUP_SUCCESS:
        return SUCCESS
    if res.get("failed") is True or popup in POPUP_FAILURE:
        return FAILED

    # ② 还在加载/发放中 → 继续等,不算失败(必须在词表之前,避免被当作无结果)
    if res.get("pending") is True or popup in POPUP_PENDING:
        return PENDING
    if _has_any(blob, _cfg(cfg, "loading_keywords") or []):
        return PENDING

    # ③ 没有明确结论时退回词表
    if res.get("claimed") is True or _has_any(blob, _cfg(cfg, "claimed_keywords") or []):
        return ALREADY
    if _has_any(blob, _cfg(cfg, "success_keywords") or []):
        return SUCCESS
    if _has_any(blob, _cfg(cfg, "failure_keywords") or []):
        return FAILED

    # ④ 点过之后卡片整张不见了:按已领取收尾(不重试,避免重复点击与无谓重启)
    if clicked and res.get("card_visible") is False:
        return ALREADY
    return RETRY
