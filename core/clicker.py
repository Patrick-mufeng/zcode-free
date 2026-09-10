"""鼠标点击:把归一化坐标换算成屏幕物理像素后点击。

pyautogui.FAILSAFE = True:把鼠标甩到屏幕左上角可紧急中止。
"""
from __future__ import annotations

import pyautogui
from loguru import logger

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def click_screen(x: float, y: float, humanize: bool = False) -> tuple[int, int]:
    screen_w, screen_h = pyautogui.size()
    px = max(0, min(int(round(x)), screen_w - 1))
    py = max(0, min(int(round(y)), screen_h - 1))
    if humanize:
        pyautogui.moveTo(px, py, duration=0.3)
    else:
        pyautogui.moveTo(px, py, duration=0.05)
    pyautogui.click()
    logger.info(f"已点击屏幕坐标 ({px}, {py})")
    return px, py


def click_norm(rect: tuple[int, int, int, int], box: tuple[float, float, float, float],
               humanize: bool = False) -> tuple[int, int]:
    """box 为归一化 (x1,y1,x2,y2),rect 为窗口屏幕坐标 (x,y,w,h)。"""
    x, y, w, h = rect
    center_x = (box[0] + box[2]) / 2.0
    center_y = (box[1] + box[3]) / 2.0
    return click_screen(x + center_x * w, y + center_y * h, humanize=humanize)
