"""场次调度:APScheduler CronTrigger,支持热更新与「下一次场次」查询。"""
from __future__ import annotations

import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from core.config import ConfigStore


def parse_hhmm(text: str) -> tuple[int, int] | None:
    try:
        hh, mm = str(text).strip().split(":")
        hour, minute = int(hh), int(mm)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except Exception:
        pass
    return None


class SlotScheduler:
    """按 config.schedule.slots 注册每日定时任务,改动后 reload() 热更新。"""

    def __init__(self, cfg: ConfigStore, fire_cb, master_check=None):
        self.cfg = cfg
        self.fire_cb = fire_cb
        self.master_check = master_check or (lambda: True)
        self._scheduler = BackgroundScheduler()
        self._lock = threading.RLock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._scheduler.start()
                self._started = True
            self.reload()

    def shutdown(self) -> None:
        with self._lock:
            if self._started:
                try:
                    self._scheduler.shutdown(wait=False)
                except Exception:
                    pass
                self._started = False

    def reload(self) -> None:
        with self._lock:
            if not self._started:
                return
            for job in self._scheduler.get_jobs():
                if job.id.startswith("slot:"):
                    job.remove()
            slots = self.cfg.get("schedule", "slots") or []
            registered = 0
            for index, slot in enumerate(slots):
                if not isinstance(slot, dict) or not slot.get("enabled", True):
                    continue
                hm = parse_hhmm(slot.get("time", ""))
                if not hm:
                    logger.warning(f"场次时间格式错误,已忽略:{slot}")
                    continue
                hour, minute = hm
                job_id = f"slot:{index}:{hour:02d}{minute:02d}"
                self._scheduler.add_job(
                    self._fire,
                    CronTrigger(hour=hour, minute=minute),
                    args=[dict(slot)],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=120,   # 电脑短暂卡顿/睡眠唤醒后 2 分钟内仍补触发
                    coalesce=True,
                    max_instances=1,
                )
                registered += 1
            logger.info(f"场次调度已更新,共注册 {registered} 个场次")

    def _fire(self, slot: dict) -> None:
        if not self.master_check():
            logger.info(f"场次 {slot.get('time')} 触发,但总开关关闭,跳过")
            return
        logger.info(f"场次 {slot.get('time')} 到点,开始领取")
        self.fire_cb(slot)

    def next_run(self) -> dict | None:
        with self._lock:
            if not self._started:
                return None
            jobs = [
                job for job in self._scheduler.get_jobs()
                if job.id.startswith("slot:") and getattr(job, "next_run_time", None)
            ]
        if not jobs:
            return None
        job = min(jobs, key=lambda j: j.next_run_time)
        dt = job.next_run_time
        return {
            "ts": dt.timestamp(),
            "label": dt.strftime("%H:%M"),
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "job": job.id,
        }
