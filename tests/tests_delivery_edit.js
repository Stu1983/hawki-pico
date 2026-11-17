// node tests_delivery_edit.js firmware/  - editing a delivery the sensor saw: its estimate is a hint, never saved as
// the receipt's litres unless the user takes it (it then counted as a receipt and fed the capacity fit).
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'hist.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const NOW=Date.UTC(2026,10,16,11)/1000,M='aa:bb:cc:00:00:01';
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const state={tanks:[{mac:M,name:'Tank 1',level:700,litres:611,percent:46,age:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}],found:[],primary:M};
const posts=[];
const w=new JSDOM(html,{url:'http://pico/history#deliveries',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>NOW*1000;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.localStorage.hawkiSession='s';
 w.fetch=async(u,o)=>{if(o&&o.method==='POST')posts.push(JSON.parse(o.body));return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:{},arrayBuffer:async()=>new ArrayBuffer(0)}}}}).window;
(async()=>{await wait(500);const d=w.document;
 const seen={t:NOW-3*86400,mac:M,f:{add:487.4}};
 w.editDel(seen);
 ok(d.getElementById('d_l').value==='','the sensor\'s estimate is not filled in as the receipt litres');
 ok(/487/.test(d.getElementById('d_l').placeholder+d.getElementById('d_lh').textContent),'it is shown as a hint: "'+d.getElementById('d_lh').textContent+'"');
 d.getElementById('d_p').value='60';d.getElementById('d_p').dispatchEvent(new w.Event('input'));
 ok(d.getElementById('d_c').value==='','typing only the price works out no total from the estimate');
 await w.saveDel({preventDefault(){}});await wait(50);
 ok(posts.length===1&&posts[0].litres===null&&posts[0].total===null&&posts[0].ppl===60,'saved: the price only, no litres or total made up: '+JSON.stringify({l:posts[0]&&posts[0].litres,c:posts[0]&&posts[0].total,p:posts[0]&&posts[0].ppl}));
 w.editDel(seen);const use=[...d.getElementById('d_lh').querySelectorAll('button')].find(b=>/Use/.test(b.textContent));
 ok(!!use,'a button to take the estimate on purpose');if(use)use.click();
 ok(d.getElementById('d_l').value==='487','...which fills it in: '+d.getElementById('d_l').value);
 d.getElementById('d_p').value='60';d.getElementById('d_p').dispatchEvent(new w.Event('input'));
 ok(d.getElementById('d_c').value==='292.20','...and then the total follows: '+d.getElementById('d_c').value);
 process.exit(fails?1:0)})();
