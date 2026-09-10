"""环境侦察脚本(M1):一次性摸清 ZCode 的路径、窗口与福利页截图。

用法:
    .venv\\Scripts\\python.exe probe.py            # 只做本地侦察(找 exe/窗口/截图)
    .venv\\Scripts\\python.exe probe.py --vision   # 额外调用一次视觉模型做定位测试

产出:
    data/probe/report-<时间>.txt   侦察报告
    data/probe/shot-<时间>.png     截图(窗口优先,找不到窗口则整屏)
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from datetime import datetime


def set_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="ZCode 环境侦察")
    parser.add_argument("--vision", action="store_true", help="额外跑一次视觉定位测试(需已配置 API Key)")
    parser.add_argument("--title", default=None, help="窗口标题关键字(默认读配置)")
    args = parser.parse_args()

    set_dpi_awareness()

    from core.config import PROJECT_ROOT, ConfigStore
    from core.logging_setup import setup_logging

    setup_logging(None, keep_days=3)
    from loguru import logger

    import core.capture as capture
    import core.zcode_ctrl as zcode
    from core.vision import VisionClient

    cfg = ConfigStore()
    title = args.title or cfg.get("app", "window_title_match", default="ZCode") or "ZCode"

    probe_dir = PROJECT_ROOT / "data" / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lines: list[str] = []

    def report(text: str = "") -> None:
        lines.append(text)
        print(text)

    report(f"=== ZCode 环境侦察 {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    report(f"窗口标题关键字:{title}")

    # 1) exe
    report("\n[1] 进程与安装路径")
    running = zcode.find_running_exe()
    report(f"  运行中的 ZCode:{running or '未发现'}")
    searched = zcode.search_exe()
    report(f"  磁盘扫描结果:{searched or '未找到'}")
    configured = (cfg.get("app", "zcode_path") or "").strip()
    report(f"  当前配置路径:{configured or '(空)'}")
    best = running or searched or configured
    if best and best != configured:
        cfg.patch({"app": {"zcode_path": best}})
        report(f"  → 已回填配置:{best}")

    # 2) 窗口
    report("\n[2] 窗口枚举与进程校验")
    windows = zcode.list_windows(title)
    if not windows:
        report(f"  未找到标题含「{title}」的可见窗口(客户端可能未打开)")
    expected = (cfg.get("app", "zcode_path") or "").strip()
    for win in windows:
        pid = zcode.window_pid(win["hwnd"])
        ok, reason = zcode.verify_client_window(win, expected)
        flag = "✓ 客户端" if ok else "✗ 已排除"
        report(f"  {flag} hwnd={win['hwnd']} pid={pid} rect={win['rect']} title={win['title']!r}")
        report(f"       {reason}")
    main_window = zcode.find_client_window(title, expected)
    if main_window:
        report(f"  → 采用窗口:pid={zcode.window_pid(main_window['hwnd'])} rect={main_window['rect']}")
    elif windows:
        report("  → 有标题相近的窗口,但没有一个通过进程校验(不会被当成客户端操作)")

    # 3) 截图
    report("\n[3] 截图")
    if main_window:
        shot = capture.grab_region(tuple(main_window["rect"]))
        source = "窗口"
    else:
        shot = capture.grab_fullscreen()
        source = "整屏"
    shot_path = probe_dir / f"shot-{stamp}.png"
    shot_path.write_bytes(shot.png)
    report(f"  来源:{source} 尺寸:{shot.width}x{shot.height} 单色占比:{shot.uniform_ratio:.3f}")
    report(f"  已保存:{shot_path}")
    if shot.uniform_ratio > 0.95:
        report("  ⚠ 画面接近纯色:可能锁屏/黑屏,或窗口尚未渲染")

    # 4) 视觉定位(可选)
    if args.vision:
        report("\n[4] 视觉定位测试(DeepSeek)")
        if not (cfg.get("vision", "api_key") or "").strip():
            report("  未配置 API Key,跳过。请先在面板「识别」页填写。")
        else:
            start = time.time()
            result = VisionClient(cfg).locate(shot.png)
            elapsed = time.time() - start
            report(f"  耗时:{elapsed:.1f}s")
            import json
            report("  返回:" + json.dumps(result, ensure_ascii=False, indent=2))
            if not result.get("error"):
                report("  → 请核对:图上是否有可点击的领取按钮?button_box 是否大致落在按钮上?")
                report("    (可将 shot 图片交给面板「识别」页的测试识别,会画出识别框)")

    report("\n=== 侦察结束 ===")
    report_path = probe_dir / f"report-{stamp}.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"报告已保存:{report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
