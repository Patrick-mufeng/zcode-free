"""自检脚本:验证依赖、配置、调度、判定逻辑与 HTTP 桥是否正常。

不需要 API Key,不会点击鼠标、不会启动/关闭 ZCode。
    .venv\\Scripts\\python.exe selftest.py
"""
from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
import urllib.request

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        PASS.append(f"[PASS] {name}{(' — ' + str(detail)) if detail else ''}")
    except Exception as exc:
        FAIL.append(f"[FAIL] {name} — {exc}")


def set_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def main() -> int:
    set_dpi_awareness()

    check("依赖导入(mss/PIL/pyautogui/pywin32/httpx/yaml/loguru/apscheduler)", lambda: __import_deps())
    check("静态检查:未定义名称 / 未使用导入(pyflakes)", lambda: __static_check_case())
    check("配置加载与 patch(临时文件)", lambda: __config_roundtrip())
    check("判定逻辑:归一化坐标容错", lambda: __box_cases())
    check("判定逻辑:定位/校验决策", lambda: __judge_cases())
    check("截图模块(整屏抓取,不保存)", lambda: __capture_case())
    check("截图模块:越界窗口裁剪与坐标一致性", lambda: __capture_clip_case())
    check("执行状态机装配与场次调度注册", lambda: __app_case())
    check("执行器:演练模式单次尝试与记录", lambda: __runner_dry_case())
    check("执行器:重试循环与收尾", lambda: __runner_retry_case())
    check("窗口进程校验(拒绝同名无关窗口 / 误关保护进程)", lambda: __window_guard_case())
    check("修饰键保护(置前失败不再卡住 ALT / 启动可清理)", lambda: __modifier_guard_case())
    check("用户占用保护(正在用键鼠时不抢前台、不点击)", lambda: __user_idle_guard_case())
    check("窗口摆放(全屏 / 固定矩形 / 演练不动窗口)", lambda: __position_window_case())
    check("加载期纯色等待与锁屏判定(不再误判跳过)", lambda: __ready_wait_case())
    check("残留任务状态自愈(断电后的 running 会话)", lambda: __stale_session_case())
    check("执行器:结果弹窗映射(成功收尾 / 失败重试)", lambda: __verify_mapping_case())
    check("测试识别接口(整屏,无 Key 时报错而不抛异常)", lambda: __test_locate_case())
    check("前端资源完整性(HTML / CSS / JS)", lambda: __ui_assets_case())
    check("动效与排版护栏(无自我触发 / 纯文字 / 无渐变阴影)", lambda: __motion_guard_case())
    check("HTTP 桥往返(get_state / 首页 / 静态资源)", lambda: __http_case())
    check("打包:冻结路径分流(资源 / 数据分离)", lambda: __frozen_path_case())
    check("打包:单实例锁(第二个实例必须被拒)", lambda: __single_instance_case())
    check("打包:防休眠(开关 / 执行期嵌套计数)", lambda: __awake_case())
    check("打包:开始菜单快捷方式解析(win32com 链路)", lambda: __shortcut_resolve_case())
    print()
    for line in PASS:
        print(line)
    for line in FAIL:
        print(line)
    print()
    print(f"结果:{len(PASS)} 项通过,{len(FAIL)} 项失败")
    return 1 if FAIL else 0


# ---------------- 各项检查 ----------------

def __import_deps():
    import importlib

    for name in ("mss", "PIL", "pyautogui", "win32gui", "httpx", "yaml", "loguru", "apscheduler"):
        importlib.import_module(name)
    return "全部依赖可导入"


def __static_check_case():
    """静态检查:抓未定义名称/语法类问题(pyflakes 未安装时跳过)。"""
    import importlib.util
    import subprocess
    import sys

    if importlib.util.find_spec("pyflakes") is None:
        return "跳过(未安装 pyflakes,可执行 pip install pyflakes)"

    from core.config import PROJECT_ROOT

    targets = [str(PROJECT_ROOT / "core"), str(PROJECT_ROOT / "main.py"),
               str(PROJECT_ROOT / "probe.py"), str(PROJECT_ROOT / "selftest.py")]
    result = subprocess.run([sys.executable, "-m", "pyflakes", *targets],
                            capture_output=True, text=True, errors="replace", timeout=90)
    issues = (result.stdout or "").strip()
    if result.returncode != 0 and issues:
        raise AssertionError(issues.replace("\n", "; ")[:400])
    return "pyflakes 未发现未定义名称/未使用导入"


def __config_roundtrip():
    import tempfile
    from pathlib import Path

    from core.config import ConfigStore

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.yaml"
        store = ConfigStore(path)
        assert store.get("retry", "max_attempts") == 5, "默认值缺失"
        store.patch({"retry": {"max_attempts": 7}, "schedule": {"slots": [{"time": "10:00", "enabled": True}]}})
        assert store.get("retry", "max_attempts") == 7
        assert store.get("schedule", "slots")[0]["time"] == "10:00"
        reloaded = ConfigStore(path)
        assert reloaded.get("retry", "max_attempts") == 7, "落盘后读取不一致"
        assert reloaded.get("retry", "retry_gap_s") == 5, "缺项未补默认值"
    return "读写/深度合并/落盘正常"


def __box_cases():
    from core.validate import normalize_box

    assert normalize_box([0.1, 0.2, 0.5, 0.6], 1000, 800) == (0.1, 0.2, 0.5, 0.6)
    assert normalize_box([10, 20, 50, 60], 1000, 800) == (0.1, 0.2, 0.5, 0.6), "百分比换算失败"
    assert normalize_box([100, 200, 500, 600], 1000, 1000) == (0.1, 0.2, 0.5, 0.6), "像素换算失败"
    assert normalize_box([0.5, 0.6, 0.1, 0.2], 100, 100) == (0.1, 0.2, 0.5, 0.6), "顺序纠正失败"
    assert normalize_box("bad", 100, 100) is None
    assert normalize_box([0.1, 0.2], 100, 100) is None
    assert normalize_box([0.4, 0.4, 0.4, 0.6], 100, 100) is None, "零宽框应判非法"
    return "归一化/百分比/像素/非法输入全部正确"


