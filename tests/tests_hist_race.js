// node tests_hist_race.js hist.html  - tap another tank's tab while the first tank's history is still loading:
// the page must end up showing ONLY the tank tapped last (title, readings, live level), never a mix, and must
// never be half one tank and half the other while the newer load is still waiting (a resize or range button
// redraws from those globals at any moment).
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const common=fs.readFileSync(path.join(path.dirname(process.argv[2]),'common.js.html'),'utf8');
const html=fs.readFileSync(process.argv[2],'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const NOW=Date.UTC(2026,10,16,11)/1000,H=3600;
function hist(days,mm){const n=days*24,b=Buffer.alloc(n*6);for(let i=0;i<n;i++){b.writeUInt32LE(NOW-(n-i)*H,i*6);b.writeUInt16LE(mm+Math.floor(i/40),i*6+4)}return b.buffer.slice(b.byteOffset,b.byteOffset+b.length)}
const A1='aa:bb:cc:00:00:01',A2='aa:bb:cc:00:00:02';
const H1=hist(100,600),H2=hist(1,1228);  /* tank 1: 100 days; tank 2: 1 day */
const state={tanks:[{mac:A1,name:'Tank 1',level:700,litres:611,percent:46,age:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}},
 {mac:A2,name:'Tank 2',level:1228,litres:73,percent:5.5,age:60,cfg:{capacity_l:1323,height_cm:130}}],found:[]};
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
function page(opts){return new JSDOM(html,{url:'http://pico/history?mac='+A1,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.Date.now=()=>NOW*1000;let dl=0;
 w.fetch=async u=>{const t1=u.startsWith('/api/hist?mac='+A1)||u.startsWith('/api/curve?mac='+A1);
  if(t1){await wait(opts.slow1||400);if(opts.fail1)throw new TypeError('Failed to fetch')}
  if(u.startsWith('/api/deliveries')&&dl++>0&&opts.slowDl)await wait(opts.slowDl);  /* the newer load's deliveries lag */
  return {ok:true,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:{},
   arrayBuffer:async()=>u.startsWith('/api/hist?mac='+A1)?H1:u.startsWith('/api/hist?mac='+A2)?H2:new ArrayBuffer(0)}};
 w.onerror=m=>console.log('ERR',m)}})}
const tap=(d,name)=>{const b=[...d.querySelectorAll('#tabs button')].find(x=>x.textContent===name);if(b)b.click();return !!b};
const one=w=>{const T=w.eval('T'),P=w.eval('P'),A=w.eval('A');if(!T)return 'none';
 const n=P.length,tank=T.mac===A1?'t1':T.mac===A2?'t2':'?';const pOk=tank==='t1'?n>2000:n<=26;const aOk=A&&(tank==='t1'?A.span>90:A.span<2);
 return pOk&&aOk?tank:'MIXED (T '+tank+', '+n+' points, span '+(A&&A.span.toFixed(1))+')'};
(async()=>{
 /* 1. a late answer for tank 1 must not win over tank 2 */
 {const dom=page({});const w=dom.window,d=w.document;await wait(100);ok(tap(d,'Tank 2'),'Tank 2 tab is there');await wait(1100);
  const ttl=d.getElementById('ttl').textContent,sub=d.getElementById('sub').textContent;console.log('title:',ttl,'| sub:',sub);
  ok(ttl==='Tank 2','title is the tank tapped last: '+ttl);ok(one(w)==='t2','the page holds tank 2 only: '+one(w));
  ok(/hours|1 days/.test(sub)&&!/100 days/.test(sub),'readings are tank 2\'s, not tank 1\'s 100 days: '+sub)}
 /* 2. while the newer load still waits (its deliveries lag), every moment is ONE tank, never a mix */
 {const dom=page({slow1:10,slowDl:600});const w=dom.window,d=w.document;await wait(300);const before=one(w);ok(before==='t1','tank 1 shown first: '+before);
  tap(d,'Tank 2');const seen=new Set();for(let i=0;i<12;i++){await wait(60);seen.add(one(w))}
  ok([...seen].every(x=>x==='t1'||x==='t2'),'during the switch the page is always one tank: '+[...seen].join(', '));
  await wait(400);ok(one(w)==='t2'&&d.getElementById('ttl').textContent==='Tank 2','then tank 2: '+one(w))}
 /* 3. an older load that fails after a newer one has finished doesn't put "Could not load" over it */
 {const dom=page({slow1:500,fail1:true});const w=dom.window,d=w.document;await wait(100);tap(d,'Tank 2');await wait(900);
  const sub=d.getElementById('sub').textContent;ok(!/Could not load/.test(sub)&&one(w)==='t2','a late failure of the older load is ignored: '+sub)}
 process.exit(fails?1:0)})();
