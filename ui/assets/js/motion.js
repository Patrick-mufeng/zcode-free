/* =========================================================================
   动效层 — 静默方格 Quiet Bento
   原则:
   1. 时长 .12~.24s,缓动 power2.out。安静、短促,不做弹跳和缩放。
   2. 只观察 DOM 变化,不参与业务逻辑;GSAP 缺失或系统偏好"减少动效"时静态呈现。
   3. 只用 transform / opacity;悬停靠 CSS 换底色,不动位移。
   4. 禁止"观察某元素 → 再把动画写回该元素"的自我触发写法。
   ========================================================================= */
(function () {
  const $ = (id) => document.getElementById(id);
  const gsap = window.gsap;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const params = new URLSearchParams(location.search);

  // ?motion=0 关闭动效(低功耗 / 远程桌面 / 截图核对)
  const motionOff = ['0', 'off', 'false'].includes((params.get('motion') || '').toLowerCase());
  const animated = !!gsap && !reduceMotion && !motionOff;

  // ?theme=dark|light 强制主题(默认深色)
  const theme = (params.get('theme') || '').toLowerCase();
  if (theme === 'dark' || theme === 'light') {
    document.documentElement.dataset.theme = theme;
  }

  const EASE = 'power2.out';
  const DUR = 0.18;

  function onReady(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  /* ---------- 侧栏选中指示条 ---------- */

  let ruleTween = null;

  function ruleTarget() {
    const tabs = $('tabs');
    const active = tabs && tabs.querySelector('.tab.active');
    if (!tabs || !active) return null;
    const parent = tabs.getBoundingClientRect();
    const rect = active.getBoundingClientRect();
    return { y: rect.top - parent.top + (rect.height - 30) / 2, height: 30 };
  }

  function positionRule(animate) {
    const rule = $('navGlow');
    const target = ruleTarget();
    if (!rule || !target) return;
    rule.style.height = target.height + 'px';
    if (animate && animated) {
      if (ruleTween) ruleTween.kill();
      ruleTween = gsap.to(rule, { y: target.y, scaleY: 1, opacity: 1, duration: 0.2, ease: EASE, overwrite: 'auto' });
    } else {
      rule.style.transform = 'translateY(' + target.y + 'px)';
      rule.style.opacity = '1';
    }
  }

  /* ---------- 页面内容入场:细线先画出来,内容随之上移淡入 ---------- */

  function animatePageIn() {
    if (!animated) return;
    const page = document.querySelector('.page:not(.hidden)');
    if (!page) return;
    const items = page.querySelectorAll(':scope > .panel, :scope > .cards, :scope > .dash-grid, :scope > .logs-layout');
    gsap.fromTo(items,
      { autoAlpha: 0, y: 6 },
      { autoAlpha: 1, y: 0, duration: 0.22, stagger: 0.03, ease: EASE, overwrite: 'auto', clearProps: 'transform' });
  }

  /* ---------- 开场序列:总时长控制在 1 秒内 ---------- */

  function bootEntrance() {
    if (!animated || bootEntrance.done) return;
    bootEntrance.done = true;
    const tl = gsap.timeline({ defaults: { ease: EASE, duration: DUR } });
    tl.from('.sidebar', { autoAlpha: 0, duration: 0.2 })
      .from('.brand', { autoAlpha: 0, y: -4, duration: 0.18 }, 0.04)
      .from('#tabs .tab', { autoAlpha: 0, x: -5, stagger: 0.025, duration: 0.18 }, 0.08)
      .from('.sidebar-foot', { autoAlpha: 0, duration: 0.16 }, 0.2)
      .from('.topbar', { autoAlpha: 0, y: -4, duration: 0.2 }, 0.06)
      .from('.topbar > *', { autoAlpha: 0, duration: 0.18, stagger: 0.03 }, 0.12)
      .from('.dt-rule', { scaleX: 0, transformOrigin: 'left center', duration: 0.3 }, 0.16)
      .from('.dt-tick', { scaleY: 0, duration: 0.14, stagger: 0.008 }, 0.24)
      .add(() => positionRule(true), 0.14)
      .add(() => animatePageIn(), 0.22);
  }

  /* ---------- 观察器工具 ---------- */

  function observe(target, options, fn) {
    if (!target || !animated) return;
    new MutationObserver(fn).observe(target, options);
  }

  /* ---------- Toast:轻微右移淡入 ---------- */

  function observeToasts() {
    observe($('toasts'), { childList: true }, (records) => {
      records.forEach((record) => {
        record.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.classList.contains('toast')) {
            gsap.from(node, { x: 14, autoAlpha: 0, duration: 0.22, ease: EASE });
          }
        });
      });
    });
  }

  /* ---------- 顶部提示条 ---------- */

  function observeBanner() {
    observe($('banner'), { attributes: true, attributeFilter: ['class'] }, () => {
      const banner = $('banner');
      if (!banner || banner.classList.contains('hidden')) return;
      gsap.fromTo(banner, { autoAlpha: 0, y: -6 }, { autoAlpha: 1, y: 0, duration: 0.2, ease: EASE });
    });
  }

  /* ---------- 状态文案副标题 ---------- */

  function observeStatus() {
    const sub = $('statusSub');
    let lastLabel = '';

    const sync = () => {
      const label = ($('statusText') || {}).textContent || '';
      if (label === lastLabel) return;
      lastLabel = label;
      if (!sub) return;
      const master = $('master');
      if (label.indexOf('执行中') >= 0) sub.textContent = '正在按流程执行,请勿遮挡 ZCode';
      else if (label.indexOf('需人工') >= 0) sub.textContent = '需要手动处理,详情见运行日志';
      else if (label.indexOf('失败') >= 0) sub.textContent = '本场未成功,详情见运行日志';
      else if (master && !master.checked) sub.textContent = '定时已关闭,可手动试领';
      else sub.textContent = '自动领取待命';
    };

    observe($('statusText'), { childList: true, characterData: true, subtree: true }, sync);
    const master = $('master');
    if (master) master.addEventListener('change', () => { lastLabel = ''; setTimeout(sync, 30); });
    sync();
  }

  /* ---------- 执行步骤:节点逐个冒出来 ---------- */

  function observeSteps() {
    observe($('steps'), { childList: true }, (records) => {
      records.forEach((record) => {
        const added = Array.from(record.addedNodes).filter((n) => n.nodeType === 1);
        if (added.length) gsap.from(added, { autoAlpha: 0, duration: 0.18, stagger: 0.02, ease: EASE });
      });
    });
  }

  /* ---------- 实时截图:换图时淡入(只监听 src,避免与动画互触) ---------- */

  function observeLiveShot() {
    const shot = $('liveShot');
    let lastSrc = shot ? shot.getAttribute('src') : null;
    observe(shot, { attributes: true, attributeFilter: ['src'] }, () => {
      const src = shot.getAttribute('src');
      if (!src || src === lastSrc) return;
      lastSrc = src;
      gsap.fromTo(shot, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.24, ease: EASE });
    });
  }

  /* ---------- 数字滚动(显式调用,不由观察触发) ---------- */

  function countTo(el, value) {
    if (!el) return;
    // 只对纯数字做滚动,避免把 "✓2 ✗1" 这类组合文本拆坏
    if (!/^\s*-?\d+(\.\d+)?\s*$/.test(String(el.textContent || ''))) {
      el.textContent = String(value);
      return;
    }
    const target = Number(value);
    if (!Number.isFinite(target)) { el.textContent = String(value); return; }

    const current = Number(String(el.textContent || '').trim());
    if (!animated || !Number.isFinite(current) || current === target) {
      el.textContent = String(value);
      return;
    }
    if (el.__numTween) el.__numTween.kill();
    const st = { v: current };
    el.__numTween = gsap.to(st, {
      v: target, duration: 0.32, ease: EASE,
      onUpdate: () => { el.textContent = String(Math.round(st.v)); },
      onComplete: () => { el.__numTween = null; el.textContent = String(value); },
    });
  }

  window.MOTION = {
    countTo,
    // 开场序列:app.js 建好 24 小时轨道后再调用,避免 GSAP 找不到 .dt-tick
    entrance: () => bootEntrance(),
    entranceDone: () => !!bootEntrance.done,
    ready: () => {
      observeToasts(); observeBanner(); observeStatus(); observeSteps();
      observeLiveShot(); observeLogs(); observeLiveLog();
    },
  };

  /* ---------- 日志回放卡片与缩略图 ---------- */

  function observeLogs() {
    const detail = $('sessionDetail');
    observe(detail, { childList: true }, (records) => {
      records.forEach((record) => {
        const attempts = Array.from(record.addedNodes)
          .filter((n) => n.nodeType === 1 && n.classList.contains('attempt'));
        if (attempts.length) gsap.from(attempts, { autoAlpha: 0, y: 5, duration: 0.2, stagger: 0.03, ease: EASE });
      });
    });
    observe(detail, { childList: true, subtree: true }, (records) => {
      records.forEach((record) => {
        record.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.tagName === 'IMG') {
            gsap.from(node, { autoAlpha: 0, duration: 0.2, ease: EASE });
          }
        });
      });
    });
  }

  /* ---------- 实时日志:新行轻微下移淡入 ---------- */

  function observeLiveLog() {
    const box = $('liveLog');
    let seen = box ? box.children.length : 0;
    observe(box, { childList: true }, () => {
      const nodes = Array.from(box.children);
      if (nodes.length <= seen) { seen = nodes.length; return; }
      const fresh = nodes.slice(seen);
      seen = nodes.length;
      gsap.from(fresh, { autoAlpha: 0, y: 4, duration: 0.16, ease: EASE });
    });
  }

  /* ---------- 连接标识 ---------- */

  function connectLabel() {
    const text = $('connText');
    if (text) text.textContent = location.host || '本地服务';
  }

  /* ---------- 启动 ---------- */

  onReady(() => {
    connectLabel();

    // 后台标签页里 rAF 会被暂停,入场动画会把元素停在透明态;
    // 因此页面不可见时直接呈现最终状态。
    const canAnimate = animated && document.visibilityState !== 'hidden';
    if (!canAnimate) {
      positionRule(false);
      return;
    }

    gsap.defaults({ ease: EASE, duration: DUR });
    observeToasts();
    observeBanner();
    observeStatus();
    observeSteps();
    observeLiveShot();
    observeLogs();
    observeLiveLog();

    // 兜底:app.js 若因为接口异常没能建出轨道,这里 1.5 秒后仍把界面显示完整
    setTimeout(() => bootEntrance(), 1500);

    const tabs = $('tabs');
    if (tabs) {
      tabs.addEventListener('click', (event) => {
        if (!event.target.closest('.tab')) return;
        setTimeout(() => { positionRule(true); animatePageIn(); }, 30);
      });
    }

    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => positionRule(false), 150);
    });
  });
})();
