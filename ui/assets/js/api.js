/* 前后端通信:POST /api JSON-RPC(页面始终由本地服务提供) */
(function () {
  const waiters = [];
  let ready = false;

  function markReady() {
    if (ready) return;
    ready = true;
    waiters.splice(0).forEach((fn) => fn());
  }

  document.addEventListener('DOMContentLoaded', () => setTimeout(markReady, 0));

  async function call(method, payload) {
    const resp = await fetch('/api', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method, args: [payload || null] }),
    });
    const data = await resp.json();
    if (data && data.error) throw new Error(data.error);
    return data ? data.result : null;
  }

  window.API = {
    call,
    ready() { return new Promise((resolve) => (ready ? resolve() : waiters.push(resolve))); },
  };
})();
