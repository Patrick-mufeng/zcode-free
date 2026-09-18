/* 场次表页:增删改 + 未来 7 天预览(即时保存) */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};
  let slots = [];
  let lastResults = {};

  // 星期编号沿用 Python 的 weekday():周一=0 … 周日=6,顺序与后端一致
  const DAY_NAMES = ['一', '二', '三', '四', '五', '六', '日'];
  const DAY_ORDER = [4, 5, 6, 0, 1, 2, 3];   // 展示顺序从周五起(与福利周期一致)

  function collect() {
    const rows = $('slotTable').querySelectorAll('tbody tr');
    const out = [];
    rows.forEach((row) => {
      const time = row.querySelector('input[type="time"]').value || '10:00';
      const enabled = row.querySelector('input[type="checkbox"]').checked;
      const attemptsRaw = row.querySelector('.attempts').value.trim();
      const gapRaw = row.querySelector('.gap').value.trim();
      // 「每天」时不写 days(保持与旧配置一致);选了部分星期才落字段
      const picked = [];
      row.querySelectorAll('.days .day.on').forEach((btn) => {
        picked.push(Number(btn.dataset.day));
      });
      const entry = {
        time,
        enabled,
        attempts: attemptsRaw ? Number(attemptsRaw) : null,
        retry_gap_s: gapRaw ? Number(gapRaw) : null,
      };
      if (picked.length && picked.length < 7) entry.days = picked.sort((a, b) => a - b);
      out.push(entry);
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
      // 结果按「时间 + 星期」匹配:同一时间的场次可能排在不同星期
      const result = lastResults[slotKey(slot)];
      const info = result ? window.UITL.statusInfo(result.status) : null;
      // 只显示「今天」的记录:否则改完场次后,这一列还挂着上次触发的旧结果,
      // 看起来像是刚失败/被跳过(实际是几天前那场的)
      const detail = info
        ? window.UITL.esc(info.text) + ' · ' + window.UITL.esc(window.UITL.dt(result.started_at))
        : '<span class="muted">今日未执行</span>';
      const picked = (slot.days && slot.days.length && slot.days.length < 7) ? slot.days : null;
      // 未指定星期 = 每天:按钮全灰(靠 .all 的样式传达"每天"),并加 title 说明
      const daysHtml = DAY_ORDER.map((d) => {
        const on = !!picked && picked.indexOf(d) >= 0;
        return `<button type="button" class="day${on ? ' on' : ''}${picked ? '' : ' all'}"
                  data-day="${d}" title="周${DAY_NAMES[d]}">${DAY_NAMES[d]}</button>`;
      }).join('');
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><input type="checkbox" ${slot.enabled !== false ? 'checked' : ''} /></td>
        <td><input type="time" value="${window.UITL.esc(slot.time || '10:00')}" /></td>
        <td class="days" title="点击切换星期;全灰=每天">${daysHtml}</td>
        <td><input type="number" class="attempts" min="1" max="20" placeholder="默认" value="${slot.attempts != null ? slot.attempts : ''}" /></td>
        <td><input type="number" class="gap" min="1" max="120" placeholder="默认" value="${slot.retry_gap_s != null ? slot.retry_gap_s : ''}" /></td>
        <td class="${info ? info.cls : 'muted'}">${detail}</td>
        <td><button class="btn small danger" title="删除场次" aria-label="删除场次">删除</button></td>`;

      tr.querySelector('input[type="checkbox"]').addEventListener('change', () => save(true));
      tr.querySelector('input[type="time"]').addEventListener('change', () => save(true));
      tr.querySelector('.attempts').addEventListener('change', () => save(true));
      tr.querySelector('.gap').addEventListener('change', () => save(true));

      // 星期按钮:没有任何 .on 表示「每天」;点了某个星期就变成"只跑这些星期"。
      // 从「每天」点第一下时,意图必然是"只排这一天",所以直接切成单天;
      // 已是自定义状态时按普通开关切换,全部取消则回到「每天」。
      const dayBtns = tr.querySelectorAll('.days .day');
      const applyDays = () => {
        const on = [...dayBtns].filter((b) => b.classList.contains('on'));
        dayBtns.forEach((b) => {
          b.classList.toggle('all', on.length === 0);
          b.classList.toggle('on', on.length > 0 && b.classList.contains('on'));
        });
      };
      dayBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
          const custom = [...dayBtns].some((b) => b.classList.contains('on'));
          if (!custom) {
            btn.classList.add('on');            // 每天 → 只留这一天
          } else {
            btn.classList.toggle('on');
          }
          applyDays();
          save(true);
          renderWeek(collect());
        });
      });

      tr.querySelector('button.danger').addEventListener('click', () => {
        slots.splice(index, 1);
        render();
        save(true);
      });
      tbody.appendChild(tr);
    });
    renderWeek(slots);
  }

  /* 场次唯一键:时间 + 星期。老配置没有 days,按「每天」处理 */
  function slotKey(slot) {
    const days = (slot.days && slot.days.length && slot.days.length < 7)
      ? slot.days.slice().sort((a, b) => a - b).join('') : 'all';
    return `${slot.time}|${days}`;
  }

  function renderWeek(list) {
    const box = $('weekPreview');
    box.innerHTML = '';
    const enabled = (list || slots).filter((s) => s.enabled !== false && s.time);
    const names = ['日', '一', '二', '三', '四', '五', '六'];
    for (let i = 0; i < 7; i += 1) {
      const day = new Date();
      day.setDate(day.getDate() + i);
      // JS 的 getDay() 是周日=0,换算成 Python 的周一=0
      const pyDay = (day.getDay() + 6) % 7;
      const todays = enabled
        .filter((s) => !s.days || !s.days.length || s.days.indexOf(pyDay) >= 0)
        .sort((a, b) => String(a.time).localeCompare(String(b.time)));
      const label = `${day.getMonth() + 1}/${day.getDate()} 周${names[day.getDay()]}${i === 0 ? '(今天)' : ''}`;
      const row = document.createElement('div');
      row.className = 'week-row';
      row.innerHTML = `<span class="week-day">${label}</span><span>${
        todays.length
          ? todays.map((s) => `<span class="week-slot">${window.UITL.esc(s.time)}</span>`).join('')
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
        const today = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
        (data && data.items ? data.items : []).forEach((item) => {
          // 只看今天的记录:历史场次的旧结果挂在这里会被误读成"刚刚又失败了"
          if (!item.slot || lastResults[item.slot]) return;
          if (!String(item.started_at || '').startsWith(todayStr)) return;
          lastResults[item.slot] = item;
        });
      } catch (err) { lastResults = {}; }
      render();
    },
  };
})();
