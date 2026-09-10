"""ZCode 客户端进程与窗口控制(Windows / pywin32)。

职责:探测 exe、枚举窗口、启动/置前/复位窗口、结束进程树。
只操作「标题匹配到的那个窗口及其进程」,不碰其他程序。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process
from loguru import logger

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 任何情况下都不得结束的进程:系统外壳/关键进程 + 本程序自身
# (实测事故:标题为 "zcode-free" 的窗口被误当成 ZCode 客户端,进程随后被结束)
PROTECTED_EXES = {
    "explorer.exe", "dwm.exe", "winlogon.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "smss.exe", "svchost.exe", "sihost.exe",
    "taskhostw.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "textinputhost.exe", "runtimebroker.exe", "ctfmon.exe",
    "python.exe", "pythonw.exe",           # 本程序自己就是 python
    "chrome.exe", "msedge.exe", "firefox.exe",  # 面板网页标题含 "ZCode"
}


def is_protected_exe(path: str | None) -> bool:
    return bool(path) and Path(path).name.lower() in PROTECTED_EXES


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def verify_client_window(win: dict | None, expected_exe: str = "",
                         exe_name_match: str = "zcode") -> tuple[bool, str]:
    """确认窗口确实属于 ZCode 客户端,返回 (是否通过, 原因)。

    只靠标题匹配是不够的:标题里恰好含 "zcode" 的窗口(项目文件夹名、面板网页
    "ZCode 福利助手"、同名目录窗口等)都会被误认。这里追加进程级校验:
    优先与配置的 exe 路径严格比对;未配置路径时要求进程名含关键字且不是受保护进程。
    """
    win = win or {}
    hwnd = win.get("hwnd")
    if not hwnd:
        return False, "窗口句柄无效"
    pid = window_pid(hwnd)
    if not pid:
        return False, "无法获取窗口所属进程"
    path = process_path(pid)
    if not path:
        return False, f"无法读取进程路径(PID {pid},可能权限不足)"
    name = Path(path).name.lower()
    if name in PROTECTED_EXES:
        return False, f"进程 {name} 属于受保护/无关程序,已排除"
    if expected_exe:
        if _same_path(path, expected_exe):
            return True, f"进程匹配:{path}"
        return False, f"进程 {path} 与配置的 {expected_exe} 不一致"
    if exe_name_match and exe_name_match in name and name.endswith(".exe"):
        return True, f"进程名匹配:{path}"
    return False, f"进程名 {name} 不含关键字「{exe_name_match}」"


def find_client_window(title_match: str, expected_exe: str = "") -> dict | None:
    """按标题找候选窗口,但只返回通过进程校验的那个;被拒候选写日志便于排查。"""
    rejected: list[str] = []
    for win in sorted(list_windows(title_match), key=lambda w: -w["area"]):
        ok, reason = verify_client_window(win, expected_exe)
        if ok:
            return win
        rejected.append(f"{win['title']!r} → {reason}")
    for item in rejected:
        logger.warning(f"已忽略标题相近但校验不通过的窗口:{item}")
    return None


def wait_client_window(title_match: str, timeout: float, expected_exe: str = "") -> dict | None:
    """轮询等待"通过进程校验"的客户端窗口出现。"""
    deadline = time.time() + max(float(timeout), 1.0)
    while time.time() < deadline:
        win = find_client_window(title_match, expected_exe)
        if win:
            return win
        time.sleep(0.5)
    return None


# ---------------- 窗口 ----------------

def list_windows(title_match: str) -> list[dict]:
    """枚举可见窗口,标题包含关键字(不区分大小写)的返回 {hwnd,title,rect,area}。"""
    match = (title_match or "").lower()
    out: list[dict] = []

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return True
        if not title or (match and match not in title.lower()):
            return True
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return True
        out.append({"hwnd": hwnd, "title": title, "rect": [left, top, w, h], "area": w * h})
        return True

    win32gui.EnumWindows(_cb, None)
    return out


def find_window(title_match: str) -> dict | None:
    """取面积最大的匹配窗口(通常是主窗口)。"""
    windows = list_windows(title_match)
    if not windows:
        return None
    return max(windows, key=lambda x: x["area"])


def window_pid(hwnd: int) -> int | None:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return int(pid) or None
    except Exception:
        return None


def _is_foreground(hwnd: int) -> bool:
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def foreground(hwnd: int) -> bool:
    """还原(如最小化)并置前;前台锁定夺不到焦点时,至少把窗口抬到 z 序顶部。

    返回是否真正成为前台窗口(截图前调用,避免被其他窗口遮挡)。
    """
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass

    for _ in range(3):
        if _is_foreground(hwnd):
            return True
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # 前台锁定限制:用 ALT 键解锁后再试
            try:
                win32api.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
                win32gui.SetForegroundWindow(hwnd)
                win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
        if _is_foreground(hwnd):
            return True
        # 仍抢不到前台时,抬高 z 序:即使不抢键盘焦点,也不会被其他窗口压在下面
        try:
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
        except Exception:
            pass
        time.sleep(0.25)

    ok = _is_foreground(hwnd)
    if not ok:
        logger.warning("窗口未能置前(已尝试抬高 z 序),截图仍可能被遮挡")
    return ok


def move_window(hwnd: int, rect: list[int] | tuple[int, int, int, int]) -> None:
    x, y, w, h = (int(v) for v in rect)
    win32gui.MoveWindow(hwnd, x, y, w, h, True)


def maximize(hwnd: int) -> None:
    """把客户端窗口最大化(全屏显示),便于稳定截图与定位。"""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    except Exception as exc:
        logger.warning(f"窗口最大化失败:{exc}")


def window_rect(hwnd: int) -> list[int] | None:
    """读取窗口当前 [x, y, w, h];窗口无效(如仍最小化)时返回 None。

    置顶/还原后重新取一次位置,避免用最小化状态下的无效坐标去截图。
    """
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    return [left, top, width, height]


# ---------------- 进程 ----------------

def is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    handle = None
    try:
        handle = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        return win32process.GetExitCodeProcess(handle) == STILL_ACTIVE
    except Exception:
        return False
    finally:
        if handle:
            try:
                win32api.CloseHandle(handle)
            except Exception:
                pass


def launch(exe: str) -> subprocess.Popen:
    exe_path = Path(exe)
    if not exe_path.is_file():
        raise FileNotFoundError(f"ZCode.exe 不存在:{exe}")
    logger.info(f"启动客户端:{exe}")
    return subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))


def wait_window(title_match: str, timeout: float) -> dict | None:
    """轮询等待窗口出现(不做进程校验;面向客户端的场景请用 wait_client_window)。"""
    deadline = time.time() + max(float(timeout), 1.0)
    while time.time() < deadline:
        win = find_window(title_match)
        if win:
            return win
        time.sleep(0.5)
    return None


def kill_tree(pid: int | None, timeout: float = 15.0, expected_exe: str = "") -> bool:
    """结束进程树并等待其真正退出。

    带三重安全闸:受保护进程一律拒绝;进程路径必须可读;若给了 expected_exe,
    必须与之严格一致——避免 PID 复用或误判窗口导致关掉无关程序。
    """
    if not pid:
        return False
    path = process_path(pid)
    if not path:
        logger.error(f"拒绝结束 PID {pid}:无法读取其进程路径,无法确认身份")
        return False
    if is_protected_exe(path):
        logger.error(f"拒绝结束受保护进程 {Path(path).name}(PID {pid})")
        return False
    if expected_exe and not _same_path(path, expected_exe):
        logger.error(f"拒绝结束 PID {pid}:进程为 {path},与预期 {expected_exe} 不一致")
        return False

    logger.info(f"关闭 ZCode(PID {pid},{path})")
    try:
        res = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            errors="replace",   # taskkill 输出为 GBK,UTF-8 模式下需容错,避免解码异常
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if res.returncode != 0:
            logger.warning(f"taskkill 返回 {res.returncode}:{(res.stderr or res.stdout or '').strip()}")
    except Exception as exc:
        logger.warning(f"taskkill 执行异常:{exc}")
    deadline = time.time() + 8
    while time.time() < deadline and is_alive(pid):
        time.sleep(0.3)
    return not is_alive(pid)


def process_path(pid: int) -> str | None:
    """查询进程可执行文件路径(可能因权限失败)。"""
    handle = None
    try:
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value or None
        return None
    except Exception:
        return None
    finally:
        if handle:
            try:
                ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                pass


# ---------------- exe 探测 ----------------

def find_running_exe(name_match: str = "zcode") -> str | None:
    """从运行中的进程里找(最可靠:用户已打开过客户端)。"""
    match = name_match.lower()
    try:
        pids = win32process.EnumProcesses()
    except Exception:
        return None
    for pid in pids:
        if pid <= 4:
            continue
        path = process_path(pid)
        if path and match in Path(path).name.lower():
            return path
    return None


def _start_menu_dirs() -> list[Path]:
    dirs = []
    for key in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(key)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.exists()]


def _resolve_lnk(path: Path) -> str | None:
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        target = ""
        try:
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(path))
            target = str(shortcut.TargetPath or "")
            del shortcut
            del shell
        finally:
            pythoncom.CoUninitialize()
        return target or None
    except Exception:
        return None


def _iter_files(root: Path, max_depth: int = 3, limit: int = 30000):
    """受限深度遍历,避免全盘扫描。"""
    count = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except OSError:
            continue
        for entry in entries:
            count += 1
            if count > limit:
                return
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        stack.append((Path(entry.path), depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
            except OSError:
                continue


def search_exe(name_match: str = "zcode") -> str | None:
    """扫描开始菜单快捷方式与常见安装目录。"""
    match = name_match.lower()
    for d in _start_menu_dirs():
        try:
            links = list(d.rglob("*.lnk"))
        except OSError:
            continue
        for lnk in links:
            if match in lnk.stem.lower():
                target = _resolve_lnk(lnk)
                if target and target.lower().endswith(".exe") and Path(target).is_file():
                    logger.info(f"从开始菜单找到 ZCode:{target}")
                    return target

    roots: list[Path] = []
    for key in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value))
    roots.append(Path.home() / "AppData" / "Local" / "Programs")
    for root in roots:
        if not root.exists():
            continue
        for f in _iter_files(root, max_depth=3):
            if f.suffix.lower() == ".exe" and match in f.name.lower():
                logger.info(f"在安装目录找到 ZCode:{f}")
                return str(f)
    return None


def autodetect_exe(name_match: str = "zcode") -> str | None:
    """优先从运行进程取路径,其次扫描磁盘。"""
    return find_running_exe(name_match) or search_exe(name_match)
