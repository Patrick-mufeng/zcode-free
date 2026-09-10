# ZCode 福利自动领取助手 — 技术方案 v1.0

| 项 | 内容 |
|---|---|
| 版本 | v1.1(视觉供应商定为 DeepSeek) |
| 日期 | 2026-09-10 |
| 平台 | Windows 10 x64(本机 Python 3.14.4) |
| 项目代号 | `zcode-welfare-bot` |
| 关联文档 | 《ZCode福利助手-UI设计方案v1.md》 |

## 0. 需求决策记录(经提问确认)

| # | 决策点 | 结论 |
|---|---|---|
| D1 | 福利入口 | ZCode **桌面客户端** 内,程序负责打开/操作桌面窗口 |
| D2 | 识别方式 | **截图 + 云端视觉 API(DeepSeek `deepseek-v4-flash-vision-exp`)** 定位按钮与判断状态,鼠标模拟点击 |
| D3 | 领取节奏 | 每天**多个固定时间点**(具体时间表由用户日后在 UI 中配置,默认空) |
| D4 | 程序形态 | **纯 Web 面板**:Python 只做后端(截图/点击/视觉/调度),本地服务 + 浏览器访问(见关联文档) |
| D5 | 成功判定 | 视觉模型读取**提示文案/弹窗**(关键词清单,可配置) |
| D6 | 前置状态 | 打开即**已登录、直达福利页**;仍需页面状态自检兜底 |
| D7 | 福利性质 | **场次内随时可领**(非限量抢),重试策略无需激进,低骚扰 |

用户描述的领取流程(必须原样满足):
**到点 → 打开 ZCode → 截图 → 视觉定位"领取"按钮 → 点击 → 视觉校验是否成功 → 未成功则关闭 ZCode → 等 5 秒 → 重开 → 再试(最多 5 次)→ 仍失败则收尾并等待下一场次。**

## 1. 背景与目标

### 1.1 目标
- 到配置的场次时间,自动完成"打开客户端 → 识别领取 → 点击 → 校验 → 重试"全流程,无需人工。
- 每次尝试留证据(截图),失败可追溯、可通知。
- 提供本地 Web 图形面板(浏览器访问),配置场次/参数、查看日志与截图回放。

### 1.2 非目标(V1 不做)
- 不限量抢购的极速抢跑、并发多开、验证码/扫码自动处理。
- 多账号自动切换登录(V1 单账号,数据模型预留 `account` 字段)。
- 客户端 UI 被改版后的自动适配学习(改版后由人工更新截图/关键词再校准)。

## 2. 总体架构

