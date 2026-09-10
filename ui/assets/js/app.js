/* 应用入口:标签页、顶栏状态、事件总线、Toast / 灯箱 / 确认框 */
(function () {
  const $ = (id) => document.getElementById(id);
  const STEPS = ['打开客户端', '识别按钮', '点击领取', '校验结果', '收尾'];

  let state = null;
  let stepStatus = {};
  let lastAttempt = 0;
  let alertState = null;

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

  /* ---------- 顶栏与步骤条 ---------- */

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
    if (state && state.current) {
      $('liveAttempt').textContent = `第 ${state.current.attempt || 0} / ${state.current.max_attempts || 0} 次尝试`;
    }
  }

  function renderTopbar() {
    if (!state) return;
    const dot = $('statusDot');
    const text = $('statusText');
    let cls = 'idle';
    let label = '空闲';
    if (state.running) {
      cls = 'running';
      label = '执行中' + (state.current && state.current.step ? ' · ' + state.current.step : '');
    } else if (alertState) {
      cls = alertState.type === 'manual' ? 'manual' : 'failed';
      label = alertState.type === 'manual' ? '需人工' : '失败';
    } else if (state.next_slot && (state.next_slot.ts - Date.now() / 1000) < 600) {
      cls = 'waiting';
      label = '等待中';
    }
    dot.className = 'dot ' + cls;
    text.textContent = label;
    $('nextSlot').textContent = state.next_slot ? state.next_slot.label : '--';
    const busy = !!state.running;
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
    el.textContent = `(还有 ${h}:${m}:${s})`;
  }

  async function refreshState() {
    try {
      state = await window.API.call('get_state');
    } catch (err) {
      return;
    }
    renderTopbar();
    renderSteps();
    if (window.PAGES.dashboard && window.PAGES.dashboard.refresh) {
      window.PAGES.dashboard.refresh(state);
    }
  }

  /* ---------- 事件 ---------- */

  function wireEvents() {
    EV.on('state_change', refreshState);

    EV.on('exec_start', (event) => {
      alertState = null;
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
      if (event.detail) $('liveMsg').textContent = `${event.step}:${event.detail}`;
    });

    EV.on('attempt_update', async (event) => {
      if (!event) return;
      $('livePanel').classList.remove('hidden');
      $('liveMsg').textContent = `第 ${event.attempt} 次尝试:${event.message || ''}`;
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
      $('banner').classList.add('hidden');   // 先收起执行提示,失败时再弹告警
      const detail = event.summary || '';
      if (event.status === 'success') {
        alertState = null;
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
        if (res && res.ok) switchTab('logs');
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
    API.call('ui_ready').catch(() => {});   // 告知后端「面板已加载」
    tickCountdown();
    setInterval(tickCountdown, 1000);
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
