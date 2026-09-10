"""生成打包用图标 build/app.ico。

设计:深色圆角底 + 琥珀横条 + 灰色方块,做成一枚"Z"的抽象写法
(横条 = Z 的上横,方块 = Z 的下半),与面板的品牌标记同源。

要点:
- 用 4 倍超采样(先 4x 画,再 LANCZOS 缩到目标),消除圆角锯齿
- 内容居中:整组图形按视觉重心对齐画布中心,而不是左侧堆叠
- 小尺寸(16/24)自动简化:去掉方块,只留琥珀横条,避免糊成一团
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "app.ico"

BG = (22, 24, 28, 255)          # 深色底
AMBER = (228, 161, 60, 255)     # 品牌强调色
GREY = (150, 158, 168, 255)     # 次级块(提亮一档,小尺寸下更清楚)

SUPERSAMPLE = 4                 # 超采样倍数
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def _render(base: int) -> Image.Image:
    """在 base×base 画布上绘制(先大后缩)。

    base < 24 时走简化版:小图标里两个细元素会糊掉,只保留"粗横条 + 大色块",
    并把留白压到 12%,让形状尽量占满像素。
    """
    S = base * SUPERSAMPLE
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ---- 圆角底:Windows 11 风格,半径 22% ----
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=BG)

    if base < 24:
        # 小尺寸简化版:横条更粗、方块更大、整体更满
        pad = int(S * 0.13)
        inner = S - pad * 2
        cx = S // 2
        bar_w = int(inner * 0.86)
        bar_h = int(inner * 0.30)
        bar_top = pad + int(inner * 0.10)
        d.rounded_rectangle(
            [cx - bar_w // 2, bar_top, cx + bar_w // 2, bar_top + bar_h],
            radius=max(1, bar_h // 2),
            fill=AMBER,
        )
        blk_w = int(inner * 0.62)
        blk_top = bar_top + bar_h + int(inner * 0.12)
        left = cx - bar_w // 2
        d.rounded_rectangle(
            [left, blk_top, left + blk_w, pad + inner],
            radius=max(1, int(inner * 0.14)),
            fill=GREY,
        )
        return img.resize((base, base), Image.LANCZOS)

    # ---- 内容区:四周留白 20%,整组居中 ----
    pad = int(S * 0.20)
    inner = S - pad * 2                      # 内容区边长
    cx = S // 2

    # 上横:占内容宽 76%,厚 17%,靠上 22% 处
    bar_w = int(inner * 0.76)
    bar_h = int(inner * 0.17)
    bar_top = pad + int(inner * 0.16)
    d.rounded_rectangle(
        [cx - bar_w // 2, bar_top, cx + bar_w // 2, bar_top + bar_h],
        radius=bar_h // 2,
        fill=AMBER,
    )

    # 下块:占内容宽 44%,与上横左对齐,构成 Z 的下半
    blk = int(inner * 0.44)
    blk_top = bar_top + bar_h + int(inner * 0.16)
    left = cx - bar_w // 2
    d.rounded_rectangle(
        [left, blk_top, left + blk, blk_top + blk],
        radius=int(blk * 0.26),
        fill=GREY,
    )

    # 超采样缩回目标尺寸
    return img.resize((base, base), Image.LANCZOS)


def main() -> int:
    master = _render(256)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [_render(w) for w, _ in SIZES]
    master.save(OUT, format="ICO", sizes=SIZES, append_images=frames[1:])

    # 导出预览,便于人工核对
    master.save(ROOT / "build" / "_icon_preview.png")
    print(f"已生成 {OUT} ({OUT.stat().st_size} 字节, {len(SIZES)} 种尺寸)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