def __judge_cases():
    import tempfile
    from pathlib import Path

    from core.config import DEFAULTS, ConfigStore
    from core.validate import judge_locate, judge_verify

    # 生产路径:执行器传入的是普通 dict(曾经的 bug:这里用了 ConfigStore 的多键 get)
    cfg = dict(DEFAULTS)
    assert judge_locate({"error": "x", "confidence": 0}, cfg) == "retry"
    assert judge_locate({"scene": "login", "confidence": 0.9}, cfg) == "manual"
    assert judge_locate({"already_claimed": True, "confidence": 0.9}, cfg) == "claimed"
    assert judge_locate({"ocr_texts": ["今日已领"], "confidence": 0.9}, cfg) == "claimed"
    assert judge_locate(
        {"button_found": True, "claimable": True, "button_box": [0.4, 0.5, 0.6, 0.6], "confidence": 0.9}, cfg
    ) == "claim"
    assert judge_locate(
        {"button_found": True, "claimable": True, "button_box": [0.4, 0.5, 0.6, 0.6], "confidence": 0.3}, cfg
    ) == "retry", "低于阈值不应点击"
    assert judge_verify({"success": True, "confidence": 0.9}, cfg) == "success"
    assert judge_verify({"keywords": ["领取成功"], "confidence": 0.9}, cfg) == "success"
    assert judge_verify({"keywords": ["明天再来"], "confidence": 0.9}, cfg) == "claimed"
    assert judge_verify({"notes": "没有出现领取成功,按钮还在", "confidence": 0.5}, cfg) == "retry", "notes 不应参与命中"

    # 结果弹窗(项目实际形态):成功=「领取成功 + 开始体验」,失败=「领取失败 + 知道了」
    assert judge_verify({"popup": "success", "keywords": ["领取成功", "开始体验"], "confidence": 0.95}, cfg) == "success"
    assert judge_verify({"success": True, "popup": "success", "confidence": 0.9}, cfg) == "success"
    assert judge_verify({"keywords": ["开始体验"], "confidence": 0.9}, cfg) == "success", "成功词表应含开始体验"
    assert judge_verify({"popup": "failure", "keywords": ["领取失败", "知道了"], "confidence": 0.95}, cfg) == "failed"
    assert judge_verify({"failed": True, "keywords": ["知道了"], "confidence": 0.9}, cfg) == "failed", "失败词表应含知道了"
    assert judge_verify({"success": False, "failed": False, "popup": None, "confidence": 0.5}, cfg) == "retry"

    # 兼容性:面板侧传入 ConfigStore 也必须可用
    store = ConfigStore(Path(tempfile.mkdtemp(prefix="zcode-judge-")) / "config.yaml")
    assert judge_locate(
        {"button_found": True, "claimable": True, "button_box": [0.4, 0.5, 0.6, 0.6], "confidence": 0.9}, store
    ) == "claim"
    assert judge_verify({"keywords": ["领取成功"], "confidence": 0.9}, store) == "success"
    assert judge_locate({"ocr_texts": ["明天再来"], "confidence": 0.9}, store) == "claimed"
    assert judge_verify({"popup": "success", "keywords": ["开始体验"], "confidence": 0.95}, store) == "success"
    assert judge_verify({"popup": "failure", "keywords": ["领取失败"], "confidence": 0.95}, store) == "failed"
    return "定位/校验各分支正确(含成功/失败弹窗;普通 dict 与 ConfigStore 两种入参)"


def __capture_case():
    from core.capture import grab_fullscreen

    shot = grab_fullscreen()
    assert len(shot.png) > 1000, "截图数据过小"
    assert 0.0 <= shot.uniform_ratio <= 1.0
    return f"{shot.width}x{shot.height},单色占比 {shot.uniform_ratio:.2f}"


def __capture_clip_case():
    from core.capture import grab_region

    # 模拟最大化窗口(-8,-8 起始的 DWM 边框)越界场景
    shot = grab_region((-8, -8, 1936, 1056))
    assert shot.width == shot.rect[2] and shot.height == shot.rect[3], \
        f"裁剪矩形 {shot.rect} 与图片 {shot.width}x{shot.height} 不一致"
    assert shot.rect[0] >= 0 and shot.rect[1] >= 0, "裁剪矩形应被限制在屏幕内"
    return f"越界窗口裁剪一致,rect={shot.rect}"


def __app_case():
    import tempfile
    from pathlib import Path

    from core.api import Api
    from core.config import ConfigStore
    from core.events import EventBus
    from core.logging_setup import setup_logging
    from core.runner import Runner
    from core.scheduler import SlotScheduler
    from core.storage import SessionStore
    from core.vision import VisionClient

    tmp_dir = Path(tempfile.mkdtemp(prefix="zcode-selftest-"))
    cfg = ConfigStore(tmp_dir / "config.yaml")   # 自检不污染真实配置
    cfg.patch({"schedule": {"slots": [{"time": "23:59", "enabled": True, "attempts": None, "retry_gap_s": None}]}})
    bus = EventBus()
    setup_logging(bus, keep_days=3)
    store = SessionStore()
    vision = VisionClient(cfg)
    runner = Runner(cfg, bus, store, vision)
    scheduler = SlotScheduler(cfg, lambda slot: None,
                              master_check=lambda: bool(cfg.get("schedule", "enabled", default=True)))
    scheduler.start()
    api = Api(cfg, bus, store, vision, runner, scheduler)

    state = api.get_state()
    assert state["slots_total"] >= 1
    assert state["next_slot"] is not None and state["next_slot"]["ts"] > time.time(), "下一场次计算错误"
    api.save_schedule({"slots": [{"time": "08:30", "enabled": True}, {"time": "bad", "enabled": True}]})
    slots = api.get_schedule()["slots"]
    assert len(slots) == 1 and slots[0]["time"] == "08:30", f"场次清洗失败:{slots}"
    assert api.get_prompts()["locate"].startswith("你是桌面软件自动化助手")

    from core import api as api_module
    api_module._SELFTEST_API = api  # 供 HTTP 桥检查复用
    return f"下一场 {state['next_slot']['datetime']}"


