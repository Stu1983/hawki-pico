// node tests/tests_month_gaps.js firmware/  - "Usage by month" when a month has days without readings: those days are
// filled in (across a gap: the straight line between the readings either side; otherwise the month's own litres a day)
// and drawn apart from the measured, so a Pico set up on the 19th never shows November as 33 L.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2]||path.join(__dirname,'..','firmware'),common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const pg=fs.readFileSync(path.join(dir,'hist.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const NOW=Date.UTC(2026,10,23,18,30)/1000,H=3600,DAY=86400,M='aa:bb:cc:00:00:02';
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>1300-i*10)};  /* 1 L a mm: litres = 1300 - distance */
/* the friend's tank: hourly from 19 Nov 18:53 (heard at odd seconds), using 9.3 L a day; maybe one reading typed in for 29 Oct */
function hist(oct){const r=[];if(oct)r.push([Date.UTC(2026,9,29,8)/1000,1300-436]);const t0=Date.UTC(2026,10,19,18,53,58)/1000;
 for(let t=t0;t<=NOW;t+=H)r.push([t,Math.round(1300-(310-9.3*(t-t0)/DAY))]);
 const b=Buffer.alloc(r.length*6);r.forEach(([t,mm],i)=>{b.writeUInt32LE(t,i*6);b.writeUInt16LE(mm,i*6+4)});return b.buffer.slice(b.byteOffset,b.byteOffset+b.length)}
const state={tanks:[{mac:M,name:'Tank 1',level:1300-283,litres:283,percent:22,age:60,cfg:{capacity_l:1300,reserve_l:60,height_cm:130}}],found:[],primary:M,year_l:2200,update:{version:'1.3.28',boot:1},pin_set:true,ssid:'x',ip:'192.0.2.5'};
function open(oct){return new JSDOM(pg,{url:'http://pico/history?mac='+M,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>NOW*1000;w.setInterval=()=>0;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.localStorage.hawkiSession='s';
 w.fetch=async u=>({ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:{},text:async()=>'{}',clone(){return this},arrayBuffer:async()=>u.startsWith('/api/hist')?hist(oct):new ArrayBuffer(0)})}}).window}
(async()=>{const fcs=[];
 for(const oct of[true,false]){const w=open(oct);await wait(900);const d=w.document;
  const rows=[...d.querySelectorAll('#tbl tr')].map(r=>[...r.children].map(c=>c.textContent)),nov=rows.find(x=>x[0]==='Nov')[1];
  const tot=+nov.match(/^(\d+) L/)[1],fill=+(nov.match(/≈(\d+) filled in/)||[0,0])[1],st=d.getElementById('c2s').textContent,lg=d.getElementById('lg2').textContent;
  /* measured: 19 Nov midnight-to-midnight days, 20-22 Nov = 3 x 9.3 = 28 L */
  if(oct){/* 29 Oct 436 L to 19 Nov ~310 L: ~5.9 L a day across the gap, so 1-19 Nov ~ 19 x 5.9 = 112 L */
   ok(fill>=100&&fill<=125&&tot>=fill+25&&tot<=fill+40,'a reading on 29 Oct, the Pico from 19 Nov: November filled in across the gap: '+nov);
   const oc=rows.find(x=>x[0]==='Oct')[1],ol=+oc.match(/^(\d+) L/)[1];ok(ol>=12&&ol<=22&&/filled in/.test(oc),'October gets only its share of that gap (29-31 Oct), nothing multiplied out from it: '+oc)}
  else ok(fill>=150&&fill<=200&&tot>=fill+25,'no earlier reading: 1-19 Nov at the measured 9.3 L a day: '+nov);
  fcs.push(nov.match(/\+ ≈(\d+) L$/)[1]);if(fcs.length===2)ok(fcs[0]===fcs[1],'the forecast is the same with or without the gap filled in (it never feeds the forecast): '+fcs.join(' / '));
  ok(/No readings \(filled in\)/.test(lg)&&/of it filled in/.test(st),'legend and summary say part of it is filled in: '+st);
  const bar=[...d.querySelectorAll('#c2 rect[opacity="0.4"]')];ok(bar.length>=1,'the filled-in part drawn lighter, on the measured bar')}
 /* the last reading 4 days ago: those days are the forecast's, never filled in as well */
 {const T2=NOW;const w=new JSDOM(pg,{url:'http://pico/history?mac='+M,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.Date.now=()=>(T2+4*DAY)*1000;w.setInterval=()=>0;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.localStorage.hawkiSession='s';
  w.fetch=async u=>({ok:true,status:200,json:async()=>u.startsWith('/api/state')?Object.assign({},state,{tanks:[Object.assign({},state.tanks[0],{age:4*DAY})]}):u.startsWith('/api/curve')?cv:{},text:async()=>'{}',clone(){return this},arrayBuffer:async()=>u.startsWith('/api/hist')?hist(false):new ArrayBuffer(0)})}}).window;
  await wait(900);const nov=[...w.document.querySelectorAll('#tbl tr')].map(r=>[...r.children].map(c=>c.textContent)).find(x=>x[0]==='Nov')[1],m=nov.match(/^(\d+) L.*≈(\d+) filled in\) \+ ≈(\d+) L$/);
  ok(m&&+m[2]<=200&&+m[1]+ +m[3]<=330,'readings stopped 4 days ago: the days since are only forecast, not filled in too: '+nov)}
 process.exit(fails?1:0)})();
