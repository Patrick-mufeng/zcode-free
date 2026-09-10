/* =========================================================================
   动效层(Aurora Console)
   原则:只观察 DOM 变化,不参与业务逻辑;GSAP 缺失或系统偏好"减少动效"时
   自动退化为静态呈现。全部动效仅使用 transform / opacity。
   ========================================================================= */
(function () {
  const $ = (id) => document.getElementById(id);
  const gsap = window.gsap;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // 支持 ?motion=0 关闭动效(低功耗 / 远程桌面 / 截图核对)
  const motionOff = ['0', 'off', 'false'].includes(
    (new URLSearchParams(location.search).get('motion') || '').toLowerCase());
  const animated = !!gsap && !reduceMotion && !motionOff;

  function onReady(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  /* ---------- 侧栏导航光条 ---------- */

  let glowTween = null;

  function glowTarget() {
    const tabs = $('tabs');
    const active = tabs && tabs.querySelector('.tab.active');
    if (!tabs || !active) return null;
    const parent = tabs.getBoundingClientRect();
    const rect = active.getBoundingClientRect();
    return { y: rect.top - parent.top, height: rect.height };
  }

  function positionGlow(animate) {
    const glow = $('navGlow');
    const target = glowTarget();
    if (!glow || !target) return;
    glow.style.height = target.height + 'px';
    if (animate && animated) {
      if (glowTween) glowTween.kill();
      glowTween = gsap.to(glow, {
        y: target.y, opacity: 1, duration: 0.5, ease: 'expo.out', overwrite: 'auto',
      });
    } else {
      glow.style.transform = 'translateY(' + target.y + 'px)';
      glow.style.opacity = '1';
    }
  }

  /* ---------- 页面切换:内容依次浮入 ---------- */

  function animatePageIn(delay) {
    const page = document.querySelector('.page:not(.hidden)');
    if (!page) return;
    const items = page.querySelectorAll(':scope > .cards > .card, :scope > .panel, :scope > .logs-layout');
    if (!animated) return;
    gsap.fromTo(items,
      { autoAlpha: 0, y: 14 },
      { autoAlpha: 1, y: 0, duration: 0.55, stagger: 0.05, delay: delay || 0, ease: 'expo.out', overwrite: 'auto' });
  }

  /* ---------- 开场序列 ---------- */

  function bootEntrance() {
    const tl = gsap.timeline({ defaults: { ease: 'expo.out', duration: 0.55 } });
    tl.from('.sidebar .brand', { autoAlpha: 0, x: -12, duration: 0.5 })
      .from('#tabs .tab', { autoAlpha: 0, x: -10, stagger: 0.05 }, '-=0.34')
      .from('.topbar > *', { autoAlpha: 0, y: -10, stagger: 0.05 }, '-=0.42')
      .from('.sidebar-foot > *', { autoAlpha: 0, y: 8, stagger: 0.06 }, '-=0.4')
      .add(() => positionGlow(true), 0.15)
      .add(() => animatePageIn(0), 0.1);
  }

  /* ---------- 观察器工具 ---------- */

  const observers = [];
  function observe(target, options, fn) {
    if (!target || !animated) return;
    const mo = new MutationObserver(fn);
    mo.observe(target, options);
    observers.push(mo);
  }

  /* ---------- Toast:弹性入场 ---------- */

  function observeToasts() {
    observe($('toasts'), { childList: true }, (records) => {
      records.forEach((record) => {
        record.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.classList.contains('toast')) {
            gsap.from(node, { x: 30, autoAlpha: 0, duration: 0.5, ease: 'back.out(1.7)' });
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
      gsap.fromTo(banner, { autoAlpha: 0, y: 18 }, { autoAlpha: 1, y: 0, duration: 0.5, ease: 'expo.out' });
    });
  }

  /* ---------- 状态灯:执行中呼吸 ---------- */

  function observeStatus() {
    const dot = $('statusDot');
    const sub = $('statusSub');
    let lastLabel = '';

    const sync = () => {
      const label = ($('statusText') || {}).textContent || '';
      if (label === lastLabel) return;
      lastLabel = label;
      if (sub) {
        const master = $('master');
        sub.textContent = label.indexOf('执行中') >= 0
          ? '正在按流程执行,请勿遮挡 ZCode'
          : (master && !master.checked ? '定时已关闭,可手动试领' : '自动领取待命');
      }
      if (!animated || !dot) return;
      if (label.indexOf('执行中') >= 0) {
        gsap.fromTo(dot, { scale: 0.8 }, { scale: 1, duration: 0.45, ease: 'back.out(2.4)' });
      }
    };

    observe($('statusText'), { childList: true, characterData: true, subtree: true }, sync);
    const master = $('master');
    if (master) master.addEventListener('change', () => { lastLabel = ''; setTimeout(sync, 30); });
    sync();
  }

  /* ---------- 执行步骤:入场与状态弹跳 ---------- */

  function observeSteps() {
    const steps = $('steps');
    observe(steps, { childList: true }, (records) => {
      records.forEach((record) => {
        const added = Array.from(record.addedNodes).filter((n) => n.nodeType === 1);
        if (added.length) {
          gsap.from(added, { autoAlpha: 0, y: 8, duration: 0.45, stagger: 0.04, ease: 'expo.out' });
        }
      });
    });
    observe(steps, { attributes: true, attributeFilter: ['class'], subtree: true }, (records) => {
      records.forEach((record) => {
        const el = record.target;
        if (!el.classList || !el.classList.contains('circle')) return;
        const cls = el.parentElement ? el.parentElement.className : '';
        gsap.fromTo(el,
          { scale: 0.7 },
          { scale: 1, duration: 0.42, ease: 'back.out(2.6)', overwrite: 'auto' });
      });
    });
  }

  /* ---------- 实时截图:换图时交叉淡入 ----------
     只监听 src 变化:GSAP 动画本身会写 style 属性,若连 style 一起监听,
     就会像数字动画那样自我触发成环。 */

  function observeLiveShot() {
    const shot = $('liveShot');
    let lastSrc = shot ? shot.getAttribute('src') : null;
    observe(shot, { attributes: true, attributeFilter: ['src'] }, () => {
      const src = shot.getAttribute('src');
      if (!src || src === lastSrc) return;
      lastSrc = src;
      gsap.fromTo(shot, { autoAlpha: 0, scale: 0.985 }, { autoAlpha: 1, scale: 1, duration: 0.45, ease: 'expo.out' });
    });
  }

  /* ---------- 数字滚动 ----------
     注意:数字动画**不能**由"观察自身文字变化"来驱动 —— 动画每一帧写回的
     中间值会被当成新的数据变化,再次触发动画,形成永久来回弹跳(数字狂闪)。
     因此改为显式调用:由数据层调用 MOTION.countTo(el, 目标值)。 */

  function countTo(el, value) {
    if (!el) return;
    const target = Number(value);
    if (!Number.isFinite(target)) { el.textContent = String(value); return; }

    const current = Number(String(el.textContent || '').trim());
    if (!animated || !Number.isFinite(current) || current === target) {
      el.textContent = String(value);
      return;
    }
    if (el.__numTween) el.__numTween.kill();     // 上一次未播完先停掉,避免叠加
    const state = { v: current };
    el.__numTween = gsap.to(state, {
      v: target, duration: 0.55, ease: 'power2.out',
      onUpdate: () => { el.textContent = String(Math.round(state.v)); },
      onComplete: () => { el.__numTween = null; el.textContent = String(value); },
    });
  }

  window.MOTION = { countTo };

  /* ---------- 日志页:回放卡片与缩略图 ---------- */

  function observeLogs() {
    const detail = $('sessionDetail');
    observe(detail, { childList: true }, (records) => {
      records.forEach((record) => {
        const attempts = Array.from(record.addedNodes)
          .filter((n) => n.nodeType === 1 && n.classList.contains('attempt'));
        if (attempts.length) {
          gsap.from(attempts, { autoAlpha: 0, y: 12, duration: 0.5, stagger: 0.07, ease: 'expo.out' });
        }
      });
    });
    observe(detail, { childList: true, subtree: true }, (records) => {
      records.forEach((record) => {
        record.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.tagName === 'IMG') {
            gsap.from(node, { autoAlpha: 0, duration: 0.45, ease: 'expo.out' });
          }
        });
      });
    });
  }

  /* ---------- 环境光缓慢漂移 ---------- */

  function ambient() {
    gsap.to('.blob-1', { xPercent: 8, yPercent: 6, duration: 23, repeat: -1, yoyo: true, ease: 'sine.inOut' });
    gsap.to('.blob-2', { xPercent: -7, yPercent: -5, duration: 29, repeat: -1, yoyo: true, ease: 'sine.inOut' });
    gsap.to('.blob-3', { xPercent: 10, yPercent: -8, duration: 34, repeat: -1, yoyo: true, ease: 'sine.inOut' });
  }

  /* ---------- 启动 ---------- */

  function connectLabel() {
    const text = $('connText');
    if (text) text.textContent = location.host || '本地服务';
  }

  onReady(() => {
    connectLabel();

    // 后台标签页里 rAF 会被暂停,入场动画会把元素停在透明态;
    // 因此页面不可见时直接呈现最终状态。
    const canAnimate = animated && document.visibilityState !== 'hidden';
    if (!canAnimate) {
      positionGlow(false);
      return;
    }

    gsap.defaults({ ease: 'expo.out', duration: 0.5 });
    ambient();
    bootEntrance();
    observeToasts();
    observeBanner();
    observeStatus();
    observeSteps();
    observeLiveShot();
    observeLogs();

    const tabs = $('tabs');
    if (tabs) {
      tabs.addEventListener('click', (event) => {
        if (!event.target.closest('.tab')) return;
        setTimeout(() => { positionGlow(true); animatePageIn(0.04); }, 40);
      });
    }

    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => positionGlow(false), 150);
    });
  });
})();
