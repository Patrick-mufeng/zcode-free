/* 流程页:整体流程的可视化 + 执行时实时高亮 */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};

  // 流程图节点顺序(与 runner 的步骤名一一对应)
  const ORDER = ['trigger', 'open', 'shot1', 'locate', 'click', 'verify', 'done'];
  const STEP_TO_NODE = {
    '打开客户端': 'open',
    '截图': 'shot1',
    '识别按钮': 'locate',
    '点击领取': 'click',
    '校验结果': 'verify',
    '收尾': 'done',
  };
  const END_LABEL = {
    success: '成功', failed: '失败', need_manual: '需人工',
    aborted: '已中止', dry_run: '演练完成',
  };

  const nodes = {};
  let lastAttempt = 0;
  // 只标记"真实走过"的节点:未执行到的步骤保持中性,避免把没跑的点击/校验标成完成
  let visited = new Set();
  let failed = new Set();
  let current = null;

  function resetPath(withTrigger) {
    // 触发节点贯穿整个会话;每次重试只重置"本次尝试"走过的路径
    visited = new Set(withTrigger ? ['trigger'] : []);
    failed = new Set();
    current = null;
    render();
  }

  function render() {
    ORDER.forEach((id) => {
      const el = nodes[id];
      if (!el) return;
      el.classList.toggle('fail', failed.has(id));
      el.classList.toggle('active', current === id && !failed.has(id));
      el.classList.toggle('done', visited.has(id) && current !== id && !failed.has(id));
    });
  }

  function applyStep(step, status) {
    const node = STEP_TO_NODE[step];
    if (!node) return;
    if (current && current !== node) visited.add(current);
    current = node;
    if (status === 'fail') failed.add(node);
    render();
  }

  function flash(branch) {
    const el = document.querySelector('.branch[data-branch="' + branch + '"]');
    if (!el) return;
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1600);
  }

  function setPhase(text) {
    const el = $('flowPhase');
    if (el) el.textContent = text;
  }

  window.PAGES.flow = {
    init() {
      ORDER.forEach((id) => {
        nodes[id] = document.querySelector('#flowMain .flow-node[data-node="' + id + '"]');
      });

      EV.on('exec_start', (event) => {
        resetPath(true);
        setPhase((event && event.dry_run ? '演练中' : '执行中') + ' · 打开客户端');
      });

      EV.on('step_update', (event) => {
        if (!event || !event.step) return;
        applyStep(event.step, event.status);
        const attempt = event.attempt ? ' · 第 ' + event.attempt + ' 次尝试' : '';
        setPhase('执行中' + attempt + ' · ' + event.step);
      });

      EV.on('attempt_update', (event) => {
        if (!event) return;
        if (event.status === 'retry') flash('retry');
        // 新一次尝试:重新开始画路径(触发节点保留)
        if (event.status === 'running' && event.attempt !== lastAttempt) {
          lastAttempt = event.attempt;
          resetPath(true);
          setPhase('执行中 · 第 ' + event.attempt + ' 次尝试');
        }
      });

      EV.on('session_end', (event) => {
        if (!event) return;
        if (current) {
          if (event.status === 'success' || event.status === 'dry_run') visited.add(current);
          else if (!failed.size) failed.add(current);
        }
        current = null;
        render();
        setPhase(END_LABEL[event.status] || event.status || '空闲');
        if (event.status === 'success') flash('ok');
        else if (event.status === 'need_manual') flash('manual');
        else if (event.status === 'failed') flash('retry');
      });
    },

    async onShow() {
      try {
        const state = await window.API.call('get_state');
        if (state && state.current && state.current.step) {
          resetPath(true);
          applyStep(state.current.step, 'ok');
          lastAttempt = state.current.attempt || 0;
          setPhase('执行中 · 第 ' + lastAttempt + ' 次尝试');
        } else if (!current && !visited.size) {
          setPhase('空闲');   // 若还画着上次的路径,保留那次的结果标签
        }
      } catch (err) { /* 忽略:仅影响高亮 */ }
    },
  };
})();