```
┌────────────────────────── Python 进程(单实例) ──────────────────────────┐
│                                                                        │
│  ┌────────────┐   事件总线   ┌────────────┐                            │
│  │  调度器     │────────────→│  执行器      │  (状态机, 领取核心循环)      │
│  │ APScheduler│ 到点触发     │  Runner     │                            │
│  └────────────┘             └─────┬──────┘                            │
│                                   │ 调用                                 │
│        ┌──────────┬─────────┬─────┴──────┬───────────┬───────────┐     │
│        ▼          ▼         ▼            ▼           ▼           │     │
│  ┌─────────┐ ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐ ┌─────────┐ │
│  │进程/窗口 │ │ 截图模块 │ │ 点击模块 │ │ 视觉识别  │ │ 成功判定 │ │ 通知/日志 │ │
│  │ZCodeCtrl│ │Capture │ │Clicker │ │VisionAPI │ │Validate │ │NotifyLog │ │
│  └────┬────┘ └───┬────┘ └───┬────┘ └────┬─────┘ └───┬────┘ └────┬────┘ │
│       │          │          │           │            │           │     │
│  Windows API    mss       pyautogui    httpx      规则/词表    loguru    │
│  (pywin32)     快速截屏     SendInput   DeepSeek视觉   (纯逻辑)   桌面通知    │
│       └──────────┴──────────┴─────┬─────┴────────────┴─────┬──────┘     │
│                                   ▼                         ▼            │
│                            ZCode 桌面客户端(被操作对象)    data/(截图/日志) │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  UI: 本地 Web 面板(http://127.0.0.1:8760/,浏览器打开,见 UI 文档)  │ │
│  │   ↔ POST /api(JSON-RPC)/ GET /events(SSE)读写配置、日志与截图      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

核心思路一句话:**截全屏并裁出 ZCode 窗口图 → DeepSeek 视觉模型在图中定位按钮(返回归一化坐标)→ 换算成屏幕坐标模拟点击 → 再截图让视觉模型判定结果**,全程不依赖 ZCode 内部结构,客户端改版只需更新关键词与校准截图,不需要改代码框架。

## 3. 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.12+ / 3.14(本机) | — |
| 窗口/进程控制 | `pywin32`(win32gui/win32process) | FindWindow、SetForegroundWindow、ShowWindow、TerminateProcess |
| 截图 | `mss` | 速度最快(≥30fps),多显示器支持好,纯物理像素 |
| 鼠标点击 | `pyautogui`(SendInput 实现) | 简单可靠;开启 FAILSAFE 急停 |
| 视觉识别 | **DeepSeek 官方 API**(OpenAI 兼容),`deepseek-v4-flash-vision-exp` | 见 §3.1,不需 GPU |
| HTTP | `httpx` | 超时/重试可控,依赖轻 |
| 调度 | `APScheduler`(CronTrigger) | 到点触发、跨天计算下一次场次 |
| 配置 | `PyYAML` | 人类可读可编辑 |
| 日志 | `loguru`(按天轮转) | 结构化、留档 |
| 桌面通知 | `winotify` / `plyer` | 成功/失败气泡(可关) |
| UI 面板 | 浏览器 + 本地服务(标准库 `http.server`,零额外依赖) | 见 §3.2 |
| 防休眠 | `ctypes SetThreadExecutionState` | 可选,执行期防系统休眠 |

> 若个别包在 Python 3.14 尚无 wheel,降级方案:py -3.12 建独立 venv(本机已装多版本时)。

### 3.1 视觉 API:DeepSeek(默认,OpenAI 兼容)

统一封装成"聊天补全 + 图片 + 强制 JSON 输出",切换供应商只改 3 个配置项。以下参数已对照官方文档(api-docs.deepseek.com/zh-cn/guides/vision)核实:

| 项 | 值 |
|---|---|
| base_url | `https://api.deepseek.com`(OpenAI 格式;Anthropic 格式 `/anthropic` 不用) |
| model | `deepseek-v4-flash-vision-exp`——当前**唯一支持图片输入**的模型,其他模型传图会报 400 `This model does not support image` |
| 图片传参 | content 块数组:`{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`;也支持公开 http(s) 链接、Files API(本项目用 base64) |
| 结构化输出 | `response_format: {"type":"json_object"}`;官方要求 prompt 中出现 "json" 字样并给出结构示例(我们的 prompt 已满足)。官方未明确视觉模型是否支持该参数 → 代码做兼容:参数报错则去掉重发,最终靠本地 JSON 修复兜底 |
| 图片限制 | PNG/JPEG/GIF/WebP(按文件实际内容判断);单图 ≤32MiB(base64);请求体 ≤48MiB;单边 ≤8192px;单请求 ≤600 张(我们每次只发 1 张) |
| 分辨率行为 | 图片会被内部缩放:**小于约 384×384 会放大、更大的缩到约 800×800 等效**;单图折算 **≤384 tokens**;`detail` 可选 low(512×512)/high/original/auto(默认 auto) |
| 思考模式 | 模型支持思考/非思考两种模式;自动化定位任务优先用**非思考模式**降低延迟(具体开关按官方"思考模式"指南,封装层做成参数) |
| 计费 | 与 `deepseek-v4-flash` 同价:输入 cache miss **1.5(空闲)/ 3.0(高峰)元/百万 tokens**,输出 4.5 / 9.0;高峰=北京时间周一至五 9:00-12:00、14:00-18:00,其余时段空闲价。单次识别(≤384 图 tokens + 数百文本/输出 tokens)≈ **0.002 元**,一天下来成本可忽略 |
| 并发 | 2500,个人使用无任何限制 |

**由"内部缩放到约 800×800"引出的两个关键设计决策:**

