// node tests_small_pages.js firmware/  - small page fixes (audit item 29b).
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const pg=n=>fs.readFileSync(path.join(dir,n),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const NOW=Date.UTC(2026,10,16,11)/1000,M='aa:bb:cc:00:00:01';
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const state={tanks:[{mac:M,name:'Tank 1',level:700,litres:611,percent:46,age:60,battery:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}],
 found:[{mac:'cc:00:00:00:00:02',name:'B sensor',rssi:-60,age:5,level:900},{mac:'aa:00:00:00:00:01',name:'A sensor',rssi:-80,age:5,level:800}],
 primary:M,update:{version:'1.2.53'},pin_set:true,ssid:'x',ip:'192.0.2.5'};
function open(url,route){return new JSDOM(pg('ui.html'),{url,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>NOW*1000;w.setInterval=()=>0;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.alert=()=>0;
 w.fetch=async(u,o)=>route(u,o)||({ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:{},text:async()=>'{}',clone(){return this},arrayBuffer:async()=>new ArrayBuffer(0)})}}).window}
(async()=>{
 /* the Pico's error message without its JSON quotes */
 {const w=open('http://pico/#cfg',u=>u==='/api/maint'?{ok:false,status:400,text:async()=>'"Could not save: not JSON"',json:async()=>'Could not save: not JSON',clone(){return this}}:null);await wait(300);
  let msg='';try{await w.api('/api/maint',{on:true})}catch(e){msg=e.message}ok(msg==='Could not save: not JSON','error text without quotes: '+msg)}
 /* sensors nearby: a stable order (they swapped rows as their signal changed, so a tap could land on the other one) */
 {const w=open('http://pico/#cfg',()=>null);await wait(300);const t=w.document.getElementById('found').textContent;
  ok(t.indexOf('A sensor')<t.indexOf('B sensor'),'nearby sensors in a fixed order (by address), not by signal')}
 /* Change PIN with a stale session: sign in, then carry on to the new PIN (it used to close as if changed) */
 {let n=0;const w=open('http://pico/#cfg',(u,o)=>{if(u==='/api/pin/set'){n++;return n===1?{ok:false,status:401,json:async()=>({auth:'login'})}:{ok:true,status:200,json:async()=>({session:'s2'})}}
   if(u==='/api/pin/login')return{ok:true,status:200,json:async()=>({session:'s1'})};return null});await wait(300);const d=w.document;
  w.askPin('change');d.getElementById('p1').value='1234';d.getElementById('p2').value='1234';await w.pinSubmit({preventDefault(){}});
  ok(d.getElementById('pT').textContent==='Enter the current PIN'&&d.getElementById('pdlg').open,'stale session: asks for the current PIN');
  d.getElementById('p1').value='0000';await w.pinSubmit({preventDefault(){}});
  ok(d.getElementById('pdlg').open&&d.getElementById('pT').textContent==='Choose a new PIN','signed in: carries on to the new PIN, not closed');
  d.getElementById('p1').value='5678';d.getElementById('p2').value='5678';await w.pinSubmit({preventDefault(){}});
  ok(!d.getElementById('pdlg').open&&n===2,'and the new PIN is set')}
 /* inputs at 16 px: iOS zooms the page on anything smaller */
 {const w=open('http://pico/#cfg',()=>null);await wait(200);ok(/input,select\{[^}]*font-size:16px/.test(w.document.querySelector('style').textContent),'inputs are 16 px')}
 /* no PIN yet: says how to set one (changes are refused without one) */
 {const s0=JSON.parse(JSON.stringify(state));s0.pin_set=false;const w=open('http://pico/#cfg',u=>u.startsWith('/api/state')?{ok:true,status:200,json:async()=>s0}:null);await wait(300);
  const t=w.document.body.textContent;ok(!/Anyone on your Wi-Fi can change/.test(t)&&/No PIN yet/.test(t),'no-PIN wording matches what the Pico does')}
 /* a live reading older than the last saved one isn't appended (out of order it read as a delivery) */
 {const H=3600,n=48,b=Buffer.alloc(n*6);for(let i=0;i<n;i++){b.writeUInt32LE(NOW-(n-i)*H+3300,i*6);b.writeUInt16LE(700,i*6+4)}
  const s1=JSON.parse(JSON.stringify(state));s1.tanks[0].age=1000;s1.tanks[0].level=600;  /* heard 17 min ago (fresh enough to be appended), but before the last saved reading, 5 min ago */
  const w=open('http://pico/#dash',u=>u.startsWith('/api/state')?{ok:true,status:200,json:async()=>s1}:u.startsWith('/api/hist')?{ok:true,status:200,arrayBuffer:async()=>b.buffer.slice(b.byteOffset,b.byteOffset+b.length)}:null);
  let P=null;const real=w.analyse;w.analyse=(p,o)=>{P=p;return real(p,o)};await wait(500);
  ok(P&&P.every((x,i)=>!i||x[0]>P[i-1][0]),'the series stays in time order ('+(P&&P.length)+' points)')}
 process.exit(fails?1:0)})();
