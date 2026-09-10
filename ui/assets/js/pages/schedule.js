/* 场次表页:增删改 + 未来 7 天预览(即时保存) */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};
  let slots = [];
  let lastResults = {};

  function collect() {
    const rows = $('slotTable').querySelectorAll('tbody tr');
    const out = [];
    rows.forEach((row) => {
      const time = row.querySelector('input[type="time"]').value || '10:00';
      const enabled = row.querySelector('input[type="checkbox"]').checked;
      const attemptsRaw = row.querySelector('.attempts').value.trim();
      const gapRaw = row.querySelector('.gap').value.trim();
      out.push({
        time,
        enabled,
        attempts: attemptsRaw ? Number(attemptsRaw) : null,
        retry_gap_s: gapRaw ? Number(gapRaw) : null,
      });
    });
    return out;
  }

  async function save(showToast) {
    slots = collect();
    try {
      await window.API.call('save_schedule', { slots });
      if (showToast) window.APP.toast('场次表已更新', 'ok');
    } catch (err) {
      window.APP.toast('保存失败:' + err.message, 'err');
    }
  }

  function render() {
    const tbody = $('slotTable').querySelector('tbody');
    tbody.innerHTML = '';
    $('slotEmpty').classList.toggle('hidden', slots.length > 0);
    const countEl = $('slotCount');
    if (countEl) {
      const on = slots.filter((s) => s.enabled !== false).length;
      countEl.textContent = slots.length + ' 个场次 · 启用 ' + on + ' 个';
    }

    slots.forEach((slot, index) => {
      const result = lastResults[slot.time];
      const info = result ? window.UITL.statusInfo(result.status) : null;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><input type="checkbox" ${slot.enabled !== false ? 'checked' : ''} /></td>
        <td><input type="time" value="${window.UITL.esc(slot.time || '10:00')}" /></td>
        <td><input type="number" class="attempts" min="1" max="20" placeholder="默认" value="${slot.attempts != null ? slot.attempts : ''}" /></td>
        <td><input type="number" class="gap" min="1" max="120" placeholder="默认" value="${slot.retry_gap_s != null ? slot.retry_gap_s : ''}" /></td>
        <td class="${info ? info.cls : 'muted'}">${info ? window.UITL.esc(info.text) + (result.started_at ? ' · ' + window.UITL.esc(window.UITL.dt(result.started_at)) : '') : '—'}</td>
        <td><button class="btn small danger" title="删除场次" aria-label="删除场次">删除</button></td>`;
      tr.querySelector('input[type="checkbox"]').addEventListener('change', () => save(true));
      tr.querySelector('input[type="time"]').addEventListener('change', () => save(true));
      tr.querySelector('.attempts').addEventListener('change', () => save(true));
      tr.querySelector('.gap').addEventListener('change', () => save(true));
      tr.querySelector('button').addEventListener('click', () => {
        slots.splice(index, 1);
        render();
        save(true);
      });
      tbody.appendChild(tr);
    });
    renderWeek();
  }

  function renderWeek() {
    const box = $('weekPreview');
    box.innerHTML = '';
    const enabled = slots.filter((s) => s.enabled !== false && s.time);
    const names = ['日', '一', '二', '三', '四', '五', '六'];
    for (let i = 0; i < 7; i += 1) {
      const day = new Date();
      day.setDate(day.getDate() + i);
      const label = `${day.getMonth() + 1}/${day.getDate()} 周${names[day.getDay()]}${i === 0 ? '(今天)' : ''}`;
      const row = document.createElement('div');
      row.className = 'week-row';
      row.innerHTML = `<span class="week-day">${label}</span><span>${
        enabled.length
          ? enabled.map((s) => `<span class="week-slot">${window.UITL.esc(s.time)}</span>`).join('')
          : '<span class="muted">无场次</span>'
      }</span>`;
      box.appendChild(row);
    }
  }

  window.PAGES.schedule = {
    init() {
      document.getElementById('addSlot').addEventListener('click', () => {
        slots.push({ time: '10:00', enabled: true, attempts: null, retry_gap_s: null });
        render();
        save(true);
      });
    },

    async onShow() {
      const cfg = await window.API.call('get_schedule');
      slots = (cfg && cfg.slots) || [];
      try {
        const data = await window.API.call('list_sessions', { limit: 200 });
        lastResults = {};
        (data && data.items ? data.items : []).forEach((item) => {
          if (item.slot && !lastResults[item.slot]) lastResults[item.slot] = item;
        });
      } catch (err) { lastResults = {}; }
      render();
    },
  };
})();