1. **发送前先裁剪**:不把 1920×1080 全屏图直接送模型,而是裁出 ZCode 窗口区域(约 1240×860)再送——等效分辨率提升约 2 倍,按钮定位更准、token 更省;窗口位置由程序控制(见 §6.2 复位窗口),裁剪矩形直接用程序设定的 rect,不依赖 GetWindowRect 的边框口径。
2. **坐标一律用归一化值(0~1)**:模型内部会缩放图片,像素坐标含义不确定;要求模型输出相对整图的归一化框,程序再乘窗口 rect 换算成屏幕物理像素点击,与内部缩放完全解耦。

**备选供应商(同一封装,改 3 个配置项即可切换):**

| Provider | base_url | 示例 model | 备注 |
|---|---|---|---|
| deepseek(默认) | `https://api.deepseek.com` | `deepseek-v4-flash-vision-exp` | 见上 |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4v-flash` | 备选,有免费额度 |
| 通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-vl-plus` | 备选 |
| custom | 用户填 | 任意 | 支持自建网关 |

### 3.2 UI 形态:纯 Web 面板

Python 只做后端,界面是一个标准的本地 Web 面板:

1. 进程内启动本地 HTTP 服务(`127.0.0.1:8760`,**仅回环地址,不对外暴露**):页面 + `/api` RPC + `/events` SSE;
2. 启动时自动用默认浏览器打开该地址;`--no-open` 可只起服务不弹浏览器;端口被占用自动顺延;
3. 前端为纯静态 HTML/CSS/JS(无 CDN、无构建、离线可用),动效使用**本地化 GSAP 3.13**(`ui/assets/js/vendor/gsap.min.js`,集中在 `motion.js`,仅观察 DOM 不侵入业务逻辑);与浏览器环境完全同构;关闭浏览器标签不影响后端调度,结束程序用 Ctrl+C 或面板「设置 → 退出程序」。

不采用原生窗口的原因:实测 pywebview 的 `evaluate_js` 在窗口加载早期可能阻塞,file:// 下中文路径也存在隐患;纯 Web 形态链路单一、依赖更少,且可脱离 GUI 独立验证(RPC/SSE/静态资源均有自检覆盖,见 `selftest.py`)。

## 4. 目录结构

```
zcode-welfare-bot/
├── main.py                  # 入口:加载配置→启动调度器→拉起 UI 面板
├── core/
│   ├── config.py            # YAML 读写、热更新、默认值合并
│   ├── scheduler.py         # 场次表→CronTrigger;下一次场次计算;防重入
│   ├── runner.py            # 领取执行状态机(§5),向 UI 发事件
│   ├── zcode_ctrl.py        # 探测 exe、启动/置前/复位窗口、强杀进程
│   ├── capture.py           # 全屏截图(mss)、窗口区域裁剪、黑屏检测
│   ├── vision.py            # 视觉 API 封装、JSON 修复、重试
│   ├── clicker.py           # 坐标点击、可选平滑轨迹、fail-safe
│   └── validate.py          # 结果判定(弹窗 popup + 词表 + 结构化字段)
├── ui/                      # 前端(纯静态,离线可用,见 UI 设计文档)
│   ├── index.html
│   └── assets/{css,js}/
├── data/
│   ├── config.yaml          # 唯一配置文件(UI 与调度共用)
│   ├── logs/                # app-YYYY-MM-DD.log(按天轮转)
│   └── shots/               # 截图留档:2026-09-10/10-00-00/attempt-1-locate.png ...
└── requirements.txt
```

## 5. 核心领取流程(执行状态机)

```
                       ┌─────────────────────────────┐
       到点触发         │        ATTEMPT 循环          │
  IDLE ────────────► OPEN_APP ──► WAIT_READY ──► LOCATE
  (等下场)  ▲                                        │
           │                                        ▼
           │                                  CLAIM(点击)
           │                                        │
           │                              VERIFY 截图判定
           │                                    │
           │                      ┌─────────────┴──────────────┐
           │                 成功/已领                        未成功(含失败弹窗)
           │                     │                              │
           │             RECORD_SUCCESS                    attempt<5?
           │                     │                           /       \
           │                 通知+留档                       是        否
           │                     │                        CLOSE_APP   │
           │                     ▼                        sleep 5s    ▼
           │                  IDLE ──► 等下一场         ┌────────► RECORD_FAIL
           │                                           │  (重开再试)   │
           │                                           │          通知+留档
           └───────────────────────────────────────────┴──────────► IDLE
```

