// node tests_modes_pages.js firmware/  - tank modes on the pages (In use / Standby / Off).
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const pg=n=>fs.readFileSync(path.join(dir,n),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
const cv={step:10,h:1300,l:Array.from({length:131},(_,i)=>+(1323*(1-i/130)).toFixed(1))};
const NOW=Date.UTC(2026,10,16,11)/1000,H=3600,mmOf=L=>Math.round(1300*(1-L/1323));
function hist(days,L0,perDay){const n=days*24,b=Buffer.alloc(n*6);for(let i=0;i<n;i++){b.writeUInt32LE(NOW-(n-i)*H,i*6);b.writeUInt16LE(mmOf(L0-perDay*i/24),i*6+4)}return b.buffer.slice(b.byteOffset,b.byteOffset+b.length)}
const A1='aa:bb:cc:00:00:01',A2='aa:bb:cc:00:00:02';
const H1=hist(30,550,10),H2=hist(30,7,0);  /* tank 1: 550 L falling 10 L/day to ~250; tank 2 flat */
const tank=(mac,name,litres,cfg)=>({mac,name,level:mmOf(litres),litres,percent:+(litres/13.23).toFixed(1),age:60,battery:60,cfg:Object.assign({capacity_l:1323,reserve_l:200,height_cm:130},cfg)});
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
function open(file,url,state,posts){return new JSDOM(pg(file),{url,runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.Date.now=()=>NOW*1000;w.setInterval=()=>0;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.localStorage.hawkiSession='s';
 w.fetch=async(u,o)=>{if(o&&o.method==='POST'&&posts)posts.push([u,JSON.parse(o.body)]);
  return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:u.startsWith('/api/tank')?'ok':{},
   arrayBuffer:async()=>u.startsWith('/api/hist?mac='+A1)?H1:u.startsWith('/api/hist?mac='+A2)?H2:new ArrayBuffer(0)}};
 w.alert=m=>console.log('ALERT',m);w.onerror=m=>console.log('ERR',m)}}).window}