def __test_locate_case():
    """「测试识别」接口:整屏分支(不抢焦点);无 Key 时应返回错误而不是抛异常。"""
    from core import api as api_module

    api = getattr(api_module, "_SELFTEST_API", None)
    assert api is not None, "先执行上一项装配检查"
    if (api.cfg.get("vision", "api_key") or "").strip():
        return "跳过(已配置 API Key,避免真实视觉调用)"

    result = api.test_locate({"source": "screen"})
    assert str(result.get("image", "")).startswith("data:image/"), "截图数据缺失"
    assert result.get("size") and result["size"][0] > 100, f"截图尺寸异常:{result.get('size')}"
    assert result.get("ok") is False and result.get("error"), f"无 Key 应返回错误信息:{result}"
    return f"整屏截图链路正常(预期报错:{result['error']})"


def __verify_mapping_case():
    """执行器级:结果弹窗的成功/失败如何映射到收尾与重试(假截图 + 假视觉,不碰真实窗口)。"""
    import tempfile
    import threading
    from pathlib import Path
    from types import SimpleNamespace

    from core.config import ConfigStore
    from core.events import EventBus
    from core.runner import Runner
    from core.storage import SessionStore
    from core.vision import VisionClient

    tmp = Path(tempfile.mkdtemp(prefix="zcode-verify-"))
    cfg = ConfigStore(tmp / "config.yaml")
    cfg.patch({
        "app": {"dry_run": False},
        "retry": {"verify_delay_s": 0, "focus_settle_s": 0},
        "vision": {"api_key": "selftest-fake-key"},   # 让流程走到视觉调用(视觉已被打桩)
    })
    store = SessionStore(tmp / "shots")
    runner = Runner(cfg, EventBus(), store, VisionClient(cfg))
    cfg_dict = cfg.all()

    fake_shot = SimpleNamespace(png=b"\x89PNG-fake", width=1240, height=860,
                                rect=(40, 40, 1240, 860), uniform_ratio=0.3,
                                full_size=(1920, 1080))
    runner._open_client = lambda dry, cfg: {"hwnd": 1, "title": "FakeZCode", "rect": [40, 40, 1240, 860], "area": 1}
    runner._close_client = lambda dry: None
    # 真实方法名是 _grab_ready(曾经的 bug:这里写的是不存在的 _grab_window,
    # 打桩落空 → 自检真的截图并点了用户的鼠标)。返回 (截图, 未就绪原因)。
    runner._grab_ready = lambda win, rect, cfg, dry, label, timeout=None: (fake_shot, None)
    runner._position_window = lambda win, cfg, dry: tuple(win["rect"])
    runner._wait_user_idle = lambda cfg, abort: False
    runner._ensure_foreground = lambda win, cfg: True
    runner.vision.locate = lambda png: {
        "button_found": True, "claimable": True, "button_box": [0.4, 0.5, 0.6, 0.6],
        "button_label": "领取", "confidence": 0.95, "scene": "welfare",
    }

    # 保险:即便上面的打桩将来再次失效,也绝不允许自检真的移动/点击鼠标
    import core.clicker as clicker_module
    real_click_norm, real_click_screen = clicker_module.click_norm, clicker_module.click_screen
    clicks: list[tuple] = []
    clicker_module.click_norm = lambda rect, box, humanize=False: clicks.append(("norm", rect, box))
    clicker_module.click_screen = lambda x, y, humanize=False: clicks.append(("screen", x, y))

    def run(verify_result):
        runner.vision.verify = lambda png: verify_result
        session = store.begin("manual", {"time": None})
        attempt = store.begin_attempt(session, 1)
        return runner._one_attempt(session, attempt, False, threading.Event(), cfg_dict)[0]

    try:
        success = run({"popup": "success", "keywords": ["领取成功", "开始体验"], "confidence": 0.95})
        failure = run({"popup": "failure", "keywords": ["领取失败", "知道了"], "confidence": 0.95})
        nothing = run({"popup": None, "success": False, "failed": False, "confidence": 0.4})
        claimed = run({"claimed": True, "keywords": ["明日再来"], "confidence": 0.9})
    finally:
        clicker_module.click_norm, clicker_module.click_screen = real_click_norm, real_click_screen

    assert clicks, "点击未被拦截?这会让自检真的操作鼠标"
    assert all(c[0] == "norm" for c in clicks), f"出现了屏幕直点:{clicks}"
    assert success == "success", f"成功弹窗应判成功,得到 {success}"
    assert claimed == "success", f"已领应判成功,得到 {claimed}"
    assert failure == "retry", f"失败弹窗应进入重试,得到 {failure}"
    assert nothing == "retry", f"无弹窗应进入重试,得到 {nothing}"

    # 前台校验不通过:跳过点击、计一次未成功(否则点击会落到用户当前窗口上)
    intercepted = len(clicks)
    runner._ensure_foreground = lambda win, cfg: False
    clicks.clear()
    blocked = run({"popup": "success", "keywords": ["领取成功"], "confidence": 0.95})
    assert blocked == "retry", f"窗口不在前台应判重试,得到 {blocked}"
    assert not clicks, f"窗口不在前台时不应点击:{clicks}"
    runner._ensure_foreground = lambda win, cfg: True
    return f"弹窗映射正确;点击全部被拦截({intercepted} 次);窗口不在前台时拒绝点击"


