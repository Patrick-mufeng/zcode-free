"""日志:loguru 控制台 + 按天轮转文件 + 内存环形缓冲 + UI 事件推送。"""
from __future__ import annotations

import sys
import threading
from collections import deque

from loguru import logger

from core.config import LOG_DIR
from core.events import EventBus

# 供 UI「实时日志」查询的环形缓冲
LOG_RING: deque[dict] = deque(maxlen=2000)
_ring_lock = threading.Lock()

_FMT_CONSOLE = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<level>{message}</level>"
)


def _ring_sink(message) -> None:
    rec = message.record
    item = {
        "ts": rec["time"].strftime("%Y-%m-%d %H:%M:%S"),
        "level": rec["level"].name,
        "message": rec["message"],
    }
    with _ring_lock:
        LOG_RING.append(item)


def get_logs(limit: int = 300, level: str | None = None, keyword: str = "") -> list[dict]:
    """读取最近日志(供 UI),按需过滤级别/关键词。"""
    with _ring_lock:
        items = list(LOG_RING)
    items.reverse()
    out = []
    for item in items:
        if level and item["level"] != level:
            continue
        if keyword and keyword.lower() not in item["message"].lower():
            continue
        out.append(item)
        if len(out) >= limit:
            break
    out.reverse()
    return out


def setup_logging(bus: EventBus | None = None, keep_days: int = 7, level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, format=_FMT_CONSOLE, colorize=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        LOG_DIR / "app-{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention=f"{max(int(keep_days), 1)} days",
        encoding="utf-8",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
        enqueue=True,  # 多线程写入安全
    )
    logger.add(_ring_sink, level="INFO")
    if bus is not None:
        def _bus_sink(message) -> None:
            rec = message.record
            bus.publish(
                "log_line",
                {
                    "ts": rec["time"].strftime("%H:%M:%S"),
                    "level": rec["level"].name,
                    "message": rec["message"],
                },
            )

        logger.add(_bus_sink, level="INFO")


def log():
    return logger
