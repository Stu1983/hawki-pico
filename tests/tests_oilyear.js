// node tests_oilyear.js firmware/  - "Usage by month" as an oil year (July to June): this year's use, the forecast
// carried past December, and an average year; and the Config box for a typical year's oil.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const pg=n=>fs.readFileSync(path.join(dir,n),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const NOW=Date.UTC(2026,10,16,11)/1000,H=3600,M='aa:bb:cc:00:00:01';
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
function hist(days){const n=days*24,b=Buffer.alloc(n*6);for(let i=0;i<n;i++){b.writeUInt32LE(NOW-(n-i)*H,i*6);b.writeUInt16LE(300+Math.floor(i/6),i*6+4)}return b.buffer.slice(b.byteOffset,b.byteOffset+b.length)}
const state=y=>({tanks:[{mac:M,name:'Tank 1',level:700,litres:611,percent:46,age:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}],found:[],primary:M,year_l:y,update:{version:'1.3.2',boot:1},pin_set:true,ssid:'x',ip:'192.0.2.5'});
const posts=[];
function open(page,url,y){return new JSDOM(pg(page),{url,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>NOW*1000;w.setInterval=()=>0;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.localStorage.hawkiSession='s';
 w.fetch=async(u,o)=>{if(o&&o.method==='POST'){posts.push([u,JSON.parse(o.body)]);if(u==='/api/year')return {ok:true,status:200,json:async()=>({year_l:JSON.parse(o.body).litres})}}
  return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state(y):u.startsWith('/api/curve')?cv:{},text:async()=>'{}',clone(){return this},arrayBuffer:async()=>u.startsWith('/api/hist')?hist(100):new ArrayBuffer(0)}}}}).window}
(async()=>{
 for(const y of [2100,null]){const w=open('hist.html','http://pico/history?mac='+M,y);await wait(900);const d=w.document;
  const rows=[...d.querySelectorAll('#tbl tr')].map(r=>[...r.children].map(c=>c.textContent)),head=rows[0],mon=rows.slice(1).map(r=>r[0]);
  if(y){
   ok(mon.join(' ')==='Jul Aug Sep Oct Nov Dec Jan Feb Mar Apr May Jun','the year runs July to June: '+mon.join(' '));
   ok(head.join('|')==='Month|2026/27|Average year','columns: '+head.join('|'));
   const r=m=>rows.find(x=>x[0]===m);
   ok(/^\d+ L$/.test(r('Oct')[1])&&/^\d+ L \(\d+d\) \+ ≈\d+ L$/.test(r('Nov')[1]),'October used, November used so far + the rest forecast: '+r('Oct')[1]+' | '+r('Nov')[1]);
   ok(['Dec','Jan','Feb','Mar','Jun'].every(m=>/^≈\d+ L$/.test(r(m)[1])),'the forecast carries on past December: Jan '+r('Jan')[1]+', Feb '+r('Feb')[1]);
   ok(r('Jul')[1]==='–'&&/^\d+ L$/.test(r('Jul')[2]),'a month before the readings began: a dash, and still its average');
   const avg=rows.slice(1).reduce((a,x)=>a+parseInt(x[2]),0);ok(Math.abs(avg-2100)<15,'the average year adds up to the 2,100 L given: '+avg);
   ok(/The typical year you gave \(2,100 L\)/.test(d.getElementById('lg2').textContent)&&/Used 2026\/27/.test(d.getElementById('lg2').textContent),'legend: '+d.getElementById('lg2').textContent);
   const st=d.getElementById('c2s').textContent;ok(/^Since Aug: [\d,]+ L used · about [\d,]+ L more by June · the same months of an average year [\d,]+ L$/.test(st)&&+st.match(/year ([\d,]+)/)[1].replace(',','')<2100,'readings began in August: a part year is compared with the same months, never the whole 2,100: '+st);
   const svg=d.getElementById('c2');ok(svg.querySelectorAll('rect[stroke-dasharray]').length===8&&svg.querySelectorAll('line[stroke="var(--fg)"]').length===12,'8 forecast bars (Nov to Jun) and 12 average marks drawn')}
  else{ok(head.join('|')==='Month|2026/27|Average year'&&/Average year \(usual weather\)/.test(d.getElementById('lg2').textContent),'no figure given: the average year is the usual weather for your own use');
   const avg=rows.slice(1).reduce((a,x)=>a+parseInt(x[2]),0);ok(avg>300&&avg<2000,'...'+avg+' L')}}
 {const w=open('ui.html','http://pico/#cfg',2100);await wait(400);const d=w.document;
  ok(d.getElementById('yr_l').value==='2100','Config shows the figure saved');
  d.getElementById('yr_l').value='1800';await w.yrSave();const p=posts.find(x=>x[0]==='/api/year');
  ok(p&&p[1].litres===1800&&/Saved/.test(d.getElementById('yr_st').textContent),'saving sends it: '+JSON.stringify(p&&p[1])+' "'+d.getElementById('yr_st').textContent+'"');
  posts.length=0;d.getElementById('yr_l').value='';await w.yrSave();ok(posts[0]&&posts[0][1].litres===null&&d.getElementById('yr_st').textContent==='Removed.','emptied: removed')}
 process.exit(fails?1:0)})();
