"""防休眠:场次执行期阻止系统睡眠,否则到点了进程还醒着、调度却不会触发。

两种模式(来源于设置页的 schedule.keep_awake 与执行时机):
  always     程序运行期间一直保活(默认)。显示器一起保持,因为屏幕一黑
             mss 截到的是黑图,视觉识别必然失败。
  execution  只在执行场次前后保活(调用 start()/stop() 圈定范围)。

实现:SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)。
注意该 API 是"按线程"生效的,所以保活状态挂在调用它的那个线程上:
- always 模式在启动时由主线程设置,主线程全程存活,状态一直有效;
- execution 模式在 runner 的执行线程里设置与清除。

它阻止不了锁屏:锁屏是安全策略而非电源策略,需要在系统设置里把
"屏幕保护/锁屏超时"关掉(见打包方案 §3.1)。
"""
from __future__ import annotations

import ctypes
import threading
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_FLAGS = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED

_lock = threading.RLock()
_always_on = False          # always 模式是否已开启
_exec_depth = 0             # execution 模式的嵌套计数


def _apply(flags: int) -> bool:
    """把执行状态推给系统;非 Windows 或调用失败返回 False。"""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
        kernel32.SetThreadExecutionState.restype = ctypes.c_uint
        # 返回 0 表示失败;成功时返回上一个状态值(非 0)
        return bool(kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))
    except Exception:
        return False


def set_always(enabled: bool) -> bool:
    """常驻保活开关(程序启动时按配置调用一次)。"""
    global _always_on
    with _lock:
        ok = _apply(_FLAGS if enabled else ES_CONTINUOUS)
        if ok:
            _always_on = bool(enabled)
        return ok


def start_execution() -> bool:
    """进入一次执行场次,开始保活(可嵌套)。"""
    global _exec_depth
    with _lock:
        _exec_depth += 1
        if _exec_depth == 1 and not _always_on:
            return _apply(_FLAGS)
        return True


def stop_execution() -> bool:
    """执行场次结束。仍有外层嵌套或 always 模式开着时不解除保活。"""
    global _exec_depth
    with _lock:
        if _exec_depth > 0:
            _exec_depth -= 1
        if _exec_depth == 0 and not _always_on:
            return _apply(ES_CONTINUOUS)
        return True


def is_active() -> bool:
    """当前是否处于保活状态(供自检与日志判断,不代表系统真的接受了)。"""
    with _lock:
        return _always_on or _exec_depth > 0
