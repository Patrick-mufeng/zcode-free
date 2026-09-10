/* 应用入口:标签页、顶栏状态、24 小时轨道、事件总线、Toast / 灯箱 / 确认框 */
(function () {
  const $ = (id) => document.getElementById(id);
  const STEPS = ['打开客户端', '识别按钮', '点击领取', '校验结果', '收尾'];

  let state = null;
  let stepStatus = {};
  let lastAttempt = 0;
  let alertState = null;
  let trackMarks = [];

  // 本地执行态:exec_start 立刻切「执行中」,session_end 立刻切结果,
  // 不必等后端下一次 get_state 回来(那一趟可能慢半秒,状态会显得滞后)。
  let execRunning = false;
  let freshResult = null;        // { type: 'success' , timer }
  let freshTimer = null;

  function setFreshResult(type) {
    freshResult = type;
    renderTopbar();
    clearTimeout(freshTimer);
    freshTimer = setTimeout(() => { freshResult = null; renderTopbar(); }, 4000);
  }

  /* ---------- 通用组件 ---------- */

  function toast(text, kind) {
    if (!text) return;
    const box = $('toasts');
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = text;
    el.title = text;            // 折行截断后仍可悬停查看全文
    box.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .3s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 320);
    }, 3200);
  }

  function lightbox(src) {
    $('lightboxImg').src = src;
    $('lightbox').classList.remove('hidden');
  }

  function closeLightbox() {
    $('lightbox').classList.add('hidden');
    $('lightboxImg').removeAttribute('src');
  }

  function confirmDialog(text) {
    return new Promise((resolve) => {
      $('confirmText').textContent = text;
      $('confirmMask').classList.remove('hidden');
      const ok = () => done(true);
      const cancel = () => done(false);
      function done(value) {
        $('confirmMask').classList.add('hidden');
        $('confirmOk').removeEventListener('click', ok);
        $('confirmCancel').removeEventListener('click', cancel);
        resolve(value);
      }
      $('confirmOk').addEventListener('click', ok);
      $('confirmCancel').addEventListener('click', cancel);
    });
  }

  function showBanner(text, isError) {
    $('bannerText').textContent = text || '';
    $('banner').classList.remove('hidden');
    $('banner').classList.toggle('err', !!isError);
  }

  /* ---------- 标签页 ---------- */

  function switchTab(name) {
    document.querySelectorAll('#tabs .tab').forEach((tab) =>
      tab.classList.toggle('active', tab.dataset.page === name));
    document.querySelectorAll('.page').forEach((page) =>
      page.classList.toggle('hidden', page.id !== 'page-' + name));
    const page = window.PAGES[name];
    if (page && page.onShow) page.onShow();
  }

  /* ---------- 顶栏 ---------- */

  function renderTopbar() {
    if (!state) return;
    const dot = $('statusDot');
    const text = $('statusText');
    let cls = 'idle';
    let label = '空闲';
    if (execRunning || state.running) {
      cls = 'running';
      label = '执行中';
    } else if (alertState) {
      cls = alertState.type === 'manual' ? 'manual' : 'failed';
      label = alertState.type === 'manual' ? '需人工' : '失败';
    } else if (freshResult === 'success') {
      cls = 'success';
      label = '成功';
    } else if (state.next_slot && (state.next_slot.ts - Date.now() / 1000) < 600) {
      cls = 'waiting';
      label = '等待中';
    }
    dot.className = 'dot ' + cls;
    text.textContent = label;
    $('nextSlot').textContent = state.next_slot ? state.next_slot.label : '--';
    const busy = !!(state.running || execRunning);
    $('master').checked = !!state.master;
    $('master').disabled = busy;
    ['runOnce', 'runOncePage', 'runDryPage'].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = busy;
    });
  }

  function tickCountdown() {
    const el = $('countdown');
    if (!state || !state.next_slot) {
      el.textContent = '';
      return;
    }
    const diff = Math.max(0, Math.floor(state.next_slot.ts - Date.now() / 1000));
    const h = String(Math.floor(diff / 3600)).padStart(2, '0');
    const m = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
    const s = String(diff % 60).padStart(2, '0');
    el.textContent = '还有 ' + h + ':' + m + ':' + s;
  }

  /* ---------- 24 小时轨道(签名元素) ---------- */

  const MIN = 24 * 60;

  function buildTrack() {
    const axis = $('dtAxis');
    if (!axis) return;
    // 清掉旧的刻度与标记,只留基准线
    axis.querySelectorAll('.dt-tick, .dt-tick-lbl, .dt-mark, .dt-cursor').forEach((n) => n.remove());

    // 刻度:每 2 小时一根,每 6 小时一根主刻度并标时间
    for (let h = 0; h <= 24; h += 2) {
      const major = h % 6 === 0;
      const left = (h / 24) * 100;
      const tick = document.createElement('span');
      tick.className = 'dt-tick' + (major ? ' major' : '');
      tick.style.left = left + '%';
      axis.appendChild(tick);
      if (major) {
        const lbl = document.createElement('span');
        lbl.className = 'dt-tick-lbl' + (h === 0 ? ' edge-start' : (h === 24 ? ' edge-end' : ''));
        lbl.style.left = left + '%';
        lbl.textContent = String(h).padStart(2, '0') + ':00';
        axis.appendChild(lbl);
      }
    }

    // 场次标记:位置由时间换算,结果由最近记录回填
    const slots = (state && state.slots) || [];
    trackMarks = [];
    slots.forEach((slot) => {
      const time = String(slot.time || '');
      const parts = time.split(':');
      if (parts.length !== 2) return;
      const minutes = Number(parts[0]) * 60 + Number(parts[1]);
      if (!Number.isFinite(minutes)) return;

      const mark = document.createElement('span');
      mark.className = 'dt-mark' + (slot.enabled === false ? ' off' : '');
      mark.style.left = (minutes / MIN) * 100 + '%';
      mark.dataset.time = time;
      mark.title = time + (slot.enabled === false ? ' · 未启用' : '') +
        (slot.attempts != null ? ' · 覆盖尝试 ' + slot.attempts + ' 次' : '');
      mark.innerHTML = '<span class="pin"></span><span class="dot"></span>' +
        '<span class="lbl mono"></span><span class="out mono"></span>';
      mark.querySelector('.lbl').textContent = time;
      axis.appendChild(mark);
      trackMarks.push(mark);
    });

    // 「现在」游标
    const cursor = document.createElement('span');
    cursor.className = 'dt-cursor';
    cursor.id = 'dtCursor';
    cursor.innerHTML = '<span class="cap mono" id="dtCursorCap">--:--</span>';
    axis.appendChild(cursor);
  }

  function applyTrackResults(items) {
    if (!trackMarks.length) return;
    const byTime = {};
    (items || []).forEach((item) => {
      const slot = item.slot;
      if (slot && !byTime[slot]) byTime[slot] = item;
    });
    trackMarks.forEach((mark) => {
      const rec = byTime[mark.dataset.time];
      const out = mark.querySelector('.out');
      if (!rec) { out.textContent = ''; out.className = 'out mono'; return; }
      const info = window.UITL.statusInfo(rec.status);
      out.textContent = info.text;
      out.className = 'out mono ' + (info.cls === 'ok' ? 'ok' : (info.cls === 'fail' ? 'fail' : ''));
    });
  }

  function tickTrack() {
    const cursor = $('dtCursor');
    const cap = $('dtCursorCap');
    const now = $('dtNow');
    const d = new Date();
    const minutes = d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
    const hhmm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    const pct = (minutes / MIN) * 100;
    if (cursor) cursor.style.left = pct + '%';
    if (cap) {
      cap.textContent = hhmm;
      // 贴边时把胶囊的锚点向内换,避免时间戳被面板裁掉
      cap.style.left = pct < 4 ? '0%' : (pct > 96 ? '100%' : '50%');
      cap.style.transform = pct < 4 ? 'translateX(0)' : (pct > 96 ? 'translateX(-100%)' : 'translateX(-50%)');
    }
    if (now) now.textContent = hhmm + ' · 本地时间';
  }

  /* ---------- 执行步骤条 ---------- */

  function buildSteps() {
    const box = $('steps');
    box.innerHTML = '';
    STEPS.forEach((name, index) => {
      const el = document.createElement('span');
      el.className = 'step';
      el.dataset.step = name;
      el.innerHTML = '<span class="circle">•</span><span class="label">' + name + '</span>';
      box.appendChild(el);
      if (index < STEPS.length - 1) {
        const arrow = document.createElement('span');
        arrow.className = 'step-arrow';
        arrow.textContent = '→';
        box.appendChild(arrow);
      }
    });
  }

  function renderSteps() {
    document.querySelectorAll('#steps .step').forEach((el) => {
      const status = stepStatus[el.dataset.step] || '';
      el.classList.remove('ok', 'fail', 'running');
      if (status) el.classList.add(status);
      el.querySelector('.circle').textContent = status === 'ok' ? '✓' : (status === 'fail' ? '✕' : '•');
    });
  }

  /* ---------- 状态刷新 ---------- */

  async function refreshState() {
    try {
      state = await window.API.call('get_state');
    } catch (err) {
      return;
    }
    renderTopbar();
    renderSteps();
    // 场次数量或启用状态变化时重建轨道;否则只回填结果
    const signature = ((state.slots || []).map((s) => s.time + (s.enabled === false ? '0' : '1')).join(',')) +
      '|' + ((state.recent || []).map((r) => r.id || r.slot).join(','));
    if (signature !== buildTrack.signature) {
      buildTrack.signature = signature;
      buildTrack();
    }
    applyTrackResults(state.recent);
    if (window.PAGES.dashboard && window.PAGES.dashboard.refresh) {
      window.PAGES.dashboard.refresh(state);
    }
  }

  /* ---------- 事件 ---------- */

  function wireEvents() {
    EV.on('state_change', refreshState);

    EV.on('exec_start', (event) => {
      alertState = null;
      freshResult = null;
      clearTimeout(freshTimer);
      execRunning = true;
      stepStatus = {};
      lastAttempt = 0;
      $('livePanel').classList.remove('hidden');
      $('liveSession').textContent = (event && event.session_id) || '';
      $('liveMsg').textContent = '已开始,正在打开客户端…';
      renderSteps();
      showBanner('执行中:请勿让浏览器窗口遮挡 ZCode(可最小化本窗口,自动化会把 ZCode 切到前台)', false);
      if (event && event.trigger === 'manual') switchTab('logs');
      refreshState();
    });

    EV.on('step_update', (event) => {
      if (!event || !event.step) return;
      stepStatus[event.step] = event.status;
      renderSteps();
      if (event.detail) $('liveMsg').textContent = event.step + ':' + event.detail;
      if (event.attempt) $('liveAttempt').textContent = '第 ' + event.attempt + ' 次尝试';
    });

    EV.on('attempt_update', async (event) => {
      if (!event) return;
      $('livePanel').classList.remove('hidden');
      $('liveMsg').textContent = '第 ' + event.attempt + ' 次尝试:' + (event.message || '');
      $('liveAttempt').textContent = '第 ' + event.attempt + ' 次尝试';
      if (event.attempt !== lastAttempt) {
        lastAttempt = event.attempt;
        stepStatus = {};
        renderSteps();
      }
      const images = event.images || [];
      if (images.length) {
        const last = images[images.length - 1];
        try {
          const res = await window.API.call('get_shot',
            { session: last.session, name: last.name, thumb: true, max_width: 640 });
          if (res && res.ok) {
            $('liveShot').src = res.image;
            $('liveShot').style.display = 'block';
          }
        } catch (err) { /* 忽略 */ }
      }
    });

    EV.on('log_line', (event) => {
      if (window.PAGES.logs && window.PAGES.logs.appendLog) window.PAGES.logs.appendLog(event);
    });

    EV.on('session_end', (event) => {
      if (!event) return;
      execRunning = false;
      $('banner').classList.add('hidden');   // 先收起执行提示,失败时再弹告警
      const detail = event.summary || '';
      if (event.status === 'success') {
        alertState = null;
        setFreshResult('success');
        toast('领取成功' + (detail ? ':' + detail : ''), 'ok');
      } else if (event.status === 'need_manual') {
        alertState = { type: 'manual', text: detail };
        showBanner('需要人工处理:' + detail, true);
        toast('需要人工处理,详情见运行日志', 'err');
      } else if (event.status === 'failed') {
        alertState = { type: 'err', text: detail };
        showBanner((event.slot ? '[' + event.slot + '] ' : '') + '领取失败:' + detail, true);
        toast('领取失败,详情见运行日志', 'err');
      } else if (event.status === 'aborted') {
        alertState = { type: 'err', text: detail };
        toast('已中止,详情见运行日志', 'err');
      } else {
        toast('演练完成,详情见运行日志');
      }
      refreshState();
    });

    EV.on('need_manual', (event) => {
      if (event) showBanner(event.reason || '需要人工处理', true);
    });
  }

  /* ---------- 启动 ---------- */

  async function boot() {
    await window.API.ready();
    buildSteps();
    buildTrack();

    document.querySelectorAll('#tabs .tab').forEach((tab) =>
      tab.addEventListener('click', () => switchTab(tab.dataset.page)));

    $('master').addEventListener('change', async () => {
      try {
        const res = await window.API.call('set_master', { enabled: $('master').checked });
        toast(res && res.master ? '总开关已开启' : '总开关已关闭', 'ok');
      } catch (err) {
        toast('操作失败:' + err.message, 'err');
      }
      refreshState();
    });

    $('runOnce').addEventListener('click', async () => {
      try {
        const res = await window.API.call('run_once');
        toast((res && res.message) || '', res && res.ok ? 'ok' : 'err');
        if (res && res.ok) { execRunning = true; renderTopbar(); switchTab('logs'); }
      } catch (err) {
        toast('启动失败:' + err.message, 'err');
      }
      refreshState();
    });

    $('bannerClose').addEventListener('click', () => $('banner').classList.add('hidden'));
    $('lightbox').addEventListener('click', closeLightbox);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeLightbox();
        $('confirmMask').classList.add('hidden');
      }
    });

    wireEvents();
    Object.keys(window.PAGES).forEach((key) => {
      const page = window.PAGES[key];
      if (page.init) page.init();
    });

    await refreshState();
    switchTab('dashboard');
    // 概览页就有「运行日志」面板,启动时先补一段历史,否则刚打开只有一行
    if (window.PAGES.logs && window.PAGES.logs.loadHistory) {
      window.PAGES.logs.loadHistory().catch(() => {});
    }
    // 轨道已建好,现在播开场序列(顺序确定,GSAP 不会找不到节点)
    if (window.MOTION && window.MOTION.entrance) window.MOTION.entrance();
    API.call('ui_ready').catch(() => {});   // 告知后端「面板已加载」
    tickCountdown();
    tickTrack();
    setInterval(tickCountdown, 1000);
    setInterval(tickTrack, 1000);
    setInterval(refreshState, 15000);
  }

  window.APP = {
    toast,
    lightbox,
    confirm: confirmDialog,
    switchTab,
    refreshState,
    showBanner,
  };

  boot();
})();
