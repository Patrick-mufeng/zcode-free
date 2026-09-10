"""极简事件总线:执行器/调度器发布,UI 桥与日志订阅。

事件类型见 UI 设计文档 §11:state_change / exec_start / step_update /
attempt_update / log_line / need_manual。
"""
from __future__ import annotations

import threading
from typing import Any, Callable


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: list[Callable[[str, Any], None]] = []

    def subscribe(self, fn: Callable[[str, Any], None]) -> Callable[[], None]:
        """注册订阅者,返回取消订阅函数。"""
        with self._lock:
            self._subs.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._subs:
                    self._subs.remove(fn)

        return unsubscribe

    def publish(self, event_type: str, payload: Any = None) -> None:
        with self._lock:
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(event_type, payload)
            except Exception:
                # 订阅者异常不允许影响主流程
                pass
