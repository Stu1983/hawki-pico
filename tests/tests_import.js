// node tests_import.js firmware/  - importing a backup from the page: settings first, then each tank's deliveries
// in batches small enough for the Pico (16 KB a request), upper-case MACs from older backups included.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'ui.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const M='C0:04:56:C4:0C:71',m=M.toLowerCase();
const recs=[];for(let i=0;i<120;i++)recs.push({t:1700000000+i*86400,litres:500,total:400,ppl:80,supplier:i%2?'AH Fuels':'中'.repeat(40),note:i%2?'x'.repeat(80):'中'.repeat(80)});  /* (3-byte UTF-8 text: count by bytes, not characters) */
const h=Buffer.alloc(12);h.writeUInt32LE(1790000000,0);h.writeUInt16LE(700,4);h.writeUInt32LE(1790003600,6);h.writeUInt16LE(701,10);
const backup={format:'hawki-backup',version:1,exported:'2026-11-17T20:00:00Z',tanks:{[M]:{name:'Tank 1',shape:'cuboid',height_cm:123,length_cm:173,width_cm:69,tank_l:1306}},
 deliveries:{[M]:recs},history:{[M]:h.toString('base64')}};
const state={tanks:[],found:[],primary:null,update:{version:'1.2.53'},ssid:'x',ip:'192.0.2.5'};
const posts=[];
const w=new JSDOM(html,{url:'http://pico/#cfg',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.setInterval=()=>0;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.TextEncoder=TextEncoder;w.localStorage.hawkiSession='s';w.confirm=()=>true;w.alert=x=>console.log('ALERT',x);
 w.fetch=async(u,o)=>{if(o&&o.method==='POST')posts.push([u,o.body]);return {ok:true,status:200,json:async()=>u.startsWith('/api/state')?state:'ok',arrayBuffer:async()=>new ArrayBuffer(0)}};
 w.onerror=x=>console.log('ERR',x)}}).window;
(async()=>{await wait(300);
 await w.importBackup({text:async()=>JSON.stringify(backup)});await wait(300);
 const rs=posts.filter(p=>p[0]==='/api/restore').map(p=>JSON.parse(p[1])),hs=posts.filter(p=>p[0].startsWith('/api/hist'));
 const last=rs[rs.length-1],dels=rs.slice(0,-1);
 ok(last.tanks&&last.tanks[m]&&last.staged===true&&!last.deliveries,'settings last (under the lower-case MAC), committing what was held aside');
 ok(dels.length>=2&&dels[0].part==='first'&&dels.slice(1).every(r=>r.part==='more')&&dels.every(r=>r.deliveries[m]),'deliveries first, in '+dels.length+' batches: first, more…');
 ok(dels.reduce((a,r)=>a+r.deliveries[m].length,0)===120,'all 120 receipts sent');
 const bytes=posts.filter(p=>p[0]==='/api/restore').map(p=>Buffer.byteLength(p[1]));ok(bytes.every(n=>n<16000),'every request under the Pico\'s 16 KB limit in bytes (largest '+Math.max(...bytes)+')');
 ok(hs.length===1&&hs[0][0]==='/api/hist?mac='+m,'readings uploaded for the tank: '+(hs[0]&&hs[0][0]));
 ok(/Imported 1 tank/.test(w.document.getElementById('bkst').textContent),'says so: '+w.document.getElementById('bkst').textContent);
 ok(rs.every(r=>r.import&&r.import===rs[0].import),'every request carries the same import id');
 posts.length=0;await w.importBackup({text:async()=>JSON.stringify(Object.assign({},backup,{deliveries:{[M]:'oops'}}))});await wait(200);
 ok(!posts.some(p=>p[0]==='/api/restore'&&JSON.parse(p[1]).staged)&&/damaged/.test(w.document.getElementById('bkst').textContent),'a damaged delivery list: nothing committed, says so: '+w.document.getElementById('bkst').textContent);
 process.exit(fails?1:0)})();
