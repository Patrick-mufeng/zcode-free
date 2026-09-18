/* 生成 README 用的六页截图(带脱敏)。
   用法: node readme-shots.mjs http://127.0.0.1:8760/ [outDir] [--mask=a,b,c]

   脱敏三处:
   1) 设置页 Webhook 输入框 —— 显示真实机器人地址(含 token,拿到就能往群里发消息),换成占位文本。
   2) 会话详情里的截图缩略图 —— 会带出客户端里的项目列表与账号,统一模糊。
   3) 模型 notes 里的账号名 —— 如 "左下角仅有用户头像 xxx 与设置图标"。
      名单不写死在本文件里(否则脱敏清单本身就成了泄露源),默认从本地
      data/shots/<会话>/session.json 自动提取(data/ 不入版本库),也可用 --mask= 手动指定。 */
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const argv = process.argv.slice(2);
const flag = (name) => {
  const hit = argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : null;
};
const positional = argv.filter((a) => !a.startsWith("--"));
const URL_ = positional[0] || "http://127.0.0.1:8760/";
const OUT = positional[1] || "out/readme";

/* 从本地会话记录里提炼"疑似账号名":形如 字母+数字 的短标识(如 abc12345)。
   只在本机读取,提取结果不落盘到版本库。 */
function detectNames() {
  const manual = flag("mask");
  if (manual) return manual.split(",").map((s) => s.trim()).filter(Boolean);

  const names = new Set();
  const roots = ["data/shots", "../../../data/shots", "D:/工作数据/zcode-free/data/shots"];
  const dir = roots.find((d) => existsSync(d));
  if (!dir) return [];

  for (const child of readdirSync(dir)) {
    const f = `${dir}/${child}/session.json`;
    if (!existsSync(f)) continue;
    let text;
    try { text = readFileSync(f, "utf8"); } catch { continue; }
    // 会话记录里的时间戳、文件名同样符合"字母+数字",用更严的模式收敛到正文里的短标识
    for (const m of text.matchAll(/(?<![A-Za-z0-9_-])([a-z]{3,8}\d{1,4})(?![A-Za-z0-9_.-])/g)) {
      if (!/^(attempt|session|json|png)/.test(m[1])) names.add(m[1]);
    }
  }
  return [...names];
}

const NAMES = detectNames();
console.log(NAMES.length ? `脱敏名单(${NAMES.length} 个,来自本地会话记录):` + NAMES.join(", ")
                         : "脱敏名单为空(未找到本地会话记录,可加 --mask=名字 手动指定)");

const PORT = 9700 + Math.floor(Math.random() * 200);
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PROFILE = `C:\\Users\\${process.env.USERNAME}\\AppData\\Local\\Temp\\rs-${PORT}`;
mkdirSync(OUT, { recursive: true });

// 视口与 README 里既有的截图保持一致(1920x919);用 2x 采样再缩回去,边缘更干净
const VIEW_W = 1920;
const VIEW_H = 919;

const child = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
  "--force-device-scale-factor=1", `--window-size=${VIEW_W},${VIEW_H}`, "about:blank"], { stdio: "ignore" });

let ws, id = 0; const pending = new Map();
const send = (m, p = {}) => { const mid = ++id; ws.send(JSON.stringify({ id: mid, method: m, params: p })); return new Promise((res, rej) => pending.set(mid, { res, rej })); };

async function connect() {
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const pg = (await r.json()).find((t) => t.type === "page");
      if (pg?.webSocketDebuggerUrl) return pg.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error("chrome 未就绪");
}

ws = new WebSocket(await connect());
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) {
    const { res, rej } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? rej(new Error(m.error.message)) : res(m.result);
  }
};

const evaluate = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error("eval 失败:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  return r.result.value;
};

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: VIEW_W, height: VIEW_H, deviceScaleFactor: 1, mobile: false });

const errors = [];
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text);
});