const st=(t2cfg,primary)=>({tanks:[tank(A1,'Tank 1',250,{}),tank(A2,'Tank 2',t2cfg.litres,t2cfg.cfg)],found:[],primary,update:{version:'1.2.53'},ssid:'x',ip:'192.0.2.5'});
(async()=>{
 /* dashboard, both tanks together: an off tank is left out */
 {const w=open('ui.html','http://pico/#dash',st({litres:7,cfg:{mode:'off',isolated:1790000000}},'all'));await wait(500);const d=w.document;
  ok(d.getElementById('d_name').textContent==='Tank 1'&&d.getElementById('d_l').textContent==='250 L','Tank 2 off: the dashboard is Tank 1 alone ('+d.getElementById('d_name').textContent+' '+d.getElementById('d_l').textContent+')');
  ok(!/unusable/.test(d.getElementById('d_l2').textContent)||!/7 L/.test(d.getElementById('d_l2').textContent),'...its oil and unusable part not added: '+d.getElementById('d_l2').textContent)}
 {const w=open('ui.html','http://pico/#dash',st({litres:700,cfg:{mode:'standby',isolated:1790000000}},'all'));await wait(500);const d=w.document;
  ok(d.getElementById('d_name').textContent==='Both tanks'&&d.getElementById('d_l').textContent==='950 L','Tank 2 standby with oil: both counted ('+d.getElementById('d_l').textContent+')');
  ok(/\(standby\)/.test(d.getElementById('d_l2').textContent),'...and marked standby: '+d.getElementById('d_l2').textContent)}
 /* dashboard on Tank 1: time to order -> switch to the standby tank with oil */
 {const w=open('ui.html','http://pico/#dash',st({litres:700,cfg:{mode:'standby',isolated:1790000000}},A1));await wait(500);const d=w.document,t=d.getElementById('d_w2').textContent;
  ok(/^Switch to Tank 2 (now|around)/.test(t),'Tank 1 near its reorder level, Tank 2 on standby with oil: "'+t+'"')}
 {const w=open('ui.html','http://pico/#dash',st({litres:7,cfg:{mode:'off',isolated:1790000000}},A1));await wait(500);const t=w.document.getElementById('d_w2').textContent;
  ok(/^Order (now|around)/.test(t),'Tank 2 off: order oil: "'+t+'"')}
 /* the form: mode shown and saved */
 {const posts=[],w=open('ui.html','http://pico/#tanks',st({litres:7,cfg:{mode:'off',isolated:1790000000,shape:'cuboid',length_cm:173,width_cm:69,tank_l:1306}},A1),posts);await wait(400);
  w.edit(A2);const d=w.document;ok(d.getElementById('f_mode').value==='off','editing Tank 2: the form shows Off');
  d.getElementById('f_mode').value='standby';await w.saveTank({preventDefault(){}});await wait(100);const p=posts.find(x=>x[0]==='/api/tank');
  ok(p&&p[1].mode==='standby'&&!('isolated' in p[1]),'saving sends the mode: '+JSON.stringify(p&&{mode:p[1].mode,isolated:p[1].isolated}))}
 {const w=open('ui.html','http://pico/#tanks',st({litres:700,cfg:{isolated:1790000000}},A1));await wait(400);w.edit(A2);
  ok(w.document.getElementById('f_mode').value==='standby','settings from before modes (Isolated ticked): shown as Standby')}
 /* history page: an off tank has its own tab, never in "All tanks" */
 {const w=open('hist.html','http://pico/history',st({litres:7,cfg:{mode:'off',isolated:1790000000}},'all'));await wait(600);const d=w.document,tabs=[...d.querySelectorAll('#tabs button')].map(b=>b.textContent);
  ok(!tabs.includes('All tanks')&&tabs.includes('Tank 2')&&d.getElementById('ttl').textContent==='Tank 1','history with Tank 2 off: tabs '+tabs.join('/')+', showing '+d.getElementById('ttl').textContent)}
 {const w=open('hist.html','http://pico/history',st({litres:700,cfg:{mode:'standby',isolated:1790000000}},'all'));await wait(600);const d=w.document,tabs=[...d.querySelectorAll('#tabs button')].map(b=>b.textContent);
  ok(tabs[0]==='All tanks'&&d.getElementById('ttl').textContent==='Both tanks','history with Tank 2 standby: '+tabs.join('/')+', showing '+d.getElementById('ttl').textContent)}
 /* every tank off: the dashboard says so, and forecasts nothing */
 {const s=st({litres:7,cfg:{mode:'off',isolated:1790000000}},'all');s.tanks[0].cfg.mode='off';s.tanks[0].cfg.isolated=1790000000;const w=open('ui.html','http://pico/#dash',s);await wait(500);const d=w.document;
  ok(d.getElementById('d_name').textContent==='All tanks are off'&&d.getElementById('d_l').textContent==='–','all tanks off: "'+d.getElementById('d_name').textContent+'" '+d.getElementById('d_l').textContent)}
 {const s=st({litres:7,cfg:{mode:'off',isolated:1790000000}},A1);s.tanks[0].cfg.mode='off';const w=open('ui.html','http://pico/#dash',s);await wait(500);const d=w.document;
  ok(d.getElementById('d_w').textContent==='–'&&/^Off/.test(d.getElementById('d_w2').textContent),'an off tank shown on its own: its oil, no forecast ("'+d.getElementById('d_w2').textContent+'")')}
 /* "same tank as" an off tank: this tank stays in use */
 {const posts=[],w=open('ui.html','http://pico/#tanks',st({litres:7,cfg:{mode:'off',isolated:1790000000,shape:'cuboid',length_cm:173,width_cm:69,tank_l:1306}},A1),posts);await wait(400);
  w.edit(A1);const d=w.document;d.getElementById('m_from').value=A2;w.copyFrom();ok(d.getElementById('f_mode').value==='use','copying settings from an off tank keeps this one In use ('+d.getElementById('f_mode').value+')')}
 /* a lone tank that isn't in use can still be put back */
 {const s=st({litres:7,cfg:{}},A1);s.tanks=[tank(A1,'Tank 1',250,{mode:'off',isolated:1790000000})];const w=open('ui.html','http://pico/#tanks',s);await wait(400);w.edit(A1);
  ok(w.document.getElementById('f_isoL').style.display!=='none','the only tank, set to Off: the mode is still shown')}
 /* the switch hint: shown from the Pico's guess, only opens the settings; its room is kept while a tank is on standby */
 {const posts=[],s=st({litres:700,cfg:{mode:'standby',isolated:1790000000,shape:'cuboid',length_cm:173,width_cm:69,tank_l:1306}},A1);s.switch={from:A1,to:A2,fell:12};
  const w=open('ui.html','http://pico/#dash',s,posts);await wait(500);const d=w.document,el=d.getElementById('d_sw');
  ok(/Switched to Tank 2\?/.test(el.textContent)&&/went down 12 L/.test(el.textContent),'hint shown: '+el.textContent.slice(0,90));
  const b=el.querySelector('button');ok(b&&b.textContent==='Edit Tank 2','its button says what it does: '+(b&&b.textContent));
  b.click();await wait(50);ok(w.eval('cur')===A2&&d.getElementById('f_mode').value==='standby'&&!posts.some(p=>p[0]!=='/api/forecast'),'it opens Tank 2\'s settings unchanged (still standby), nothing saved');
  s.switch=null;w.load();await wait(300);ok(el.textContent===''&&el.style.height==='2.4em','no hint: its room stays while a tank is on standby (nothing below moves)')}
 {const w=open('ui.html','http://pico/#dash',st({litres:7,cfg:{mode:'off',isolated:1790000000}},A1));await wait(400);
  ok(w.document.getElementById('d_sw').style.height==='0px'||w.document.getElementById('d_sw').style.height==='0','no standby tank: no room kept')}
 /* the forecast goes to the Pico for Home Assistant's order date: once per history refresh, never for an off tank */
 {const posts=[],w=open('ui.html','http://pico/#dash',st({litres:700,cfg:{mode:'standby',isolated:1790000000}},A1),posts);await wait(500);w.load();await wait(400);
  const f=posts.filter(p=>p[0]==='/api/forecast');ok(f.length===1&&f[0][1].mac===A1&&f[0][1].cum.length===400&&f[0][1].reserve===200,'dashboard sends its forecast once ('+f.length+'), 400 days of running totals')}
 {const posts=[],s=st({litres:7,cfg:{mode:'off',isolated:1790000000}},A2);const w=open('ui.html','http://pico/#dash',s,posts);await wait(500);
  ok(!posts.some(p=>p[0]==='/api/forecast'),'an off tank on the dashboard: nothing sent')}
 process.exit(fails?1:0)})();