def __ready_wait_case():
    """回归:加载期纯色画面不得被判成"锁屏跳过",而应等待渲染完成。

    事故背景:打开客户端后约 5 秒的加载闪屏是纯色,旧逻辑(单色占比>0.95 → manual
    "疑似锁屏")把这种情况误判成本场跳过。
    """
    import tempfile
    from dataclasses import dataclass
    from pathlib import Path

    from core.config import ConfigStore
    from core.events import EventBus
    from core.runner import Runner
    from core.storage import SessionStore
    from core.vision import VisionClient
    import core.capture as capture_module

    @dataclass
    class FakeShot:
        png: bytes = b"x"
        width: int = 100
        height: int = 100
        rect: tuple = (0, 0, 100, 100)
        uniform_ratio: float = 0.5
        full_size: tuple = (100, 100)

    tmp = Path(tempfile.mkdtemp(prefix="zcode-ready-"))
    cfg = ConfigStore(tmp / "config.yaml")
    cfg.patch({"retry": {"ready_poll_s": 0.05, "uniform_ratio_max": 0.98}})
    runner = Runner(cfg, EventBus(), SessionStore(tmp / "shots"), VisionClient(cfg))
    cfg_dict = cfg.all()
    win = {"hwnd": 1, "title": "Fake", "rect": [0, 0, 100, 100]}
    orig_grab, orig_locked = capture_module.grab_region, capture_module.desktop_locked
    orig_position = runner._position_window
    runner._position_window = lambda w, c, d: tuple(w["rect"])

    try:
        capture_module.desktop_locked = lambda: False

        # ① 前两次纯色(模拟加载中)→ 应继续等待,最终返回就绪
        frames = [FakeShot(uniform_ratio=1.0), FakeShot(uniform_ratio=0.995), FakeShot(uniform_ratio=0.62)]
        calls = {"n": 0}

        def grab_seq(rect):
            shot = frames[min(calls["n"], len(frames) - 1)]
            calls["n"] += 1
            return shot

        capture_module.grab_region = grab_seq
        shot, reason = runner._grab_ready(win, tuple(win["rect"]), cfg_dict, True, "测试", timeout=5)
        assert reason is None and shot.uniform_ratio == 0.62, f"应等到渲染完成,得到 {reason}"
        assert calls["n"] == 3, f"应轮询 3 次,实际 {calls['n']}"

        # ② 一直纯色 → 超时返回 blank(交给重开重试),而不是锁屏
        calls["n"] = 0

        def always_blank(rect):
            calls["n"] += 1
            return FakeShot(uniform_ratio=1.0)

        capture_module.grab_region = always_blank
        _, reason = runner._grab_ready(win, tuple(win["rect"]), cfg_dict, True, "测试", timeout=0.3)
        assert reason == "blank", f"持续纯色应为 blank,得到 {reason}"
        assert calls["n"] > 1, f"纯色期间应多次轮询,实际 {calls['n']}"

        # ③ 真锁屏 → 由系统 API 判定,返回 locked
        capture_module.desktop_locked = lambda: True
        calls["n"] = 0
        _, reason = runner._grab_ready(win, tuple(win["rect"]), cfg_dict, True, "测试", timeout=5)
        assert reason == "locked", f"锁屏应为 locked,得到 {reason}"
        assert calls["n"] == 1, f"锁屏应只截一次就退出,实际 {calls['n']}"

        # ④ 首次即就绪:不额外轮询
        capture_module.desktop_locked = lambda: False
        calls["n"] = 0

        def ready_first(rect):
            calls["n"] += 1
            return FakeShot(uniform_ratio=0.55)

        capture_module.grab_region = ready_first
        shot, reason = runner._grab_ready(win, tuple(win["rect"]), cfg_dict, True, "测试", timeout=5)
        assert reason is None, f"就绪时不应有问题,得到 {reason}"
        assert calls["n"] == 1, f"就绪时应只截一次,实际 {calls['n']}"
    finally:
        capture_module.grab_region, capture_module.desktop_locked = orig_grab, orig_locked
        runner._position_window = orig_position

    # 真实系统调用可用性(不改变状态):当前未锁屏应返回 False
    assert capture_module.desktop_locked() is False, "当前未锁屏,判定应为 False"
    return "纯色=等待渲染(不再误判锁屏);真锁屏=locked;无额外轮询"


def __position_window_case():
    """摆放策略:全屏开启时最大化;关闭时移到固定矩形;演练不动窗口。"""
    from core.runner import Runner
    from core.events import EventBus
    from core.storage import SessionStore
    from core.vision import VisionClient
    from core.config import ConfigStore
    import core.zcode_ctrl as zc
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="zcode-pos-"))
    runner = Runner(ConfigStore(tmp / "config.yaml"), EventBus(),
                    SessionStore(tmp / "shots"), VisionClient(ConfigStore(tmp / "config.yaml")))

    calls = {"max": 0, "move": None, "fg": 0}
    orig_max, orig_move, orig_fg, orig_rect = zc.maximize, zc.move_window, zc.foreground, zc.window_rect
    try:
        zc.maximize = lambda hwnd: calls.__setitem__("max", calls["max"] + 1)
        zc.move_window = lambda hwnd, rect: calls.__setitem__("move", list(rect))
        zc.foreground = lambda hwnd: calls.__setitem__("fg", calls["fg"] + 1) or True
        zc.window_rect = lambda hwnd: [0, 0, 1920, 1080]
        win = {"hwnd": 1, "title": "Fake", "rect": [0, 0, 100, 100]}

        cfg_full = ConfigStore(tmp / "a.yaml")
        cfg_full.patch({"app": {"fullscreen": True}})
        rect = runner._position_window(win, cfg_full.all(), dry=False)
        assert calls["max"] == 1, "全屏开启时应调用最大化"
        assert rect == (0, 0, 1920, 1080), f"应使用最大化后的窗口矩形,得到 {rect}"

        calls.update({"max": 0, "move": None})
        cfg_rect = ConfigStore(tmp / "b.yaml")
        cfg_rect.patch({"app": {"fullscreen": False, "restore_window_rect": True,
                                "window_rect": [40, 40, 1240, 860]}})
        rect = runner._position_window(win, cfg_rect.all(), dry=False)
        assert calls["max"] == 0 and calls["move"] == [40, 40, 1240, 860], "关闭全屏时应移到固定矩形"
        assert rect == (40, 40, 1240, 860)

        calls.update({"max": 0, "move": None})
        runner._position_window(win, cfg_full.all(), dry=True)
        assert calls["max"] == 0 and calls["move"] is None, "演练模式不应改变窗口"
    finally:
        zc.maximize, zc.move_window, zc.foreground, zc.window_rect = orig_max, orig_move, orig_fg, orig_rect
    return "全屏/固定矩形/演练不动窗口 三种策略正确"


