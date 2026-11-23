// node tests/tests_share_card.js firmware/  - Config → Share for support: switching it on and off, the ID shown,
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
   if(u==='/api/share'){if(b.on===true)Object.assign(state.share,{on:true,id:'HK-7QM2-XFD9',busy:true});if(b.on===false)Object.assign(state.share,{on:false,id:null});if(b.now)state.share.busy=true}
   return {ok:true,status:200,json:async()=>state.share}}
  gets.push(u);if(u.startsWith('https://'))return u.endsWith('/u/HK-7QM2-XFD9')?{ok:true,status:200,json:async()=>backup}:{ok:false,status:404,json:async()=>({})};
  return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:{},arrayBuffer:async()=>new ArrayBuffer(0)}};
 w.onerror=x=>console.log('ERR',x)}}).window;
const $=id=>w.document.getElementById(id);
(async()=>{await wait(400);w.tab('cfg');await w.load();await wait(50);
 ok($('shBtn').disabled&&$('shRes').disabled&&/isn't ready yet/.test($('shSt').textContent)&&$('shId').textContent==='–','no share server yet: says so, nothing to press');
 const box=$('shSt').getBoundingClientRect?$('shSt').style.minHeight:'';ok(box==='38px'&&$('shCopy').style.visibility==='hidden','its space kept (the card never jumps)');
 state.share.host='share.example';await w.load();await wait(50);
 ok(!$('shBtn').disabled&&$('shBtn').textContent==='Start sharing'&&$('shNow').disabled&&/Not sharing/.test($('shSt').textContent),'ready: Start sharing; nothing to send yet');
 await w.shToggle();await wait(50);
 ok(posts.length===1&&posts[0][0]==='/api/share'&&JSON.parse(posts[0][1]).on===true,'Start sharing: asks the Pico');
 ok($('shId').textContent==='HK-7QM2-XFD9'&&$('shCopy').style.visibility==='visible'&&$('shBtn').textContent==='Stop sharing'&&/Sending/.test($('shSt').textContent),'the ID shown, with Copy; sending');
 Object.assign(state.share,{busy:false,at:1795500000});await w.load();await wait(50);
 ok(/Last sent/.test($('shSt').textContent)&&/share\.example\/v\/HK-7QM2-XFD9/.test($('shSt').textContent)&&!$('shNow').disabled,'sent: when, and the address to give: '+$('shSt').textContent);
 state.share.err='the share server said 500';await w.load();await wait(50);
 ok(/Could not send: the share server said 500/.test($('shSt').textContent),'a failure: said');state.share.err=null;
 asked=null;await w.shToggle();await wait(50);
 ok(/deleted from the share server/.test(asked)&&posts.length===1,'Stop sharing: asks first (says what happens), nothing sent if not confirmed');
 /* restore */
 $('shIn').value='nope';await w.shRestore();ok(/looks like HK-/.test(alerted)&&!gets.some(u=>u.startsWith('https://')),'a mistyped ID: said, nothing fetched');
 $('shIn').value=' hk 7qm2 xfd9 ';asked=null;await w.shRestore();await wait(50);
 ok(gets.includes('https://share.example/u/HK-7QM2-XFD9')&&/Import from the backup of 2026-11-23/.test(asked)&&/Back tank/.test(asked),'Restore: fetched by its ID (as typed), then the backup\'s own question: '+JSON.stringify((asked||'').slice(0,60)));
 $('shIn').value='HK-0000-0001';alerted=null;await w.shRestore();ok(/nothing is shared under HK-0000-0001/.test(alerted),'an ID with nothing: said');
 process.exit(fails?1:0)})();
