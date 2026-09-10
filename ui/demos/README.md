# 前端重做 · 5 个设计方向 Demo

打开 **[index.html](index.html)** 看选型页（含每个方向的截图、色板、参数与对比表）。

## 五个方向

| # | 文件 | 一句话 |
|---|---|---|
| A | [01-aurora.html](01-aurora.html) | 深空极光 + 玻璃面板 + 轨道环倒计时，像一台有仪式感的仪器 |
| B | [02-blueprint.html](02-blueprint.html) | 深蓝图纸 + 坐标网格 + 尺寸标注，像一张正在被绘制的工程图 |
| C | [03-manual.html](03-manual.html) | 冷白纸面 + 零圆角 + 双线章节 + 印章，像一本排版讲究的说明书 |
| D | [04-hardedge.html](04-hardedge.html) | 纯白机身 + 2px 黑框 + 硬投影 + 机械摇杆，像一台工业设备 |
| E | [05-quiet.html](05-quiet.html) | 石墨灰 + 1px 细线 + 唯一琥珀色 + 24 小时轨道，最安静、密度最高 |

每个都是**自包含的单文件原型**，双击即可打开（离线，只用项目里已 vendor 的 GSAP）。

## 每个 Demo 都能点什么

- **六个页签**都能切，六个页面都有真实内容，不是占位图
- **「试领一次」**跑一段约 14 秒的模拟执行：顶栏状态切「执行中」→ 五步时间线依次点亮 → 出现一次失败并自动进入「第 2 次尝试」→ 成功 → 4 秒后回到「空闲」，结束时在「最近记录」插入一条新记录
- **顶栏倒计时真实跳动**（秒级），跨天时「今天 / 明天」会跟着改
- **执行中**：实时截图占位交叉淡入（带红色定位框与坐标标注）、实时日志逐条追加
- **右下角「演示控制」徽标**：悬停展开，可切换 空闲 / 执行中 / 成功 / 需人工，以及「重播开场」「跑一次执行」
- 词表 chip 可以按回车真加、点 × 真删；总开关、页签、按钮都有反馈

## 设计约束（五版共同遵守）

| 项 | 做法 |
|---|---|
| 语义色 | 绿=成功、红=失败、黄=等待、蓝/琥珀=进行中；品牌色只用于操作与选中，不参与状态表达 |
| 圆角 | 每个方向定一套（如 A 是 18/10/全圆角，C 与 D 是 0px），全站不出现第四种 |
| 字号 | 正文 ≥ 11.5px；正文与次级文字对比度全部 ≥ 4.5:1（脚本逐元素实测） |
| 动效 | 只用 transform / opacity / clip-path / stroke-dashoffset；不动 width/height/top/left |
| 降级 | 系统「减少动态效果」或地址栏加 `?motion=0` → 全部静态化，且不留透明残骸 |
| 视口 | 1440 设计基准，1100 侧栏收窄，760 单列；三档均无横向滚动条 |
| 图标 | 全部内联 SVG（1.75 描边、currentColor），没有 emoji 当图标 |

## 目录

```
demos/
├── index.html            选型页(先看这个)
├── 01-aurora.html        A 极光仪控
├── 02-blueprint.html     B 制图台
├── 03-manual.html        C 纸面手册
├── 04-hardedge.html      D 硬边运维
├── 05-quiet.html         E 静默方格
├── _shared/
│   ├── model.js          五版共用的内容模型(场次/步骤/日志/设置项/流程/词表)
│   └── kit.js            五版共用的行为与动效底座(页签/倒计时/执行剧本/控制条)
└── _design/
    ├── BRIEF.md          共享简报:产品定位、硬约束、内容模型、验收标准
    ├── spec-A~E.md       五个方向的完整视觉规范
    ├── cdp.mjs           无依赖 headless Chrome 驱动:截图 / 跑交互 / 抓控制台报错
    ├── audit.mjs         无依赖视觉审计:截断 / 重叠 / 对比度 / 过小字号 / 空白页
    └── out/final/        15 张终版截图(每方向 空闲 / 执行中 / 成功)
```

## 实测结果

五个方向逐一在 headless Chrome 中跑过：

- 控制台 **零 error / 零 warning**
- 执行剧本走完：状态 `idle → running → success`，5 步全绿，新记录插入成功
- 视觉审计：**无文字截断、无元素重叠、无对比度不达标项、无过小字号、无空白页**
- 1100 / 760 两档窄视口 **无横向溢出**
- `?motion=0` 下页面完全可见（`opacity: 1`），不会卡在透明态

## 选定之后怎么落地

1. 保留选中的那个 HTML，把它的 CSS 抽成 `ui/assets/css/app.css`，结构合回 `ui/index.html`
2. 删掉演示用的 `_shared/kit.js` 里的 `simulate()` 剧本与 `demoBar()`，改接 `ui/assets/js/api.js`（`get_state` / `run_once` / `get_schedule` …）与 `events.js`（SSE 的 `state_change` / `step_update` / `log_line`）
3. 演示里已经在用的类名就是正式版的接口，接真实数据不用重新设计：
   - `.step[data-state="idle|run|done|fail"]`
   - `.logline[data-level="info|muted|action|ok|warn|err"]`
   - `.chip[data-kind="success|claimed|failure"]`
   - `.shot[data-kind="locate|verify"]`
   - `.res[data-ok="0|1"]`、`.flow-node[data-state]`
4. 截图占位（`.shot-canvas`）替换成 `get_shot` 返回的 data URI 图片即可