def __window_guard_case():
    """回归:标题含 "zcode" 的无关窗口不得被当成客户端;受保护进程不得被结束。

    事故背景:标题为 "zcode-free"(项目目录)的窗口被标题匹配命中,
    随后该进程被当作 ZCode 关闭,可能连带影响系统外壳。
    """
    import core.zcode_ctrl as zc

    # 纯函数:保护名单
    assert zc.is_protected_exe(r"C:\Windows\explorer.exe") is True
    assert zc.is_protected_exe(r"C:\Program Files\Google\Chrome\Application\chrome.exe") is True
    assert zc.is_protected_exe(r"D:\app_file\Zcode\ZCode.exe") is False
    assert zc.is_protected_exe(None) is False

    # 路径比较:Windows 大小写不敏感
    assert zc._same_path(r"d:\APP_FILE\zcode\zcode.exe", r"D:\app_file\Zcode\ZCode.exe") is True
    assert zc._same_path(r"D:\other\ZCode.exe", r"D:\app_file\Zcode\ZCode.exe") is False

    # 无效句柄直接拒绝
    ok, _ = zc.verify_client_window({"hwnd": 0, "title": "ZCode"}, "")
    assert ok is False

    # 用打桩替换进程信息,覆盖真实的误判场景(不会触碰任何真实进程)
    orig_pid, orig_path = zc.window_pid, zc.process_path
    try:
        zc.window_pid = lambda hwnd: 4242
        # ① 标题像客户端,但进程是资源管理器 → 必须拒绝
        zc.process_path = lambda pid: r"C:\Windows\explorer.exe"
        ok, reason = zc.verify_client_window({"hwnd": 1, "title": "zcode-free"}, "")
        assert ok is False and "受保护" in reason, f"应拒绝受保护进程,得到 {ok}/{reason}"

        # ② 标题像客户端,进程是别的编辑器 → 与配置路径不一致,拒绝
        zc.process_path = lambda pid: r"D:\app_file\SomeEditor\editor.exe"
        ok, reason = zc.verify_client_window(
            {"hwnd": 1, "title": "zcode-free"}, r"D:\app_file\Zcode\ZCode.exe")
        assert ok is False and "不一致" in reason, f"应因路径不符拒绝,得到 {ok}/{reason}"

        # ③ 真正的客户端(大小写不同) → 通过
        zc.process_path = lambda pid: r"d:\APP_FILE\zcode\zcode.exe"
        ok, reason = zc.verify_client_window(
            {"hwnd": 1, "title": "ZCode"}, r"D:\app_file\Zcode\ZCode.exe")
        assert ok is True, f"正确客户端应通过,得到 {ok}/{reason}"

        # ④ 关闭时的二次校验:进程与预期不符 → 拒绝执行 taskkill
        zc.process_path = lambda pid: r"C:\Windows\explorer.exe"
        assert zc.kill_tree(4242, expected_exe=r"D:\app_file\Zcode\ZCode.exe") is False
        zc.process_path = lambda pid: None          # 读不到路径也不许关
        assert zc.kill_tree(4242) is False
    finally:
        zc.window_pid, zc.process_path = orig_pid, orig_path

    # 真实窗口抽样:通过校验的窗口里不得出现受保护进程
    accepted = [w for w in zc.list_windows("") if zc.verify_client_window(w, "")[0]]
    for win in accepted:
        path = zc.process_path(zc.window_pid(win["hwnd"]))
        assert not zc.is_protected_exe(path), f"不应接受受保护进程:{path}"
    return f"误判/误关均已拦截(当前可见窗口中通过校验 {len(accepted)} 个)"


def __stale_session_case():
    """断电/崩溃残留的 running 会话,启动时应被标记为中止。"""
    import json
    import tempfile
    from pathlib import Path

    from core.storage import SessionStore

    tmp = Path(tempfile.mkdtemp(prefix="zcode-stale-"))
    store = SessionStore(tmp / "shots")
    session = store.begin("schedule", {"time": "16:30"})
    store.begin_attempt(session, 1)          # 会话停在 running
    assert store.load(session["id"])["status"] == "running"

    count = store.abort_stale()
    assert count == 1, f"应清理 1 个残留会话,实际 {count}"
    data = json.loads((tmp / "shots" / session["id"] / "session.json").read_text(encoding="utf-8"))
    assert data["status"] == "aborted" and data["ended_at"], "残留会话未被正确收尾"
    assert data["attempts"][0]["result"] == "aborted"
    assert store.abort_stale() == 0, "重复清理应为 0"
    return "残留 running 会话已自愈为 aborted"


def __motion_guard_case():
    """回归护栏:动效层不得出现"观察某元素 → 再把动画写回该元素"的自我触发写法。

    事故背景:「今日场次」数字持续闪烁 —— 数字动画由"观察自身文字变化"驱动,
    动画每一帧写回的中间值又被当成新的变化,再次触发动画,形成永久弹跳。
    """
    import re

    from core.config import UI_DIR

    motion = (UI_DIR / "assets/js/motion.js").read_text(encoding="utf-8")
    issues = []
    if "observeNumbers" in motion:
        issues.append("observeNumbers 仍存在(应改为显式 MOTION.countTo)")
    if re.search(r"observe\(el, \{[^}]*characterData", motion):
        issues.append("仍存在对文本元素的 characterData 观察,可能自我触发")
    if re.search(r"attributeFilter:\s*\['src',\s*'style'\]", motion):
        issues.append("实时截图仍在监听 style 属性(GSAP 会写 style,会成环)")
    assert not issues, "; ".join(issues)

    # 数据层必须通过显式接口驱动数字动画
    dashboard = (UI_DIR / "assets/js/pages/dashboard.js").read_text(encoding="utf-8")
    assert "MOTION.countTo" in dashboard, "数字卡片应使用 MOTION.countTo 显式驱动"

    # 排版纪律:页面结构里不应出现图标 SVG(纯文字排版)
    index = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "<svg" not in index, "纯文字排版页面中不应再出现 SVG 图标"
    css = (UI_DIR / "assets/css/app.css").read_text(encoding="utf-8")
    for banned in ("backdrop-filter", "linear-gradient(135deg", "box-shadow"):
        assert banned not in css, f"排版方案应避免 {banned}"
    return "动效无自我触发写法;页面无图标;样式无渐变/阴影/毛玻璃"


