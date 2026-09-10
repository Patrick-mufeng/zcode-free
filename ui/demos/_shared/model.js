/* ============================================================================
   ZModel — 5 个 demo 共用的内容模型(纯数据,不含任何 DOM 结构)
   保证 5 个设计方向展示的是同一套内容,只比设计,不比内容。
   所有中文文案统一使用全角标点。
   ========================================================================== */
window.ZModel = (function () {
  "use strict";

  // 场次表
  var slots = [
    { time: "10:00", enabled: true, attempts: null, gap: null, last: "今天 成功", lastOk: true },
    { time: "16:00", enabled: true, attempts: null, gap: null, last: "今天 成功", lastOk: true },
    { time: "22:00", enabled: false, attempts: 3, gap: 8, last: "暂无记录", lastOk: null }
  ];

  // 概览 · 最近记录
  var recent = [
    { when: "今天 10:00", slot: "第 1 场", ok: true, note: "第 2 次重试后领取成功", attempts: 2 },
    { when: "昨天 16:00", slot: "第 2 场", ok: false, note: "5 次重试均未成功", attempts: 5 },
    { when: "昨天 10:00", slot: "第 1 场", ok: true, note: "首次点击即成功", attempts: 1 }
  ];

  // 未来 7 天预览
  var week = [
    { date: "今天 09-10", weekday: "周四", items: [{ time: "10:00", ok: true }, { time: "16:00", next: true }, { time: "22:00", off: true }] },
    { date: "09-11", weekday: "周五", items: [{ time: "10:00" }, { time: "16:00" }, { time: "22:00", off: true }] },
    { date: "09-12", weekday: "周六", items: [{ time: "10:00" }, { time: "16:00" }, { time: "22:00", off: true }] },
    { date: "09-13", weekday: "周日", items: [{ time: "10:00" }, { time: "16:00" }, { time: "22:00", off: true }] },
    { date: "09-14", weekday: "周一", items: [{ time: "10:00" }, { time: "16:00" }, { time: "22:00", off: true }] },
    { date: "09-15", weekday: "周二", items: [{ time: "10:00" }, { time: "16:00" }, { time: "22:00", off: true }] },
    { date: "09-16", weekday: "周三", items: [{ time: "10:00" }, { time: "16:00" }, { time: "22:00", off: true }] }
  ];

  // 执行步骤(概览「本次执行」)
  var steps = [
    { key: "open", name: "打开客户端", hint: "复用运行中的窗口" },
    { key: "ready", name: "窗口就绪", hint: "1240×860 已置顶" },
    { key: "locate", name: "截图定位", hint: "视觉模型 ①" },
    { key: "click", name: "点击领取", hint: "归一化坐标换算" },
    { key: "verify", name: "校验结果", hint: "视觉模型 ②" }
  ];

  // 流程页 · 主流程节点
  var nodes = [
    { id: "trigger", no: "01", name: "触发", desc: "场次到点 / 手动测试" },
    { id: "open", no: "02", name: "打开客户端", desc: "复用或启动,置顶" },
    { id: "shot", no: "03", name: "截图", desc: "等渲染后按窗口裁图" },
    { id: "locate", no: "04", name: "视觉定位", desc: "模型调用 ① 找按钮" },
    { id: "click", no: "05", name: "点击领取", desc: "归一化 → 屏幕坐标" },
    { id: "verify", no: "06", name: "校验", desc: "模型调用 ② 看弹窗" },
    { id: "done", no: "07", name: "收尾", desc: "留档 + 通知" }
  ];

  var branches = [
    { kind: "ok", name: "成功弹窗", cond: "领取成功 + 开始体验", act: "截图留档 → 通知 → 保留窗口,等下一场" },
    { kind: "retry", name: "失败弹窗", cond: "领取失败 + 知道了 / 未成功", act: "关闭客户端 → 等 5 秒 → 重开重试(最多 5 次)" },
    { kind: "manual", name: "需人工", cond: "登录页 / 验证码 / 锁屏", act: "立即停止本场 → 通知,不消耗重试次数" }
  ];

  // 流程页 · 四个阶段
  var stages = [
    {
      no: "01", name: "截图", tag: "本地 · 无网络",
      lines: [
        "先置顶 ZCode(必要时复位窗口位置),再抓屏",
        "mss 抓全屏 → 按窗口矩形裁剪出「窗口图」",
        "锁屏由系统 API 判定;纯色画面视为「未渲染」,继续等待"
      ]
    },
    {
      no: "02", name: "定位 · 模型调用 ①", tag: "DeepSeek 视觉",
      lines: [
        "输入:窗口图 + 定位 Prompt(要求只输出 JSON)",
        "输出:scene / claimable / already_claimed / button_found / button_box(归一化 0~1) / ocr_texts / confidence",
        "结构化保障:Prompt 含 JSON 示例 + response_format + 本地 JSON 修复"
      ]
    },
    {
      no: "03", name: "点击", tag: "本地",
      lines: [
        "取 button_box 中心 → 归一化坐标",
        "屏幕坐标 = 窗口矩形原点 + 归一化 × 矩形尺寸",
        "pyautogui 点击;鼠标甩到左上角可急停,点完等 2.5 秒"
      ]
    },
    {
      no: "04", name: "校验 · 模型调用 ②", tag: "DeepSeek 视觉",
      lines: [
        "结果以弹窗呈现:成功 =「领取成功 + 开始体验」,失败 =「领取失败 + 知道了」",
        "再次置顶 + 截图,送入校验 Prompt",
        "输出:success / failed / popup / keywords / confidence"
      ]
    }
  ];

  // 流程页 · 判定规则(8 行)
  var rules = [
    { stage: "定位", cond: "场景 = 登录页 / 验证码等异常界面", act: "需人工,立即停止本场", kind: "manual" },
    { stage: "定位", cond: "已领标记为真,或命中已领词(如:明日再来)", act: "按已领取收尾,不再点击", kind: "ok" },
    { stage: "定位", cond: "找到按钮 且 可领 且 置信度 ≥ 阈值(默认 0.70)", act: "执行点击,进入校验", kind: "" },
    { stage: "定位", cond: "以上都不满足(没找到 / 置信度不足)", act: "未成功 → 关客户端重试", kind: "fail" },
    { stage: "校验", cond: "成功弹窗:含「领取成功」或「开始体验」", act: "成功,留档 + 通知", kind: "ok" },
    { stage: "校验", cond: "失败弹窗:含「领取失败」或「知道了」", act: "未成功 → 关客户端重试", kind: "fail" },
    { stage: "校验", cond: "claimed 为真,或命中已领词", act: "按已领取收尾", kind: "ok" },
    { stage: "校验", cond: "没有弹窗,与点击前无明显变化", act: "未成功 → 关客户端重试", kind: "fail" }
  ];

  // 识别页 · 词表
  var chips = {
    success: ["领取成功", "开始体验", "奖励到账", "已到账"],
    claimed: ["已领取", "今日已领", "明天再来"],
    failure: ["领取失败", "知道了"]
  };

  // 日志页 · 一次场次的尝试时间轴
  var timeline = [
    { t: "10:00:00.1", msg: "打开客户端", res: "ok", note: "0.8s", shot: null },
    { t: "10:00:01.2", msg: "窗口就绪", res: "ok", note: "1240×860", shot: null },
    { t: "10:00:02.0", msg: "第 1 次尝试", res: "mark", note: "", shot: null },
    { t: "10:00:02.3", msg: "截图 → 视觉定位", res: "ok", note: "命中[领取] 置信 0.92", shot: "locate" },
    { t: "10:00:03.9", msg: "校验:未成功(无成功文案)", res: "fail", note: "", shot: "verify" },
    { t: "10:00:04.0", msg: "关闭客户端,5s 后重试", res: "warn", note: "", shot: null },
    { t: "10:00:09.5", msg: "第 2 次尝试 · 领取成功", res: "mark-ok", note: "", shot: null },
    { t: "10:00:10.2", msg: "截图 → 视觉定位", res: "ok", note: "命中[领取] 置信 0.94", shot: "locate" },
    { t: "10:00:12.6", msg: "校验:命中[领取成功]", res: "ok", note: "置信 0.96", shot: "verify" },
    { t: "10:00:12.8", msg: "留档 + 通知,本场结束", res: "ok", note: "session=20260910-1000", shot: null }
  ];

  // 日志页 · 历史场次
  var sessions = [
    { when: "今天 10:00", ok: true, note: "第 2 次成功", active: true },
    { when: "昨天 16:00", ok: false, note: "5 次全失败", active: false },
    { when: "昨天 10:00", ok: true, note: "首次即成功", active: false }
  ];

  // 实时日志(初始几行,执行时会继续追加)
  var logs = [
    { t: "14:02:11", src: "调度器", msg: "16:00 场已就绪,等待触发", level: "info" },
    { t: "14:02:11", src: "面板", msg: "前端已就绪(mode=web)", level: "muted" },
    { t: "10:00:02", src: "视觉", msg: "定位命中 confidence=0.92 box=(0.44,0.58,0.56,0.66)", level: "action" },
    { t: "10:00:03", src: "判定", msg: "未命中成功词,准备重试(1/5)", level: "warn" },
    { t: "10:00:09", src: "视觉", msg: "校验:命中[领取成功] confidence=0.96", level: "ok" },
    { t: "10:00:09", src: "执行", msg: "领取成功,截图留档 session=20260910-1000", level: "ok" }
  ];

  // 执行剧本结束后追加的日志(带语义级别)
  var simLogs = [
    { t: "now", src: "执行", msg: "手动触发:试领一次(完整流程)", level: "action", at: 0 },
    { t: "now", src: "窗口", msg: "复用运行中的 ZCode 窗口 hwnd=0x2A1C", level: "info", at: 0.7 },
    { t: "now", src: "截图", msg: "窗口就绪 1240×860,界面渲染完成", level: "muted", at: 1.8 },
    { t: "now", src: "视觉", msg: "定位命中 confidence=0.92 box=(0.44,0.58,0.56,0.66)", level: "action", at: 2.6 },
    { t: "now", src: "点击", msg: "点击 (586, 545),等待 2.5s 后校验", level: "action", at: 3.9 },
    { t: "now", src: "判定", msg: "未命中成功词,准备重试(1/5)", level: "warn", at: 5.2 },
    { t: "now", src: "窗口", msg: "关闭客户端,等待 5 秒后重开", level: "warn", at: 6.0 },
    { t: "now", src: "执行", msg: "第 2 次尝试开始", level: "action", at: 7.6 },
    { t: "now", src: "视觉", msg: "定位命中 confidence=0.94 box=(0.44,0.58,0.56,0.66)", level: "action", at: 9.4 },
    { t: "now", src: "视觉", msg: "校验:命中[领取成功] confidence=0.96", level: "ok", at: 12.0 },
    { t: "now", src: "执行", msg: "领取成功,截图留档 session=20260910-1402", level: "ok", at: 12.4 }
  ];

  // 空闲时的环境日志(低频追加,体现"活着")
  var ambientLogs = [
    { src: "调度器", msg: "下一场 16:00,倒计时正常" },
    { src: "心跳", msg: "服务在线,SSE 连接保持" },
    { src: "存储", msg: "截图留档占用 12.4 MB,保留 7 天" },
    { src: "调度器", msg: "场次表校验通过,3 个场次中 2 个启用" },
    { src: "心跳", msg: "服务在线,SSE 连接保持" }
  ];

  // 设置页
  var settings = {
    app: [
      { label: "ZCode 程序路径", type: "path", value: "C:\\Program Files\\ZCode\\ZCode.exe" },
      { label: "窗口标题匹配", type: "text", value: "ZCode" },
      { label: "执行前全屏显示", type: "check", value: true, hint: "把客户端最大化后再截图,识别更稳" },
      { label: "启动后等待加载", type: "num", value: "5.0", unit: "s" },
      { label: "窗口位置 x / y / 宽 / 高", type: "rect", value: ["40", "40", "1240", "860"] }
    ],
    retry: [
      { label: "最多尝试次数", type: "num", value: "5", unit: "次" },
      { label: "失败后重试间隔", type: "num", value: "5", unit: "s" },
      { label: "等待客户端启动", type: "num", value: "60", unit: "s" },
      { label: "窗口就绪后静置", type: "num", value: "1.0", unit: "s" },
      { label: "截图前置顶等待", type: "num", value: "0.6", unit: "s" },
      { label: "界面渲染等待上限", type: "num", value: "20", unit: "s" },
      { label: "结果弹窗渲染上限", type: "num", value: "8", unit: "s" },
      { label: "单场看门狗超时", type: "num", value: "240", unit: "s" },
      { label: "动手前需空闲", type: "num", value: "2.0", unit: "s", hint: "连续这么久没有键鼠输入才动手;0 = 关闭该保护" }
    ],
    notify: [
      { label: "Windows 桌面通知", type: "check", value: true, hint: "成功静默展示,失败必发" },
      { label: "Webhook(可选)", type: "text", value: "", placeholder: "Server 酱 / 企业微信机器人 URL" }
    ],
    data: [
      { label: "截图 / 日志保留", type: "num", value: "7", unit: "天" }
    ]
  };

  // 识别页 · 测试识别返回
  var locateJson = {
    scene: "welfare_page",
    claimable: true,
    already_claimed: false,
    button_found: true,
    button_box: [0.44, 0.58, 0.56, 0.66],
    confidence: 0.92
  };

  var coord = {
    rect: "x=40, y=40, w=1240, h=860",
    norm: "cx=0.50, cy=0.65",
    screen: ["x = 40 + 0.50 × 1240 = 660", "y = 40 + 0.65 × 860 = 599"]
  };

  // 状态语义键 → 顶栏双行文案
  var statusText = {
    idle: { name: "空闲", sub: "自动领取待命" },
    waiting: { name: "等待中", sub: "距下一场不到 10 分钟" },
    running: { name: "执行中", sub: "第 2 次尝试 · 校验结果" },
    success: { name: "成功", sub: "领取成功 · 10:00:03" },
    manual: { name: "失败 · 需人工", sub: "识别到登录页,需要手动处理" }
  };

  return {
    nextSlot: "16:00",
    slots: slots,
    recent: recent,
    week: week,
    steps: steps,
    nodes: nodes,
    branches: branches,
    stages: stages,
    rules: rules,
    chips: chips,
    timeline: timeline,
    sessions: sessions,
    logs: logs,
    simLogs: simLogs,
    ambientLogs: ambientLogs,
    settings: settings,
    locateJson: locateJson,
    coord: coord,
    statusText: statusText
  };
})();