**时序(单次尝试):**

```
t0        场次时间(可配提前量 = 0,随时可领型)
t0        1. 防重入检查(单实例锁/已在跑则跳过)
t0        2. zcode_ctrl.open(): 启动 exe(未运行才启动)→ 等待窗口句柄出现(轮询 0.5s,超时 30s)
          3. 置前窗口(最小化则还原),可选按 config 移动到固定位置 [40,40,1240,860] 保证截图一致性
          3. 摆放窗口:按设置最大化(全屏,默认)或移到固定矩形
          4. 等待界面渲染完成后截图:_grab_ready()
             ├─ 锁屏由系统 API 判定(OpenInputDesktop 失败 ⇒ 锁屏)→ 需人工,跳过本场
             ├─ 画面纯色(单色占比 > 0.98)⇒ 视为"还没渲染好",继续等(默认上限 20s,1s 轮询)
             │   等待期间每轮重新置顶/复位,防止被其他窗口遮挡
             └─ 就绪 → 裁剪出窗口图(全屏时窗口矩形即屏幕范围)
          5. vision.locate(窗口图): DeepSeek 返回 {scene, claimable, button_box(归一化 0~1), ocr_texts, confidence}
             ├─ scene=login / 风控类异常 → 归为"需人工",立即停止本场(见 §7 分类)
             ├─ already_claimed=true → 视为本场"无需领",按成功收尾
             ├─ 无按钮或 claimable=false → 视为一次"未成功",走重试
             └─ button_found 且 confidence≥0.70 → 继续
          6. clicker.click(屏幕坐标 = 窗口rect左上角 + 归一化中心 × rect尺寸)  # pyautogui.FAILSAFE=True
          7. sleep verify_delay(默认 1.5s)
          8. 再截图 → vision.verify(): 判定 popup(success/failure)/ claimed / 无变化
             ├─ 成功弹窗(领取成功+开始体验)或 claimed → RECORD_SUCCESS: 留档、通知、保留窗口
             ├─ 失败弹窗(领取失败+知道了)或无变化 → 关闭客户端 → 等 5 秒重开重试
             └─ 否则 → 未成功:zcode_ctrl.kill()(关干净)→ sleep 5s(用户指定)→ attempt+1 重开
          9. 5 次全未成功 → RECORD_FAIL:最终截图留档、通知("请手动查看")、本场结束
          * 全程看门狗:从 t0 起 150s 未收敛 → 强杀 ZCode 与流程,标记失败(防窗口卡死吊住进程)
```

关键约定:
- 全流程统一**物理像素坐标系**(启动时 `SetProcessDpiAwareness(2)`,见 §6.3);视觉返回归一化坐标,程序换算为屏幕坐标点击,规避 DPI 缩放与模型内部缩放两类误差。
- **锁屏判定与"画面纯色"分开处理**(实测踩坑):客户端启动后约 5 秒的加载闪屏本身就是纯色,旧逻辑按"单色占比 > 0.95 ⇒ 疑似锁屏"会误判成"本场跳过"。现在:① 锁屏用系统 API 判定(`OpenInputDesktop` 失败即锁屏/安全桌面);② 纯色视为"界面还没渲染好",在最长 `app_ready_timeout_s`(默认 20s)内持续等待并每轮重新置顶,超时才按"未渲染 → 重开重试"处理。
- **启动流程**:打开客户端后先等待 `startup_wait_s`(默认 5 秒)加载,再把窗口**最大化(全屏)**后截图识别;`fullscreen: false` 时退回"移到固定矩形"的旧行为。
- **每次截图前都重新置顶 ZCode 窗口**:浏览器面板、通知弹窗、其他程序随时可能盖到 ZCode 上方,若直接截屏会截到遮挡窗口;因此定位截图与点击后的校验截图都会先置顶,再等 `focus_settle_s` 抓图。前台锁定夺不到焦点时退化为抬高 z 序(SetWindowPos),并记警告。
- **窗口与进程双重校验**:标题匹配只是初筛,还必须确认窗口所属进程可执行文件就是配置的 `ZCode.exe`,并且不是受保护进程(explorer/dwm/winlogon/svchost/python/chrome 等)。实测事故:标题为 `zcode-free` 的项目目录窗口曾因标题包含 "ZCode" 被误认成客户端。
- 发送给模型的是**裁剪后的 ZCode 窗口图**(非全屏),提高等效分辨率并降低 token(见 §3.1)。
- 每次尝试的定位图、点击后校验图**全部落盘**,目录按场次/attempt 组织(见 §4)。

