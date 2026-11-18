// node tests_restart_page.js firmware/  - the page side of running short of memory (v1.3.1): an install the Pico has
// to restart for says so and follows it through to the end (new version, or why not), and the Restart button.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'ui.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const M='aa:bb:cc:00:00:01';
const base=()=>({tanks:[{mac:M,name:'Tank 1',level:700,litres:611,percent:46,age:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}],
 found:[],primary:M,update:{version:'1.3.0',boot:7},pin_set:true,ssid:'x',ip:'192.0.2.5'});
/* route(u,o) -> {status, body} | 'down' (the Pico not answering) | null (the default answer) */
const F={};
function open(route){F.RST=F.INST=0;const posts=[];const w=new JSDOM(html,{url:'http://pico/#cfg',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 const st=w.setTimeout.bind(w);w.setTimeout=(f,ms)=>st(f,Math.min(ms||0,3000)/100);w.setInterval=()=>0;  /* (the page's waits, 100x faster) */
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.alert=()=>0;w.confirm=()=>true;
 w.fetch=async(u,o)=>{if(o&&o.method==='POST')posts.push(u);const r=route(u,o);if(r==='down')throw new TypeError('Failed to fetch');if(r==='hang')return new Promise(()=>{});
  const res=r||{status:200,body:u.startsWith('/api/state')?base():{}};
  return {ok:res.status<300,status:res.status,json:async()=>res.body,text:async()=>JSON.stringify(res.body),clone(){return this},arrayBuffer:async()=>new ArrayBuffer(0)}}}}).window;
 w.posts=posts;return w}
