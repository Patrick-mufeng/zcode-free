/* 运行日志页:场次回放 + 实时日志 */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};

  let sessions = [];
  let activeId = null;
  let logLines = [];
  let historyLoaded = false;
  let firstLogRender = true;
  const smoothScroll = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const LEVEL_CLASS = {
    INFO: 'lv-INFO', DEBUG: 'lv-DEBUG', WARNING: 'lv-WARNING',
    ERROR: 'lv-ERROR', CRITICAL: 'lv-CRITICAL', SUCCESS: 'lv-SUCCESS',
  };

  function renderList() {
    const box = $('sessionList');
    box.innerHTML = '';
    $('sessionEmpty').classList.toggle('hidden', sessions.length > 0);
    sessions.forEach((item) => {
      const info = window.UITL.statusInfo(item.status);
      const el = document.createElement('div');
      el.className = 'session-item' + (item.id === activeId ? ' active' : '');
      el.innerHTML = `
        <div>
          <div class="sid">${window.UITL.esc((item.started_at || item.id || '').slice(5, 16))}</div>
          <div class="muted">${window.UITL.esc(item.slot || (item.trigger === 'manual' ? '手动' : '--'))} · ${item.attempts || 0} 次</div>
        </div>
        <div class="${info.cls}">${window.UITL.esc(info.text)}</div>`;
      el.addEventListener('click', () => open(item.id));
      box.appendChild(el);
    });
  }

  async function open(id) {
    activeId = id;
    renderList();
    const box = $('sessionDetail');
    box.innerHTML = '<div class="muted">加载中…</div>';
    try {
      const res = await window.API.call('get_session_detail', { id });
      if (!res || !res.ok) throw new Error((res && res.message) || '加载失败');
      await renderDetail(res.session);
    } catch (err) {
      box.innerHTML = `<div class="empty">加载失败:${window.UITL.esc(err.message)}</div>`;
    }
  }

  async function renderDetail(session) {
    const box = $('sessionDetail');
    const info = window.UITL.statusInfo(session.status);
    box.innerHTML = `
      <div class="attempt-head">
        <div><b>${window.UITL.esc(session.id)}</b>
          <span class="muted">${window.UITL.esc(session.started_at || '')} → ${window.UITL.esc(session.ended_at || '')}</span></div>
        <div class="${info.cls}">${window.UITL.esc(info.text)}</div>
      </div>
      <div class="muted" style="margin-bottom:10px">${window.UITL.esc(session.summary || '')}</div>
      <div class="attempts"></div>`;
    const container = box.querySelector('.attempts');
    const attempts = session.attempts || [];
    if (!attempts.length) {
      container.innerHTML = '<div class="empty">尚无尝试记录</div>';
      return;
    }
    for (const attempt of attempts) {
      const el = document.createElement('div');
      el.className = 'attempt';
      const aInfo = window.UITL.statusInfo(attempt.result);
      const stepsHtml = (attempt.steps || []).map((step) => {
        const cls = step.status === 'ok' ? 'ok' : (step.status === 'fail' ? 'fail' : '');
        return `<div class="${cls}">${window.UITL.esc(step.time)} [${window.UITL.esc(step.step)}] ${window.UITL.esc(step.detail || '')}</div>`;
      }).join('');
      el.innerHTML = `
        <div class="attempt-head"><b>第 ${attempt.n} 次尝试</b>
          <span class="${aInfo.cls}">${window.UITL.esc(aInfo.text)}</span></div>
        <div class="steps-line">${stepsHtml || '<div class="muted">无步骤记录</div>'}</div>
        <div class="thumbs"></div>`;
      container.appendChild(el);

      const thumbs = el.querySelector('.thumbs');
      const images = Object.entries(attempt.images || {});
      for (const [kind, name] of images) {
        try {
          const res = await window.API.call('get_shot', { session: session.id, name, thumb: true });
          if (!res || !res.ok) continue;
          const img = document.createElement('img');
          img.src = res.image;
          img.title = `${kind === 'locate' ? '定位截图' : '点击后截图'} — 点击看大图`;
          img.addEventListener('click', async () => {
            const full = await window.API.call('get_shot', { session: session.id, name });
            if (full && full.ok) window.APP.lightbox(full.image);
          });
          thumbs.appendChild(img);
        } catch (err) { /* 跳过缺失截图 */ }
      }
    }
  }

  function renderLog() {
    const filterEl = $('logFilter');
    const filter = ((filterEl && filterEl.value) || '').trim().toLowerCase();
    const box = $('liveLog');
    const items = filter
      ? logLines.filter((line) => (line.message || '').toLowerCase().includes(filter))
      : logLines;
    if (!items.length) {
      box.innerHTML = `<div class="lv-DEBUG">${filter ? '(没有匹配的日志行)' : '暂无日志输出'}</div>`;
      return;
    }
    box.innerHTML = items.slice(-400).map((line) =>
      `<div class="${LEVEL_CLASS[line.level] || 'lv-INFO'}">[${window.UITL.esc(line.ts)}] ${window.UITL.esc(line.level)} ${window.UITL.esc(line.message)}</div>`
    ).join('');
    if (firstLogRender || !smoothScroll || !box.scrollTo) {
      box.scrollTop = box.scrollHeight;
      firstLogRender = false;
    } else {
      box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' });
    }
    renderDashLog();
  }

  /* 概览页也要能直接看到最近日志,复用同一份数据,只取尾部若干行 */
  const DASH_LINES = 40;
  function renderDashLog() {
    const box = $('dashLog');
    if (!box) return;
    if (!logLines.length) {
      box.innerHTML = '<div class="lv-DEBUG">暂无日志输出</div>';
      return;
    }
    box.innerHTML = logLines.slice(-DASH_LINES).map((line) =>
      `<div class="${LEVEL_CLASS[line.level] || 'lv-INFO'}">[${window.UITL.esc(line.ts)}] ${window.UITL.esc(line.message)}</div>`
    ).join('');
    box.scrollTop = box.scrollHeight;
  }

  /* 补拉历史日志;本地已有的实时行按「时间+内容」去重后接在后面。
     概览页与日志页共用同一份数据,所以这个方法要对两处都生效。 */
  async function loadHistory() {
    if (historyLoaded) return;
    try {
      const logs = await window.API.call('get_logs', { limit: 300 });
      const history = ((logs && logs.items) || []).map((item) => ({
        ts: (item.ts || '').slice(11), level: item.level, message: item.message,
      }));
      const localKeys = new Set(logLines.map((line) => line.ts + line.message));
      logLines = history.filter((line) => !localKeys.has(line.ts + line.message)).concat(logLines);
      historyLoaded = true;
      renderDashLog();
      if (!$('page-logs').classList.contains('hidden')) renderLog();
    } catch (err) { /* 忽略:仅影响历史日志 */ }
  }

  window.PAGES.logs = {
    init() {
      $('refreshSessions').addEventListener('click', () => window.PAGES.logs.onShow());
      $('logFilter').addEventListener('input', renderLog);
      $('clearLiveLog').addEventListener('click', () => { logLines = []; renderLog(); });
    },

    async onShow() {
      try {
        const data = await window.API.call('list_sessions', { limit: 100 });
        sessions = (data && data.items) || [];
        renderList();
        if (sessions.length && !activeId) open(sessions[0].id);
      } catch (err) {
        window.APP.toast('读取记录失败:' + err.message, 'err');
      }

      await loadHistory();
      // 无论是否新拉取过,进入页面都要渲染一次(实时行可能早已推送过来)
      renderLog();
    },

    open,
    renderDashLog,
    loadHistory,

    appendLog(event) {
      if (!event) return;
      logLines.push({ ts: event.ts || '', level: event.level || 'INFO', message: event.message || '' });
      if (logLines.length > 800) logLines = logLines.slice(-800);
      if (!$('page-logs').classList.contains('hidden')) renderLog();
      else renderDashLog();
    },
  };
})();