## 6. 模块详细设计

### 6.1 调度器 scheduler.py
- 读取 `schedule.slots`(每天多个 `HH:MM`),为每个启用场次注册 `CronTrigger(hour, minute)`。
- 提供 `next_slot()`:计算下一场时间(供 UI 倒计时)。
- **防重入**:执行器运行中置 running 标志,触发时若 running 直接跳过本场(避免两场重叠)。
- 场次表改动(UI 保存)→ 热重建触发器,无需重启。
- 可选:场次时间前 `pre_seconds`(默认 0)预热——本需求为"随时可领"型,默认关闭,保留参数。
- 可选 `keep_awake: true`:执行窗口期(触发前 2 分钟 ~ 结束)内 `SetThreadExecutionState(ES_SYSTEM_REQUIRED|ES_CONTINUOUS)` 防系统休眠;注意锁屏无法被阻止,文档提醒用户运行期不锁屏/不睡眠。

### 6.2 ZCode 进程与窗口控制 zcode_ctrl.py
- **探测 exe**:配置 `app.zcode_path` 优先;为空则扫描「开始菜单快捷方式 + 常见安装目录 + 注册表 Uninstall 项」按名字含 "zcode" 匹配,找不到回写配置并要求 UI 提示。
- `open()`:无进程才创建;然后 `FindWindow` 按 `window_title_match` 关键字轮询等句柄;`ShowWindow(SW_RESTORE)` + `SetForegroundWindow`;可选 `MoveWindow` 到固定 rect(截图一致性;用户可在设置里关掉,避免干扰自己使用)。
- `kill()`:`TerminateProcess` 目标 PID(只杀自己启动的 ZCode 主进程,不碰用户手动开的其他窗口——启动时记录 PID,关闭只关该 PID 的进程树);关闭失败视为"未成功"计数一次。
- 启动/关闭都带超时,失败进重试循环。

### 6.3 截图与坐标体系 capture.py / clicker.py
1. 进程启动即调 `ctypes.windll.shcore.SetProcessDpiAwareness(2)`(失败则退回 `SetProcessDpiAwareness(1)`),让本进程与 mss/pyautogui 处于一致的物理像素坐标系,规避 100%/125%/150% 缩放错位——**这是 Windows 自动化最常见的坑,放在第一位解决**。
2. `mss.grab()` 截全屏 → 检测纯黑/纯色占比 > 95% 判定锁屏/黑屏(跳过本场并告警)→ **按窗口 rect 裁剪出 ZCode 窗口图**。默认 `restore_window_rect: true`,窗口由程序摆到固定 rect,裁剪矩形即该 rect(不依赖 GetWindowRect 的边框口径);若用户关闭复位,退回 `GetWindowRect` 取裁剪框。裁剪图同时落盘 + 内存 base64 给 DeepSeek。
3. 坐标换算:`屏幕点 = 窗口 rect 左上角 + 归一化坐标 × rect 尺寸`(视觉输出的 button_box 为 0~1 归一化值),`pyautogui.click` 点击;可选 `humanize: true` 时先线性移动再点(默认 false,直点)。

### 6.4 视觉识别 vision.py
- 统一方法 `chat_with_image(prompt, png_bytes) -> dict`:POST `https://api.deepseek.com/chat/completions`,body 为 OpenAI 兼容格式(`model` + `messages`,content 块含 `image_url` 的 base64 data URI),`temperature≈0.2` 压制幻觉,`timeout=20s`,网络错误指数退避重试 1 次。
- 结构化输出三重保障:① prompt 含 "json" 字样与完整结构示例(满足官方 JSON Output 要求);② 首选 `response_format={"type":"json_object"}`(官方未明确视觉模型支持该参数,接口报错则去掉重发);③ 返回文本"抽取首个 `{...}` + json.loads"解析。空 content / 解析失败 → 追加"只输出 json"重发 1 次;仍失败 → 返回 `{confidence:0}`,上层按 unknown 处理。
- 发送的是 §6.3 裁剪出的窗口图(约 1240×860),坐标一律归一化(见 §3.1 的两条设计决策)。
- 两层判定 prompt(默认模板写入代码常量,UI 只读展示;词表部分可配置):

