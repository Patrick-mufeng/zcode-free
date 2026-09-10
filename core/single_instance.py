"""单实例保护:同一台机器只允许跑一个调度器。

为什么需要:两个实例会各自按场次触发,同一场次领取两次(点击行为翻倍),
还会互相抢前台窗口导致截图/点击错位。

实现:命名互斥锁(CreateMutexW)。名字用 Local\\ 前缀,限当前登录会话即可
(服务/多用户会话场景不在本项目范围内)。互斥锁随进程结束自动释放,
不需要显式清理——即使进程被强杀,内核也会回收。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

MUTEX_NAME = "Local\\ZCodeWelfareAssistant.SingleInstance"

# 已持有的互斥锁句柄。必须存成模块级,否则局部变量被回收后句柄可能被关闭。
_handle: int | None = None


def acquire() -> bool:
    """尝试获取单实例锁。

    返回 True 表示当前进程是唯一实例(或系统不支持时放行);
    返回 False 表示已有实例在跑,调用方应当提示用户后退出。
    """
    global _handle
    if sys.platform != "win32":
        return True                     # 非 Windows 不做限制(本项目只面向 Windows)
    if _handle is not None:
        return True                     # 同进程重复调用

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    err = ctypes.get_last_error()
    if not handle:
        # 创建失败(权限异常等):放行,不要因为保护逻辑本身把程序挡在门外
        return True
    if err == 183:                      # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _handle = handle
    return True


def release() -> None:
    """显式释放(正常退出时调用;进程结束也会自动释放)。"""
    global _handle
    if _handle is None:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle(wintypes.HANDLE(_handle))
    except Exception:
        pass
    finally:
        _handle = None
