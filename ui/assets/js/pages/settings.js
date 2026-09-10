/* 设置页:路径 / 重试参数 / 通知 / 数据与危险操作(全部即时保存) */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};
  let loading = false;

  const FIELDS = [
    'sZcodePath', 'sTitleMatch', 'sFullscreen', 'sStartupWait',
    'sRectX', 'sRectY', 'sRectW', 'sRectH',
    'rAttempts', 'rGap', 'rOpenTimeout', 'rSettle', 'rFocusSettle',
    'rAppReady', 'rVerifyReady', 'rWatchdog', 'rUserIdle', 'rUserIdleWait',
    'sKeepAwake', 'sNotifyDesktop', 'sWebhook', 'sKeepDays',
  ];

  function numberOr(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) && value !== '' ? n : fallback;
  }

  function readForm() {
    return {
      app: {
        zcode_path: $('sZcodePath').value.trim(),
        window_title_match: $('sTitleMatch').value.trim() || 'ZCode',
        fullscreen: $('sFullscreen').checked,
        startup_wait_s: Math.max(0, numberOr($('sStartupWait').value, 5)),
        restore_window_rect: $('sRestore').checked,
        window_rect: [
          numberOr($('sRectX').value, 40), numberOr($('sRectY').value, 40),
          numberOr($('sRectW').value, 1240), numberOr($('sRectH').value, 860),
        ],
      },
      retry: {
        max_attempts: Math.max(1, numberOr($('rAttempts').value, 5)),
        retry_gap_s: Math.max(1, numberOr($('rGap').value, 5)),
        open_timeout_s: Math.max(5, numberOr($('rOpenTimeout').value, 30)),
        settle_s: Math.max(0, numberOr($('rSettle').value, 2)),
        focus_settle_s: Math.max(0, numberOr($('rFocusSettle').value, 0.4)),
        app_ready_timeout_s: Math.max(0, numberOr($('rAppReady').value, 20)),
        verify_ready_timeout_s: Math.max(0, numberOr($('rVerifyReady').value, 8)),
        watchdog_s: Math.max(30, numberOr($('rWatchdog').value, 480)),
        user_idle_s: Math.max(0, numberOr($('rUserIdle').value, 1)),
        user_idle_wait_s: Math.max(0, numberOr($('rUserIdleWait').value, 20)),
      },
      schedule: { keep_awake: $('sKeepAwake').checked },
      notify: {
        desktop: $('sNotifyDesktop').checked,
        webhook_url: $('sWebhook').value.trim(),
      },
      data: { keep_days: Math.max(1, numberOr($('sKeepDays').value, 7)) },
    };
  }

  async function save() {
    if (loading) return;
    try {
      await window.API.call('save_settings', readForm());
    } catch (err) {
      window.APP.toast('保存失败:' + err.message, 'err');
    }
  }

  window.PAGES.settings = {
    init() {
      FIELDS.forEach((id) => $(id).addEventListener('change', save));

      $('btnDetect').addEventListener('click', async () => {
        const box = $('detectResult');
        box.classList.remove('hidden', 'ok', 'err');
        box.textContent = '探测中(首次可能需要几秒)…';
        try {
          const res = await window.API.call('detect_zcode');
          box.classList.add(res && res.ok ? 'ok' : 'err');
          box.textContent = (res && res.message) || '未知结果';
          if (res && res.ok) $('sZcodePath').value = res.path;
        } catch (err) {
          box.classList.add('err');
          box.textContent = '探测失败:' + err.message;
        }
      });

      $('btnOpenDataDir').addEventListener('click', () => window.API.call('open_data_dir'));

      $('btnClearShots').addEventListener('click', async () => {
        if (!(await window.APP.confirm('确定清除全部截图留档吗?该操作不可恢复。'))) return;
        const res = await window.API.call('cleanup', { action: 'shots' });
        window.APP.toast((res && res.message) || '已清除', 'ok');
      });

      $('btnClearLogs').addEventListener('click', async () => {
        if (!(await window.APP.confirm('确定清空全部日志文件吗?'))) return;
        const res = await window.API.call('cleanup', { action: 'logs' });
        window.APP.toast((res && res.message) || '已清空', 'ok');
      });

      $('btnReset').addEventListener('click', async () => {
        if (!(await window.APP.confirm('确定将配置重置为默认值吗?\n(保留已填写的 ZCode 路径与 API Key)'))) return;
        const res = await window.API.call('cleanup', { action: 'reset' });
        window.APP.toast((res && res.message) || '已重置', 'ok');
        await window.PAGES.settings.onShow();
        window.APP.refreshState();
      });

      $('btnQuit').addEventListener('click', async () => {
        if (!(await window.APP.confirm('确定退出程序吗?\n后台的自动领取会立即停止,正在执行的任务会被中断。'))) return;
        const res = await window.API.call('quit_app');
        window.APP.toast((res && res.message) || '程序即将退出', 'ok');
      });
    },

    async onShow() {
      loading = true;
      try {
        const data = await window.API.call('get_settings');
        const app = data.app || {};
        const retry = data.retry || {};
        $('sZcodePath').value = app.zcode_path || '';
        $('sTitleMatch').value = app.window_title_match || 'ZCode';
        $('sFullscreen').checked = app.fullscreen !== false;
        $('sStartupWait').value = app.startup_wait_s != null ? app.startup_wait_s : 5;
        $('sRestore').checked = app.restore_window_rect !== false;
        const rect = app.window_rect || [40, 40, 1240, 860];
        $('sRectX').value = rect[0]; $('sRectY').value = rect[1];
        $('sRectW').value = rect[2]; $('sRectH').value = rect[3];
        $('rAttempts').value = retry.max_attempts != null ? retry.max_attempts : 5;
        $('rGap').value = retry.retry_gap_s != null ? retry.retry_gap_s : 5;
        $('rOpenTimeout').value = retry.open_timeout_s != null ? retry.open_timeout_s : 30;
        $('rSettle').value = retry.settle_s != null ? retry.settle_s : 2;
        $('rFocusSettle').value = retry.focus_settle_s != null ? retry.focus_settle_s : 0.4;
        $('rAppReady').value = retry.app_ready_timeout_s != null ? retry.app_ready_timeout_s : 20;
        $('rVerifyReady').value = retry.verify_ready_timeout_s != null ? retry.verify_ready_timeout_s : 8;
        $('rWatchdog').value = retry.watchdog_s != null ? retry.watchdog_s : 480;
        $('rUserIdle').value = retry.user_idle_s != null ? retry.user_idle_s : 1;
        $('rUserIdleWait').value = retry.user_idle_wait_s != null ? retry.user_idle_wait_s : 20;
        $('sKeepAwake').checked = (data.schedule || {}).keep_awake !== false;
        $('sNotifyDesktop').checked = (data.notify || {}).desktop !== false;
        $('sWebhook').value = (data.notify || {}).webhook_url || '';
        $('sKeepDays').value = (data.data || {}).keep_days != null ? data.data.keep_days : 7;
        $('configPathText').textContent = data.config_path || '';
      } catch (err) {
        window.APP.toast('读取设置失败:' + err.message, 'err');
      } finally {
        loading = false;
      }
    },
  };
})();
