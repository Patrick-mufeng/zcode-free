/* 事件通道(SSE)与通用小工具 */
(function () {
  const handlers = {};

  window.__zcodeEvent = function (type, payload) {
    (handlers[type] || []).forEach((fn) => {
      try { fn(payload); } catch (err) { console.error('event handler error', type, err); }
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    try {
      const es = new EventSource('/events');
      es.onopen = () => { document.body.dataset.sse = 'on'; };
      es.onerror = () => { document.body.dataset.sse = 'off'; };
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          window.__zcodeEvent(msg.type, msg.payload);
        } catch (err) { /* 心跳等非 JSON 行 */ }
      };
    } catch (err) {
      document.body.dataset.sse = 'off';
      console.error('SSE 连接失败', err);
    }
  });

  window.EV = {
    on(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
  };

  window.UITL = {
    esc(text) {
      return String(text == null ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },
    dt(value) {
      if (!value) return '--';
      const s = String(value);
      return s.length >= 16 ? s.slice(5, 16) : s;
    },
    statusInfo(status) {
      const map = {
        success: { text: '成功', cls: 'ok' },
        claimed: { text: '已领取', cls: 'ok' },
        failed: { text: '失败', cls: 'fail' },
        need_manual: { text: '需人工', cls: 'fail' },
        aborted: { text: '已中止', cls: 'fail' },
        dry_run: { text: '演练', cls: '' },
        running: { text: '执行中', cls: '' },
        retry: { text: '重试中', cls: '' },
        manual: { text: '需人工', cls: 'fail' },
      };
      return map[status] || { text: status || '--', cls: '' };
    },
  };
})();
