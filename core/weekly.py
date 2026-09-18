"""每周一次的机会窗口:以「周五」为周期起点,记住本周是否已经领到。

为什么需要它:ZCode 的周末福利**一周只有一次机会**。用户会在一天里配好几个
候选场次(如 19:00 / 20:00 / 21:00 / 22:00),只要其中一场领到了,同一个周期里
后面的场次再跑也变不出福利来 —— 旧行为是照跑不误,每个空场次都要白开一次
客户端、截两次图、调两次视觉 API,还可能因为卡片渲染延迟而重复点击。

周期定义:周五 00:00 到下一个周五 00:00(即周五~周四为一周)。
用户只在周五开这个服务,所以把周五当起点最贴合直觉:周五当天领到之后,
周六到周四的场次全部静默跳过,下周五自动重新开始。

状态存 data/weekly.json,与截图留档分开放:
- 数据目录不可写时(打包后放在 Program Files)不影响主流程,只是退化为"每周多试几次";
- 文件损坏/内容非法一律当作"本周未领取",宁可多试一次也不要漏领。
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from loguru import logger

from core.config import DATA_DIR

WEEKLY_PATH = DATA_DIR / "weekly.json"

# 周期起点:周五。date.weekday() 里周一=0 … 周日=6,故周五=4。
WEEK_START_WEEKDAY = 4

_DAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def week_start_of(when: date | datetime | None = None) -> date:
    """返回 when 所属周期(福利周)的起点日期 —— 该周的周五。"""
    day = (when or datetime.now()).date() if isinstance(when, datetime) else (when or date.today())
    # 相对本周五偏移:周五(4)→0,周六(5)→1,…周四(3)→6
    offset = (day.weekday() - WEEK_START_WEEKDAY) % 7
    return day - timedelta(days=offset)


def week_end_of(when: date | datetime | None = None) -> date:
    """本周期的最后一天(周四),用于界面上说明"到哪天为止"。"""
    return week_start_of(when) + timedelta(days=6)


def week_label(when: date | datetime | None = None) -> str:
    """周期标签,如 "09-18(周五) ~ 09-24(周四)"。"""
    start = week_start_of(when)
    end = week_end_of(when)
    return (f"{start.strftime('%m-%d')}({_DAY_NAMES[start.weekday()]}) ~ "
            f"{end.strftime('%m-%d')}({_DAY_NAMES[end.weekday()]})")


class WeeklyStore:
    """记录「本周期是否已领到」。线程安全,读写失败不抛给调用方。"""

    def __init__(self, path: Path = WEEKLY_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()

    # ---------- 读 ----------

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning(f"读取每周状态失败(按未领取处理):{exc}")
            return {}

    def state(self, when: date | datetime | None = None) -> dict:
        """当前周期的状态。

        claimed 为 True 表示本周期已经领到过,后续场次应当跳过;
        week 是记录里的周期起点,与当前周期不一致说明那条记录属于过去的周期。
        """
        start = week_start_of(when)
        data = self._load()
        recorded = str(data.get("week_start") or "")
        claimed = bool(data.get("claimed")) and recorded == start.isoformat()
        return {
            "week_start": start.isoformat(),
            "week_end": week_end_of(when).isoformat(),
            "label": week_label(when),
            "claimed": claimed,
            "claimed_at": (data.get("claimed_at") or "") if claimed else "",
            "claimed_slot": (data.get("claimed_slot") or "") if claimed else "",
            "claimed_source": (data.get("claimed_source") or "") if claimed else "",
        }

    def claimed_this_week(self, when: date | datetime | None = None) -> bool:
        return bool(self.state(when)["claimed"])

    # ---------- 写 ----------

    def mark_claimed(self, slot: str = "", source: str = "",
                     when: date | datetime | None = None) -> dict:
        """记下"本周期已领到"。source 用于区分 schedule / manual。"""
        start = week_start_of(when)
        payload = {
            "week_start": start.isoformat(),
            "week_end": week_end_of(when).isoformat(),
            "claimed": True,
            "claimed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "claimed_slot": str(slot or ""),
            "claimed_source": str(source or ""),
        }
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"已记录本周期({payload['week_start']} 起)领取成功,后续场次将跳过")
            except OSError as exc:
                # 写不进去不影响本次结果,只是下次开机会重试
                logger.warning(f"写入每周状态失败(后续场次仍会照常执行):{exc}")
        return payload

    def clear(self, when: date | datetime | None = None) -> None:
        """清掉本周期记录(面板「清除本周状态」用,便于手动重试)。"""
        with self._lock:
            try:
                if self.path.exists():
                    self.path.unlink()
                    logger.info("已清除每周领取状态")
            except OSError as exc:
                logger.warning(f"清除每周状态失败:{exc}")
