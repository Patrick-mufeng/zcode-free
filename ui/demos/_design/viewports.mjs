/* 多档视口 × 六页:检查横向溢出与控制台报错 */
import { spawn } from "node:child_process";
import { rmSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
const URL_=process.argv[2];
const SIZES=[[1920,1080],[1680,1000],[1440,900],[1280,800],[1100,820],[900,900],[760,900]];
const PORT=9450+Math.floor(Math.random()*100);
const CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe";
const PROFILE="C:/Users/"+process.env.USERNAME+"/AppData/Local/Temp/vp-"+PORT;
const child=spawn(CHROME,["--headless=new","--remote-debugging-port="+PORT,"--user-data-dir="+PROFILE,
 "--no-first-run","--disable-gpu","--hide-scrollbars","about:blank"],{stdio:"ignore"});
let ws,id=0;const pending=new Map();const probs=[];
const send=(m,p={})=>{const mid=++id;ws.send(JSON.stringify({id:mid,method:m,params:p}));return new Promise((res,rej)=>pending.set(mid,{res,rej}));};
async function connect(){for(let i=0;i<80;i++){try{const r=await fetch("http://127.0.0.1:"+PORT+"/json/list");const l=await r.json();const pg=l.find(t=>t.type==="page");if(pg&&pg.webSocketDebuggerUrl)return pg.webSocketDebuggerUrl;}catch{}await sleep(250);}throw new Error("no chrome");}
ws=new WebSocket(await connect());
await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
ws.onmessage=e=>{const m=JSON.parse(e.data.toString());
  if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.rej(new Error(JSON.stringify(m.error))):p.res(m.result);return;}
  if(m.method==="Runtime.exceptionThrown")probs.push("EXC "+m.params.exceptionDetails.text);
  if(m.method==="Runtime.consoleAPICalled"&&["error","warning"].includes(m.params.type))
    probs.push(m.params.type.toUpperCase()+" "+m.params.args.map(a=>a.value??"").join(" ").slice(0,120));};
await send("Runtime.enable");await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride",{width:1680,height:1000,deviceScaleFactor:1,mobile:false});
await send("Page.navigate",{url:URL_});await sleep(3000);
const ev=async e=>{const r=await send("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true});return r.exceptionDetails?"ERR":r.result?.value;};
const PAGES=["dashboard","flow","schedule","vision","logs","settings"];
for(const [w,h] of SIZES){
  await send("Emulation.setDeviceMetricsOverride",{width:w,height:h,deviceScaleFactor:1,mobile:false});
  await sleep(500);
  const bad=[];
  for(const k of PAGES){
    await ev("window.APP.switchTab('"+k+"')");await sleep(420);
    const r=await ev(`(()=>{const d=document.documentElement;
      return JSON.stringify({h:d.scrollWidth-d.clientWidth,
        page:document.querySelector('.page:not(.hidden)').id});})()`);
    const o=JSON.parse(r);
    if(o.h>1) bad.push(o.page+" 横溢"+o.h+"px");
  }
  console.log(`${w}x${h}`.padEnd(10), bad.length? bad.join("  ") : "全部页面无横向溢出");
}
console.log(probs.length?"\n控制台问题:\n"+probs.join("\n"):"\n控制台: 无 error / warning");
ws.close();child.kill();try{rmSync(PROFILE,{recursive:true,force:true});}catch{}
