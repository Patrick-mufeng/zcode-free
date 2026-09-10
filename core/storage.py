"""会话存储:每次领取的尝试记录 + 截图留档,以及历史查询与清理。

目录结构:
data/shots/<session_id>/
    session.json                  # 完整过程记录
    attempt-1-locate.png          # 定位截图
    attempt-1-after.png           # 点击后校验截图
"""
from __future__ import annotations

import json
import shutil
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from core.config import SHOTS_DIR


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SessionStore:
    def __init__(self, shots_dir: Path = SHOTS_DIR):
        self.dir = Path(shots_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ---------- 写 ----------

    def begin(self, trigger: str, slot: dict | None) -> dict:
        """开启一次会话,返回会话 dict(由 runner 持有并持续更新)。"""
        now = datetime.now()
        label = str((slot or {}).get("time") or "manual").replace(":", "-")
        session_id = f"{now.strftime('%Y-%m-%d')}_{now.strftime('%H-%M-%S')}_{label}"
        session = {
            "id": session_id,
            "trigger": trigger,          # schedule | manual
            "slot": (slot or {}).get("time"),
            "started_at": _now_str(),
            "ended_at": None,
            "status": "running",         # success|failed|need_manual|aborted|dry_run
            "summary": "",
            "attempts": [],
        }
        (self.dir / session_id).mkdir(parents=True, exist_ok=True)
        self.save(session)
        return session

    def begin_attempt(self, session: dict, n: int) -> dict:
        attempt = {
            "n": n,
            "started_at": _now_str(),
            "result": "running",         # running|success|claimed|retry|manual|aborted
            "steps": [],                 # [{time, step, status, detail}]
            "images": {},                # {"locate": "attempt-1-locate.png", ...}
            "locate": None,
            "verify": None,
        }
        session["attempts"].append(attempt)
        self.save(session)
        return attempt

    def add_step(self, session: dict, attempt: dict, step: str, status: str, detail: str = "") -> None:
        attempt["steps"].append(
            {"time": datetime.now().strftime("%H:%M:%S"), "step": step, "status": status, "detail": detail}
        )
        self.save(session)

    def save_shot(self, session: dict, png: bytes, name: str) -> str:
        path = self.dir / session["id"] / name
        path.write_bytes(png)
        return name

    def save(self, session: dict) -> None:
        with self._lock:
            path = self.dir / session["id"] / "session.json"
            path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    def finish(self, session: dict, status: str, summary: str) -> None:
        session["status"] = status
        session["summary"] = summary
        session["ended_at"] = _now_str()
        self.save(session)

    # ---------- 读 ----------

    def load(self, session_id: str) -> dict | None:
        path = self.dir / session_id / "session.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_sessions(self, limit: int = 50) -> list[dict]:
        out: list[dict] = []
        for child in self.dir.iterdir():
            if not child.is_dir():
                continue
            data = self.load(child.name)
            if not data:
                continue
            out.append(
                {
                    "id": data.get("id", child.name),
                    "trigger": data.get("trigger"),
                    "slot": data.get("slot"),
                    "started_at": data.get("started_at"),
                    "ended_at": data.get("ended_at"),
                    "status": data.get("status"),
                    "summary": data.get("summary"),
                    "attempts": len(data.get("attempts") or []),
                }
            )
        out.sort(key=lambda x: x.get("started_at") or "", reverse=True)
        return out[:limit]

    def today_stats(self) -> dict:
        today = date.today().strftime("%Y-%m-%d")
        stats = {"success": 0, "failed": 0, "need_manual": 0, "total": 0}
        for item in self.list_sessions(limit=200):
            if not (item.get("started_at") or "").startswith(today):
                continue
            if item.get("status") == "running":
                continue
            stats["total"] += 1
            key = item.get("status")
            if key in stats:
                stats[key] += 1
        return stats

    def shot_path(self, session_id: str, name: str) -> Path | None:
        """安全解析截图路径,防止目录穿越。"""
        base = (self.dir / session_id).resolve()
        path = (base / name).resolve()
        if not str(path).startswith(str(self.dir.resolve())):
            return None
        return path if path.is_file() else None

    # ---------- 清理 ----------

    def cleanup_old(self, keep_days: int) -> int:
        """删除超过保留期的会话目录,返回删除数量。"""
        if keep_days <= 0:
            return 0
        cutoff = date.today() - timedelta(days=int(keep_days))
        removed = 0
        for child in list(self.dir.iterdir()):
            if not child.is_dir():
                continue
            try:
                day = date.fromisoformat(child.name.split("_")[0])
            except Exception:
                continue
            if day < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed

    def abort_stale(self, note: str = "任务执行中进程被中断(断电/崩溃/强制重启),已自动标记为中止") -> int:
        """把残留的 running 会话标记为中止。

        程序被非正常终止时(如断电、黑屏强制重启),session.json 会一直停在
        running,面板会永远显示"执行中";启动时清理一次即可自愈。
        """
        count = 0
        for child in list(self.dir.iterdir()):
            if not child.is_dir():
                continue
            data = self.load(child.name)
            if not data or data.get("status") != "running":
                continue
            data["status"] = "aborted"
            data["summary"] = note
            if not data.get("ended_at"):
                data["ended_at"] = _now_str()
            for attempt in data.get("attempts") or []:
                if isinstance(attempt, dict) and attempt.get("result") == "running":
                    attempt["result"] = "aborted"
            self.save(data)
            count += 1
        return count

    def clear_all(self) -> int:
        """清除全部截图留档。"""
        removed = 0
        for child in list(self.dir.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed
