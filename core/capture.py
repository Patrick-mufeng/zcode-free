"""截图:mss 全屏抓取 → 裁剪出 ZCode 窗口区域 → PNG 字节。

坐标体系:全流程使用 Windows 虚拟屏幕物理像素(进程已设 DPI Aware),
视觉模型返回归一化坐标,由 clicker 换算回该坐标系。
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from io import BytesIO

import mss
from PIL import Image


@dataclass
class Capture:
    png: bytes                      # 窗口裁剪图(PNG,直接发视觉 API)
    width: int
    height: int
    rect: tuple[int, int, int, int]  # 屏幕坐标 x, y, w, h
    uniform_ratio: float             # 最大单色占比,>0.95 视为锁屏/纯色
    full_size: tuple[int, int]


def desktop_locked() -> bool:
    """判断当前是否处于锁屏/安全桌面(锁屏、UAC 提示、Ctrl+Alt+Del 界面)。

    原理:这些界面由系统独占输入桌面,此时 OpenInputDesktop 会失败。
    用它替代"画面是纯色 ⇒ 锁屏"的推断——后者会把客户端的加载闪屏误判成锁屏。
    判断不出来时返回 False(宁可继续流程,也不误杀本场)。
    """
    try:
        user32 = ctypes.windll.user32
        handle = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not handle:
            return True
        user32.CloseDesktop(handle)
        return False
    except Exception:
        return False


def _uniform_ratio(img: Image.Image) -> float:
    hist = img.convert("L").histogram()
    total = sum(hist) or 1
    return max(hist) / total


def grab_region(rect: tuple[int, int, int, int] | list[int]) -> Capture:
    """截取虚拟屏幕并裁剪出 rect 区域;越界时按裁剪后的矩形为准(保证坐标映射一致)。"""
    x, y, w, h = (int(v) for v in rect)
    with mss.mss() as sct:
        monitor = sct.monitors[0]  # 所有显示器的并集
        shot = sct.grab(monitor)
        full = Image.frombytes("RGB", shot.size, shot.rgb)

    left = max(x, monitor["left"])
    top = max(y, monitor["top"])
    right = min(x + w, monitor["left"] + full.width)
    bottom = min(y + h, monitor["top"] + full.height)
    if right - left < 1 or bottom - top < 1:  # 极端情况:窗口完全在屏幕外
        left, top = monitor["left"], monitor["top"]
        right, bottom = left + min(2, full.width), top + min(2, full.height)

    crop = full.crop(
        (left - monitor["left"], top - monitor["top"],
         right - monitor["left"], bottom - monitor["top"])
    )
    buf = BytesIO()
    crop.save(buf, "PNG")
    return Capture(
        png=buf.getvalue(),
        width=crop.width,
        height=crop.height,
        rect=(left, top, right - left, bottom - top),
        uniform_ratio=_uniform_ratio(crop),
        full_size=(full.width, full.height),
    )


def grab_fullscreen() -> Capture:
    """截取主显示器(测试识别用,未找到 ZCode 窗口时的兜底)。"""
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)

    buf = BytesIO()
    img.save(buf, "PNG")
    return Capture(
        png=buf.getvalue(),
        width=img.width,
        height=img.height,
        rect=(monitor["left"], monitor["top"], monitor["width"], monitor["height"]),
        uniform_ratio=_uniform_ratio(img),
        full_size=(img.width, img.height),
    )


def thumbnail(png: bytes, width: int = 520, quality: int = 72) -> bytes:
    """生成 JPEG 缩略图(UI 列表用,避免传输大图)。"""
    img = Image.open(BytesIO(png))
    img.thumbnail((width, width * 3))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