**① 定位 prompt(点击前):**

```
你是桌面软件自动化助手。图片是 ZCode 客户端窗口的截图。
任务:在图中找到「福利领取」按钮并判断页面状态。
规则:
1. 忽略窗口标题栏与与福利页面无关的元素。
2. 领取按钮特征:可点击按钮,文字含 领取/领/收下/立即领取/签到领取 之一;
   若按钮置灰不可点,或文字为 已领取/明日再来/已签到/次数已用完,视为不可领。
3. button_box 输出相对整张图片的归一化坐标(0~1 小数,左上角为 0,0),不要输出像素值。
4. 只输出 json,不要输出任何其他文字。
输出:{"scene":"welfare|login|unknown","claimable":true|false|null,
 "already_claimed":true|false,"button_found":true|false,
 "button_label":"文字或null","button_box":[x1,y1,x2,y2],  // 归一化 0~1
 "ocr_texts":["关键文案,最多5条"],"confidence":0.0~1.0,
 "notes":"一句判断依据"}
```

**② 校验 prompt(点击后):**

```
这是点击「领取」按钮之后 ZCode 客户端窗口的截图。判断这次领取的结果。
结果以弹窗形式给出,只有两种:
- 成功弹窗:含「领取成功」文字,并带有一个「开始体验」按钮。
- 失败弹窗:含「领取失败」文字,并带有一个「知道了」按钮。
规则:
1. 看到「领取成功」或「开始体验」→ success=true,failed=false,popup="success";
2. 看到「领取失败」或「知道了」→ failed=true,success=false,popup="failure";
3. 没有弹窗时:文案含 已领取/今日已领/明天再来/今日份已领完 → claimed=true;
   页面与点击前无明显变化 → 三者都为 false,null。
只输出 JSON:{"success":bool,"failed":bool,"claimed":bool,"popup":"success"|"failure"|null,
 "keywords":["图上真实出现的关键词"],"confidence":0.0~1.0,"notes":"一句判断依据"}
```

> 该结果弹窗形态来自用户实测(领取成功→「领取成功」+「开始体验」;领取失败→「领取失败」+「知道了」),
> 已作为校验的**主证据**写进提示词与判定规则。

### 6.5 结果判定 validate.py
模型只提供"观察",决策完全由本地规则给出,顺序如下(先命中先返回):

**点击前 `judge_locate`:**
1. 模型调用失败(`error`)→ 重试;
2. `scene` 命中 login/captcha/verify/risk → 需人工,立即停本场;
3. `already_claimed=true` 或页面文字命中 `claimed_keywords` → 已领取,按成功收尾(不点击);
4. `button_found=true` 且 `claimable ≠ false` 且 `button_box` 有值 且 `confidence ≥ 阈值` → 点击;
5. 其余 → 未成功,进入重试循环。

**点击后 `judge_verify`:**
1. 模型调用失败 → 重试;
2. `success=true` 或 `popup=success` → **成功**(成功弹窗为主证据);
3. `failed=true` 或 `popup=failure` → **明确失败** → 关客户端重试;
4. `claimed=true` 或命中 `claimed_keywords` → 已领取,按成功收尾;
5. 命中 `success_keywords` → 成功;命中 `failure_keywords` → 失败;
6. 其余(无弹窗、无变化)→ 未成功,重试。

- 词表只匹配模型返回的**结构化字段**(`keywords` / `ocr_texts` / 按钮文字),不匹配 `notes`,避免模型解释性文字误命中。
- 三张词表(`success_keywords` / `claimed_keywords` / `failure_keywords`)写入 config,UI 可增删(见配置节)。

### 6.6 客户端生命周期
- **成功时不关闭客户端**(保留窗口,不打扰用户);失败/中止/需人工时在收尾阶段关闭。
- 每次重试前关闭客户端(只结束程序自己启动/记录的那个进程树),等 `retry_gap_s` 秒后重开。
- 看门狗默认 480 秒:需覆盖 5 次完整尝试(每次都含 2 次视觉调用,单次实测约 9 秒)。

