/* ============================================================================
   ZKit — 5 个 demo 共用的行为与动效底座(不含视觉,视觉全部在各 demo 的 CSS 里)
   ----------------------------------------------------------------------------
   提供的契约(各 demo 的 CSS 直接按这些类名/属性写样式):
     .demobar[data-demo] > button[data-act]      右下角 DEMO 控制条
     .logline[data-level=info|muted|action|ok|warn|err]
     .toast[data-kind=ok|warn|err|info]
     .shot[data-kind=locate|verify]  .shot-grid .shot-box .shot-cap .shot-meta
     .chip[data-kind] .chip-x
     .zk-attempt  (尝试徽标容器)

   行为:
     - 6 页签切换(点击 [data-page]),只切 .is-active,不改变布局
     - 「下一场」真实秒级倒计时
     - 总开关、试领一次 / 演练一次
     - 试领 → 约 14s 的剧本化执行(含一次失败重试 → 第 2 次成功)
     - ?motion=0 与 prefers-reduced-motion 时全部静态化(状态照常变化)
   ========================================================================== */
window.ZKit = (function () {
  "use strict";

  var M = window.ZModel;
  var G = window.gsap || null;
  var REDUCED = (function () {
    try {
      if (/[?&]motion=0/.test(location.search)) return true;
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) { return false; }
  })();

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  // <tr> 不能经 <div> 解析(会被解析器丢弃),必须借 <tbody>
  function elRow(html) {
    var tb = document.createElement("tbody");
    tb.innerHTML = html;
    return tb.firstElementChild;
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function nowText() {
    var d = new Date();
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }
  function hhmmss(sec) {
    sec = Math.max(0, Math.floor(sec));
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return pad(h) + ":" + pad(m) + ":" + pad(s);
  }
  // 下一场:今天的 16:00,已过则顺延到明天
  function nextTarget() {
    var d = new Date(), t = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 16, 0, 0, 0);
    if (t.getTime() <= d.getTime()) t.setDate(t.getDate() + 1);
    return t;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* ------------------------------ 默认结构模板 ------------------------------ */

  var tpl = {
    logLine: function (l) {
      return '<div class="logline" data-level="' + (l.level || "info") + '">' +
        '<span class="logline-t">' + esc(l.t) + "</span>" +
        '<span class="logline-src">' + esc(l.src) + "</span>" +
        '<span class="logline-msg">' + esc(l.msg) + "</span>" +
        "</div>";
    },
    recentRow: function (r) {
      return "<tr>" +
        '<td class="mono">' + esc(r.when) + "</td>" +
        "<td>" + esc(r.slot) + "</td>" +
        '<td><span class="res" data-ok="' + (r.ok ? 1 : 0) + '">' + (r.ok ? "成功" : "失败") + "</span></td>" +
        "<td>" + esc(r.note) + "</td>" +
        '<td class="ta-r mono">' + r.attempts + "</td>" +
        '<td class="ta-r"><button class="linkbtn">查看</button></td>' +
        "</tr>";
    },
    slotRow: function (s) {
      return "<tr>" +
        '<td><label class="mini-switch"><input type="checkbox"' + (s.enabled ? " checked" : "") +
        ' /><span class="mini-switch-box" aria-hidden="true"></span></label></td>' +
        '<td class="mono time">' + esc(s.time) + "</td>" +
        '<td class="mono dim">' + (s.attempts == null ? "继承默认(5)" : s.attempts) + "</td>" +
        '<td class="mono dim">' + (s.gap == null ? "继承默认(5s)" : s.gap + "s") + "</td>" +
        "<td>" + (s.lastOk == null ? '<span class="dim">' + esc(s.last) + "</span>"
          : '<span class="res" data-ok="' + (s.lastOk ? 1 : 0) + '">' + esc(s.last) + "</span>") + "</td>" +
        '<td class="ta-r"><button class="linkbtn">编辑</button><button class="linkbtn danger">删除</button></td>' +
        "</tr>";
    },
    weekDay: function (d) {
      var items = d.items.map(function (it) {
        var cls = it.off ? "off" : (it.ok ? "done" : (it.next ? "next" : ""));
        return '<span class="wk-dot ' + cls + '"><i>' + esc(it.time) + "</i></span>";
      }).join("");
      return '<div class="wk-day">' +
        '<div class="wk-head"><b>' + esc(d.date) + '</b><span class="dim">' + esc(d.weekday) + "</span></div>" +
        '<div class="wk-dots">' + items + "</div></div>";
    },
    timelineRow: function (r) {
      var mark = r.res.indexOf("mark") === 0;
      if (mark) {
        return '<div class="tl-mark" data-ok="' + (r.res === "mark-ok" ? 1 : 0) + '">' +
          '<span class="tl-line"></span><b>' + esc(r.msg) + '</b><span class="tl-line"></span></div>';
      }
      var shot = r.shot ? tpl.shot({ kind: r.shot, small: true }) : "";
      return '<div class="tl-row" data-res="' + esc(r.res) + '">' +
        '<span class="tl-t mono">' + esc(r.t) + "</span>" +
        '<span class="tl-dot" aria-hidden="true"></span>' +
        '<span class="tl-msg">' + esc(r.msg) + (r.note ? ' <i class="tl-note mono">' + esc(r.note) + "</i>" : "") + "</span>" +
        (shot ? '<span class="tl-shot">' + shot + "</span>" : "") +
        "</div>";
    },
    sessionItem: function (s) {
      return '<button class="sess' + (s.active ? " is-active" : "") + '">' +
        '<span class="sess-when">' + esc(s.when) + "</span>" +
        '<span class="sess-res" data-ok="' + (s.ok ? 1 : 0) + '">' + (s.ok ? "成功" : "失败") + "</span>" +
        '<span class="sess-note">' + esc(s.note) + "</span></button>";
    },
    chip: function (text, kind) {
      return '<span class="chip" data-kind="' + kind + '"><span>' + esc(text) + "</span>" +
        '<button class="chip-x" type="button" aria-label="删除 ' + esc(text) + '">&times;</button></span>';
    },
    shot: function (o) {
      o = o || {};
      var kind = o.kind || "locate";
      var cap = kind === "locate" ? "命中[领取] 置信 0.92" : "命中[领取成功] 置信 0.96";
      return '<figure class="shot' + (o.small ? " is-small" : "") + '" data-kind="' + kind + '">' +
        '<span class="shot-canvas"><span class="shot-grid"></span>' +
        '<span class="shot-win"><span class="shot-winbar"></span>' +
        '<span class="shot-box"></span></span></span>' +
        '<span class="shot-cap mono">' + cap + "</span>" +
        (o.small ? "" : '<figcaption class="shot-meta mono">截图占位 · 1240×860 · 真实接入后替换为 /api get_shot 返回的截图</figcaption>') +
        "</figure>";
    }
  };

  /* --------------------------------- 主逻辑 --------------------------------- */

  var state = {
    page: "dashboard",
    status: "idle",
    attempt: 1,
    master: true,
    running: false,
    timers: [],
    logCount: 0,
    hooks: {},
    rendered: false
  };

  function call(name) {
    var fn = state.hooks[name];
    if (typeof fn === "function") return fn.apply(null, Array.prototype.slice.call(arguments, 1));
  }

  function anim(fn, fallback) { if (!REDUCED && G) fn(G); else if (fallback) fallback(); }

  // 「运行状态」卡片的副文案:必须和主状态一致,不能一边"执行中"一边"无任务在跑"
  var STATE_SUB = {
    idle: "总开关:已开启 · 无任务在跑",
    waiting: "总开关:已开启 · 快到点了",
    running: "正在执行第 2 次尝试 · 最多 5 次",
    success: "最近一次:成功 · 已留档",
    manual: "需要人工处理,请到运行日志查看现场"
  };

  function setStatus(key, info) {
    state.status = key;
    document.documentElement.setAttribute("data-status", key);
    var t = M.statusText[key];
    var name = $("#statusText"), sub = $("#statusSub");
    if (name) name.textContent = t.name;
    if (sub) sub.textContent = t.sub;
    var cardSub = $("#cardStateSub");
    if (cardSub) cardSub.textContent = STATE_SUB[key] || t.sub;
    call("status", key, info || {});
  }

  function setStep(i, st, info) {
    $$("[data-step]").forEach(function (n) {
      if (+n.getAttribute("data-step") !== i) return;
      n.setAttribute("data-state", st);
      n.classList.toggle("is-run", st === "run");
      n.classList.toggle("is-done", st === "done");
      n.classList.toggle("is-fail", st === "fail");
    });
    call("step", i, st, info || {});
  }

  function resetSteps() {
    $$("[data-step]").forEach(function (n) {
      n.setAttribute("data-state", "idle");
      n.classList.remove("is-run", "is-done", "is-fail");
    });
  }

  function setPage(key, silent) {
    if (state.page === key && state.rendered) return;
    var prev = state.page;
    var initial = !state.rendered;   // 首屏不跑切页动画(开场序列负责)
    state.page = key;
    $$("[data-page]").forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-page") === key);
    });
    $$("[data-page-panel]").forEach(function (p) {
      var on = p.getAttribute("data-page-panel") === key;
      p.classList.toggle("is-active", on);
      p.hidden = !on;
    });
    var idx = $$("[data-page]").map(function (b) { return b.getAttribute("data-page"); }).indexOf(key);
    document.documentElement.setAttribute("data-page-idx", String(idx + 1));
    call("pageChange", key, prev, initial);
    state.rendered = true;
  }

  function countTo(node, to, opts) {
    if (!node) return;
    opts = opts || {};
    var from = opts.from == null ? 0 : opts.from;
    var dec = opts.decimals || 0, pre = opts.prefix || "", suf = opts.suffix || "";
    var fmt = function (v) { return pre + v.toFixed(dec) + suf; };
    if (REDUCED || !G || opts.dur === 0) { node.textContent = fmt(to); return; }
    var o = { v: from };
    G.to(o, {
      v: to, duration: opts.dur || 0.6, ease: "power2.out",
      onUpdate: function () { node.textContent = fmt(o.v); },
      onComplete: function () { node.textContent = fmt(to); }
    });
  }

  function toast(msg, kind) {
    var box = $("#toasts");
    if (!box) return;
    var n = el("div", "toast", '<span class="toast-body">' + esc(msg) + "</span>");
    n.setAttribute("data-kind", kind || "info");
    box.appendChild(n);
    call("toastIn", n);
    setTimeout(function () { call("toastOut", n); }, 3200);
  }

  function appendLog(line) {
    var box = $("#liveLog");
    if (!box) return;
    var n = el("div");
    n.innerHTML = tpl.logLine(line);
    var node = n.firstChild;
    box.appendChild(node);
    state.logCount++;
    while (box.children.length > 200) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
    call("log", node, line);
  }

  function attemptBadge(text) {
    var box = $("#liveAttempt");
    if (!box) return;
    box.textContent = text;
    box.classList.toggle("hidden", !text);
    call("attempt", state.attempt, text);
  }

  function showShot(kind) {
    var wrap = $("#liveShot");
    if (!wrap) return;
    var old = wrap.querySelectorAll(".shot");
    var holder = el("div");
    holder.innerHTML = tpl.shot({ kind: kind });
    var node = holder.firstChild;
    wrap.appendChild(node);
    if (old.length) {
      // 旧图交给 demo 的 shot 钩子淡出;钩子不处理时默认立即移除
      var handled = call("shot", node, old[old.length - 1], kind) === "keep";
      if (!handled) {
        Array.prototype.forEach.call(old, function (o) { o.remove(); });
      }
    } else {
      call("shot", node, null, kind);
    }
  }

  /* -------------------------------- 执行剧本 -------------------------------- */

  var SCRIPT = [
    [0.0, function () {
      state.running = true; state.attempt = 1;
      var p = $("#livePanel"); if (p) p.classList.remove("hidden");
      resetSteps(); setStep(0, "run"); attemptBadge("第 1 次尝试");
      setStatus("running", { attempt: 1 });
      call("execStart");
      var b = $("#execBanner"); if (b) b.classList.remove("hidden");
      if (G && !REDUCED) G.to("#countdown", { opacity: 0.35, duration: 0.2, yoyo: true, repeat: 1 });
    }],
    [0.8, function () { setStep(0, "done"); setStep(1, "run"); }],
    [1.8, function () { setStep(1, "done"); setStep(2, "run"); }],
    [2.6, function () { showShot("locate"); }],
    [3.0, function () { setStep(2, "done"); setStep(3, "run"); }],
    [3.8, function () { showShot("verify"); }],
    [4.2, function () { setStep(3, "done"); setStep(4, "run"); }],
    [5.3, function () {
      setStep(4, "fail");
      call("attemptFail", 1);
    }],
    [5.8, function () {
      state.attempt = 2;
      resetSteps(); setStep(0, "run"); attemptBadge("第 2 次尝试");
      call("retryBanner", 2);
    }],
    [6.3, function () { setStep(0, "done"); setStep(1, "run"); }],
    [7.0, function () { setStep(1, "done"); setStep(2, "run"); }],
    [7.6, function () { showShot("locate"); }],
    [7.9, function () { setStep(2, "done"); setStep(3, "run"); }],
    [8.6, function () { showShot("verify"); }],
    [9.0, function () { setStep(3, "done"); setStep(4, "run"); }],
    [9.8, function () {
      setStep(4, "done");
      var b = $("#execBanner"); if (b) b.classList.add("hidden");
      setStatus("success", { attempt: 2 });
      call("success", 2);
      var rec = { when: "今天 14:02", slot: "手动", ok: true, note: "第 2 次重试后领取成功", attempts: 2 };
      var tb = $("#recentTable tbody");
      if (tb) {
        var row = elRow(tpl.recentRow(rec));
        tb.insertBefore(row, tb.firstChild);
        call("record", row, rec);
      }
      toast("领取成功,截图已留档", "ok");
    }],
    [14.2, function () {
      state.running = false;
      setStatus("idle", {});
      var p = $("#livePanel"); if (p) p.classList.add("hidden");
      attemptBadge("");
      resetSteps();
      call("execEnd");
    }]
  ];

  function stopSim() {
    state.timers.forEach(function (t) { clearTimeout(t); });
    state.timers = [];
  }

  function simulate() {
    if (state.running) { toast("已有任务在执行,请稍候", "warn"); return; }
    stopSim();
    var box = $("#liveLog");
    M.simLogs.forEach(function (l) {
      var line = { t: nowText(), src: l.src, msg: l.msg, level: l.level };
      state.timers.push(setTimeout(function () { appendLog(line); }, l.at * 1000));
    });
    SCRIPT.forEach(function (pair) {
      state.timers.push(setTimeout(function () {
        try { pair[1](); } catch (e) { console.warn("sim step error", e); }
      }, pair[0] * 1000));
    });
  }

  /* --------------------------------- 填充渲染 -------------------------------- */

  function fill() {
    // 概览 · 最近记录
    var tb = $("#recentTable tbody");
    if (tb && !tb.children.length) {
      tb.innerHTML = M.recent.map(function (r) { return tpl.recentRow(r); }).join("");
    }
    // 场次表
    var st = $("#slotTable tbody");
    if (st) st.innerHTML = M.slots.map(function (s) { return tpl.slotRow(s); }).join("");
    // 周预览
    var wk = $("#weekPreview");
    if (wk) wk.innerHTML = M.week.map(function (d) { return tpl.weekDay(d); }).join("");
    // 流程节点
    var fn = $("#flowMain");
    if (fn && !fn.children.length) {
      fn.innerHTML = M.nodes.map(function (n) {
        return '<div class="flow-node" data-node="' + n.id + '" data-state="idle">' +
          '<i class="mono">' + n.no + "</i><b>" + esc(n.name) + "</b><span>" + esc(n.desc) + "</span></div>";
      }).join("");
    }
    // 分支
    var fb = $("#flowBranches");
    if (fb && !fb.children.length) {
      fb.innerHTML = M.branches.map(function (b) {
        return '<div class="branch" data-kind="' + b.kind + '"><b>' + esc(b.name) + "</b>" +
          '<span class="branch-cond">' + esc(b.cond) + "</span>" +
          '<span class="branch-act">' + esc(b.act) + "</span></div>";
      }).join("");
    }
    // 阶段卡
    var fst = $("#flowStages");
    if (fst && !fst.children.length) {
      fst.innerHTML = M.stages.map(function (s) {
        return '<article class="stage"><header><i class="mono">' + s.no + "</i><b>" + esc(s.name) + "</b>" +
          '<span class="stage-tag">' + esc(s.tag) + "</span></header><ul>" +
          s.lines.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul></article>";
      }).join("");
    }
    // 规则表
    var rt = $("#rulesTable tbody");
    if (rt) {
      rt.innerHTML = M.rules.map(function (r) {
        return '<tr><td class="mono">' + esc(r.stage) + "</td><td>" + esc(r.cond) + "</td>" +
          '<td data-kind="' + r.kind + '">' + esc(r.act) + "</td></tr>";
      }).join("");
    }
    // 坐标换算
    var cb = $("#coordBox");
    if (cb) {
      cb.innerHTML =
        '<div class="coord-cell"><b>窗口矩形</b><i>由程序摆放或实测</i><code class="mono">' + esc(M.coord.rect) + "</code></div>" +
        '<div class="coord-op mono">+</div>' +
        '<div class="coord-cell"><b>归一化中心点</b><i>模型返回的 button_box 中心</i><code class="mono">' + esc(M.coord.norm) + "</code></div>" +
        '<div class="coord-op mono">=</div>' +
        '<div class="coord-cell is-result"><b>屏幕坐标</b><i>交给 pyautogui 点击</i>' +
        M.coord.screen.map(function (l) { return '<code class="mono">' + esc(l) + "</code>"; }).join("") + "</div>";
    }
    // 词表
    ["success", "claimed", "failure"].forEach(function (kind) {
      var box = $("#" + kind + "Chips");
      if (!box) return;
      box.innerHTML = M.chips[kind].map(function (t) { return tpl.chip(t, kind); }).join("");
    });
    // 测试识别 JSON
    var lj = $("#locateJson");
    if (lj) lj.textContent = JSON.stringify(M.locateJson, null, 2);
    // 日志初始行
    var ll = $("#liveLog");
    if (ll && !ll.children.length) {
      M.logs.forEach(function (l) { appendLog(l); });
      state.logCount = M.logs.length;
    }
    // 日志页时间轴 + 场次列表
    var tlc = $("#timeline");
    if (tlc) tlc.innerHTML = M.timeline.map(function (r) { return tpl.timelineRow(r); }).join("");
    var sl = $("#sessionList");
    if (sl) sl.innerHTML = M.sessions.map(function (s) { return tpl.sessionItem(s); }).join("");
    // 设置页
    fillSettings();
    // 识别页大图占位
    var lw = $("#locateImageWrap");
    if (lw && !lw.children.length) lw.innerHTML = tpl.shot({ kind: "locate" });
  }

  function fieldNode(f) {
    if (f.type === "check") {
      return '<div class="field is-check"><label class="check"><input type="checkbox"' + (f.value ? " checked" : "") +
        ' /><span class="check-box" aria-hidden="true"></span><span class="check-text">' + esc(f.label) + "</span></label>" +
        (f.hint ? '<p class="field-hint">' + esc(f.hint) + "</p>" : "") + "</div>";
    }
    if (f.type === "rect") {
      return '<div class="field"><label class="field-label">' + esc(f.label) + "</label>" +
        '<div class="field-row">' + f.value.map(function (v) {
          return '<input class="mono" type="text" value="' + esc(v) + '" aria-label="窗口位置" />';
        }).join("") + "</div></div>";
    }
    if (f.type === "path") {
      return '<div class="field"><label class="field-label">' + esc(f.label) + "</label>" +
        '<div class="field-row"><input class="mono" type="text" value="' + esc(f.value) + '" />' +
        '<button class="btn small" type="button">自动探测</button></div></div>';
    }
    return '<div class="field"><label class="field-label">' + esc(f.label) + "</label>" +
      '<div class="field-row"><input type="text" value="' + esc(f.value) + '" placeholder="' + esc(f.placeholder || "") + '" />' +
      (f.unit ? '<span class="unit mono">' + esc(f.unit) + "</span>" : "") + "</div>" +
      (f.hint ? '<p class="field-hint">' + esc(f.hint) + "</p>" : "") + "</div>";
  }

  function fillSettings() {
    Object.keys(M.settings).forEach(function (sec) {
      var box = $("#set-" + sec);
      if (!box) return;
      box.innerHTML = M.settings[sec].map(fieldNode).join("");
    });
  }

  /* ---------------------------------- 控制条 --------------------------------- */

  function demoBar() {
    var bar = el("div", "demobar is-collapsed");
    bar.setAttribute("data-demo", "1");
    bar.setAttribute("title", "演示控制:切换状态、重播开场、跑一次执行");
    // 默认收成一枚小徽标,悬停或键盘聚焦才展开,避免浮层压住表格最后一行
    var expand = function (on) { bar.classList.toggle("is-collapsed", !on); };
    bar.addEventListener("mouseenter", function () { expand(true); });
    bar.addEventListener("mouseleave", function () { if (!bar.contains(document.activeElement)) expand(false); });
    bar.addEventListener("focusin", function () { expand(true); });
    bar.addEventListener("focusout", function () { expand(false); });
    bar.innerHTML =
      '<span class="demobar-toggle mono" aria-hidden="true">演示</span>' +
      '<span class="demobar-tag mono">演示控制</span>' +
      '<button data-act="idle" type="button">空闲</button>' +
      '<button data-act="running" type="button">执行中</button>' +
      '<button data-act="success" type="button">成功</button>' +
      '<button data-act="manual" type="button">需人工</button>' +
      '<span class="demobar-sep" aria-hidden="true"></span>' +
      '<button data-act="replay" type="button">重播开场</button>' +
      '<button data-act="run" type="button">跑一次执行</button>';
    document.body.appendChild(bar);
    bar.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-act]");
      if (!b) return;
      var act = b.getAttribute("data-act");
      if (act === "replay") { call("intro", true); return; }
      if (act === "run") { simulate(); return; }
      stopSim();
      state.running = false;
      var p = $("#livePanel");
      if (act === "running") {
        if (p) p.classList.remove("hidden");
        resetSteps(); setStep(2, "run"); attemptBadge("第 2 次尝试");
        $("#liveShot") && ($("#liveShot").innerHTML = "");
        showShot("locate");
      } else {
        if (p && act !== "success") p.classList.add("hidden");
        if (act === "success" && p) p.classList.remove("hidden");
        attemptBadge("");
        resetSteps();
      }
      setStatus(act, {});
      call("barAct", act);
    });
    call("bar", bar);
  }

  /* ---------------------------------- 启动 ---------------------------------- */

  function boot(hooks) {
    state.hooks = hooks || {};
    if (hooks && hooks.tpl) Object.keys(hooks.tpl).forEach(function (k) { tpl[k] = hooks.tpl[k]; });

    document.documentElement.setAttribute("data-motion", REDUCED ? "off" : "on");
    if (G) G.defaults({ ease: "power3.out", duration: 0.5 });

    // 页签
    $$("[data-page]").forEach(function (b) {
      b.addEventListener("click", function () { setPage(b.getAttribute("data-page")); });
    });
    // 顶栏开关
    var m = $("#master");
    if (m) {
      m.checked = true;
      m.addEventListener("change", function () {
        state.master = m.checked;
        document.documentElement.setAttribute("data-master", m.checked ? "on" : "off");
        call("master", m.checked);
        toast(m.checked ? "总开关已开启,到点自动执行" : "总开关已关闭,场次不再触发", m.checked ? "ok" : "warn");
        if (!m.checked && state.status === "idle") { /* 状态文案保持不变 */ }
      });
    }
    // 试领 / 演练
    ["#runOnce", "#runOncePage"].forEach(function (s) {
      var b = $(s); if (b) b.addEventListener("click", simulate);
    });
    var dry = $("#runDryPage");
    if (dry) dry.addEventListener("click", function () {
      toast("演练已开始(不点击、不关客户端)", "info");
      simulate();
    });
    // 词表增删
    ["success", "claimed", "failure"].forEach(function (kind) {
      var input = $("#" + kind + "Input");
      if (input) input.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") return;
        var v = input.value.trim(); if (!v) return;
        input.value = "";
        var box = $("#" + kind + "Chips");
        var holder = el("div"); holder.innerHTML = tpl.chip(v, kind);
        var node = holder.firstChild; box.appendChild(node);
        call("chipAdd", node, kind);
        toast("已加入词表:" + v, "ok");
      });
    });
    document.addEventListener("click", function (e) {
      var x = e.target.closest(".chip-x");
      if (!x) return;
      var chip = x.closest(".chip");
      call("chipRemove", chip);
    });
    // 手风琴 / 其它杂物
    $$("[data-goto]").forEach(function (b) {
      b.addEventListener("click", function () { setPage(b.getAttribute("data-goto")); });
    });

    fill();
    demoBar();
    setPage("dashboard");
    setStatus("idle", {});

    // 倒计时
    var target = nextTarget();
    function tick() {
      var left = Math.max(0, (target.getTime() - Date.now()) / 1000);
      var txt = hhmmss(left);
      var node = $("#countdown");
      if (node) node.textContent = txt;
      var sub = $("#cardNextSub");
      if (sub) sub.textContent = "距现在 " + txt;
      // 目标跨到明天时,卡片上的「今天」必须跟着改,否则和倒计时自相矛盾
      var dayNode = $("#cardNextDay");
      if (dayNode) {
        var now = new Date();
        var sameDay = target.getFullYear() === now.getFullYear()
          && target.getMonth() === now.getMonth() && target.getDate() === now.getDate();
        dayNode.textContent = sameDay ? "今天" : "明天";
      }
      if (state.status === "idle" && left < 600) setStatus("waiting", {});
      call("countdown", txt, left);
    }
    tick();
    setInterval(tick, 1000);

    // 空闲环境日志
    var ai = 0;
    setInterval(function () {
      if (state.running || state.page !== "logs") return;
      var a = M.ambientLogs[ai++ % M.ambientLogs.length];
      appendLog({ t: nowText(), src: a.src, msg: a.msg, level: "muted" });
    }, 9000);

    call("intro", false);
    call("ready");
  }

  return {
    boot: boot, tpl: tpl, el: el, $: $, $$: $$, esc: esc,
    reduced: REDUCED, gsap: G, countTo: countTo, toast: toast,
    setStatus: setStatus, setStep: setStep, setPage: setPage,
    simulate: simulate, appendLog: appendLog, hhmmss: hhmmss, nowText: nowText
  };
})();
