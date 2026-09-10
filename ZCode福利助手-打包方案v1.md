# ZCode 福利助手 — 打包方案 v1.1

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-10(v1.1:按当前代码校对数据) |
| 目标 | 把项目打包成可在本机/其他 Windows 机器直接双击运行的独立程序 |
| 已定决策 | **onedir(文件夹)** · **实现防休眠** · **自动生成图标** |
| 打包工具 | PyInstaller 6.22.2(官方 CHANGES 确认 **6.15.0 起支持 Python 3.14**;本机 3.14.4 兼容) |
| 关联文档 | 《技术方案 v1.1》《UI 设计方案 v1.1》(注:UI 已按「静默方格」重做,该文档待同步) |

---

## 1. 打包前置:必须修的 5 处代码

打包最容易出"源码能跑、打包即崩"的问题,以下 5 项是硬性前置。

| # | 文件 | 问题 | 改法 |
|---|---|---|---|
| 1 | `core/config.py` | `PROJECT_ROOT = Path(__file__).resolve().parents[1]`。打包后 `__file__` 指向临时解包目录,**配置每次重启丢失、截图日志写进临时目录** | 用 `getattr(sys, "frozen", False)` 分支:资源从 `sys._MEIPASS` 读,用户数据写到 exe 同级 `data/`;该目录不可写时回退 `%LOCALAPPDATA%\ZCode福利助手\`。**源码运行行为保持不变** |
| 2 | `core/logging_setup.py` | 第 54 行 `logger.add(sys.stderr, ...)` 无条件执行。`--windowed` 模式下 `sys.stderr is None`,启动即抛异常 | 仅在 `sys.stderr` 存在时挂控制台输出 |
| 3 | `main.py` | 无单实例保护,**双击两次会跑两个调度器,同一场次领取两次** | 加 `CreateMutex` 命名互斥锁;已存在实例时打印/打开面板地址后退出 |
| 4 | `core/awake.py`(新增) | 设置页有"防休眠"勾选框;`keep_awake` 只在 `core/config.py` 定义为默认值、在 `core/api.py` 读取给前端显示,**全项目没有任何地方调用 `SetThreadExecutionState`** —— 是个空开关 | 新模块实现保活,见 §3 |
| 5 | `selftest.py` | 缺打包相关自检 | 补 3 项:冻结路径解析、单实例锁、防休眠调用(当前 21 项 → 24 项,见 §4) |

### 1.1 路径分流细则(实现要点)

```python
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    RESOURCE_DIR = Path(sys._MEIPASS)            # ui/ 等只读资源
    DATA_DIR     = Path(sys.executable).parent / "data"
    if not writable(DATA_DIR):
        DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "ZCode福利助手"
else:
    RESOURCE_DIR = PROJECT_ROOT
    DATA_DIR     = PROJECT_ROOT / "data"