### 6.7 通知与日志
- `loguru` 全事件落盘;核心事件(触发/各 attempt 结果/异常)同时**广播到 UI**(事件总线)。
- 桌面通知(winotify):成功 ✓ 与"5 次失败需人工查看"两种必发,其余可关。
- 可选 webhook(Server 酱 / 企业微信机器人),只存 URL 与开关。
- 截图按 `shots/场次/attempt-n-*.png` 落盘,保留最近 N 天(默认 7,可配),防磁盘膨胀。

## 7. 异常处理与护栏

| # | 异常场景 | 策略 |
|---|---|---|
| E1 | 找不到 ZCode.exe / 窗口 30s 未出现 | 算 1 次未成功,走重开循环;5 次后告警留档 |
| E2 | 截图纯色 / 疑似未渲染 | 纯色 ⇒ 在 `app_ready_timeout_s` 内等待渲染(每轮重新置顶),超时才判"未渲染"并重开重试 |
| E2b | 锁屏 / 安全桌面 | 由系统 API(`OpenInputDesktop`)判定 ⇒ 立即停止本场并通知,不计入重试 |
| E3 | 视觉 API 网络错/超时/限流 | 单次调用内自动重试 1 次;仍失败按 unknown,计入重试循环 |
| E4 | JSON 解析失败 | "只输出 JSON"重发 1 次;仍失败按 unknown |
| E5 | 识别出登录页/验证码/风控弹窗 | 属"需人工"类 → **立即停止本场**(不浪费 5 次重开),通知人工,等下一场 |
| E6 | 点击后无任何变化(未知态) | 按未成功走重开循环(符合用户原始流程语义) |
| E7 | 全程 150s 未收敛(窗口卡死) | 看门狗强杀 ZCode + 终止流程,标记失败,等下一场 |
| E8 | 重入(本场未完又来触发) | 调度器 running 标志跳过,记日志 |
| E9 | 自身 UI 面板遮挡 ZCode 窗口 | 试领/执行时 UI 提示"建议最小化面板";截图前检测面板窗口 rect 是否与 ZCode rect 重叠,重叠则自动最小化面板再截(可选开关) |
| E10 | 杀进程失败 | 重试 2 次,仍失败:告警并等待下一场(防止残留窗口干扰下一场) |
| E11 | 配置缺失(无场次/无 API key) | UI 红条引导;到点执行器直接跳过并提示 |

安全底线:单场最多 5 次点击(±少数重试),低骚扰频率;`pyautogui.FAILSAFE=True`(光标甩到屏幕左上角即急停);所有向客户端的操作只针对**本人账号、本机**。若 ZCode 服务条款明确禁止此类自动化,应停用本工具。

## 8. 配置项(config.yaml 全量示例)

```yaml
app:
  zcode_path: ""                # ZCode.exe 全路径;空=自动探测后回填
  window_title_match: "ZCode"   # 窗口标题关键字(仅初筛,还会做进程校验)
  fullscreen: true              # 执行前把客户端最大化(全屏),再截图识别
  startup_wait_s: 5.0           # 启动客户端后等待界面加载的秒数(加载期画面可能是纯色)
  restore_window_rect: true     # 未启用全屏时:执行前把窗口移到固定位置
  window_rect: [40, 40, 1240, 860]

schedule:
  enabled: true
  slots: []                     # 示例: - {time: "10:00", enabled: true}
  keep_awake: true              # 场次执行期防休眠

vision:
  provider: deepseek            # deepseek | zhipu | dashscope | custom
  base_url: "https://api.deepseek.com"
  api_key: ""                   # 由 UI 填写,存本机(platform.deepseek.com 申请)
  model: "deepseek-v4-flash-vision-exp"
  temperature: 0.2
  timeout_s: 20
  locate_confidence_min: 0.70   # 低于此值不点击,按 unknown 重试
  humanize_mouse: false

retry:
  max_attempts: 5               # 用户指定:最多 5 次
  retry_gap_s: 5                # 用户指定:关→等5s→重开
  open_timeout_s: 30
  settle_s: 2.0                 # 窗口就绪后静置
  focus_settle_s: 0.4           # 每次截图前:置顶窗口后的等待秒数
  verify_delay_s: 2.5           # 点击后等多久再截校验图(结果弹窗需服务端往返)
  app_ready_timeout_s: 20       # 界面渲染等待上限(加载期纯色不算锁屏)
  verify_ready_timeout_s: 8     # 结果弹窗渲染等待上限
  ready_poll_s: 1.0             # 渲染等待的轮询间隔
  uniform_ratio_max: 0.98       # 单色占比高于此值视为"还没渲染出来"
  watchdog_s: 480

success_keywords: ["领取成功", "开始体验", "奖励到账", "已到账", "领取奖励", "获得", "+"]
claimed_keywords: ["已领取", "今日已领", "今日已领取", "明天再来", "明日再来", "已参加", "次数已用完"]
failure_keywords: ["领取失败", "知道了"]

notify:
  desktop: true
  webhook_url: ""               # 可选 Server酱/企微机器人

data:
  keep_days: 7                  # 截图/日志保留天数
```

