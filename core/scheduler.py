"""场次调度:APScheduler CronTrigger,支持按星期、热更新与「下一次场次」查询。"""
from __future__ import annotations

import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from core.config import ConfigStore

# 星期编号沿用 Python 的 date.weekday():周一=0 … 周日=6
WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
WEEKDAY_CRON = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_hhmm(text: str) -> tuple[int, int] | None:
    try:
        hh, mm = str(text).strip().split(":")
        hour, minute = int(hh), int(mm)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except Exception:
        pass
    return None


def parse_days(raw) -> list[int] | None:
    """把场次的 days 规整成升序去重的 [0-6] 列表;None 表示「每天」。

    兼容几种写法:整数、数字字符串、mon/tue 之类的英文缩写、以及中文「周五」。
    空列表同样视为「每天」——早期配置里没有 days 字段,行为必须保持不变。

    注意:days 字段存在但一个都认不出来时(如手改配置写错),同样返回 None(每天),
    但会记一条告警 —— 静默按每天跑比报错更危险,用户会以为只排了周五却天天触发。
    """
    if raw is None:
        return None
    if isinstance(raw, (str, int)):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return None

    out: set[int] = set()
    for item in raw:
        text = str(item).strip().lower()
        if not text:
            continue
        if text.isdigit():
            value = int(text)
            # 允许 1-7(周一=1)或 0-6(周一=0)两种直觉写法
            if 0 <= value <= 6:
                out.add(value)
            elif 1 <= value <= 7:
                out.add(value - 1)
            continue
        if text in WEEKDAY_CRON:
            out.add(WEEKDAY_CRON.index(text))
            continue
        for index, name in enumerate(WEEKDAY_NAMES):
            if text == name or text == name[1:]:      # 「周五」或「五」
                out.add(index)
                break
    if not out and any(str(i).strip() for i in raw):
        logger.warning(f"场次的星期设置无法识别,已按「每天」处理:{raw!r}")
    return sorted(out) or None


def days_label(days: list[int] | None) -> str:
    """给日志/界面用的星期说明;None 或全选显示「每天」。"""
    if not days or len(days) == 7:
        return "每天"
    return "".join(WEEKDAY_NAMES[d] for d in days if 0 <= d <= 6)


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
                days = parse_days(slot.get("days"))
                job_id = f"slot:{index}:{hour:02d}{minute:02d}"
                trigger_kwargs: dict = {"hour": hour, "minute": minute}
                if days:
                    # 只在指定星期触发。用 mon-fri 这种范围/列表写法,
                    # 避免 APScheduler 把 day_of_week 当集合时的隐式行为
                    trigger_kwargs["day_of_week"] = ",".join(WEEKDAY_CRON[d] for d in days)
                self._scheduler.add_job(
                    self._fire,
                    CronTrigger(**trigger_kwargs),
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
        # 星期兜底:定时任务只在指定星期注册,但电脑休眠/卡顿后可能补触发到次日,
        # 那时 cron 已经不再匹配。这里再核一次,避免"周五的场次跑到周六去开客户端"。
        days = parse_days(slot.get("days"))
        if days:
            today = datetime.now().weekday()
            if today not in days:
                logger.info(
                    f"场次 {slot.get('time')}({days_label(days)})已补触发到 "
                    f"{WEEKDAY_NAMES[today]},不在设定星期内,跳过"
                )
                return
        logger.info(f"场次 {slot.get('time')}({days_label(days)})到点,开始领取")
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
            # 场次可以只排在部分星期,所以「下一场」要带上日期与星期,
            # 否则看起来像"今天 19:00"却其实是下周五
            "date": dt.strftime("%m-%d"),
            "weekday": WEEKDAY_NAMES[dt.weekday()],
            "is_today": dt.date() == datetime.now().date(),
            "job": job.id,
        }