```

---

## 2. 新增文件

```
build/
├── app.ico               # 自动生成:深色圆角底 + 白色几何 Z,含 256/128/64/48/32/16
└── version_info.txt      # 产品名/版本/版权 → 显示在"属性 → 详细信息"
ZCode福利助手.spec        # PyInstaller 配置
build.bat                # 一键打包(含清理旧产物)
dist/ZCode福利助手/
└── 使用说明.txt          # 随包分发的精简说明(含杀软白名单提示)
```

### 2.1 spec 必须排除的内容

| 排除项 | 原因 |
|---|---|
| `data/` | **含 API Key 明文 + 屏幕截图(隐私内容)。当前 shots 40 张 3.6MB、probe 33 张 7.4MB、logs 320KB,合计约 11MB** |
| `.venv/`、`__pycache__/` | 构建无关 |
| `pyflakes` | 仅 `selftest.py` 使用(已核实运行时不引用) |
| `selftest.py`、`probe.py` 及对应 `.bat` | 开发期工具,运行时不引用(已核实);`run.bat` / `dry-run.bat` 是源码运行入口,打包后也不需要 |
| **`ui/demos/`** | **前端选型用的 5 个设计原型 + 29 张截图,合计 4.1MB,面板不会引用它。`server.py` 的静态处理器虽然能服务 `ui/` 下任意路径,但只有 `index.html` 与 `assets/` 会被请求,排除后不影响使用(直接访问 `/demos/...` 会 404,无副作用)** |
| `data/probe/` | 项目里也应清理(见 §6 遗留项) |

> 前端资源只需打包 `ui/index.html` + `ui/assets/`(**212KB** + 36KB)。若不排除 `ui/demos/`,它会以 4.1MB 的体量进包。

### 2.2 产物形态

```
dist/ZCode福利助手/
├── ZCode福利助手.exe     ← 双击运行
├── _internal/            ← 依赖 + ui 资源(PyInstaller 6.x 布局)
└── data/                 ← 首次运行自动生成(config / logs / shots)
```

预计体积 **60–90MB**(Pillow + pywin32 + httpx)。onedir 启动快、不额外解包、便于排障。

### 2.3 已知的隐性依赖(打包后容易"功能静默失效"的地方)

| 位置 | 说明 |
|---|---|
| `core/zcode_ctrl.py` 的 `_resolve_lnk()` | 函数内延迟 `import pythoncom` / `from win32com.client import Dispatch`。**PyInstaller 的静态分析看不到函数内导入**,需在 spec 的 `hiddenimports` 里显式声明 `pythoncom`、`win32com.client`、`pywintypes`。漏掉不会崩:该函数有 `except Exception: return None` 兜底,只会退化成"扫不到开始菜单快捷方式",自动探测 ZCode 路径更容易失败 —— 属于静默降级,验证清单 §5 第 8 项要顺带确认「自动探测」按钮仍有效 |
| `core/notify.py` | 桌面通知走 `powershell -EncodedCommand` 调 WinRT。依赖系统 PowerShell,与 PyInstaller 无关,但「无 PowerShell 的极简系统」会失败(已用 `errors="replace"` 兜底,不会崩) |

---

## 3. 防休眠设计(本次要实现)

调用 `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)`。

**为什么连显示器一起保活**:只保系统不保显示器时,屏幕一黑 `mss` 截到黑图,识别直接失败。

| 模式 | 行为 | 代价 |
|---|---|---|
| `always`(默认,建议) | 程序运行期间系统与显示器都不睡 → **定时一定能触发** | 显示器常亮(可手动关显示器,不影响程序) |
| `execution` | 仅在执行场次前后保活 | **系统睡了场次就不会触发**(调度器随进程挂起) |

### 3.1 必须告知的限制

**该 API 阻止不了锁屏。** 锁屏是安全策略,不是电源策略。一旦锁屏,现有锁屏检测(§技术方案 E2b)会把该场次判为"需人工"并跳过。因此部署时应:

- 屏幕保护设为「无」
- 锁屏超时设为「从不」

如需"系统睡眠也能唤醒领取",须改用 **Windows 任务计划程序**(勾选"唤醒计算机运行此任务"),属另一套方案,不在本次范围。

---

## 4. 打包与验证步骤

```
① 改 §1 的 5 处代码
② 跑自检(当前 21 项;补完 §1 第 5 项后应为 24 项,全过再打包)
③ build.bat → dist/ZCode福利助手/
④ 按 §5 清单验证产物
```

## 5. 打包后验证清单(9 项)

| # | 验证项 | 关注点 |
|---|---|---|
| 1 | 双击 exe → 面板打开、`get_state` 正常 | 资源是否打进去了 |
| 2 | 数据目录落在 exe 同级,重启后配置仍在 | 冻结路径分流是否生效 |
| 3 | 窗口查找 / 置顶 / 最大化 | **pywin32 打包后最常见出问题处** |
| 4 | 截图与点击坐标对齐 | DPI 感知 + 多显示器 |
| 5 | Windows 桌面通知 | 打包后 PowerShell 调用链 |
| 6 | DeepSeek 视觉 API 联网 | httpx + SSL 证书打包 |
| 7 | 单实例:双击两次是否正确提示 | 互斥锁 |
| 8 | **设置页「自动探测」按钮能找 ZCode** | `hiddenimports` 是否漏 `win32com`(见 §2.3) |
| 9 | 杀软是否拦截 | pyautogui 模拟点击 + 无签名 exe |

## 6. 已知风险

| 风险 | 影响 | 应对 |
|---|---|---|
| 无签名 exe | 首次运行弹 SmartScreen「Windows 已保护你的电脑」 | 点「更多信息 → 仍要运行」;彻底解决需购买代码签名证书 |
| 杀软误报 | pyautogui 模拟点击行为可能被判可疑 | 加入白名单 |
| onedir 不便携 | 整个文件夹需一起复制,不能只拿 exe | 使用说明中写明 |
| 打包体积 | 60–90MB | onedir 属正常范围 |

## 7. 遗留项(本次不做,记录在案)

| 项 | 说明 |
|---|---|
| 开机自启 | 用户选择本次不加。定时场景若需重启后自动运行,需在设置页加开关(写启动文件夹快捷方式) |
| 任务计划唤醒 | 系统睡眠状态下的定时触发方案 |
| 配置加密 | 当前 API Key 明文存 `config.yaml`;可改为环境变量或 DPAPI 加密 |
| `data/` 清理 | 当前 shots 40 张 3.6MB、probe 33 张 7.4MB(共约 11MB)含屏幕隐私内容,发布或打包前建议清空。两者都在 `.gitignore` 内,**不会进版本库**,仅占本机磁盘 |
| 《UI 设计方案 v1.1》待同步 | 该文档描述的是重做前的界面(渐变 Logo、滑动光条、玻璃拟态)。前端已按「静默方格」重做,文档里的页面结构、组件规范、动效章节与新实现不再一致 |