def __modifier_guard_case():
    """回归:置前失败时不得把 ALT 键卡在按下态。

    事故背景:foreground() 里"按下 ALT → SetForegroundWindow → 抬起 ALT"写在同一个
    try 中,而置前失败会抛异常,抬键语句被跳过 → ALT 永久按下,整机键鼠输入错乱
    (菜单被激活、点击变 Alt+点击、焦点乱跳)。
    """
    import win32con

    import core.zcode_ctrl as zc

    class FakeApi:
        """记录按键事件并维护"哪些键正按着"。"""

        def __init__(self, pressed=()):
            self.events = []
            self.pressed = set(pressed)

        def keybd_event(self, vk, scan, flags, extra):
            self.events.append((vk, flags))
            if flags & win32con.KEYEVENTF_KEYUP:
                self.pressed.discard(vk)
            else:
                self.pressed.add(vk)

        def GetAsyncKeyState(self, vk):
            return 0x8000 if vk in self.pressed else 0

    class FakeGui:
        def __init__(self, denied):
            self.denied = denied

        def SetForegroundWindow(self, hwnd):
            if self.denied:
                raise RuntimeError("前台锁定:系统拒绝置前")
            return None

    orig_api, orig_gui = zc.win32api, zc.win32gui
    try:
        # ① 置前被拒(抛异常):ALT 必须成对按下/抬起,不留残留
        api, gui = FakeApi(), FakeGui(denied=True)
        zc.win32api, zc.win32gui = api, gui
        assert zc._set_foreground(1) is False, "被拒时应返回 False"
        downs = [e for e in api.events if not e[1] & win32con.KEYEVENTF_KEYUP]
        ups = [e for e in api.events if e[1] & win32con.KEYEVENTF_KEYUP]
        assert len(downs) == len(ups) == 1, f"ALT 应按下 1 次、抬起 1 次,实际 {api.events}"
        assert api.pressed == set(), f"ALT 仍处于按下态:{api.pressed}"

        # ② 正常置前:不必借 ALT,也不留残留
        api2 = FakeApi()
        zc.win32api, zc.win32gui = api2, FakeGui(denied=False)
        assert zc._set_foreground(1) is True
        assert api2.events == [], f"成功路径不应注入按键:{api2.events}"

        # ③ 启动兜底:系统里已卡住的 ALT 会被抬起
        api3 = FakeApi(pressed={zc.VK_MENU})
        zc.win32api = api3
        assert zc.release_stuck_modifiers() == ["ALT"], "应清理卡住的 ALT"
        assert api3.pressed == set(), "清理后 ALT 不应仍是按下态"
        assert zc.release_stuck_modifiers() == [], "没有卡键时不应重复注入抬键"
    finally:
        zc.win32api, zc.win32gui = orig_api, orig_gui

    idle = zc.idle_seconds()                     # 真实读数,不改变任何状态
    assert idle is None or idle >= 0, f"空闲时长读数异常:{idle}"
    return "置前失败不再卡住 ALT;启动兜底可清理残留按键"


def __user_idle_guard_case():
    """回归:用户正在用键鼠时不得抢前台/点击。

    到点的场次若正撞上用户打字,会直接夺走焦点并注入点击;这里保证程序
    先等一个键鼠停顿,等不到就跳过本场(manual),而不是硬抢。
    """
    import tempfile
    from pathlib import Path

    import core.zcode_ctrl as zc
    from core.config import ConfigStore
    from core.events import EventBus
    from core.runner import Runner
    from core.storage import SessionStore
    from core.vision import VisionClient

    tmp = Path(tempfile.mkdtemp(prefix="zcode-idle-"))
    cfg = ConfigStore(tmp / "config.yaml")
    cfg.patch({"retry": {"user_idle_s": 1.0, "user_idle_wait_s": 0.6}})
    runner = Runner(cfg, EventBus(), SessionStore(tmp / "shots"), VisionClient(cfg))
    cfg_dict = cfg.all()
    abort = threading.Event()
    orig = zc.idle_seconds
    try:
        # ① 已空闲足够久 → 直接放行,不等待
        zc.idle_seconds = lambda: 5.0
        started = time.time()
        assert runner._wait_user_idle(cfg_dict, abort) is False
        assert time.time() - started < 0.3, "已空闲时不应等待"

        # ② 用户持续操作 → 等满上限后放弃本场
        zc.idle_seconds = lambda: 0.1
        started = time.time()
        assert runner._wait_user_idle(cfg_dict, abort) is True, "持续占用应判为跳过"
        elapsed = time.time() - started
        assert 0.5 <= elapsed < 3.0, f"等待时长异常:{elapsed:.2f}s"

        # ③ 先动后停 → 停止后放行
        seq = {"n": 0}

        def idle_seq():
            seq["n"] += 1
            return 0.1 if seq["n"] < 4 else 5.0

        zc.idle_seconds = idle_seq
        assert runner._wait_user_idle(cfg_dict, abort) is False, "停止操作后应放行"

        # ④ user_idle_s = 0 关闭保护 → 立即放行
        off = ConfigStore(tmp / "off.yaml")
        off.patch({"retry": {"user_idle_s": 0}})
        zc.idle_seconds = lambda: 0.0
        started = time.time()
        assert runner._wait_user_idle(off.all(), abort) is False
        assert time.time() - started < 0.3, "关闭保护后不应等待"

        # ⑤ 读不到输入状态 → 放行,避免因系统差异卡死流程
        zc.idle_seconds = lambda: None
        assert runner._wait_user_idle(cfg_dict, abort) is False
    finally:
        zc.idle_seconds = orig
    return "用户占用时等待/跳过;关闭保护与读数失败均放行"


def __ui_assets_case():
    from core.config import UI_DIR

    required = [
        "index.html",
        "assets/css/app.css",
        "assets/js/api.js",
        "assets/js/events.js",
        "assets/js/motion.js",
        "assets/js/app.js",
        "assets/js/vendor/gsap.min.js",
        "assets/js/pages/dashboard.js",
        "assets/js/pages/flow.js",
        "assets/js/pages/schedule.js",
        "assets/js/pages/vision.js",
        "assets/js/pages/logs.js",
        "assets/js/pages/settings.js",
    ]
    missing = [rel for rel in required if not (UI_DIR / rel).is_file()]
    assert not missing, f"缺少前端文件:{missing}"
    return f"{len(required)} 个前端文件齐全"


