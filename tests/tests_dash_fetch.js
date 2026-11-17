// node tests_dash_fetch.js ui.html  - the dashboard's history download: one at a time, and a failure says so.
// (Each /api/hist is the whole history file from a slow Pico on weak Wi-Fi; the page refreshes every 10 s.)
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const common=fs.readFileSync(path.join(path.dirname(process.argv[2]),'common.js.html'),'utf8');
const html=fs.readFileSync(process.argv[2],'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const NOW=Date.UTC(2026,10,16,11)/1000,H=3600;
const n=30*24,b=Buffer.alloc(n*6);for(let i=0;i<n;i++){b.writeUInt32LE(NOW-(n-i)*H,i*6);b.writeUInt16LE(600+Math.floor(i/10),i*6+4)}
const HB=b.buffer.slice(b.byteOffset,b.byteOffset+b.length);
const M='aa:bb:cc:00:00:01';
const state={tanks:[{mac:M,name:'Tank 1',level:672,litres:640,percent:48,age:60,battery:60,unusable:[100,'estimate'],cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}],
 found:[],primary:M,update:{version:'1.2.53'},ssid:'x',ip:'192.0.2.5'};
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
function page(o){const hits=[];const dom=new JSDOM(html,{url:'http://pico/#dash',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.Date.now=()=>NOW*1000+(o.clock?o.clock[0]:0);w.setInterval=()=>0;  /* polls are driven by hand */
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.fetch=async u=>{if(u.startsWith('/api/hist')||u.startsWith('/api/curve')){hits.push(u);await wait(o.slow||0);if(o.fail&&o.fail())throw new TypeError('Failed to fetch')}
  return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:{},arrayBuffer:async()=>u.startsWith('/api/hist')?HB:new ArrayBuffer(0)}};
 w.alert=m=>console.log('ALERT',m);w.onerror=m=>console.log('ERR',m)}});return {dom,w:dom.window,d:dom.window.document,hits}}
(async()=>{
 /* 1. a slow download is not started again by every refresh */
 {const p=page({slow:900});await wait(100);for(let i=0;i<3;i++){p.w.load();await wait(150)}await wait(1500);
  const h=p.hits.filter(u=>u.startsWith('/api/hist')).length;ok(h===1,'4 refreshes during one slow download: '+h+' history download(s)');
  ok(/day/.test(p.d.getElementById('d_r2').textContent),'then the usage shows: '+p.d.getElementById('d_r2').textContent)}
 /* 2. a failed download says so (not "no readings yet"), and isn't retried on every refresh */
 {const clock=[0];const p=page({fail:()=>true,clock});await wait(400);
  const r2=p.d.getElementById('d_r2').textContent,lv=p.d.getElementById('c_lvl').textContent;
  ok(!/no readings yet/i.test(r2+lv)&&/could not load/i.test(r2+lv),'a failed download says so: "'+r2+'" / "'+lv.slice(0,60)+'"');
  const before=p.hits.length;for(let i=0;i<3;i++){clock[0]+=10000;p.w.load();await wait(100)}
  ok(p.hits.length===before,'not downloaded again on each 10 s refresh after a failure ('+(p.hits.length-before)+' more)');
  clock[0]+=60000;p.w.load();await wait(200);ok(p.hits.length>before,'tried again a minute later')}
 /* 3. a later failure keeps the readings already shown */
 {const clock=[0],bad=[false];const p=page({fail:()=>bad[0],clock});await wait(400);const r0=p.d.getElementById('d_r').textContent;
  bad[0]=true;clock[0]+=601000;p.w.load();await wait(300);const r1=p.d.getElementById('d_r').textContent;
  ok(r0!=='–'&&r1===r0,'a failed 10-minute refresh keeps the usage shown: '+r0+' -> '+r1)}
 /* 4. switching the dashboard's tank while a download is slow: the page ends on the newest choice, never a mix, no errors */
 {const M2='aa:bb:cc:00:00:02',st=JSON.parse(JSON.stringify(state));st.tanks.push({mac:M2,name:'Tank 2',level:1100,litres:200,percent:15,age:60,battery:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}});
  const errs=[];process.on('unhandledRejection',e=>errs.push(String(e)));
  for(const seq of [[M,M2],[M,'all'],['all',M],[M,M2,M]]){const delay={};delay[seq[0]]=900;
   const hits=[];const dom=new JSDOM(html,{url:'http://pico/#dash',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
    w.Date.now=()=>NOW*1000;w.setInterval=()=>0;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
    w.fetch=async u=>{const mac=(u.match(/mac=([^&]+)/)||[])[1];if(u.startsWith('/api/hist')){hits.push(mac);if(hits.length===1)await wait(900)}
     return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?st:u.startsWith('/api/curve')?cv:{},arrayBuffer:async()=>u.startsWith('/api/hist')?(mac===M2?HB.slice(0,6*24):HB):new ArrayBuffer(0)}};
    w.onerror=m=>errs.push(String(m))}});const w=dom.window,d=w.document;
   st.primary=seq[0];await wait(150);for(const p of seq.slice(1)){st.primary=p;w.load();await wait(150)}await wait(1500);
   const want=seq[seq.length-1],name=d.getElementById('d_name').textContent,lit=d.getElementById('d_l').textContent;
   const exp=want==='all'?'Both tanks':want===M?'Tank 1':'Tank 2',expL=want==='all'?'840 L':want===M?'640 L':'200 L';
   ok(name===exp&&lit===expL,seq.map(x=>x===M?'T1':x===M2?'T2':'all').join(' -> ')+': shows '+name+' '+lit+' (want '+exp+' '+expL+')')}
  ok(!errs.length,'no errors while switching: '+errs.slice(0,2).join(' | '))}
 process.exit(fails?1:0)})();
