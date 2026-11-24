// node tests/tests_share_card.js firmware/  - Config → Online backup: switching it on and off, the ID shown,
// "Send now", and Restore from an ID (fetched from the share server, imported the way a backup file is).
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2]||path.join(__dirname,'..','firmware'),common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'ui.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const m='c0:04:56:c4:0c:99';
const state={tanks:[{mac:m,name:'Back tank',cfg:{capacity_l:1000},litres:600}],found:[],primary:m,update:{version:'1.3.30'},ssid:'x',ip:'192.0.2.5',authed:true,share:{on:false,id:null,at:null,err:null,busy:false,host:null}};
const posts=[],gets=[];let asked=null,alerted=null;
const backup={format:'hawki-backup',version:1,share:1,exported:'2026-11-23T20:00:00Z',tanks:{[m]:{name:'Back tank',capacity_l:1000}},deliveries:{[m]:[]},history:{[m]:Buffer.from(new Uint8Array(12)).toString('base64')}};
const w=new JSDOM(html,{url:'http://pico/#cfg',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.setInterval=()=>0;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.localStorage.hawkiSession='s';w.confirm=q=>{asked=q;return false};w.alert=x=>{alerted=x};
 w.fetch=async(u,o)=>{if(o&&o.method==='POST'){posts.push([u,o.body]);const b=JSON.parse(o.body||'{}');
   if(u==='/api/share'){if('host' in b)Object.assign(state.share,{host:b.host||'share.example',own_host:!!b.host});if(b.on===true)Object.assign(state.share,{on:true,id:'HK-7QM2-XFD9',busy:true});if(b.on===false)Object.assign(state.share,{on:false,id:null});if(b.now)state.share.busy=true}
   return {ok:true,status:200,json:async()=>state.share}}
  gets.push(u);if(/\/invite\?c=/.test(u))return {ok:/c=AB12-CD34$/.test(u),status:/c=AB12-CD34$/.test(u)?200:403,json:async()=>({})};if(u.startsWith('https://'))return u.endsWith('/u/HK-7QM2-XFD9')?{ok:true,status:200,json:async()=>backup}:{ok:false,status:404,json:async()=>({})};
  return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:{},arrayBuffer:async()=>new ArrayBuffer(0)}};
 w.onerror=x=>console.log('ERR',x)}}).window;