def __runner_dry_case():
    """演练模式 + 不存在的窗口标题:验证单次尝试、步骤记录与收尾(不启动/不点击客户端)。"""
    import json
    import tempfile
    from pathlib import Path

    from core.config import ConfigStore
    from core.events import EventBus
    from core.runner import Runner
    from core.storage import SessionStore
    from core.vision import VisionClient

    tmp_dir = Path(tempfile.mkdtemp(prefix="zcode-runner-"))
    cfg = ConfigStore(tmp_dir / "config.yaml")
    cfg.patch({
        "app": {"dry_run": True, "window_title_match": "NoSuchWindow-Zz-9999"},
        "retry": {"open_timeout_s": 5, "settle_s": 0, "watchdog_s": 60},
    })
    store = SessionStore(tmp_dir / "shots")
    runner = Runner(cfg, EventBus(), store, VisionClient(cfg))

    result = runner.run_session("manual", {"time": None, "attempts": 2, "retry_gap_s": 1})
    assert result and result["status"] == "dry_run", f"状态异常:{result}"
    session_file = tmp_dir / "shots" / result["session_id"] / "session.json"
    data = json.loads(session_file.read_text(encoding="utf-8"))
    assert len(data["attempts"]) == 1, "演练模式应点到即止(仅 1 次尝试)"
    assert data["attempts"][0]["steps"], "步骤未被记录"
    assert data["ended_at"], "收尾信息缺失"
    return f"演练尝试已记录并正确收尾({result['summary']})"


def __runner_retry_case():
    """验证重试循环:把单次尝试替换为固定失败,检查次数/间隔/最终状态(无任何真实操作)。"""
    import json
    import tempfile
    from pathlib import Path

    from core.config import ConfigStore
    from core.events import EventBus
    from core.runner import Runner
    from core.storage import SessionStore
    from core.vision import VisionClient

    tmp_dir = Path(tempfile.mkdtemp(prefix="zcode-retry-"))
    cfg = ConfigStore(tmp_dir / "config.yaml")
    cfg.patch({"app": {"dry_run": False}, "retry": {"watchdog_s": 60}})
    store = SessionStore(tmp_dir / "shots")
    runner = Runner(cfg, EventBus(), store, VisionClient(cfg))

    import core.runner as runner_module
    runner_module.notify = lambda *args, **kwargs: None  # 自检不弹桌面通知

    calls = {"n": 0}

    def fake_attempt(session, attempt, dry, abort, cfg):
        calls["n"] += 1
        return "retry", f"模拟失败 {calls['n']}"

    runner._one_attempt = fake_attempt
    runner._close_client = lambda dry: None

    started = time.time()
    result = runner.run_session("manual", {"time": None, "attempts": 3, "retry_gap_s": 1})
    elapsed = time.time() - started
    assert result and result["status"] == "failed", f"状态异常:{result}"
    assert calls["n"] == 3, f"重试次数异常:{calls['n']}"
    assert elapsed >= 2.0, f"重试间隔未生效(耗时 {elapsed:.1f}s)"
    data = json.loads(
        (tmp_dir / "shots" / result["session_id"] / "session.json").read_text(encoding="utf-8")
    )
    assert len(data["attempts"]) == 3 and data["attempts"][2]["result"] == "retry"
    return f"3 次重试后正确收尾,共耗时 {elapsed:.1f}s"


def __http_case():
    import core.server as server_module
    from core import api as api_module

    api = getattr(api_module, "_SELFTEST_API", None)
    assert api is not None, "先执行上一项检查"

    bus = api.bus
    server = server_module.serve(api, bus, port=8765)
    url = server.url

    def post(method, payload):
        body = json.dumps({"method": method, "args": [payload]}).encode()
        req = urllib.request.Request(url + "api", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    data = post("get_state", None)
    assert "result" in data and "master" in data["result"], data
    assert post("get_logs", {"limit": 5})["result"]["items"] is not None
    assert post("no_such_method", None).get("error"), "未知方法应返回 error"

    # 静态资源与事件流
    with urllib.request.urlopen(url, timeout=10) as resp:
        html = resp.read().decode("utf-8")
    assert "ZCode 福利助手" in html, "首页内容异常"
    with urllib.request.urlopen(url + "assets/css/app.css", timeout=10) as resp:
        assert resp.status == 200

    got = {}

    def listen():
        try:
            with urllib.request.urlopen(url + "events", timeout=8) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "ignore").strip()
                    if line.startswith("data: "):
                        got.update(json.loads(line[6:]))
                        break
        except Exception:
            pass

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    time.sleep(0.6)
    bus.publish("state_change", {"hello": "selftest"})
    thread.join(timeout=6)
    assert got.get("type") == "state_change", f"SSE 未收到事件:{got}"

    # 危险路径防护
    assert post("get_shot", {"session": "../../", "name": "x"})["result"]["ok"] is False
    # 前端就绪握手(面板加载完成会调用,用于确认链路与事件推送)
    assert post("ui_ready", None)["result"]["ok"] is True
    assert api.ui_ready_event.is_set(), "ui_ready 未生效"
    return "RPC / 静态资源 / SSE / 目录穿越防护全部正常"