## 9. 开发里程碑与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| M0 | 本方案 + UI 方案评审 | 关键决策确认、真实场次时间填入 |
| M1 | 环境侦察脚本 `probe.py` | 自动找到 ZCode.exe;列出窗口标题/句柄;截一张当前福利页图,人工确认定位 prompt 的识别词有效 |
| M2 | 核心链路 CLI(无 UI) | 手动触发一次:打开→识别→点击→校验全通;模拟失败能走 5 次重开并正确收尾;所有异常分支(§7)单测/手测通过 |
| M3 | 调度 + 通知 | 假场次(设 1 分钟后)自动触发成功;5 连败触发通知;时间表热更新生效 |
| M4 | Web 面板(浏览器) | 对照 UI 设计文档验收清单逐项通过 |
| M5 | 灰度观察 3 天 | 真实场次连跑 3 天无漏领;按真实截图校准关键词与置信度阈值 |

**测试要点**:坐标体系在 100%/125%/150% 缩放下各验一次;窗口最小化/遮挡/多显示器各验一次;断网时视觉 API 失败的降级路径;杀进程残留;电脑锁屏跳过。

## 10. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| ZCode 客户端改版(按钮文案/布局变) | 误判/漏点 | 截图留档完整,关键词+置信度配置化,改版后 M1 式校准一次即可,框架不动 |
| 视觉模型偶发幻觉(误报按钮位置) | 误点 | 低 temperature、≥0.70 阈值才点击、JSON 强格式、"unknown 不瞎点"原则 |
| DeepSeek 余额耗尽/调价/实验模型下线(`vision-exp` 带 exp 后缀,存在迭代可能) | 停摆 | provider 可切(智谱/通义/自定义),切换零代码;关注官方更新日志,正式版发布后改 model 名即可 |
| Windows 缩放/多屏导致坐标错位 | 点错 | DPI Awareness + 全屏物理像素统一坐标系(M2 专项测试) |
| 锁屏/休眠/断网错过场次 | 漏领 | keep_awake + 黑屏检测 + 失败通知;人工兜底 |
| 杀软拦截自动化(PyInstaller 打包后常见) | 不可用 | V1 用 venv 直接跑,不打包;需分发时再评估白名单/签名 |

## 11. 合规与边界(简)
- 仅自动化**本人账号、本机**;单场 ≤5 次低频点击;不绕验证码、不批量、不抓取。
- 若 ZCode 官方条款禁止自动化或官方后续提供"一键领取"入口,优先改用官方入口。
- 所有判定留痕(截图+日志),便于人工审计与随时接管。

## 12. 待确认清单(不阻塞开发,但需尽早回填)
1. 真实场次时间表(UI 自配,需首轮配置)。
2. 福利页真实截图 1~2 张(成功态/已领态)——用于 M1 校准识别词与按钮特征。
3. ZCode.exe 安装路径或安装目录(不填则 M1 自动探测)。
4. DeepSeek API Key(platform.deepseek.com 创建,需账户有小额余额;余额计费见 §3.1)。
5. 是否需要 webhook 通知(Server酱/企业微信),可后配。
