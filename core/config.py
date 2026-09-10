"""配置管理:data/config.yaml 与默认值深度合并,线程安全读写。

配置结构见技术方案 §8。UI 每次修改走 patch() 即时落盘。

路径分两种,打包后必须分开:
  资源(ui/)      从解包目录 sys._MEIPASS 读,只读
  数据(data/)    写到 exe 同级目录,保证重启后配置还在;不可写时回退 LOCALAPPDATA
源码运行时两者都在项目根目录下,行为与以前完全一致。
"""
from __future__ import annotations

import copy
import os
import sys
import threading
from pathlib import Path

import yaml

FROZEN = getattr(sys, "frozen", False)


def _writable(path: Path) -> bool:
    """目录是否可写(不存在则看父目录能否创建)。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


if FROZEN:
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _exe_dir = Path(sys.executable).parent
    DATA_DIR = _exe_dir / "data"
    if not _writable(DATA_DIR):
        # exe 放在 Program Files 等只读位置时,退到用户目录
        _fallback = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ZCode福利助手" / "data"
        DATA_DIR = _fallback if _writable(_fallback) else DATA_DIR
    # 打包后没有"项目根",保留同名常量指向 exe 所在目录(仅开发期工具引用)
    PROJECT_ROOT = _exe_dir
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    RESOURCE_DIR = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"

CONFIG_PATH = DATA_DIR / "config.yaml"
LOG_DIR = DATA_DIR / "logs"
SHOTS_DIR = DATA_DIR / "shots"
UI_DIR = RESOURCE_DIR / "ui"

DEFAULTS: dict = {
    "app": {
        "zcode_path": "",
        "window_title_match": "ZCode",
        "fullscreen": True,          # 操作前把客户端最大化(全屏),再截图
        "startup_wait_s": 5.0,       # 启动客户端后等待界面加载的秒数(加载期画面可能是纯色)
        "restore_window_rect": True,
        "window_rect": [40, 40, 1240, 860],
        "dry_run": False,
    },
    "schedule": {
        "enabled": True,
        # 示例: {"time": "10:00", "enabled": True, "attempts": None, "retry_gap_s": None}
        "slots": [],
        "keep_awake": True,
    },
    "vision": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-v4-flash-vision-exp",
        "temperature": 0.2,
        "detail": "auto",
        "max_tokens": 800,
        "timeout_s": 20,
        "locate_confidence_min": 0.70,
        "humanize_mouse": False,
    },
    "retry": {
        "max_attempts": 5,
        "retry_gap_s": 5,
        "open_timeout_s": 30,
        "verify_delay_s": 2.5,   # 结果弹窗是服务端往返,留足渲染时间再截图
        "settle_s": 2.0,
        "focus_settle_s": 0.4,
        "app_ready_timeout_s": 20,     # 等待客户端界面渲染完成(加载期纯色不算锁屏)
        "verify_ready_timeout_s": 8,   # 点击后等待结果弹窗渲染完成的最长秒数
        "ready_poll_s": 1.0,           # 渲染等待的轮询间隔
        "uniform_ratio_max": 0.98,     # 单色占比高于此值视为"还没渲染出来"
        "user_idle_s": 1.0,            # 需连续多少秒无键鼠输入才动手(0=关闭该保护)
        "user_idle_wait_s": 20,        # 用户正在用电脑时,最多等这么久再放弃本场
        "watchdog_s": 480,       # 需覆盖 5 次完整尝试(每次含 2 次视觉调用)
    },
    "success_keywords": ["领取成功", "开始体验", "奖励到账", "已到账", "领取奖励", "获得", "+"],
    "claimed_keywords": ["已领取", "今日已领", "今日已领取", "明天再来", "明日再来", "已参加", "次数已用完"],
    "failure_keywords": ["领取失败", "知道了"],
    "notify": {
        "desktop": True,
        "webhook_url": "",
    },
    "data": {
        "keep_days": 7,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """override 覆盖 base 的深度合并,返回新 dict。"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    """读取配置并与默认值合并(缺项自动补全)。"""
    user_cfg: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            user_cfg = raw
    return _deep_merge(DEFAULTS, user_cfg)


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    """写盘(UTF-8,允许中文原文)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class ConfigStore:
    """线程安全的配置容器,支持分节 patch 即时落盘。"""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cfg = load_config(self.path)
        if not self.path.exists():
            save_config(self._cfg, self.path)

    def get(self, *keys, default=None):
        """cfg.get("vision") 或 cfg.get("retry", "max_attempts")。"""
        with self._lock:
            node = self._cfg
            for key in keys:
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return node

    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._cfg)

    def patch(self, patch_dict: dict) -> dict:
        """深度合并并落盘,返回合并后的完整配置。"""
        with self._lock:
            self._cfg = _deep_merge(self._cfg, patch_dict or {})
            save_config(self._cfg, self.path)
            return copy.deepcopy(self._cfg)

    def reset(self) -> dict:
        """恢复默认配置(保留 zcode_path 与 api_key 之外全部重置)。"""
        with self._lock:
            keep = {
                "app": {"zcode_path": self._cfg.get("app", {}).get("zcode_path", "")},
                "vision": {"api_key": self._cfg.get("vision", {}).get("api_key", "")},
            }
            self._cfg = _deep_merge(DEFAULTS, keep)
            save_config(self._cfg, self.path)
            return copy.deepcopy(self._cfg)
