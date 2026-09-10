/* 零依赖 CDP 驱动:headless Chrome 打开页面、跑交互、抓控制台报错、截图。
   用法:
     node cdp.mjs --url=file:///D:/x.html --out=out/name \
       --steps='[{"wait":1200},{"shot":"idle"},{"eval":"ZKit.simulate()"},{"wait":4000},{"shot":"run"},{"click":"[data-page=logs]"},{"wait":800},{"shot":"logs"}]'
   步骤类型:wait(ms) / shot(名字) / eval(js) / click(选择器) / size(WxH)
*/
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const args = Object.fromEntries(process.argv.slice(2).map(a => {
  const i = a.indexOf("="); return i < 0 ? [a.replace(/^--/, ""), true] : [a.slice(2, i), a.slice(i + 1)];
}));
const URL_ = args.url;
const OUT = args.out || "out/shot";
const PORT = +(args.port || 9333);
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PROFILE = `C:\\Users\\${process.env.USERNAME}\\AppData\\Local\\Temp\\cdpprof-${PORT}`;

let steps;
if (args.stepsfile) {
  const { readFileSync } = await import("node:fs");
  steps = JSON.parse(readFileSync(args.stepsfile, "utf8"));
} else {
  steps = args.steps ? JSON.parse(args.steps) : [{ wait: 1500 }, { shot: "default" }];
}
const size = (args.size || "1440,900").split(",").map(Number);

if (!URL_) { console.error("need --url"); process.exit(2); }
mkdirSync(OUT, { recursive: true });

const child = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu",
  "--hide-scrollbars", "--force-device-scale-factor=1",
  `--window-size=${size[0]},${size[1]}`, "about:blank"
], { stdio: "ignore" });

let ws, id = 0;
const pending = new Map();
const logs = [];

function send(method, params = {}) {
  const mid = ++id;
  ws.send(JSON.stringify({ id: mid, method, params }));
  return new Promise((res, rej) => pending.set(mid, { res, rej }));
}

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find(t => t.type === "page");
      if (page && page.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error("chrome 未就绪");
}

const wsUrl = await connect();
ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = e => rej(new Error("ws error")); });
ws.onmessage = ev => {
  const m = JSON.parse(ev.data.toString());
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id); pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    return;
  }
  if (m.method === "Runtime.consoleAPICalled") {
    const lvl = m.params.type;
    const txt = m.params.args.map(a => a.value ?? a.description ?? a.type).join(" ");
    if (lvl === "error" || lvl === "warning") logs.push(`[console.${lvl}] ${txt}`);
  }
  if (m.method === "Runtime.exceptionThrown") {
    const d = m.params.exceptionDetails;
    logs.push(`[exception] ${d.text} ${d.exception?.description || ""}`.trim());
  }
  if (m.method === "Log.entryAdded") {
    const e = m.params.entry;
    if (e.level === "error") logs.push(`[log.${e.level}] ${e.text} ${e.url || ""}`);
  }
};

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: size[0], height: size[1], deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: URL_ });
await sleep(1200);

async function evaluate(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error("eval 失败: " + r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description || ""));
  return r.result?.value;
}

for (const s of steps) {
  if (s.size) {
    const [w, h] = s.size.split("x").map(Number);
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(400);
  }
  if (s.wait) await sleep(s.wait);
  if (s.eval) { const v = await evaluate(s.eval); if (v !== undefined && v !== null) console.log("eval →", JSON.stringify(v)); }
  if (s.click) {
    const ok = await evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(s.click)});if(!n)return 'NOT FOUND';n.click();return 'ok';})()`);
    if (ok !== "ok") logs.push(`[step] click ${s.click} → ${ok}`);
  }
  if (s.shot) {
    const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const p = `${OUT}/${s.shot}.png`;
    writeFileSync(p, Buffer.from(r.data, "base64"));
    console.log("shot →", p);
  }
}

const probe = await evaluate(`JSON.stringify({
  title: document.title,
  status: document.documentElement.getAttribute('data-status'),
  page: document.documentElement.getAttribute('data-page-idx'),
  countdown: document.querySelector('#countdown')?.textContent,
  logs: document.querySelectorAll('#liveLog .logline').length,
  stepsDone: document.querySelectorAll('.step.is-done,.step.is-fail').length,
  demobar: !!document.querySelector('.demobar'),
  gsap: !!window.gsap,
  scrollW: document.documentElement.scrollWidth,
  innerW: window.innerWidth
})`);
console.log("probe →", probe);
console.log(logs.length ? "---- 控制台问题 ----\n" + logs.join("\n") : "控制台: 无 error / warning");

ws.close();
child.kill();
try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}
process.exit(logs.some(l => l.startsWith("[exception]") || l.startsWith("[log.error")) ? 1 : 0);
