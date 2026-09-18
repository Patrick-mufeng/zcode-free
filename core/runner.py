"""领取执行器:用户描述的状态机。

到点 → 打开客户端 → 截图定位 → 点击领取 → 校验;
未成功则关闭客户端、等 5 秒重开,最多 5 次;全失败则收尾等下一场。

设计对照:技术方案 §5 流程 / §7 异常处理。watchdog 防窗口卡死吊住流程。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from loguru import logger

import core.awake as awake
import core.capture as capture
import core.clicker as clicker
import core.validate as validate
import core.zcode_ctrl as zcode
from core.config import ConfigStore
from core.events import EventBus
from core.notify import notify
from core.storage import SessionStore
from core.vision import VisionClient
from core.weekly import WeeklyStore

STEPS = ["打开客户端", "识别按钮", "点击领取", "校验结果", "收尾"]


class Runner:
    def __init__(self, cfg: ConfigStore, bus: EventBus, store: SessionStore, vision: VisionClient,
                 weekly: WeeklyStore | None = None):
        self.cfg = cfg
        self.bus = bus
        self.store = store
        self.vision = vision
        self.weekly = weekly or WeeklyStore()
        self._lock = threading.Lock()
        self.current: dict | None = None
        self._client_pid: int | None = None
        self._client_exe: str = ""       # 已确认的客户端进程路径,关闭时用于二次校验

    # ---------- 对外 ----------

    def is_running(self) -> bool:
        return self._lock.locked()

    def spawn(self, trigger: str = "manual", slot: dict | None = None) -> bool:
        """异步启动一次领取(不阻塞调用线程)。"""
        if self.is_running():
            logger.warning("已有领取任务在执行,忽略本次触发")
            return False
        threading.Thread(
            target=self.run_session, args=(trigger, slot), daemon=True, name="runner"
        ).start()
        return True

    def run_session(self, trigger: str = "schedule", slot: dict | None = None) -> dict | None:
        if not self._lock.acquire(blocking=False):
            logger.warning("已有领取任务在执行,忽略本次触发")
            return None
        # 执行期间额外保活一次:即使配置成非常驻,跑的这一段也不会睡
        awake.start_execution()
        try:
            return self._run(trigger, slot)
        except Exception as exc:
            logger.exception(f"领取流程异常终止:{exc}")
            return None
        finally:
            awake.stop_execution()
            self.current = None
            self._client_pid = None
            self._client_exe = ""
            self._lock.release()
            self.bus.publish("state_change", {})

    # ---------- 主流程 ----------

    def _run(self, trigger: str, slot: dict | None) -> dict:
        cfg = self.cfg.all()
        retry_cfg = cfg["retry"]
        slot = slot or {}
        # 演练可由配置总开关开启,也可由单次任务覆盖(面板「演练一次」按钮)
        dry = bool(slot.get("dry")) or bool(cfg["app"].get("dry_run"))
        max_attempts = int(slot.get("attempts") or retry_cfg["max_attempts"])
        gap = float(
            slot["retry_gap_s"] if slot.get("retry_gap_s") is not None else retry_cfg["retry_gap_s"]
        )
        watchdog_s = float(retry_cfg.get("watchdog_s") or 150)

        # 福利一周只有一次机会(周期以周五为起点)。本周期已经领到过,后面的场次再跑也
        # 变不出福利,只会白开客户端、白调两次视觉 —— 直接收尾为「已领取,本场跳过」。
        # 配置保持不动,下周五自动重新开始;手动试领不受此限(用户主动要求就该执行)。
        skip_reason = self._weekly_skip_reason(trigger, slot, cfg)
        if skip_reason:
            return self._finish_skipped(trigger, slot, skip_reason)

        session = self.store.begin(trigger, slot)
        status, summary = "failed", ""
        abort = threading.Event()

        self.current = {
            "session_id": session["id"],
            "trigger": trigger,
            "slot": slot.get("time"),
            "attempt": 0,
            "max_attempts": max_attempts,
            "step": STEPS[0],
            "started_at": session["started_at"],
        }
        self.bus.publish(
            "exec_start",
            {
                "session_id": session["id"],
                "trigger": trigger,
                "slot": slot.get("time"),
                "max_attempts": max_attempts,
                "dry_run": dry,
            },
        )
        logger.info(
            f"开始{'演练' if dry else '执行'}领取(触发:{trigger},场次:{slot.get('time') or '手动'},"
            f"最多 {max_attempts} 次,重试间隔 {gap:.0f}s)"
        )

        watchdog: threading.Timer | None = None

        def arm_watchdog() -> None:
            """按次重置超时。看门狗是防单次卡死,不是给整场设总时限。"""
            nonlocal watchdog
            if watchdog is not None:
                watchdog.cancel()
            watchdog = threading.Timer(watchdog_s, self._on_watchdog, args=(abort, session))
            watchdog.daemon = True
            watchdog.start()

        # 是否保留客户端窗口:拿到结论(成功/当期没有可领)就留着不打扰用户,
        # 失败或中止才关掉
        keep_client = False
        try:
            for attempt_no in range(1, max_attempts + 1):
                if abort.is_set():
                    status, summary = "aborted", "看门狗超时,已强制中止"
                    break

                self.current["attempt"] = attempt_no
                attempt = self.store.begin_attempt(session, attempt_no)
                self._publish_attempt(attempt_no, "running", session["id"],
                                      f"开始第 {attempt_no} 次尝试", attempt)
                arm_watchdog()   # 每次尝试重新计时:单次超时上限,而非整场总预算

                result, reason = self._one_attempt(session, attempt, dry, abort, cfg)
                attempt["result"] = result
                self.store.save(session)
                self._publish_attempt(attempt_no, result, session["id"], reason, attempt)

                if result in ("success", "claimed"):
                    status, summary = "success", reason
                    keep_client = True
                    # 记下本周期已领到:后续场次将跳过。演练不记,免得一次演练就把真机会"用掉"
                    if not dry:
                        self.weekly.mark_claimed(
                            slot=slot.get("time") or "", source=trigger, when=None)
                    break
                if result == "manual":
                    status, summary = "need_manual", reason
                    break
                if result == "aborted":
                    status, summary = "aborted", reason
                    break

                # 未成功(含结果弹窗明确报"领取失败"):关闭客户端 → 等 gap 秒 → 重开
                self._close_client(dry)
                if dry:
                    status, summary = "dry_run", f"演练模式已完成一次尝试({reason})"
                    break
                if abort.is_set():
                    status, summary = "aborted", "看门狗超时,已强制中止"
                    break
                if attempt_no < max_attempts:
                    logger.info(f"第 {attempt_no} 次未成功({reason}),{gap:.0f} 秒后重开重试")
                    if abort.wait(gap):
                        status, summary = "aborted", "看门狗超时,已强制中止"
                        break
            else:
                status, summary = "failed", f"{max_attempts} 次尝试均未成功"
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if not keep_client:      # 成功/无需领取时保留客户端窗口,不打扰用户;失败或中止才关掉
                self._close_client(dry)
            self.store.finish(session, status, summary)
            self.bus.publish(
                "step_update",
                {
                    "session_id": session["id"],
                    "attempt": (self.current or {}).get("attempt", 0),
                    "step": "收尾",
                    "status": "ok",
                    "detail": summary,
                },
            )
            self._notify_result(status, summary, slot, dry)
            self.bus.publish(
                "session_end",
                {
                    "session_id": session["id"],
                    "status": status,
                    "summary": summary,
                    "slot": slot.get("time"),
                    "trigger": trigger,
                },
            )
            logger.info(f"本次领取结束:{status} — {summary}")

        return {"status": status, "summary": summary, "session_id": session["id"]}

    # ---------- 每周一次机会 ----------

    def _weekly_skip_reason(self, trigger: str, slot: dict, cfg: dict) -> str:
        """该场次是否应当因为"本周已领到"而跳过;返回原因,不需要跳过则返回空串。"""
        if not bool(cfg["app"].get("weekly_once", True)):
            return ""
        if trigger != "schedule":        # 手动/演练是用户主动要求,不受每周限制
            return ""
        if slot.get("ignore_weekly"):    # 单场可显式豁免(目前仅供测试)
            return ""
        state = self.weekly.state()
        if not state["claimed"]:
            return ""
        when = state["claimed_at"] or "本周期早些时候"
        src = "手动试领" if state["claimed_source"] == "manual" else (
            f"{state['claimed_slot']} 场次" if state["claimed_slot"] else "定时领取"
        )
        return (f"本周期({state['label']})已于 {when} 通过{src}领取成功;"
                "一周只有一次机会,本场按已领取跳过")

    def _finish_skipped(self, trigger: str, slot: dict, reason: str) -> dict:
        """跳过场次:只记一条状态,不碰客户端、不调模型、不发通知。"""
        session = self.store.begin(trigger, slot)
        self.store.finish(session, "skipped", reason)
        logger.info(f"场次 {slot.get('time') or '手动'} 跳过:{reason}")
        self.bus.publish("exec_start", {
            "session_id": session["id"], "trigger": trigger,
            "slot": slot.get("time"), "max_attempts": 0, "dry_run": False, "skipped": True,
        })
        self.bus.publish("session_end", {
            "session_id": session["id"], "status": "skipped", "summary": reason,
            "slot": slot.get("time"), "trigger": trigger,
        })
        return {"status": "skipped", "summary": reason, "session_id": session["id"]}

    # ---------- 单次尝试 ----------

    def _one_attempt(self, session: dict, attempt: dict, dry: bool,
                     abort: threading.Event, cfg: dict) -> tuple[str, str]:
        # 0) 用户正在用电脑就先别抢前台:等一个键鼠停顿,等不到就放弃本场
        if not dry and self._wait_user_idle(cfg, abort):
            if abort.is_set():
                return "aborted", "看门狗超时,已强制中止"
            logger.warning("检测到键鼠持续活动(电脑正在使用中),本场跳过以免打断操作")
            return "manual", "检测到电脑正在使用中,已跳过本场(避免抢窗口打断操作);可稍后手动试领"

        # 1) 打开客户端
        self._set_step(STEPS[0])
        try:
            win = self._open_client(dry, cfg)
        except Exception as exc:
            self._step(session, attempt, "打开客户端", "fail", str(exc))
            return "retry", f"打开客户端失败:{exc}"
        self._step(session, attempt, "打开客户端", "ok", f"窗口就绪:{win['title']}")
        if abort.is_set():
            return "aborted", "看门狗超时,已强制中止"

        rect = self._position_window(win, cfg, dry)

        # 2) 截图 + 视觉定位(等界面渲染完成)
        self._set_step(STEPS[1])
        try:
            shot, not_ready = self._grab_ready(
                win, rect, cfg, dry, "定位截图",
                timeout=float(cfg["retry"].get("app_ready_timeout_s") or 20),
            )
        except Exception as exc:
            self._step(session, attempt, "截图", "fail", str(exc))
            return "retry", f"截图失败:{exc}"

        if not_ready == "locked":
            self._step(session, attempt, "截图", "fail", "检测到锁屏/安全桌面")
            return "manual", "电脑处于锁屏状态,本场跳过(解锁后请等下一场)"
        if not_ready == "blank":
            self._step(session, attempt, "截图", "fail",
                       f"画面持续为纯色(单色占比 {shot.uniform_ratio:.2f}),界面未渲染")
            return "retry", "客户端界面长时间未渲染出来(纯色画面),重开重试"

        attempt["images"]["locate"] = self.store.save_shot(
            session, shot.png, f"attempt-{attempt['n']}-locate.png"
        )
        self.store.save(session)
        self._publish_attempt(attempt["n"], "running", session["id"], "已截图,正在识别", attempt)
        self._step(session, attempt, "截图", "ok",
                   f"{shot.width}x{shot.height},单色占比 {shot.uniform_ratio:.2f}")

        if not (cfg["vision"].get("api_key") or "").strip():
            self._step(session, attempt, "识别按钮", "fail", "未配置 API Key")
            return "manual", "未配置 DeepSeek API Key,请到「识别」页填写后重试"

        locate = self.vision.locate(shot.png)
        attempt["locate"] = locate
        self.store.save(session)
        verdict = validate.judge_locate(locate, cfg)
        note = locate.get("notes") or locate.get("error") or ""

        # 卡片不在画面上:按用户设定的策略,先原地等 no_card_wait_s 秒再复查一次——
        # 卡片可能比主界面晚渲染。复查时出现了就直接接着点;仍不在则按普通「重试」
        # 走关闭-重开循环,由尝试次数兜底,不再单独判"当期无可领"。
        if verdict == validate.NO_CARD and not dry:
            raw_no_card_wait = cfg["retry"].get("no_card_wait_s")
            no_card_wait = max(float(5 if raw_no_card_wait is None else raw_no_card_wait), 0.0)
            if abort.wait(no_card_wait):
                return "aborted", "看门狗超时,已强制中止"
            probe_shot, probe_bad = self._grab_ready(
                win, rect, cfg, dry, "复查福利卡片",
                timeout=float(cfg["retry"].get("verify_ready_timeout_s") or 8),
            )
            if probe_bad == "locked":
                return "manual", "电脑处于锁屏状态,本场跳过(解锁后请等下一场)"
            probe = self.vision.locate(probe_shot.png)
            probe_verdict = validate.judge_locate(probe, cfg)
            # 记入 attempt.images,面板的截图回放才能看到复查过程
            attempt["images"]["card-probe"] = self.store.save_shot(
                session, probe_shot.png, f"attempt-{attempt['n']}-card-probe.png"
            )
            self.store.save(session)
            if probe_verdict == validate.CLAIM:
                # 卡片只是晚出来了:改用这张的结果继续走点击流程。
                # shot 也要一起换掉 —— 点击要用"量出按钮坐标的那张图"的尺寸与窗口矩形,
                # 否则期间的窗口位移会让归一化坐标换算到错误位置。
                locate, verdict, shot = probe, validate.CLAIM, probe_shot
                note = probe.get("notes") or ""
                logger.info("福利卡片在复查时出现,继续领取")
            elif probe_verdict in (validate.ALREADY, validate.MANUAL):
                verdict = probe_verdict
                note = probe.get("notes") or probe.get("error") or ""

        self._step(session, attempt, "识别按钮",
                   "ok" if verdict in (validate.CLAIM, validate.ALREADY) else "fail",
                   f"判定:{verdict};{note}")

        if verdict == validate.MANUAL:
            return "manual", f"识别到需人工处理的界面:{note or '未知'}"
        if verdict == validate.ALREADY:
            return "claimed", "页面显示已领取,无需重复领取"
        if verdict == validate.NO_CARD:
            return "retry", (
                f"等待 {cfg['retry'].get('no_card_wait_s')}s 复查后仍未见福利卡片,"
                "关闭客户端重开再找"
            )
        if verdict != validate.CLAIM:
            return "retry", f"未找到可点击的领取按钮:{note or '未知'}"

        box = validate.normalize_box(locate.get("button_box"), shot.width, shot.height)
        if box is None:
            return "retry", "模型返回的按钮位置无效"

        # 3) 点击(动手前再确认两件事:用户没在用电脑、客户端确实在前台)
        self._set_step(STEPS[2])
        if dry:
            self._step(session, attempt, "点击领取", "ok", "演练模式:跳过实际点击")
        else:
            if self._wait_user_idle(cfg, abort):
                if abort.is_set():
                    return "aborted", "看门狗超时,已强制中止"
                self._step(session, attempt, "点击领取", "fail", "点击前检测到键鼠活动,已放弃")
                return "manual", "点击前检测到电脑正在使用中,已跳过本次点击"
            if not self._ensure_foreground(win, cfg):
                self._step(session, attempt, "点击领取", "fail", "客户端窗口不在前台,已跳过点击")
                return "retry", "客户端窗口未能置前,跳过点击以避免误点到其他窗口"
            clicker.click_norm(shot.rect, box, humanize=bool(cfg["vision"].get("humanize_mouse")))
            self._step(session, attempt, "点击领取", "ok",
                       f"已点击「{locate.get('button_label') or '领取'}」")

        # 4) 校验
        #
        # 点击后的判定策略(按用户设定):等待加载动画 verify_wait_s 秒(默认 30s),
        # 然后截图判定一次——成功/已领取则收尾;失败、仍在加载、或没有任何结论,
        # 一律按未成功进入"关客户端 → 等间隔 → 重开"的重试循环,由尝试次数兜底。
        self._set_step(STEPS[3])
        verify, v2, after = self._await_verify(win, rect, cfg, dry, session, attempt, abort)

        # "aborted" 只可能来自等待期间看门狗超时;此时不要当成未成功再去重试
        if v2 == "aborted":
            return "aborted", "看门狗超时,已强制中止"
        if after is None:                      # 连一张校验截图都没拿到
            self._step(session, attempt, "校验结果", "fail", "未能截到校验图")
            return "retry", "点击后未能截到校验图"

        note2 = verify.get("notes") or verify.get("error") or ""
        self._step(session, attempt, "校验结果",
                   "ok" if v2 in (validate.SUCCESS, validate.ALREADY) else "fail",
                   f"判定:{v2};{note2}")

        if v2 in (validate.SUCCESS, validate.ALREADY):
            hit = verify.get("keywords") or []
            return "success", f"领取成功({v2}{',命中:' + '/'.join(map(str, hit)) if hit else ''})"
        if v2 == validate.FAILED:
            hit = verify.get("keywords") or []
            return "retry", f"弹窗提示领取失败({',命中:' + '/'.join(map(str, hit)) if hit else ''})"
        if v2 == validate.PENDING:
            return "retry", (
                f"点击后等待 {cfg['retry'].get('verify_wait_s')}s,界面仍在加载中未拿到结果,"
                "按未成功重试(若实际已领到,重开后页面会显示已领取)"
            )
        return "retry", f"点击后未检测到成功弹窗:{note2 or '未知'}"

    def _await_verify(self, win: dict, rect, cfg: dict, dry: bool, session: dict,
                      attempt: dict, abort: threading.Event
                      ) -> tuple[dict, str, "capture.Capture | None"]:
        """点击后等待 verify_wait_s 秒,再截图判定一次。

        返回 (校验结果, 判定, 校验截图);看门狗中止时截图可能为 None。
        演练模式不点击,等不来结果弹窗,不空等、直接截一张判定即收。
        """
        retry_cfg = cfg["retry"]
        raw_wait = retry_cfg.get("verify_wait_s")
        wait = max(float(30 if raw_wait is None else raw_wait), 0.0)
        ready_timeout = float(retry_cfg.get("verify_ready_timeout_s") or 8)

        if not dry and wait > 0:
            logger.info(f"已点击,等待加载动画 {wait:.0f}s 后判定结果…")
            self._publish_attempt(
                attempt["n"], "running", session["id"],
                f"已点击,等待加载动画({wait:.0f}s)", attempt,
            )
            if abort.wait(wait):
                logger.warning("等待领取结果期间看门狗超时,中止本场")
                return {}, "aborted", None

        shot, _ = self._grab_ready(win, rect, cfg, dry, "校验截图", timeout=ready_timeout)
        attempt["images"]["after"] = self.store.save_shot(
            session, shot.png, f"attempt-{attempt['n']}-after.png"
        )
        verify = self.vision.verify(shot.png)
        attempt["verify"] = verify
        self.store.save(session)
        verdict = validate.judge_verify(verify, cfg, clicked=not dry)
        return verify, verdict, shot

    # ---------- 输入与前台保护 ----------

    def _wait_user_idle(self, cfg: dict, abort: threading.Event) -> bool:
        """用户正在用键鼠时先等一等:等到停顿返回 False,一直没停返回 True。

        自动化会抢前台并注入点击,用户正在打字/拖拽时既打断操作,也可能点错窗口。
        retry.user_idle_s = 0 可关闭该保护。
        """
        retry_cfg = cfg["retry"]
        need = float(retry_cfg.get("user_idle_s") or 0)
        wait = float(retry_cfg.get("user_idle_wait_s") or 0)
        if need <= 0:
            return False
        deadline = time.time() + max(wait, 0.0)
        while True:
            idle = zcode.idle_seconds()
            if idle is None:            # 读不到就放行,避免因系统差异卡死流程
                return False
            if idle >= need:
                return False
            if abort.is_set() or time.time() >= deadline:
                return True
            time.sleep(0.25)

    def _ensure_foreground(self, win: dict, cfg: dict) -> bool:
        """点击前确认窗口真的在前台;不在就再置前一次。

        窗口没在前台时,点击坐标会落到用户当前正在用的窗口上——宁可不点。
        """
        hwnd = win["hwnd"]
        if zcode.is_foreground(hwnd):
            return True
        zcode.foreground(hwnd)
        if not zcode.is_foreground(hwnd):
            return False
        time.sleep(float(cfg["retry"].get("focus_settle_s") or 0.0))
        return True

    # ---------- 客户端生命周期 ----------

    def _position_window(self, win: dict, cfg: dict, dry: bool) -> tuple[int, int, int, int]:
        """摆放客户端窗口:按设置最大化(全屏)或移到固定矩形,返回用于截图的矩形。"""
        hwnd = win["hwnd"]
        app_cfg = cfg["app"]
        fullscreen = bool(app_cfg.get("fullscreen", True))

        if dry:
            # 演练不改变窗口尺寸/位置,只读当前几何;读完重新取一次,避免最小化时的无效坐标
            zcode.foreground(hwnd)
            fresh = zcode.window_rect(hwnd)
            if fresh:
                win["rect"] = list(fresh)
            return tuple(win["rect"])

        zcode.foreground(hwnd)
        if fullscreen:
            zcode.maximize(hwnd)
            time.sleep(0.35)
            fresh = zcode.window_rect(hwnd)
            if fresh:
                win["rect"] = list(fresh)
        elif app_cfg.get("restore_window_rect"):
            rect = app_cfg.get("window_rect") or [40, 40, 1240, 860]
            zcode.move_window(hwnd, rect)
            win["rect"] = list(rect)
        return tuple(win["rect"])

    def _grab_ready(self, win: dict, rect, cfg: dict, dry: bool, label: str,
                    timeout: float) -> tuple["capture.Capture", str | None]:
        """等界面渲染完成再截图,返回 (截图, 未就绪原因)。

        未就绪原因:None=已就绪;"locked"=锁屏/安全桌面;"blank"=持续纯色(没渲染出来)。
        纯色画面不再直接判"锁屏跳过"——客户端加载期的闪屏本身就是纯色,
        真正锁屏交给系统 API 判定,避免把"正在加载"误杀成本场跳过。
        """
        retry_cfg = cfg["retry"]
        deadline = time.time() + max(float(timeout), 0.0)
        poll = max(float(retry_cfg.get("ready_poll_s") or 1.0), 0.2)
        ratio_max = float(retry_cfg.get("uniform_ratio_max") or 0.98)

        attempt_index = 0
        while True:
            attempt_index += 1
            if attempt_index > 1:
                self._position_window(win, cfg, dry)   # 再置顶/复位一次,防止等待期间被遮挡
            shot = capture.grab_region(rect)

            if attempt_index == 1 and capture.desktop_locked():
                logger.warning(f"{label}:检测到锁屏/安全桌面,放弃本场")
                return shot, "locked"

            if shot.uniform_ratio <= ratio_max:
                if attempt_index > 1:
                    logger.info(f"{label}:界面已渲染完成(等待 {attempt_index - 1} 次轮询)")
                return shot, None

            if time.time() >= deadline:
                logger.warning(
                    f"{label}:等待 {timeout:.0f}s 后画面仍为纯色(单色占比 {shot.uniform_ratio:.2f})"
                )
                return shot, "blank"
            logger.info(
                f"{label}:画面还是纯色(单色占比 {shot.uniform_ratio:.2f}),"
                f"等待界面加载…(最长 {timeout:.0f}s)"
            )
            time.sleep(poll)

    def _open_client(self, dry: bool, cfg: dict) -> dict:
        app_cfg = cfg["app"]
        match = app_cfg.get("window_title_match") or "ZCode"
        exe = (app_cfg.get("zcode_path") or "").strip()
        if exe and not Path(exe).is_file():
            logger.warning(f"配置的客户端路径已失效,将重新探测:{exe}")
            exe = ""

        # 只接受"进程校验通过"的窗口:标题里含 ZCode 的其他程序(项目目录窗口、
        # 面板网页等)不会被误当成客户端
        win = zcode.find_client_window(match, exe)

        if win is None:
            if not exe:
                exe = zcode.autodetect_exe() or ""
                if exe:
                    self.cfg.patch({"app": {"zcode_path": exe}})
                    logger.info(f"已自动探测到 ZCode 并写入配置:{exe}")
            if not exe:
                raise RuntimeError("未找到 ZCode.exe,请在「设置」页手动指定路径")
            if dry:
                raise RuntimeError("演练模式:客户端未运行且不自动启动")
            zcode.launch(exe)
            win = zcode.wait_client_window(match, float(cfg["retry"]["open_timeout_s"]), exe)
            if win is None:
                raise TimeoutError(
                    f"{cfg['retry']['open_timeout_s']}s 内未等到 ZCode 窗口出现"
                    "(仅接受属于 ZCode 客户端进程的窗口)"
                )
            # 刚启动的客户端需要加载时间,此时画面常为纯色;先等界面出来
            startup_wait = float(app_cfg.get("startup_wait_s") or 0)
            if startup_wait > 0:
                if dry:
                    logger.info(f"演练模式:跳过客户端启动等待 {startup_wait:.0f}s")
                else:
                    logger.info(f"客户端已启动,等待 {startup_wait:.0f}s 让界面加载…")
                    time.sleep(startup_wait)
        else:
            logger.info(f"客户端已在运行:{win['title']}")

        ok, reason = zcode.verify_client_window(win, exe)
        if not ok:
            raise RuntimeError(f"窗口校验未通过,已中止以免误操作:{reason}")
        self._client_pid = zcode.window_pid(win["hwnd"])
        self._client_exe = exe
        logger.info(f"已确认客户端进程(PID {self._client_pid}):{reason}")

        if not dry:
            zcode.foreground(win["hwnd"])
            if app_cfg.get("fullscreen", True):
                logger.info("已把客户端窗口最大化(全屏)")
            elif app_cfg.get("restore_window_rect"):
                zcode.move_window(win["hwnd"], app_cfg.get("window_rect") or [40, 40, 1240, 860])
            time.sleep(float(cfg["retry"].get("settle_s") or 2.0))
        return win

    def _close_client(self, dry: bool) -> None:
        if dry:
            return
        pid = self._client_pid
        if pid and zcode.is_alive(pid):
            if not zcode.kill_tree(pid, expected_exe=self._client_exe):
                logger.warning("关闭客户端未执行(可能出于安全校验被拒),继续后续流程")
        self._client_pid = None
        self._client_exe = ""

    # ---------- 辅助 ----------

    def _on_watchdog(self, abort: threading.Event, session: dict) -> None:
        if abort.is_set():
            return
        logger.error("看门狗超时:强制中止本次领取并关闭 ZCode")
        abort.set()
        self.bus.publish(
            "need_manual",
            {"reason": "看门狗超时,已强制中止本次领取", "session_id": session.get("id")},
        )
        try:
            self._close_client(dry=False)
        except Exception:
            pass

    def _notify_result(self, status: str, summary: str, slot: dict, dry: bool) -> None:
        if dry:
            return
        label = slot.get("time") or "手动"
        if status == "success":
            notify(self.cfg, f"ZCode 福利[{label}] 领取成功", summary)
        elif status == "failed":
            notify(self.cfg, f"ZCode 福利[{label}] 领取失败", f"{summary},请手动查看")
        elif status == "need_manual":
            notify(self.cfg, f"ZCode 福利[{label}] 需要人工处理", summary)

    def _set_step(self, step: str) -> None:
        if self.current is not None:
            self.current["step"] = step

    def _step(self, session: dict, attempt: dict, step: str, status: str, detail: str = "") -> None:
        self.store.add_step(session, attempt, step, status, detail)
        if status == "fail":
            logger.warning(f"[{step}] {detail}")
        elif detail:
            logger.info(f"[{step}] {detail}")
        self.bus.publish(
            "step_update",
            {
                "session_id": session["id"],
                "attempt": attempt["n"],
                "step": step,
                "status": status,
                "detail": detail,
            },
        )

    def _publish_attempt(self, n: int, status: str, session_id: str,
                         message: str, attempt: dict) -> None:
        images = [
            {"session": session_id, "name": name}
            for name in (attempt.get("images") or {}).values()
        ]
        self.bus.publish(
            "attempt_update",
            {
                "session_id": session_id,
                "attempt": n,
                "status": status,
                "message": message,
                "images": images,
            },
        )
