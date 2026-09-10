"""UI 后端 API:原生窗口(js_api)与浏览器回退(JSON-RPC)共用同一套方法。

前端调用约定:每个方法接收一个 payload dict(可为 None),返回 JSON 可序列化结果。
"""
from __future__ import annotations

import base64
import os
import threading
import time
from pathlib import Path

from loguru import logger

import core.capture as capture
import core.zcode_ctrl as zcode
from core.config import CONFIG_PATH, DATA_DIR, LOG_DIR, ConfigStore
from core.events import EventBus
from core.logging_setup import get_logs
from core.runner import Runner
from core.scheduler import SlotScheduler, parse_hhmm
from core.storage import SessionStore
from core.validate import normalize_box
from core.vision import LOCATE_PROMPT, VERIFY_PROMPT, VisionClient


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


class Api:
    def __init__(self, cfg: ConfigStore, bus: EventBus, store: SessionStore,
                 vision: VisionClient, runner: Runner, scheduler: SlotScheduler):
        self.cfg = cfg
        self.bus = bus
        self.store = store
        self.vision = vision
        self.runner = runner
        self.scheduler = scheduler
        self.ui_ready_event = threading.Event()

    # 事件统一由 core/server.py 的 /events(SSE)推送给浏览器面板;此处不持有任何窗口对象。

    def ui_ready(self, payload=None) -> dict:
        """前端启动完成时调用一次:确认面板已加载(事件走 SSE,不依赖 JS 注入)。"""
        self.ui_ready_event.set()
        logger.info("面板前端已就绪")
        return {"ok": True, "mode": "web"}

    # ---------- 总状态 ----------

    def get_state(self, payload=None) -> dict:
        cfg = self.cfg.all()
        slots = cfg["schedule"].get("slots") or []
        return {
            "master": bool(cfg["schedule"].get("enabled", True)),
            "running": self.runner.is_running(),
            "current": self.runner.current,
            "next_slot": self.scheduler.next_run(),
            "slots_total": len(slots),
            "slots_enabled": len([s for s in slots if isinstance(s, dict) and s.get("enabled", True)]),
            "slots": slots,          # 面板首页的 24 小时轨道按时间画出每个场次
            "today": self.store.today_stats(),
            "recent": self.store.list_sessions(limit=12),   # 概览底部的记录表要铺满面板
            "has_key": bool((cfg["vision"].get("api_key") or "").strip()),
            "zcode_path": cfg["app"].get("zcode_path") or "",
            "dry_run": bool(cfg["app"].get("dry_run")),
            "config_path": str(CONFIG_PATH),
        }

    def set_master(self, payload=None) -> dict:
        enabled = bool((payload or {}).get("enabled", True))
        self.cfg.patch({"schedule": {"enabled": enabled}})
        self.scheduler.reload()
        self.bus.publish("state_change", {})
        logger.info(f"总开关已{'开启' if enabled else '关闭'}")
        return {"ok": True, "master": enabled}

    def run_once(self, payload=None) -> dict:
        """手动跑一次:<payload.dry=true> 为演练(只截图识别,不点击、不关客户端)。"""
        if self.runner.is_running():
            return {"ok": False, "message": "已有任务在执行,请稍候"}
        payload = payload or {}
        dry = bool(payload.get("dry"))
        slot = {"dry": True} if dry else None
        ok = self.runner.spawn("manual", slot)
        if not ok:
            return {"ok": False, "message": "启动失败"}
        return {"ok": True, "dry": dry,
                "message": "演练已开始(不点击、不关客户端)" if dry else "已开始试领(完整流程)"}

    # ---------- 场次 ----------

    def get_schedule(self, payload=None) -> dict:
        return {"slots": self.cfg.get("schedule", "slots") or []}

    def save_schedule(self, payload=None) -> dict:
        slots = self._clean_slots((payload or {}).get("slots"))
        self.cfg.patch({"schedule": {"slots": slots}})
        self.scheduler.reload()
        self.bus.publish("state_change", {})
        logger.info(f"场次表已更新,共 {len(slots)} 个场次")
        return {"ok": True, "slots": slots}

    @staticmethod
    def _clean_slots(raw) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            time_text = str(item.get("time") or "").strip()
            if parse_hhmm(time_text) is None or time_text in seen:
                continue
            seen.add(time_text)
            entry: dict = {"time": time_text, "enabled": bool(item.get("enabled", True))}
            for key in ("attempts", "retry_gap_s"):
                value = item.get(key)
                if value in (None, "", "null"):
                    entry[key] = None
                else:
                    try:
                        entry[key] = max(1, int(float(value)))
                    except (TypeError, ValueError):
                        entry[key] = None
            out.append(entry)
        return out

    # ---------- 设置 ----------

    def get_settings(self, payload=None) -> dict:
        return {
            "app": self.cfg.get("app") or {},
            "retry": self.cfg.get("retry") or {},
            "schedule": {"keep_awake": self.cfg.get("schedule", "keep_awake", default=True)},
            "notify": self.cfg.get("notify") or {},
            "data": self.cfg.get("data") or {},
            "config_path": str(CONFIG_PATH),
        }

    def save_settings(self, payload=None) -> dict:
        payload = payload or {}
        patch: dict = {}
        for section in ("app", "retry", "schedule", "notify", "data"):
            value = payload.get(section)
            if isinstance(value, dict):
                patch[section] = value
        if patch:
            self.cfg.patch(patch)
            self.scheduler.reload()
            # 「场次执行期防休眠」是常驻开关,改完要立刻生效,不能等下次启动
            if isinstance(patch.get("schedule"), dict) and "keep_awake" in patch["schedule"]:
                import core.awake as awake
                want = bool(patch["schedule"]["keep_awake"])
                if awake.set_always(want):
                    logger.info(f"防休眠已{'开启' if want else '关闭'}")
                else:
                    logger.warning("切换防休眠失败,系统可能按原设置进入睡眠")
            self.bus.publish("state_change", {})
        return {"ok": True, "settings": self.get_settings()}

    def get_vision_config(self, payload=None) -> dict:
        return {
            "vision": self.cfg.get("vision") or {},
            "verify_delay_s": self.cfg.get("retry", "verify_delay_s", default=2.5),
            "success_keywords": self.cfg.get("success_keywords") or [],
            "claimed_keywords": self.cfg.get("claimed_keywords") or [],
            "failure_keywords": self.cfg.get("failure_keywords") or [],
        }

    def save_vision_config(self, payload=None) -> dict:
        payload = payload or {}
        patch: dict = {}
        vision = payload.get("vision")
        if isinstance(vision, dict):
            patch["vision"] = vision
        if "verify_delay_s" in payload:
            patch.setdefault("retry", {})["verify_delay_s"] = payload["verify_delay_s"]
        if "max_attempts" in payload:
            patch.setdefault("retry", {})["max_attempts"] = payload["max_attempts"]
        for key in ("success_keywords", "claimed_keywords", "failure_keywords"):
            value = payload.get(key)
            if isinstance(value, list):
                patch[key] = [str(k).strip() for k in value if str(k).strip()]
        if patch:
            self.cfg.patch(patch)
        return {"ok": True, "vision": self.cfg.get("vision")}

    def get_prompts(self, payload=None) -> dict:
        return {"locate": LOCATE_PROMPT, "verify": VERIFY_PROMPT}

    # ---------- 探测与测试 ----------

    def detect_zcode(self, payload=None) -> dict:
        path = zcode.autodetect_exe() or ""
        if path:
            self.cfg.patch({"app": {"zcode_path": path}})
            logger.info(f"已探测到 ZCode:{path}")
        return {"ok": bool(path), "path": path,
                "message": f"已找到:{path}" if path else "未找到 ZCode.exe,请手动填写完整路径"}

    def diagnose_shortcut(self, payload=None) -> dict:
        """诊断开始菜单快捷方式的解析链路(打包后验证 win32com 是否可用)。

        自动探测有两条路径:运行中进程(优先)与开始菜单 .lnk(兜底)。
        客户端没运行时才会走后者,而它依赖函数内延迟导入的 win32com——
        PyInstaller 容易漏掉。这里主动跑一次,把结论暴露给调用方。
        """
        import core.zcode_ctrl as zc

        lnks: list[str] = []
        for d in zc._start_menu_dirs():
            try:
                lnks.extend(str(p) for p in d.rglob("*.lnk") if "zcode" in p.stem.lower())
            except OSError:
                continue

        result = {
            "ok": False,
            "shortcuts": lnks,
            "resolved": None,
            "message": "",
        }
        if not lnks:
            result["message"] = "本机开始菜单里没有 ZCode 快捷方式,该链路不会被用到"
            return result

        target = zc._resolve_lnk(Path(lnks[0]))
        if target:
            result["ok"] = True
            result["resolved"] = target
            result["message"] = f"快捷方式解析正常:{target}"
            logger.info(f"快捷方式解析正常:{lnks[0]} → {target}")
        else:
            result["message"] = (
                "快捷方式解析失败(win32com 可能未打包)。"
                "客户端正在运行时不影响使用;未运行时会探测不到 ZCode 路径。"
            )
            logger.warning("快捷方式解析失败:.lnk 链路不可用")
        return result

    def test_vision_connection(self, payload=None) -> dict:
        result = self.vision.test_connection()
        logger.info(f"视觉连接测试:{result.get('message')}")
        return result

    def test_locate(self, payload=None) -> dict:
        cfg = self.cfg.all()
        source = (payload or {}).get("source") or "window"
        if source == "window":
            match = cfg["app"].get("window_title_match") or "ZCode"
            exe = (cfg["app"].get("zcode_path") or "").strip()
            win = zcode.find_client_window(match, exe)   # 带进程校验,避免截到同名无关窗口
            if win:
                zcode.foreground(win["hwnd"])   # 先置顶,避免截到被遮挡或已最小化的画面
                if cfg["app"].get("fullscreen", True):
                    zcode.maximize(win["hwnd"])  # 与自动执行保持一致:全屏后再截图
                    time.sleep(0.6)
                shot = None
                deadline = time.time() + 12          # 界面还在加载时等它渲染出来
                while True:
                    fresh = zcode.window_rect(win["hwnd"]) or win["rect"]
                    shot = capture.grab_region(tuple(fresh))
                    if shot.uniform_ratio <= 0.98 or time.time() >= deadline:
                        break
                    time.sleep(0.8)
                pid = zcode.window_pid(win["hwnd"])
                source_label = f"窗口:{win['title']}(PID {pid})"
            else:
                shot = capture.grab_fullscreen()
                source_label = "整屏(ZCode 窗口未找到或未通过进程校验)"
        else:
            shot = capture.grab_fullscreen()
            source_label = "整屏"

        result = self.vision.locate(shot.png)
        box = None
        raw_box = result.get("button_box")
        if isinstance(raw_box, (list, tuple)):
            box = normalize_box(raw_box, shot.width, shot.height)
        return {
            "ok": not result.get("error"),
            "result": result,
            "source": source_label,
            "image": _data_uri(shot.png, "image/png"),
            "box": box,
            "size": [shot.width, shot.height],
            "error": result.get("error"),
        }

    # ---------- 日志与记录 ----------

    def get_logs(self, payload=None) -> dict:
        payload = payload or {}
        items = get_logs(
            limit=int(payload.get("limit") or 300),
            level=payload.get("level") or None,
            keyword=payload.get("keyword") or "",
        )
        return {"items": items}

    def list_sessions(self, payload=None) -> dict:
        limit = int((payload or {}).get("limit") or 50)
        return {"items": self.store.list_sessions(limit=limit)}

    def get_session_detail(self, payload=None) -> dict:
        session_id = (payload or {}).get("id") or ""
        data = self.store.load(session_id)
        if data is None:
            return {"ok": False, "message": "记录不存在"}
        return {"ok": True, "session": data}

    def get_shot(self, payload=None) -> dict:
        payload = payload or {}
        path = self.store.shot_path(payload.get("session") or "", payload.get("name") or "")
        if path is None:
            return {"ok": False, "message": "截图不存在"}
        data = path.read_bytes()
        mime = "image/png"
        if payload.get("thumb"):
            try:
                data = capture.thumbnail(data, int(payload.get("max_width") or 520))
                mime = "image/jpeg"
            except Exception:
                pass
        return {"ok": True, "image": _data_uri(data, mime)}

    # ---------- 其他 ----------

    def cleanup(self, payload=None) -> dict:
        action = (payload or {}).get("action")
        if action == "shots":
            count = self.store.clear_all()
            return {"ok": True, "message": f"已清除 {count} 个场次的截图"}
        if action == "logs":
            count = 0
            for log_file in LOG_DIR.glob("*.log"):
                try:
                    log_file.unlink()
                    count += 1
                except OSError:
                    pass
            return {"ok": True, "message": f"已删除 {count} 个日志文件"}
        if action == "reset":
            self.cfg.reset()
            self.scheduler.reload()
            self.bus.publish("state_change", {})
            return {"ok": True, "message": "配置已重置(保留 ZCode 路径与 API Key)"}
        return {"ok": False, "message": "未知操作"}

    def open_data_dir(self, payload=None) -> dict:
        try:
            os.startfile(str(DATA_DIR))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def quit_app(self, payload=None) -> dict:
        """退出整个程序(面板「设置 → 退出程序」;正在执行的任务会被中断)。"""
        logger.warning("收到退出指令,程序将在 1 秒后结束")
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return {"ok": True, "message": "程序即将退出,可直接关闭本页面"}
