// node tests_hist.js hist.html [out.svg prefix]  - synthetic 14 months of hourly data through the real page
const {JSDOM}=require('jsdom');const fs=require('fs');
const path=require('path');const common=fs.readFileSync(path.join(path.dirname(process.argv[2]),'common.js.html'),'utf8');
const html=fs.readFileSync(process.argv[2],'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
// linear tank: 1300 mm = 1323 L
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const mmOf=L=>Math.round(1300*(1-L/1323));
const NOW=Date.UTC(+(process.env.Y||2026),+(process.env.M||10),16,11)/1000,H=3600,DAY=86400,start=NOW-(+(process.env.DAYS||430))*DAY;
const HDD=[340,300,280,210,140,75,45,50,90,170,260,320];
// a household: hot water ~1.2 L/day in August, ~25 % more in February (colder mains); heating off June-August
const doyU=t=>(t*1000-Date.UTC(new Date(t*1000).getUTCFullYear(),0,1))/864e5;
const use=(t,m)=>1.2*(1+0.25*(1+Math.cos(2*Math.PI*(doyU(t)-46)/365))/2)+(m>=5&&m<=7?0:HDD[m]/30*0.9);
let L=900,trueUse={},fills=[],buf=Buffer.alloc(0),rnd=1;const rand=()=>{rnd=(rnd*16807)%2147483647;return rnd/2147483647};
const recs=[];
for(let t=start;t<=NOW-H;t+=H){const m=new Date(t*1000).getUTCMonth(),perDay=use(t,m);
 const u=perDay/24;L-=u;const k=new Date(t*1000).getUTCFullYear()+'-'+m;trueUse[k]=(trueUse[k]||0)+u;
 if(L<250){L+=800;fills.push(t)}
 if(t>start+40*DAY&&t<start+43*DAY)continue;// a 3-day outage
 const noisy=L+(rand()-.5)*6+3*Math.sin(t/DAY*2*Math.PI);recs.push([t,mmOf(noisy)])}
const b=Buffer.alloc(recs.length*6);recs.forEach(([t,mm],i)=>{b.writeUInt32LE(t,i*6);b.writeUInt16LE(mm,i*6+4)});
const state={tanks:[{mac:'aa:bb:cc:00:00:01',name:'Tank 1',level:mmOf(L),litres:L,percent:+(L/13.23).toFixed(1),age:60,battery:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}},
 {mac:'aa:bb:cc:00:00:02',name:'Tank 2',level:1228,litres:77,percent:5.8,age:5,cfg:{capacity_l:1323,height_cm:130}}],found:[]};
const empty=process.argv[4]==='empty';
const dom=new JSDOM(html,{url:'http://pico/history?mac='+(empty?'aa:bb:cc:00:00:02':'aa:bb:cc:00:00:01'),runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.Date.now=()=>NOW*1000;
 w.fetch=async u=>({ok:true,json:async()=>u.startsWith('/api/state')?state:cv,arrayBuffer:async()=>empty?new ArrayBuffer(0):b.buffer.slice(b.byteOffset,b.byteOffset+b.length)});
 w.onerror=m=>console.log('ERR',m)}});
setTimeout(()=>{const w=dom.window,d=w.document,A=w.eval('A');
 const txt=id=>d.getElementById(id).textContent;
 console.log('sub:',txt('sub'));console.log('tiles:',['t_now','t_now2','t_rate','t_rate2','t_ord','t_ord2','t_dry','t_dry2'].map(txt).join(' | '));
 if(!empty){
  console.log('fills detected',A.fills.length,'actual',fills.length,A.fills.map(f=>Math.round(f.add)).join(','));
  let worst=0;for(const k in A.months){const m=A.months[k];const dim=new Date(m.y,m.m+1,0).getDate();if(m.days<dim)continue;const e=m.used-trueUse[k];worst=Math.max(worst,Math.abs(e)/trueUse[k]);}
  console.log('full months',Object.values(A.months).filter(m=>m.days>=28).length,'worst month error %',(worst*100).toFixed(1));
  console.log('recent',A.recent.toFixed(2),'useOwn',A.useOwn,'k',A.k&&A.k.toFixed(2));
  // forecast check vs truth: simulate truth forward
  let l=L,t=NOW,dry=null;for(let i=0;i<730&&dry==null;i++){const m=new Date(t*1000).getUTCMonth();l-=use(t,m);t+=DAY;if(l<=200)dry=t}
  console.log('true reorder date',new Date(dry*1000).toISOString().slice(0,10),'forecast',new Date(A.fc.ord*1000).toISOString().slice(0,10));
 }
 console.log('fills text:',txt('fills').slice(0,120));console.log('how:',txt('how').slice(0,300));
 if(process.argv[3]){
  const css=d.querySelector('style').textContent.replace(/@media[^{]*\{:root\{[^}]*\}\}/,'');const vars={};(css.match(/:root\{([^}]*)\}/)[1]).split(';').forEach(p=>{const[k,v]=p.split(':');if(k)vars[k.trim()]=v.trim()});
  const fix=s=>s.replace(/var\((--[a-z0-9]+)\)/g,(_,k)=>vars[k]);
  const rules=fix(css.match(/svg text\{[^}]*\}|\.(gl|ax|ln|fc|rsv|rsvt|fill|xh|dot)\{[^}]*\}/g).join('\n')).replace(/\{([^}]*)\}/g,'{$1}');
  for(const id of ['c1','c2']){fs.writeFileSync(process.argv[3]+id+'.svg',fix(d.getElementById(id).outerHTML).replace('<svg ',`<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="${id==='c1'?480:440}" `).replace(/>/,`><style>${rules}</style><rect width="100%" height="100%" fill="#fff"/>`))}
 }
 process.exit(0)},800);
