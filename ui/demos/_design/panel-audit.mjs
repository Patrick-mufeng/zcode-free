/* 真实面板审计:遍历六个页签,检查控制台报错、溢出、对比度、截断、重叠、空白页。
   用法: node panel-audit.mjs http://127.0.0.1:8791/ [outDir] */
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const URL_ = process.argv[2] || "http://127.0.0.1:8791/";
const OUT = process.argv[3] || "out/panel";
const PORT = 9500 + Math.floor(Math.random() * 300);
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PROFILE = `C:\\Users\\${process.env.USERNAME}\\AppData\\Local\\Temp\\pa-${PORT}`;
mkdirSync(OUT, { recursive: true });

const child = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
  "--window-size=1680,1000", "about:blank"], { stdio: "ignore" });

let ws, id = 0; const pending = new Map(); const problems = [];
const send = (m, p = {}) => { const mid = ++id; ws.send(JSON.stringify({ id: mid, method: m, params: p })); return new Promise((res, rej) => pending.set(mid, { res, rej })); };

async function connect() {
  for (let i = 0; i < 80; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/list`); const l = await r.json();
      const pg = l.find(t => t.type === "page"); if (pg?.webSocketDebuggerUrl) return pg.webSocketDebuggerUrl; } catch {}
    await sleep(250);
  }
  throw new Error("chrome 未就绪");
}
ws = new WebSocket(await connect());
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data.toString());
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Runtime.exceptionThrown") {
    const d = m.params.exceptionDetails;
    problems.push("EXCEPTION " + d.text + " " + (d.exception?.description || "").split("\n")[0]);
  }
  if (m.method === "Runtime.consoleAPICalled" && (m.params.type === "error" || m.params.type === "warning")) {
    problems.push("CONSOLE." + m.params.type.toUpperCase() + " " + m.params.args.map(a => a.value ?? a.description ?? "").join(" ").slice(0, 200));
  }
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error") {
    problems.push("LOG.ERROR " + m.params.entry.text + " " + (m.params.entry.url || ""));
  }
};

await send("Runtime.enable"); await send("Log.enable"); await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1680, height: 1000, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: URL_ });
await sleep(3000);

async function ev(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) return "EVAL_ERR: " + r.exceptionDetails.text;
  return r.result?.value;
}

async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.data, "base64"));
}

const CHECK = `(() => {
  const lum = c => { const m = String(c).match(/[\\d.]+/g); if (!m) return null;
    const [r,g,b] = m.slice(0,3).map(Number).map(v => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); });
    return 0.2126*r + 0.7152*g + 0.0722*b; };
  const bgOf = n => { let e = n; while (e && e !== document.documentElement) {
    const c = getComputedStyle(e).backgroundColor; const m = String(c).match(/[\\d.]+/g);
    if (m && (m.length < 4 || Number(m[3]) > 0.55)) return c; e = e.parentElement; } return 'rgb(14,15,17)'; };
  const ratio = (a,b) => { const l1 = lum(a), l2 = lum(b); if (l1==null||l2==null) return null;
    return Math.round(((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05))*100)/100; };

  const out = { clipped: [], lowContrast: [], overlap: [], tiny: [], vScroll: 0, hScroll: 0 };
  const page = document.querySelector('.page:not(.hidden)') || document.body;
  out.hScroll = document.documentElement.scrollWidth - document.documentElement.clientWidth;

  page.querySelectorAll('*').forEach(n => {
    const cs = getComputedStyle(n);
    if (n.children.length === 0) {
      const t = (n.textContent || '').trim();
      if (t.length >= 2 && cs.overflow !== 'visible') {
        if (n.scrollWidth > n.clientWidth + 1 && cs.textOverflow !== 'ellipsis' && cs.whiteSpace !== 'nowrap')
          out.clipped.push({ cls: (n.className||'').toString().slice(0,26), t: t.slice(0,18) });
      }
      if (t && cs.overflow !== 'visible') {
        const fs = parseFloat(cs.fontSize);
        const large = fs >= 18.66 || (fs >= 14 && (+cs.fontWeight || 400) >= 700);
        const need = large ? 3 : 4.5;
        const r = ratio(cs.color, bgOf(n));
        if (r != null && r < need) out.lowContrast.push({ cls: (n.className||'').toString().slice(0,22), t: t.slice(0,16), fs, r, need });
      }
      const fs2 = parseFloat(cs.fontSize);
      if (t && fs2 && fs2 < 10.5) out.tiny.push({ cls: (n.className||'').toString().slice(0,20), fs: fs2, t: t.slice(0,14) });
    }
  });

  // 兄弟块重叠(只查面板级,避免误报嵌套)
  const blocks = Array.from(page.querySelectorAll(':scope > .panel, :scope > .cards > .card, :scope > .dash-grid > .panel, :scope > .logs-layout > .panel, .flow > .flow-node, .stages > .stage'));
  for (let i = 0; i < blocks.length; i++) for (let j = i+1; j < blocks.length; j++) {
    const a = blocks[i].getBoundingClientRect(), b = blocks[j].getBoundingClientRect();
    if (!a.width || !b.width) continue;
    if (blocks[i].contains(blocks[j]) || blocks[j].contains(blocks[i])) continue;
    const ox = Math.min(a.right,b.right) - Math.max(a.left,b.left);
    const oy = Math.min(a.bottom,b.bottom) - Math.max(a.top,b.top);
    if (ox > 3 && oy > 3) out.overlap.push({ a: (blocks[i].className||'').slice(0,18), b: (blocks[j].className||'').slice(0,18), ox: Math.round(ox), oy: Math.round(oy) });
  }
  out.items = page.querySelectorAll('*').length;
  return JSON.stringify(out);
})()`;

const PAGES = ["dashboard", "flow", "schedule", "vision", "logs", "settings"];
const NAMES = { dashboard: "概览", flow: "流程", schedule: "场次表", vision: "识别", logs: "运行日志", settings: "设置" };

for (const key of PAGES) {
  await ev(`window.APP.switchTab('${key}')`);
  await sleep(900);
  const raw = await ev(CHECK);
  let data = {};
  try { data = JSON.parse(raw); } catch { problems.push(`CHECK 解析失败 ${key}: ${raw}`); }
  const flags = [];
  for (const k of ["clipped", "lowContrast", "overlap", "tiny"]) {
    if (data[k] && data[k].length) flags.push(`${k}=${JSON.stringify(data[k].slice(0, 3))}`);
  }
  if (data.hScroll > 1) flags.push(`横向溢出 ${data.hScroll}px`);
  console.log(`${key.padEnd(10)} ${NAMES[key].padEnd(6)} 元素 ${String(data.items || 0).padStart(5)}  ${flags.length ? flags.join("  ") : "OK"}`);
  await shot(key);
}

console.log(problems.length ? "\n---- 控制台问题 ----\n" + problems.join("\n") : "\n控制台: 无 error / warning");
ws.close(); child.kill();
try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}