async function goto(url) {
  await send("Page.navigate", { url });
  for (let i = 0; i < 60; i++) { await sleep(250); if (await evaluate("document.readyState === 'complete'")) break; }
  await sleep(1600);
}

async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  const { writeFileSync } = await import("node:fs");
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.data, "base64"));
  console.log("shot →", `${OUT}/${name}.png`);
}

async function page(tab) {
  const ok = await evaluate(`(()=>{const n=document.querySelector('[data-page=${tab}]');if(!n)return 'NOT FOUND';n.click();return 'ok';})()`);
  if (ok !== "ok") throw new Error(`切页失败:${tab}`);
  await sleep(1500);
}

// 脱敏:会话详情里的截图缩略图会带出客户端里的项目列表与账号(实测可辨认出多个仓库名),
// 统一模糊掉。截图回放功能本身仍然可辨,只是内容不可读。
const MASK_THUMBS = `(()=>{
  const st = document.getElementById('__mask_style') || document.createElement('style');
  st.id = '__mask_style';
  st.textContent = '.thumbs img{filter:blur(7px);}';
  document.head.appendChild(st);
  return document.querySelectorAll('.thumbs img').length;
})()`;

// 脱敏:把 webhook 输入框的真实值换成占位文本(只改显示,不动配置)
const MASK_WEBHOOK = `(()=>{
  const el = document.getElementById('sWebhook');
  if (!el) return 'NOT FOUND';
  const real = el.value || '';
  el.value = real ? 'https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' : '';
  el.setAttribute('data-masked', real ? 'yes' : 'no');
  return el.value;
})()`;

// 脱敏:会话详情里的模型 notes 会带上客户端里的账号名(如 "左下角仅有用户头像 xxx 与设置图标"),
// 这些名字会随截图一起公开,逐页替换成占位符。名单见文件头的 detectNames()。
const MASK_NAMES = `(()=>{
  const names = ${JSON.stringify(NAMES)};
  if (!names.length) return 'skipped';
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let hit = 0, node;
  while ((node = walk.nextNode())) {
    let t = node.nodeValue;
    for (const n of names) {
      if (t.includes(n)) { t = t.split(n).join('user***'); hit++; }
    }
    if (t !== node.nodeValue) node.nodeValue = t;
  }
  return 'masked ' + hit;
})()`;

try {
  await goto(`${URL_}?motion=0`);
  console.log("脱敏(概览):", await evaluate(MASK_NAMES));
  await page("dashboard"); await shot("01-dashboard");
  await page("flow");      await shot("02-flow");
  await page("schedule");  await shot("03-schedule");
  await page("vision");    await shot("04-vision");
  await page("logs");
  // 挑一条"有截图留档"的记录来展示回放功能(最新的可能是不带截图的跳过记录)
  await evaluate(`(async()=>{
    const r = await window.API.call('list_sessions',{limit:30});
    const items = (r && r.items) || [];
    for (const it of items) {
      const d = await window.API.call('get_session_detail',{id:it.id});
      const s = d && d.session;
      const has = s && (s.attempts||[]).some(a => Object.keys(a.images||{}).length);
      if (has) { await PAGES.logs.open(it.id); return 'picked ' + it.id; }
    }
    if (items[0]) { await PAGES.logs.open(items[0].id); return 'fallback ' + items[0].id; }
    return 'none';
  })()`);
  await sleep(2500);
  console.log("脱敏(日志):", await evaluate(MASK_NAMES));
  console.log("脱敏(缩略图):", await evaluate(MASK_THUMBS), "张");
  await sleep(400);
  await shot("05-logs");
  await page("settings");
  console.log("脱敏(webhook):", await evaluate(MASK_WEBHOOK));
  console.log("脱敏(设置):", await evaluate(MASK_NAMES));
  await shot("06-settings");
  console.log(errors.length ? "控制台异常:" + JSON.stringify(errors) : "控制台: 无 error");
} finally {
  ws.close();
  child.kill();
  await sleep(400);
  try { rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
