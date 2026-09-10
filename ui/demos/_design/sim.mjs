/* 用 SSE 事件模拟一次完整执行,验证 UI 在状态流转下的表现(零副作用,不碰真实客户端) */
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const URL_ = process.argv[2] || "http://127.0.0.1:8791/";
const OUT = process.argv[3] || "out/panel";
const PORT = 9800 + Math.floor(Math.random() * 150);
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PROFILE = `C:/Users/${process.env.USERNAME}/AppData/Local/Temp/sim-${PORT}`;
mkdirSync(OUT, { recursive: true });

const child = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--window-size=1680,1000", "about:blank"], { stdio: "ignore" });
let ws, id = 0; const pending = new Map(); const problems = [];
const send = (m, p = {}) => { const mid = ++id; ws.send(JSON.stringify({ id: mid, method: m, params: p })); return new Promise((res, rej) => pending.set(mid, { res, rej })); };
async function connect() {
  for (let i = 0; i < 80; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/list`); const l = await r.json();
      const pg = l.find(t => t.type === "page"); if (pg?.webSocketDebuggerUrl) return pg.webSocketDebuggerUrl; } catch {}
    await sleep(250);
  }
  throw new Error("no chrome");
}
ws = new WebSocket(await connect());
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
ws.onmessage = (ev) => { const m = JSON.parse(ev.data.toString());
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Runtime.exceptionThrown") problems.push("EXCEPTION " + m.params.exceptionDetails.text);
  if (m.method === "Runtime.consoleAPICalled" && ["error","warning"].includes(m.params.type))
    problems.push("CONSOLE." + m.params.type.toUpperCase() + " " + m.params.args.map(a => a.value ?? a.description ?? "").join(" ").slice(0,180));
};
await send("Runtime.enable"); await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1680, height: 1000, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: URL_ });
await sleep(3200);
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); return r.exceptionDetails ? "ERR " + r.exceptionDetails.text : r.result?.value; };
const shot = async (n) => { const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(`${OUT}/${n}.png`, Buffer.from(r.data, "base64")); };

const fire = (type, payload) => `window.__zcodeEvent(${JSON.stringify(type)}, ${JSON.stringify(payload)})`;

// 切回概览,播放一次完整执行
await ev(`window.APP.switchTab('dashboard')`);
await sleep(500);
await ev(fire("exec_start", { session_id: "20260910-1402", trigger: "manual" }));
await sleep(400);
await shot("sim-01-start");
console.log("exec_start →", await ev(`document.getElementById('statusText').textContent`));

const STEPS = ["打开客户端", "识别按钮", "点击领取", "校验结果", "收尾"];
for (let i = 0; i < STEPS.length; i++) {
  await ev(fire("step_update", { step: STEPS[i], status: "ok", detail: "示例细节 " + (i + 1), attempt: 1 }));
  await sleep(220);
}
await ev(fire("attempt_update", { attempt: 1, status: "fail", message: "未命中成功词", images: [] }));
await sleep(300);
await shot("sim-02-fail");
console.log("第1次失败后 →", await ev(`document.getElementById('liveMsg').textContent`));

await ev(fire("attempt_update", { attempt: 2, status: "running", message: "重开客户端", images: [] }));
await sleep(300);
console.log("第2次尝试 →", await ev(`document.getElementById('liveAttempt').textContent`));

for (const s of STEPS) { await ev(fire("step_update", { step: s, status: "ok", attempt: 2 })); await sleep(160); }
await ev(fire("session_end", { status: "success", summary: "第 2 次重试后领取成功", slot: "16:00" }));
await sleep(700);
await shot("sim-03-success");
console.log("成功后状态 →", await ev(`document.getElementById('statusText').textContent`), "| 轨道标记:", await ev(`document.querySelectorAll('.dt-mark').length`));

// 失败需人工
await ev(fire("session_end", { status: "need_manual", summary: "识别到登录页", slot: "16:00" }));
await sleep(600);
await shot("sim-04-manual");
console.log("需人工 →", await ev(`document.getElementById('statusText').textContent`), "| 横幅:", await ev(`!document.getElementById('banner').classList.contains('hidden')`));

// 流程页看高亮
await ev(`window.APP.switchTab('flow')`);
await sleep(600);
await shot("sim-05-flow");
console.log("流程页阶段:", await ev(`document.getElementById('flowPhase').textContent`));

console.log(problems.length ? "\n控制台问题:\n" + problems.join("\n") : "\n控制台: 无 error / warning");
ws.close(); child.kill();
try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}
