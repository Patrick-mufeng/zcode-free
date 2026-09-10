# 方向 A — 极光仪控 Aurora Instrument

**一句话**：把自动化任务做成一台有仪式感的仪器——深空底色上浮着极光，玻璃面板像仪表一样悬浮，唯一的"活物"是那枚绕着下一场转动的轨道环。

**设计意图**：用户是深夜盯着它自动干活的人。画面要安静、有纵深、有微光，长时间看不累；所有运动都缓慢、连续、有物理感，像仪器在呼吸。

## 调色板

| token | 值 | 用途 |
|---|---|---|
| `--bg` | `#070B16` | 底 |
| `--glow-1/2/3` | `#4C4BE0` / `#22D3EE` / `#A855F7` | 三团模糊光斑（blur 120px, opacity .10~.16） |
| `--surface` | `rgba(255,255,255,.045)` | 玻璃面板 |
| `--surface-2` | `rgba(255,255,255,.075)` | 悬浮/次容器 |
| `--line` / `--line-2` | `rgba(255,255,255,.09)` / `.16` | 分隔线 / 强调边 |
| `--text-1/2/3` | `#EDF1FB` / `#A7B3CC` / `#75819B` | 主/次/弱 |
| `--brand` | `linear-gradient(135deg,#6D6BFF,#A855F7 55%,#33D6E8)` | 只用于操作与选中 |
| `--ok / --warn / --err / --info` | `#3ED598` / `#FFB84D` / `#FF6B7A` / `#5AA9FF` | 语义 |

面板：`background: var(--surface); backdrop-filter: blur(14px);` + 顶部 1px 内高光 `inset 0 1px 0 rgba(255,255,255,.07)`。**禁止外发光**，光只从光斑和渐变来。

## 字体与尺度

- 显示/数字：`Bahnschrift, "Segoe UI Variable Display", "Segoe UI"` — 数字大而窄，是仪表感的关键
- 正文：`"Segoe UI", "Microsoft YaHei UI", system-ui` 13px / 1.6
- 等宽：`Consolas, "Cascadia Mono", monospace`（日志、坐标、ID）
- 统计数值 30px/600，卡片标签 11.5px 字距 .08em，`tabular-nums` 全站

## 圆角规则（全站唯一）

`卡片 18px / 控件 10px / chip 与状态点全圆角`。不许出现第 4 种。

## 布局

左上角品牌（渐变菱形 + 双行字），左侧栏 232px，主区 `max-width 1320px`。概览页用 4 列统计卡 + 2 列主内容（左 7 右 5：左=手动测试+上手检查，右=本次执行，水平时并排）。

**签名元素 · 轨道环**：顶栏「下一场」左侧一枚 92px 环——外圈 2px 极细轨道，一段 120° 的渐变彗尾弧随剩余时间转动（转一圈 = 一个场次周期,不是 60 秒），圆心是距开场的 `02:13:09`。执行中时彗尾加速并变实，成功时爆发一次青色外扩。

## 动效基调（GSAP，`../assets/js/vendor/gsap.min.js`）

- 缓动统一 `power3.out`；入场 `expo.out`；微交互 0.18~0.24s
- 开场：光斑 1.2s 淡入并开始 48s 无限漂移（y/x ±30px, `sine.inOut`）；品牌标记 `stroke-dashoffset` 描出；导航项 stagger .06 浮入；顶栏 0.05；卡片 stagger .07 从 y=14, opacity 0 起
- 切页：内容 stagger .05（y 10 → 0），退场 0.12s 快于入场
- 执行中：「本次执行」面板 `y:12 → 0` 展开；当前步骤胶囊呼吸（`scale 1↔1.03`, `sine.inOut`, yoyo）；连接线上一道渐变光按 `xPercent` 扫过；截图 `autoAlpha` 交叉淡入 + `scale 1.02 → 1`
- 状态灯：空闲=静止暗点；执行中=外环 `scale 1→2.4, opacity .6→0` 循环；成功=闪两下；失败=持续脉冲
- 数字：统计值变化用 `gsap.to(obj, {v: target, onUpdate})` 滚动，0.6s
- 按钮：hover `y:-1`，active `scale:.98`；主按钮有顶部 1px 高光

## 禁止

大面积渐变文字、紫蓝外发光、六边形科技纹、粒子、任何形式的 loading 转圈（用扫光骨架）。
