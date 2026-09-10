/* 视觉缺陷程序化审计:截断文字 / 元素重叠 / 对比度不足 / 空白页 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { rmSync } from "node:fs";

const url = process.argv[2];
const PORT = 9400 + Math.floor(Math.random() * 300);
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PROFILE = `C:\\Users\\${process.env.USERNAME}\\AppData\\Local\\Temp\\audit-${PORT}`;

const child = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });

let ws, id = 0; const pending = new Map();
const send = (method, params = {}) => { const mid = ++id; ws.send(JSON.stringify({ id: mid, method, params })); return new Promise((res, rej) => pending.set(mid, { res, rej })); };

async function connect() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/list`); const l = await r.json();
      const p = l.find(t => t.type === "page"); if (p?.webSocketDebuggerUrl) return p.webSocketDebuggerUrl; } catch {}
    await sleep(250);
  }
  throw new Error("no chrome");
}
ws = new WebSocket(await connect());
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
ws.onmessage = ev => { const m = JSON.parse(ev.data.toString()); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); } };
await send("Runtime.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await sleep(2200);

async function ev(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result?.value;
}

const AUDIT = `(() => {
  const lum = c => { const m = c.match(/[\\d.]+/g); if (!m) return null;
    const [r,g,b] = m.slice(0,3).map(Number).map(v => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); });
    return 0.2126*r + 0.7152*g + 0.0722*b; };
  const bgOf = n => { let e = n; while (e && e !== document.documentElement) { const c = getComputedStyle(e).backgroundColor;
    const m = c.match(/[\\d.]+/g); if (m && (m.length < 4 || Number(m[3]) > 0.55)) return c; e = e.parentElement; } return 'rgb(255,255,255)'; };
  const ratio = (a,b) => { const l1 = lum(a), l2 = lum(b); if (l1==null||l2==null) return null;
    return Math.round(((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05))*100)/100; };

  const out = { clipped: [], lowContrast: [], overlap: [], emptyPages: [], tiny: [] };
  const page = document.querySelector('.page.is-active');
  const host = page || document.body;

  // 1) 文字被截断(内容超出自身盒子且没有省略号的兜底)
  host.querySelectorAll('*').forEach(n => {
    if (n.children.length) return;
    const t = (n.textContent || '').trim(); if (!t || t.length < 2) return;
    const cs = getComputedStyle(n);
    if (cs.overflow === 'visible') return;
    if (n.scrollWidth > n.clientWidth + 1 && cs.textOverflow !== 'ellipsis')
      out.clipped.push({ cls: (n.className||'').toString().slice(0,28), t: t.slice(0,20), sw: n.scrollWidth, cw: n.clientWidth });
    if (n.scrollHeight > n.clientHeight + 2 && cs.overflowY === 'hidden' && cs.textOverflow !== 'ellipsis')
      out.clipped.push({ cls: (n.className||'').toString().slice(0,28), t: t.slice(0,20), sh: n.scrollHeight, ch: n.clientHeight, vert: 1 });
  });

  // 2) 对比度
  host.querySelectorAll('span,b,i,td,th,label,div,p,button,a').forEach(n => {
    if (!n.textContent || !n.textContent.trim()) return;
    if (n.children.length) return;
    const cs = getComputedStyle(n);
    const fs = parseFloat(cs.fontSize), fw = +cs.fontWeight || 400;
    const large = fs >= 18.66 || (fs >= 14 && fw >= 700);
    const need = large ? 3 : 4.5;
    const r = ratio(cs.color, bgOf(n));
    if (r != null && r < need) out.lowContrast.push({ cls: (n.className||'').toString().slice(0,24), t: n.textContent.trim().slice(0,18), fs, r, need });
  });

  // 3) 兄弟元素重叠(仅受检页面的直接视觉块)
  const blocks = Array.from(host.querySelectorAll('.card,.panel,.stage,.flow-node,.branch,.sess,.tl-row,section > div'));
  for (let i = 0; i < blocks.length; i++) for (let j = i+1; j < blocks.length; j++) {
    const a = blocks[i].getBoundingClientRect(), b = blocks[j].getBoundingClientRect();
    if (!a.width || !b.width) continue;
    if (blocks[i].contains(blocks[j]) || blocks[j].contains(blocks[i])) continue;
    const ox = Math.min(a.right,b.right) - Math.max(a.left,b.left);
    const oy = Math.min(a.bottom,b.bottom) - Math.max(a.top,b.top);
    if (ox > 3 && oy > 3) out.overlap.push({ a: (blocks[i].className||'').slice(0,20), b: (blocks[j].className||'').slice(0,20), ox: Math.round(ox), oy: Math.round(oy) });
  }

  // 4) 过小字号(可读性下限)
  host.querySelectorAll('*').forEach(n => {
    if (n.children.length || !n.textContent.trim()) return;
    const fs = parseFloat(getComputedStyle(n).fontSize);
    if (fs && fs < 10.5) out.tiny.push({ cls: (n.className||'').toString().slice(0,24), fs, t: n.textContent.trim().slice(0,16) });
  });

  // 5) 各页空白检测(切到每页数一下可见元素)
  return JSON.stringify(out);
})()`;

console.log("AUDIT →", await ev(AUDIT));

// 逐页检查是否有内容
const pages = await ev(`JSON.stringify(Array.from(document.querySelectorAll('[data-page]')).map(b=>b.getAttribute('data-page')))`);
const list = JSON.parse(pages);
for (const key of list) {
  await ev(`document.querySelector('[data-page="${key}"]').click()`);
  await sleep(500);
  const info = await ev(`(()=>{const p=document.querySelector('[data-page-panel="${key}"]');
    if(!p) return 'MISSING';
    const kids=p.children.length;
    const text=(p.textContent||'').replace(/\\s+/g,'').length;
    const h=Math.round(p.getBoundingClientRect().height);
    return JSON.stringify({kids,text,h});})()`);
  console.log(`  page ${key}: ${info}`);
}

ws.close(); child.kill();
try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}