def __frozen_path_case():
    """冻结路径分流:打包后资源从 _MEIPASS 读、数据写到 exe 同级。

    不真的打包,而是用一个隔离进程把 sys.frozen / sys._MEIPASS 造出来,
    再 import core.config,验证路径常量落在预期位置。
    """
    import subprocess
    import tempfile
    from pathlib import Path

    from core.config import FROZEN, UI_DIR, DATA_DIR

    # 源码运行:FROZEN 为假,资源与数据都在项目根下
    assert FROZEN is False, "源码运行时 FROZEN 应为 False"
    assert UI_DIR.name == "ui" and UI_DIR.is_dir(), f"UI_DIR 不对:{UI_DIR}"
    expected_data = Path(__file__).resolve().parent / "data"
    assert DATA_DIR == expected_data, f"源码运行的 DATA_DIR 应为项目 data/:{DATA_DIR}"

    # 打包运行:在子进程里伪造 frozen 环境。
    # 子进程代码写到临时文件再执行,避免多层引号/转义把脚本拼坏。
    with tempfile.TemporaryDirectory() as tmp:
        meipass = Path(tmp) / "meipass"
        exe_dir = Path(tmp) / "exe"
        (meipass / "ui").mkdir(parents=True)
        (meipass / "ui" / "index.html").write_text("x", encoding="utf-8")
        exe_dir.mkdir(parents=True)

        script = exe_dir / "check.py"
        script.write_text(
            "import sys, pathlib\n"
            "sys.frozen = True\n"
            f"sys._MEIPASS = {str(meipass)!r}\n"
            f"sys.executable = {str(exe_dir / 'ZCode.exe')!r}\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
            "from core import config as c\n"
            "assert c.FROZEN is True, 'FROZEN 未生效'\n"
            f"assert c.UI_DIR == pathlib.Path({str(meipass / 'ui')!r}), f'UI_DIR 应为 _MEIPASS/ui: {{c.UI_DIR}}'\n"
            f"assert c.DATA_DIR == pathlib.Path({str(exe_dir / 'data')!r}), f'DATA_DIR 应为 exe 同级 data/: {{c.DATA_DIR}}'\n"
            "assert c.CONFIG_PATH.parent == c.DATA_DIR, 'CONFIG_PATH 应落在 DATA_DIR 内'\n"
            "assert c.LOG_DIR.parent == c.DATA_DIR, '日志目录应落在 DATA_DIR 内'\n"
            "assert c.SHOTS_DIR.parent == c.DATA_DIR, '截图目录应落在 DATA_DIR 内'\n"
            "print('ok')\n",
            encoding="utf-8",
        )
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=90)
        assert proc.returncode == 0, f"冻结路径模拟失败:{proc.stderr.strip()[-300:]}"
        assert "ok" in proc.stdout, f"子进程输出异常:{proc.stdout!r}"

    return "源码与冻结两种模式路径均正确(资源 _MEIPASS / 数据 exe 同级)"


def __single_instance_case():
    """单实例锁:同进程重复 acquire 幂等;跨进程第二个必须被拒。

    父进程持锁期间子进程应拿不到;释放后子进程应能拿到。
    """
    import subprocess
    import tempfile
    from pathlib import Path

    from core import single_instance as si

    if sys.platform != "win32":
        assert si.acquire() is True
        si.release()
        return "非 Windows 平台:跳过多实例校验(acquire 恒放行)"

    assert si.acquire() is True, "首次 acquire 应成功"
    assert si.acquire() is True, "同进程重复 acquire 应幂等返回 True"

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "child.py"
        script.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
            "from core.single_instance import acquire\n"
            "print('ACQUIRED' if acquire() else 'BLOCKED')\n",
            encoding="utf-8",
        )
        blocked = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=90)
        assert blocked.returncode == 0, f"子进程执行失败:{blocked.stderr.strip()[-200:]}"
        assert "BLOCKED" in blocked.stdout, f"已有实例时子进程不应拿到锁,实际:{blocked.stdout!r}"

        si.release()
        free = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=90)
        assert "ACQUIRED" in free.stdout, f"释放后子进程应能拿到锁,实际:{free.stdout!r}"

    return "同进程幂等;跨进程占用时被拒、释放后可获得"


def __awake_case():
    """防休眠:开关语义、execution 嵌套计数、以及真的会调用系统 API。

    会短暂调用 SetThreadExecutionState(改的是"本进程所在线程"的执行状态,
    进程退出即失效,不影响系统设置),调用后立刻复位。
    """
    from core import awake

    if sys.platform != "win32":
        assert awake.is_active() is False
        return "非 Windows 平台:仅验证状态机(调用直接返回 False)"

    # 初始:未保活
    awake.set_always(False)
    assert awake.is_active() is False, "初始应为未保活"

    # always 模式:开启 → 激活;关闭 → 失活
    assert awake.set_always(True) is True, "set_always(True) 应成功调用系统 API"
    assert awake.is_active() is True, "always 开启后应处于保活"
    assert awake.set_always(False) is True, "set_always(False) 应成功"
    assert awake.is_active() is False, "always 关闭后应失活"

    # execution 模式:嵌套计数,内层退出不应提前解除
    awake.start_execution()
    assert awake.is_active() is True, "进入执行应保活"
    awake.start_execution()
    awake.stop_execution()
    assert awake.is_active() is True, "仍有外层嵌套时不应解除保活"
    awake.stop_execution()
    assert awake.is_active() is False, "全部退出后应解除保活"
    awake.stop_execution()          # 多余调用不应把计数弄成负数
    assert awake.is_active() is False, "多余 stop 后仍应失活"

    # always 与 execution 叠加:always 开着时,执行结束不该解除保活
    awake.set_always(True)
    awake.start_execution()
    awake.stop_execution()
    assert awake.is_active() is True, "always 模式开着时,执行结束应继续保活"
    awake.set_always(False)
    assert awake.is_active() is False

    return "always 开关 / execution 嵌套计数正确,且确实调用了 SetThreadExecutionState"


def __shortcut_resolve_case():
    """开始菜单 .lnk 解析(win32com 延迟导入链路)。

    打包后 win32com 若漏打,自动探测会静默退化成"找不到 ZCode";
    这里直接调用解析函数,确认该链路在本机可用。
    本机没有 ZCode 快捷方式时跳过(那种情况下这条链路本来就不参与)。
    """
    from pathlib import Path

    import core.zcode_ctrl as zc

    lnks = []
    for d in zc._start_menu_dirs():
        try:
            lnks.extend(p for p in d.rglob("*.lnk") if "zcode" in p.stem.lower())
        except OSError:
            continue

    if not lnks:
        return "本机开始菜单无 ZCode 快捷方式,跳过该项(不影响使用)"

    target = zc._resolve_lnk(lnks[0])
    assert target, f"快捷方式解析失败:{lnks[0]}(win32com 可能不可用)"
    assert target.lower().endswith(".exe"), f"解析结果不是 exe:{target}"
    assert Path(target).is_file(), f"解析出的路径不存在:{target}"
    return f"快捷方式解析正常:{lnks[0].name} → {target}"


if __name__ == "__main__":
    sys.exit(main())
