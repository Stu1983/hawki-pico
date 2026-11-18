// node tests_fitcap.js firmware/  - the tank-capacity fit (several ~2 s curve requests to the Pico) only runs when
// the Deliveries page is open, and isn't redone for the same tank, settings and deliveries.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'hist.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const NOW=Date.UTC(2026,10,16,11)/1000,H=3600,DAY=86400,M='aa:bb:cc:00:00:01';
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))},mmOf=L=>Math.round(1300*(1-L/1323));
const recs=[];let L=400,fillT=null;for(let t=NOW-60*DAY;t<NOW;t+=H){L-=8/24;if(!fillT&&t>NOW-30*DAY){L+=600;fillT=t}recs.push([t,mmOf(L)])}
const b=Buffer.alloc(recs.length*6);recs.forEach(([t,mm],i)=>{b.writeUInt32LE(t,i*6);b.writeUInt16LE(mm,i*6+4)});
const state={tanks:[{mac:M,name:'Tank 1',level:mmOf(L),litres:L,percent:30,age:60,cfg:{capacity_l:1323,tank_l:1323,reserve_l:200,height_cm:130}}],found:[],primary:M};
const deliv={[M]:[{t:fillT,litres:610,total:null,ppl:null,supplier:'',note:''}]};
function open(hash){const curves=[];const w=new JSDOM(html,{url:'http://pico/history'+hash,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>NOW*1000;
 w.fetch=async u=>{if(/tank_l=/.test(u))curves.push(u);return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:u.startsWith('/api/deliveries')?deliv:{},
  arrayBuffer:async()=>u.startsWith('/api/hist')?b.buffer.slice(b.byteOffset,b.byteOffset+b.length):new ArrayBuffer(0)}}}}).window;return {w,curves}}
(async()=>{
 {const p=open('');p.w.localStorage.hawkiPage='use';await wait(800);
  ok(p.curves.length===0,'history opened on Usage: no capacity-fit requests ('+p.curves.length+')');
  p.w.page('del');await wait(800);const n=p.curves.length;
  ok(n>0&&/capacity|fits/.test(p.w.document.getElementById('fit').textContent),'opening Deliveries runs it: '+n+' requests, "'+p.w.document.getElementById('fit').textContent.slice(0,60)+'"');
  p.w.renderDeliveries();await wait(500);ok(p.curves.length===n,'shown again (e.g. after saving a delivery): no new requests ('+(p.curves.length-n)+')');
  p.w.page('use');p.w.page('del');await wait(300);ok(p.curves.length===n,'switching pages back and forth: none either')}
 /* a fit cut short by a failed request isn't kept: the next showing tries again */
 {const p=open('#deliveries');let n=0;const real=p.w.fetch;p.w.fetch=async u=>{if(/tank_l=/.test(u)&&++n===3)throw new TypeError('Failed to fetch');return real(u)};
  await wait(800);const a=p.curves.length;p.w.fetch=real;p.w.renderDeliveries();await wait(800);
  ok(p.curves.length>a,'after a failed request the next showing fits again ('+(p.curves.length-a)+' more requests)')}
 process.exit(fails?1:0)})();
