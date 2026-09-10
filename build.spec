# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置(onedir)。

构建:
    .venv\\Scripts\\pyinstaller.exe ZCode福利助手.spec --noconfirm --clean
或直接用 build.bat(含清理与图标生成)。

关键点:
1. 只打包 ui/index.html + ui/assets/,**排除 ui/demos/**(选型原型与截图,
   4.1MB,面板不引用)。
2. data/ 绝不打包:里面是 API Key 明文与屏幕截图。
3. win32com / pythoncom 是函数内延迟导入,静态分析看不到,必须写进
   hiddenimports,否则「自动探测 ZCode 路径」会静默失效。
4. 排除开发期工具(selftest / probe)与 pyflakes。
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()
IS_WIN = sys.platform == "win32"

# ---------- 数据文件:只带前端运行时真正用到的部分 ----------
datas = [
    (str(ROOT / "ui" / "index.html"), "ui"),
    (str(ROOT / "ui" / "assets"), "ui/assets"),
]

# ---------- 隐藏导入 ----------
hiddenimports = [
    # 函数内延迟导入(PyInstaller 静态分析盲区)
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    # pywin32 常用子模块,避免按需导入时缺失
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
]
hiddenimports += collect_submodules("apscheduler")

# ---------- 排除:缩小体积 + 避免误带隐私数据 ----------
excludes = [
    "data",              # 不是模块,但显式声明意图(真正靠 datas 控制)
    "ui.demos",
    "pyflakes",
    "selftest",
    "probe",
    # 开发/构建期依赖,运行不需要
    "PyInstaller",
    "setuptools",
    "pip",
    "pytest",
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "test",
    # 科学计算/图像处理的大件(Pillow 已足够,不需要这些)
    "numpy",
    "scipy",
    "pandas",
    "matplotlib",
    "IPython",
    "notebook",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZCodeAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX 压缩常被杀软误报,这里关掉
    console=False,                  # 双击不弹黑窗(日志仍写 data/logs)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "build" / "app.ico") if (ROOT / "build" / "app.ico").exists() else None,
    version=str(ROOT / "build" / "version_info.txt")
    if (ROOT / "build" / "version_info.txt").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZCodeAssistant",
)
