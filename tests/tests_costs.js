// node tests_costs.js firmware/  - the Costs page's "Oil a year": the average a year of what was bought in the last 2 years, as entered (v1.3.23)
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'hist.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const NOW=Date.UTC(2026,10,16,11)/1000,DAY=86400,M='aa:bb:cc:00:00:01';
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const state={tanks:[{mac:M,name:'Tank 1',level:700,litres:611,percent:46,age:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}],found:[],primary:M};
function run(deliv){return new Promise(res=>{const w=new JSDOM(html,{url:'http://pico/history#costs',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>NOW*1000;
 w.fetch=async u=>({ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:u.startsWith('/api/deliveries')?deliv:{},arrayBuffer:async()=>new ArrayBuffer(0)})}}).window;
 setTimeout(()=>{w.costs();res([w.document.getElementById('c_spent').textContent,w.document.getElementById('c_spent2').textContent])},600)})}
(async()=>{
 let [v,n]=await run({[M]:[{t:NOW-40*DAY,litres:1800,total:869}]});
 ok(v==='1,800 L'&&/£869/.test(n)&&/last 12 months/.test(n),'receipts going back under 18 months: the last 12 months, as entered: '+v+' · '+n);
 [v,n]=await run({[M]:[{t:NOW-40*DAY,litres:1800,total:869},{t:NOW-600*DAY,litres:500,total:200}]});
 ok(v==='1,150 L'&&/£535 a year/.test(n)&&/last 2 years/.test(n),'receipts back 600 days: the 2 years halved (1800+500): '+v+' · '+n);
 [v,n]=await run({[M]:[{t:NOW-40*DAY,litres:900,total:430},{t:NOW-300*DAY,litres:500,total:300},{t:NOW-400*DAY,litres:700,total:400},{t:NOW-800*DAY,litres:1000,total:500}]});
 ok(v==='1,050 L'&&/£565/.test(n),'only receipts from the last 2 years count, halved: '+v+' · '+n);
 process.exit(fails?1:0)})();