const txt=(w,id)=>w.document.getElementById(id).textContent;
const until=async(f,ms=4000)=>{for(let t=0;t<ms;t+=20){if(f())return true;await wait(20)}return false};
(async()=>{
 /* 1. install short of memory: restarts, then the install after the start fails: says why */
 {let polls=0;const failed=Object.assign(base(),{update:{version:'1.3.0',last:{ok:false,from:'1.3.0',to:'1.3.1',id:'9-7200',stage:'install',reason:'not enough memory even after restarting'}}});
  const w=open(u=>{if(u==='/api/update/install')return {status:202,body:{restart:true,id:'9-7200'}};
   if(u.startsWith('/api/state')&&F.INST){polls++;return polls<4?'down':{status:200,body:failed}}return null});
  await wait(300);w.eval('UPD={newer:true,latest:"1.3.1"}');F.INST=1;const p=w.installUpd();await wait(30);
  ok(/short of memory/.test(txt(w,'updBox'))&&/restarting/.test(txt(w,'updBox')),'says it is restarting to make room: "'+txt(w,'updBox')+'"');
  await p;ok(/^Update failed, nothing was changed: not enough memory/.test(txt(w,'updBox')),'then why it could not install: "'+txt(w,'updBox')+'"');
  ok(/could not be installed: not enough memory/.test(txt(w,'ver2')),'the version line says so too: "'+txt(w,'ver2')+'"');
  ok(!w.document.getElementById('updBtn').disabled,'the button works again')}
 /* 2. an old failure of an earlier try is not taken for this one: it waits for the new version */
 {let polls=0;const old=Object.assign(base(),{update:{version:'1.3.0',last:{ok:false,to:'1.3.1',id:'3-100',stage:'install',reason:'old'}}});
  const done=Object.assign(base(),{update:{version:'1.3.1'}});
  const w=open(u=>{if(u==='/api/update/install')return {status:202,body:{restart:true,id:'9-7200'}};
   if(u.startsWith('/api/state')&&F.INST){polls++;return polls<3?{status:200,body:old}:{status:200,body:done}}return null});
  await wait(300);w.eval('UPD={newer:true,latest:"1.3.1"}');F.INST=1;await w.installUpd();
  ok(/Now running version 1.3.1/.test(txt(w,'updBox')),'an older try\'s failure is ignored; ends on the new version: "'+txt(w,'updBox')+'"')}
 /* 3. an ordinary install still reads as before */
 {const w=open(u=>{if(u==='/api/update/install')return {status:200,body:'1.3.1'};if(u.startsWith('/api/state')&&F.INST)return {status:200,body:Object.assign(base(),{update:{version:'1.3.1'}})};return null});
  await wait(300);w.eval('UPD={newer:true,latest:"1.3.1"}');F.INST=1;const p=w.installUpd();await wait(30);
  ok(txt(w,'updBox')==='Installed. Restarting…','ordinary install: "Installed. Restarting…"');await p}
 /* 4. the Restart button */
 {let polls=0;const w=open(u=>{if(u.startsWith('/api/state')&&F.RST){polls++;return polls<2?{status:200,body:base()}:polls<4?'down':{status:200,body:Object.assign(base(),{update:{version:'1.3.0',boot:8}})}}return null});
  await wait(300);ok(!!w.document.getElementById('rstBtn')&&/Saves the latest readings/.test(txt(w,'rstM')),'a Restart button in Settings, saying what it does');
  await until(()=>w.eval('S&&S.update&&S.update.boot')===7);F.RST=1;const p=w.restartPico();await wait(30);
  ok(w.posts.includes('/api/restart')&&txt(w,'rstM')==='Restarting…'&&w.document.getElementById('rstBtn').disabled,'asks the Pico to restart, says so');
  await p;ok(txt(w,'rstM')==='Restarted and running again.'&&!w.document.getElementById('rstBtn').disabled&&polls>=4,'the old start still answering is not "back"; says so once it has restarted: "'+txt(w,'rstM')+'" after '+polls+' polls')}
 {const w=open(u=>u==='/api/restart'?'hang':null);await wait(300);await w.restartPico();
  ok(txt(w,'rstM')==='It has not restarted yet: refresh this page in a minute.','a restart request that never answers and a Pico that never restarts: says so, never "restarted"')}
 {let polls=0;const w=open(u=>{if(u==='/api/update/install')return 'hang';if(u.startsWith('/api/state')&&F.INST){polls++;return {status:200,body:Object.assign(base(),{update:{version:'1.3.1',boot:8}})}}return null});
  await wait(300);w.eval('UPD={newer:true,latest:"1.3.1"}');F.INST=1;await w.installUpd();
  ok(/Now running version 1.3.1/.test(txt(w,'updBox')),'an install request that never answers is followed through like a restart: "'+txt(w,'updBox')+'"')}
 {const w=open(u=>u==='/api/restart'?{status:401,body:{auth:'login'}}:null);await wait(300);w.restartPico();
  ok(await until(()=>w.document.getElementById('pdlg').open),'not signed in: asks for the PIN first');
  ok(!w.posts.slice(1).includes('/api/restart')&&txt(w,'rstM')!=='Restarting…','...and has not restarted it')}
 /* 4b. a poll that never answers (the Pico went mid-request) doesn't stall it */
 {let polls=0;const w=open(u=>{if(u.startsWith('/api/state')&&F.RST){polls++;return polls===1?{status:200,body:base()}:polls===2?'hang':{status:200,body:Object.assign(base(),{update:{version:'1.3.0',boot:8}})}}return null});
  await until(()=>w.eval('S&&S.update&&S.update.boot')===7);F.RST=1;const p=w.restartPico();ok(await until(()=>/Restarted and running/.test(txt(w,'rstM'))),'a hung poll is given up on, then it carries on: "'+txt(w,'rstM')+'"');await p}
 /* 4c. no answer for the "before" check: nothing is restarted, and it says so */
 {const w=open(u=>u.startsWith('/api/state')&&F.RST?'down':null);await until(()=>w.eval('S&&S.update&&S.update.boot')===7);F.RST=1;await w.restartPico();
  ok(!w.posts.includes('/api/restart')&&/Cannot reach the Pico/.test(txt(w,'rstM')),'Pico not answering first: no restart sent, says so: "'+txt(w,'rstM')+'"')}
 /* 5. after restarting by itself */
 {const w=open(u=>u.startsWith('/api/state')?{status:200,body:Object.assign(base(),{update:{version:'1.3.0',why:'memory',last:{ok:true,from:'1.2.53',to:'1.3.0'}}})}:null);
  await until(()=>/memory/.test(txt(w,'ver2')));ok(txt(w,'ver2')==='Restarted by itself to free up memory.','says it restarted by itself: "'+txt(w,'ver2')+'"')}
 process.exit(fails?1:0)})();