const $=id=>w.document.getElementById(id);
(async()=>{await wait(400);w.tab('cfg');await w.load();await wait(50);
 ok(!$('shNote').textContent&&$('shNote').style.minHeight==='40px'&&$('shBtn').disabled&&$('shRes').disabled&&/isn't ready yet/.test($('shSt').textContent)&&$('shId').textContent==='–','no share server yet: says so, nothing to press');
 const box=$('shSt').getBoundingClientRect?$('shSt').style.minHeight:'';ok(box==='38px'&&$('shCopy').style.visibility==='hidden','its space kept (the card never jumps)');
 state.share.host='share.example';await w.load();await wait(50);
 ok(!$('shBtn').disabled&&$('shBtn').textContent==='Turn on'&&$('shNow').disabled&&/Off: nothing is kept online/.test($('shSt').textContent),'ready: Turn on; nothing to back up yet');
 ok($('shInvRow').style.visibility==='visible'&&$('shHost').textContent==='share.example'&&$('shHostDef').style.visibility==='hidden'&&!$('shHostIn').disabled,'off: the invite code box; the server named; can be changed');
 alerted=null;await w.shToggle();ok(/invite code you were given/.test(alerted)&&!posts.length&&gets.includes('https://share.example/invite?c='),'Turn on without an invite code: the server asked (an open one needs none); this one does: says so, nothing changed');
 $('shInv').value='AB12-CD35';alerted=null;await w.shToggle();ok(/isn't right/.test(alerted)&&!posts.length&&gets.includes('https://share.example/invite?c=AB12-CD35'),'a wrong code: checked with the server first, said, nothing changed');
 $('shInv').value=' AB12-CD34 ';alerted=null;await w.shToggle();await wait(50);
 ok(posts.length===1&&posts[0][0]==='/api/share'&&JSON.parse(posts[0][1]).on===true&&JSON.parse(posts[0][1]).invite==='AB12-CD34'&&$('shInv').value==='','Turn on: asks the Pico, with the invite code (then clears the box)');
 ok($('shInvRow').style.visibility==='hidden'&&$('shHostIn').disabled,'on: no invite box (its space kept); the server can\'t be changed');
 ok($('shId').textContent==='HK-7QM2-XFD9'&&$('shCopy').style.visibility==='visible'&&$('shBtn').textContent==='Turn off'&&/Backing up/.test($('shSt').textContent),'the ID shown, with Copy; backing up');
 ok(/Your backup ID is HK-7QM2-XFD9[\s\S]*Make a note of it/.test(alerted)&&/Make a note of this ID/.test($('shNote').textContent),'turning on: told to note the ID (once, and always under it)');
 {let copied=null;w.document.execCommand=c=>{copied=w.document.activeElement&&w.document.activeElement.value;return c==='copy'};await w.shCopy();
  ok(copied==='HK-7QM2-XFD9'&&$('shCopy').textContent==='Copied','Copy: works on the Pico\'s plain-http page (no navigator.clipboard there)');
  w.document.execCommand=()=>false;alerted=null;await w.shCopy();ok(/press and hold/.test(alerted)&&w.getSelection().toString()==='HK-7QM2-XFD9','a browser that won\'t copy: the ID selected, and says how');
  await w.load();await wait(50);ok(w.getSelection().toString()==='HK-7QM2-XFD9','...and still selected after the page refreshes')}
 Object.assign(state.share,{busy:false,at:1795500000});await w.load();await wait(50);
 ok(/Last backed up/.test($('shSt').textContent)&&/share\.example\/v\/HK-7QM2-XFD9/.test($('shSt').textContent)&&!$('shNow').disabled,'sent: when, and the address to give: '+$('shSt').textContent);
 state.share.err='the backup server said 500';await w.load();await wait(50);
 ok(/Could not back up: the backup server said 500/.test($('shSt').textContent),'a failure: said');state.share.err=null;
 asked=null;await w.shToggle();await wait(50);
 ok(/online copy is deleted/.test(asked)&&posts.length===1,'Turn off: asks first (says what happens), nothing sent if not confirmed');
 Object.assign(state.share,{on:false,id:null,deleting:true,derr:'the backup server said 500'});await w.load();await wait(50);
 ok(/Off\. Deleting the online copy \(could not yet: the backup server said 500/.test($('shSt').textContent),'turned off, not deleted yet: says so: '+$('shSt').textContent);
 Object.assign(state.share,{deleting:false,derr:null});await w.load();await wait(50);ok(/Off: nothing is kept online/.test($('shSt').textContent),'deleted: nothing kept online');
 /* restore */
 $('shIn').value='nope';await w.shRestore();ok(/looks like HK-/.test(alerted)&&!gets.some(u=>u.startsWith('https://')&&u.includes('/u/')),'a mistyped ID: said, nothing fetched');
 $('shIn').value=' hk 7qm2 xfd9 ';asked=null;await w.shRestore();await wait(50);
 ok(gets.includes('https://share.example/u/HK-7QM2-XFD9')&&/Import from the backup of 2026-11-23/.test(asked)&&/Back tank/.test(asked),'Restore: fetched by its ID (as typed), then the backup\'s own question: '+JSON.stringify((asked||'').slice(0,60)));
 $('shIn').value='HK-0000-0001';alerted=null;await w.shRestore();ok(/nothing is backed up under HK-0000-0001/.test(alerted),'an ID with nothing: said');
 Object.assign(state.share,{on:false,id:null});await w.load();await wait(50);posts.length=0;
 $('shHostIn').value='my-own.workers.dev';await w.shSetHost();await wait(50);
 ok(JSON.parse(posts[0][1]).host==='my-own.workers.dev'&&/my-own\.workers\.dev \(your own\)/.test($('shHost').textContent)&&$('shHostDef').style.visibility==='visible','another server: saved, named as your own, a way back');
 await w.shSetHost(1);await wait(50);ok(JSON.parse(posts[1][1]).host===''&&$('shHost').textContent==='share.example','...back to the usual one');
 process.exit(fails?1:0)})();
