"""ZCode 福利自动领取助手 — 入口。

形态:Python 后端(截图 / 点击 / DeepSeek 视觉 / 调度)+ 本地 Web 面板。
启动后自动用默认浏览器打开 http://127.0.0.1:8760/;关闭浏览器不影响后台自动领取,
按 Ctrl+C(或面板「设置 → 退出程序」)结束程序。

用法:
    python main.py                  # 启动服务并打开浏览器面板
    python main.py --no-open        # 只启动服务,不自动开浏览器
    python main.py --dry-run        # 演练模式:不点击、不关闭客户端
    python main.py --run-now        # 启动后立即试领一次
    python main.py --headless       # 不启动 Web 服务,仅按场次调度
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
import webbrowser


def set_dpi_awareness() -> None:
    """必须在导入 mss / pyautogui 之前调用,统一物理像素坐标系。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def parse_args():
    parser = argparse.ArgumentParser(description="ZCode 福利自动领取助手")
    parser.add_argument("--no-open", action="store_true", help="只启动本地服务,不自动打开浏览器")
    parser.add_argument("--headless", action="store_true", help="不启动 Web 服务,仅按场次调度")
    parser.add_argument("--run-now", action="store_true", help="启动后立即试领一次")
    parser.add_argument("--dry-run", action="store_true", help="演练模式:不点击、不关闭客户端")
    parser.add_argument("--port", type=int, default=8760, help="面板服务端口(默认 8760)")
    return parser.parse_args()


def build_app():
    from core.api import Api
    from core.config import ConfigStore
    from core.events import EventBus
    from core.logging_setup import setup_logging
    from core.runner import Runner
    from core.scheduler import SlotScheduler
    from core.storage import SessionStore
    from core.vision import VisionClient
    from loguru import logger

    cfg = ConfigStore()
    bus = EventBus()
    setup_logging(bus, keep_days=int(cfg.get("data", "keep_days", default=7) or 7))
    logger.info("ZCode 福利助手启动中…")

    store = SessionStore()
    try:
        stale = store.abort_stale()
        if stale:
            logger.warning(f"发现 {stale} 个上次未正常结束的任务(断电/崩溃残留),已标记为中止")
    except Exception as exc:
        logger.warning(f"清理残留任务状态失败:{exc}")
    vision = VisionClient(cfg)
    runner = Runner(cfg, bus, store, vision)
    scheduler = SlotScheduler(
        cfg,
        lambda slot: runner.spawn("schedule", slot),
        master_check=lambda: bool(cfg.get("schedule", "enabled", default=True)),
    )
    api = Api(cfg, bus, store, vision, runner, scheduler)
    return cfg, bus, store, vision, runner, scheduler, api


def main() -> int:
    args = parse_args()
    set_dpi_awareness()

    # 单实例:两个实例会各自按场次触发,同一场次领取两次,还会互抢前台窗口
    from core.single_instance import acquire as acquire_single_instance
    from core.single_instance import release as release_single_instance

    if not acquire_single_instance():
        # 这里还没建好日志/配置,只能用最朴素的方式提示用户
        msg = "ZCode 福利助手已经在运行中(同一时间只允许一个实例)。\n\n请在浏览器打开面板,或先结束已有的那个实例。"
        try:
            ctypes.windll.user32.MessageBoxW(None, msg, "ZCode 福利助手", 0x40)
        except Exception:
            print(msg)
        return 1

    try:
        return _run(args)
    finally:
        release_single_instance()


def _run(args) -> int:
    cfg, bus, store, vision, runner, scheduler, api = build_app()
    from loguru import logger
    from core.server import serve
    from core.zcode_ctrl import release_stuck_modifiers
    from core import awake

    # 旧版本在置前失败时会把 ALT 卡在按下态,拖累整台机器的键鼠输入;启动时兜底清一次
    released = release_stuck_modifiers()
    if released:
        logger.warning(f"已清理残留的按键状态:{'/'.join(released)}(不清会导致键盘/鼠标输入错乱)")

    # 防休眠:默认常开。系统睡了调度器会跟着挂起,到点根本不会触发。
    keep_awake = bool(cfg.get("schedule", "keep_awake", default=True))
    if keep_awake:
        if awake.set_always(True):
            logger.info("已开启防休眠(系统与显示器保持唤醒;锁屏仍需在系统设置里关掉)")
        else:
            logger.warning("防休眠开启失败,系统可能按原设置进入睡眠")

    if args.dry_run:
        cfg.patch({"app": {"dry_run": True}})
        logger.warning("演练模式已开启:不会点击、不会关闭客户端")

    try:
        store.cleanup_old(int(cfg.get("data", "keep_days", default=7) or 7))
    except Exception as exc:
        logger.warning(f"清理过期截图失败:{exc}")

    scheduler.start()
    if args.run_now:
        runner.spawn("manual")

    if args.headless:
        logger.info("headless 模式运行中(未启动 Web 服务),Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.shutdown()
        return 0

    server = serve(api, bus, port=args.port)
    if args.no_open:
        logger.info(f"面板服务已启动,请自行访问:{server.url}")
    else:
        logger.info(f"面板地址:{server.url}(已尝试用默认浏览器打开)")
        try:
            webbrowser.open(server.url)
        except Exception as exc:
            logger.warning(f"自动打开浏览器失败({exc}),请手动访问上述地址")
    logger.info("关闭浏览器不影响后台自动领取;结束程序请按 Ctrl+C 或使用面板「设置 → 退出程序」")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号,正在停止…")
    finally:
        server.shutdown()
        scheduler.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
