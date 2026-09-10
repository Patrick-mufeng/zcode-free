/* 概览页:统计卡片 + 上手检查 + 最近记录 */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};

  window.PAGES.dashboard = {
    init() {
      $('gotoLogs').addEventListener('click', () => window.APP.switchTab('logs'));

      // 手动测试区:完整流程 / 演练(不点击)
      const bindRun = (id, dry) => {
        const button = $(id);
        if (!button) return;
        button.addEventListener('click', async () => {
          try {
            const res = await window.API.call('run_once', dry ? { dry: true } : null);
            window.APP.toast((res && res.message) || '已开始', res && res.ok ? 'ok' : 'err');
            if (res && res.ok) window.APP.refreshState();
          } catch (err) {
            window.APP.toast('启动失败:' + err.message, 'err');
          }
        });
      };
      bindRun('runOncePage', false);
      bindRun('runDryPage', true);

      $('setupList').addEventListener('click', async (event) => {
        const button = event.target.closest('button');
        if (!button) return;
        if (button.dataset.goto) {
          window.APP.switchTab(button.dataset.goto);
          return;
        }
        if (button.dataset.action === 'master') {
          $('master').checked = true;
          try {
            await window.API.call('set_master', { enabled: true });
            window.APP.toast('总开关已开启', 'ok');
          } catch (err) {
            window.APP.toast('开启失败:' + err.message, 'err');
          }
          window.APP.refreshState();
        }
      });
    },

    refresh(state) {
      const next = state.next_slot;
      $('cardNext').textContent = next ? next.label : '--';
      $('cardNextSub').textContent = next ? next.datetime : (state.slots_enabled ? '今天已无场次' : '未配置场次');

      // 数字卡片走显式滚动动画(只对纯数字生效),不再靠观察自身文字变化
      if (window.MOTION) window.MOTION.countTo($('cardSlots'), state.slots_total || 0);
      else $('cardSlots').textContent = String(state.slots_total || 0);
      $('cardSlotsSub').textContent = `启用 ${state.slots_enabled || 0} 个`;

      const today = state.today || {};
      const parts = [`✓${today.success || 0}`, `✗${today.failed || 0}`];
      if (today.need_manual) parts.push(`⚠${today.need_manual}`);
      $('cardToday').textContent = (today.total || 0) ? parts.join('  ') : '-';
      $('cardTodaySub').textContent = (today.total || 0) ? `共 ${today.total} 场` : '暂无记录';

      $('cardState').textContent = state.running ? '执行中' : (state.master ? '待命' : '已关闭');
      $('cardStateSub').textContent = `总开关:${state.master ? '开启' : '关闭'}${state.dry_run ? ' · 演练模式' : ''}`;

      this.renderSetup(state);
      this.renderRecent(state.recent || []);
    },

    /* 三步上手检查:全部完成后自动收起 */
    renderSetup(state) {
      const panel = $('setupPanel');
      if (!panel) return;
      const flags = {
        key: !!state.has_key,
        slots: (state.slots_enabled || 0) > 0,
        master: !!state.master,
      };
      const items = $('setupList').querySelectorAll('li[data-key]');
      let done = 0;
      items.forEach((item) => {
        const ok = !!flags[item.dataset.key];
        if (ok) done += 1;
        item.classList.toggle('done', ok);
        const button = item.querySelector('button');
        if (button) button.classList.toggle('hidden', ok);
        const chip = item.querySelector('.done-chip');
        if (ok && !chip) {
          const mark = document.createElement('span');
          mark.className = 'chip-chip done-chip';
          mark.textContent = '已完成';
          item.appendChild(mark);
        } else if (!ok && chip) {
          chip.remove();
        }
      });
      $('setupCount').textContent = `${done} / ${items.length}`;
      panel.classList.toggle('hidden', done === items.length);
    },

    renderRecent(items) {
      const tbody = $('recentTable').querySelector('tbody');
      const empty = $('recentEmpty');
      tbody.innerHTML = '';
      empty.classList.toggle('hidden', items.length > 0);
      items.forEach((item) => {
        const info = window.UITL.statusInfo(item.status);
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="mono">${window.UITL.esc(window.UITL.dt(item.started_at))}</td>
          <td>${window.UITL.esc(item.slot || '手动')}</td>
          <td class="${info.cls}">${window.UITL.esc(info.text)}</td>
          <td>${window.UITL.esc(item.summary || '')}</td>
          <td>${item.attempts || 0}</td>
          <td><button class="btn small">回放</button></td>`;
        tr.querySelector('button').addEventListener('click', () => {
          window.APP.switchTab('logs');
          window.PAGES.logs.open(item.id);
        });
        tbody.appendChild(tr);
      });
    },
  };
})();
