// node tests/tests_paste.js firmware/  - Config → Earlier readings: readings pasted in (from the Magnus app's history,
// say) become the distances the monitor would have read and are merged into the tank's history; only those from before
// the Pico's own first reading; litres or %; lines it can't read are named, never guessed at.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2]||path.join(__dirname,'..','firmware'),common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'ui.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const m='c0:04:56:c4:0c:99';
/* a plain tank: 1,000 L full at 30 mm from the sensor, empty at 1,030 mm, straight-sided */
const cv={step:10,h:1030,l:Array.from({length:104},(_,i)=>Math.max(0,Math.min(1000,(1030-i*10)/1000*1000)))};
const own=Date.parse('2026-11-19T20:00:37Z')/1000,hist=Buffer.alloc(6*15);for(let k=0;k<15;k++){hist.writeUInt32LE(own+k*3600,k*6);hist.writeUInt16LE(400,k*6+4)}  /* the Pico's own: hourly from 8pm on the 19th, at the second each was heard */
const state={tanks:[{mac:m,name:'Back tank',cfg:{capacity_l:1000},litres:600}],found:[],primary:m,update:{version:'1.3.8'},ssid:'x',ip:'192.0.2.5',authed:true};
const posts=[];let asked=null,hist2=null;
const w=new JSDOM(html,{url:'http://pico/#cfg',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
 w.setInterval=()=>0;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.TextEncoder=TextEncoder;w.localStorage.hawkiSession='s';w.confirm=q=>{asked=q;return true};w.alert=x=>console.log('ALERT',x);
 w.fetch=async(u,o)=>{if(o&&o.method==='POST')posts.push([u,o.body]);const j=u.startsWith('/api/state')?state:u.startsWith('/api/curve')?cv:3;
  return {ok:true,status:200,json:async()=>j,arrayBuffer:async()=>u.startsWith('/api/hist')?hist2?hist2.buffer.slice(hist2.byteOffset,hist2.byteOffset+hist2.length):hist.buffer.slice(hist.byteOffset,hist.byteOffset+hist.length):new ArrayBuffer(0)}};
 w.onerror=x=>console.log('ERR',x)}}).window;
const $=id=>w.document.getElementById(id);
(async()=>{await wait(400);w.tab('fc');await wait(100);
 ok($('pTank').options.length===1&&$('pTank').value===m&&$('pBtn').disabled,'the card lists the tank; nothing to add yet');
 $('pTxt').value=['# from the Magnus app','2026-11-12 08:00 850 L','13/11/2026 8:00pm 70%','14 Nov 2026 08:00 1,500 L','next Tuesday 600 L','2026-11-20 09:00 590 L',''].join('\n');
 $('pTxt').dispatchEvent(new w.Event('input'));
 ok(/4 readings, 12 Nov 2026 to 20 Nov 2026/.test($('pPrev').textContent)&&/line 5\b/.test($('pPrev').textContent)&&!$('pBtn').disabled,'preview: how many, from when to when, and the line it couldn\'t read ('+$('pPrev').textContent+')');
 await w.pasteAdd();await wait(200);
 const hs=posts.filter(p=>p[0]==='/api/hist?mac='+m);ok(hs.length===1,'sent to the tank\'s history');
 const v=new DataView(hs[0][1]),got=[];for(let i=0;i<v.byteLength;i+=6)got.push([v.getUint32(i,true),v.getUint16(i+4,true)]);
 ok(got.length===2&&got[0][0]===Date.parse('2026-11-12T08:00:00Z')/1000&&got[1][0]===Date.parse('2026-11-13T20:00:00Z')/1000,'two readings, oldest first, at the times given (8:00pm = 20:00)');
 ok(Math.abs(got[0][1]-180)<=1&&Math.abs(got[1][1]-330)<=1,'850 L and 70% of 1,000 L as the distances the monitor would read: '+got.map(g=>g[1]+' mm').join(', '));
 ok(/1 left out: a reading is already saved within 2 hours/.test(asked)&&/more than the tank holds \(1500 L\)/.test(asked),'asked first, saying what is left out and why: '+JSON.stringify(asked));
 ok(/Added 2 readings to Back tank/.test($('pPrev').textContent)&&$('pTxt').value==='','says so, and clears the box');
 posts.length=0;$('pTxt').value='2026-11-19 21:00 500 L';await w.pasteAdd();await wait(100);
 ok(!posts.length&&/Nothing to add: 1 already covered/.test($('pPrev').textContent),'a time the Pico already has readings for: nothing sent ('+$('pPrev').textContent+')');
 /* the level typed is all the oil in the tank (a delivery, the Magnus app): the part below the outlet comes off; % of the whole tank */
 state.tanks[0].unusable=[100,'estimate'];state.tanks[0].cfg.tank_l=1100;posts.length=0;asked=null;
 $('pTxt').value='2026-11-10 08:00 600 L\n2026-11-11 08:00 50%\n2026-11-11 20:00 80 L';await w.pasteAdd();await wait(100);
 const g2=(()=>{const h=posts.filter(p=>p[0].startsWith('/api/hist?mac='+m));if(!h.length)return[];const v=new DataView(h[0][1]),o=[];for(let i=0;i<v.byteLength;i+=6)o.push(v.getUint16(i+4,true));return o})();
 ok(g2.length===3&&Math.abs(g2[0]-530)<=1&&Math.abs(g2[1]-580)<=1&&g2[2]===1029,'600 L in the tank = 500 L usable; 50% of 1,100 L = 450 L usable; 80 L = below the outlet: '+g2.join(', ')+' mm');
 ok(posts.length===1&&!/replace/.test(posts[0][0])&&!/replaces/.test(asked),'new times: added, nothing replaced');
 /* the friend's case: 524 L typed for 29 Oct went in as usable; the same time typed again corrects it */
 const t29=Date.parse('2026-10-29T08:00:00Z')/1000,old=hist;let h2=Buffer.alloc(6);h2.writeUInt32LE(t29,0);h2.writeUInt16LE(506,4);hist2=Buffer.concat([h2,old]);
 posts.length=0;asked=null;$('pTxt').value='2026-10-29 08:00 524 L';await w.pasteAdd();await wait(100);
 ok(posts.length===1&&/&replace=1$/.test(posts[0][0])&&new DataView(posts[0][1]).getUint16(4,true)===606&&/1 of them replaces the reading saved for the same time:\n29 Oct 2026 08:00: 524 → 424 L usable/.test(asked),'the same time typed again: sent as a correction (424 L usable = 606 mm, replace=1), and said so: '+(posts[0]&&posts[0][0]));
 posts.length=0;hist2.writeUInt16LE(606,4);$('pTxt').value='2026-10-29 08:00 524 L';await w.pasteAdd();await wait(100);
 ok(!posts.length&&/Nothing to add: 1 already covered/.test($('pPrev').textContent),'typed again with the same level: nothing to change');
 const tc=Date.parse('2024-01-10T12:00:00Z')/1000;h2=Buffer.alloc(6);h2.writeUInt32LE(tc,0);h2.writeUInt16LE(500,4);hist2=Buffer.concat([h2,old]);
 posts.length=0;$('pTxt').value='2024-01-10 12:00 900 L';await w.pasteAdd();await wait(100);
 ok(!posts.length,'a day over 2 years old, boiled down to one reading at midday UTC: never replaced');
 /* a reading typed for 08:00 with another at 09:00: still correctable; one at noon (pasted, not 2 years old) too */
 const t9=t29+3600,tn=Date.parse('2026-10-28T12:00:00Z')/1000,h3=Buffer.alloc(18);[[tn,506],[t29,506],[t9,510]].forEach(([a,b],i)=>{h3.writeUInt32LE(a,i*6);h3.writeUInt16LE(b,i*6+4)});hist2=Buffer.concat([h3,old]);
 posts.length=0;$('pTxt').value='2026-10-29 08:00 524 L\n2026-10-28 12:00 530 L';await w.pasteAdd();await wait(100);
 ok(posts.length===1&&/&replace=1$/.test(posts[0][0])&&new DataView(posts[0][1]).byteLength===12&&/2 of them replace/.test(asked),'a neighbour within 2 hours, or a typed noon reading: both still corrected');
 hist2=null;delete state.tanks[0].unusable;delete state.tanks[0].cfg.tank_l;
 const P=w.pasteParse('31/02/2026 10:00 500 L\n2026-11-12 850\n12th Nov 2026 07:30am 800L\n12.11.26 12:00pm 790 litres\n2026-11-12 64.50%\n2026-11-12 12.50 L\n2026-11-12 -50 L',Date.parse('2026-11-20')/1000);
 ok(P.bad.join()==='1,2,7'&&P.rows.length===4&&P.rows.filter(r=>r[1]===64.5||r[1]===12.5).length===2&&P.rows.filter(r=>r[1]===64.5||r[1]===12.5).every(r=>new Date(r[0]*1000).getHours()===12)&&new Date(P.rows[0][0]*1000).getHours()===7&&new Date(P.rows[1][0]*1000).getHours()===12,'no 31 February, no number without L or %; "12th Nov", "12.11.26", 12pm = noon; a decimal level (64.50%, 12.50 L) is never taken for a time; -50 L refused');
 state.tanks=[];await w.load();await wait(50);
 ok($('pTank').options.length===0&&$('pBtn').disabled,'the tank removed (from another phone, say): gone from the list, nothing to add to');
 /* the dashboard's tank drawing: tap for full screen, tap again to close */
 state.tanks=[{mac:m,name:'Back tank',cfg:{capacity_l:1000,shape:'cuboid',height_cm:103,length_cm:120,width_cm:60,mode:'use'},litres:600,level:400,percent:60}];
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.tab('dash');await w.load();await wait(300);
 w.document.getElementById('d_tank').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));const f=$('tfull');
 ok(f.open&&f.querySelector('svg').innerHTML===$('d_tank').innerHTML&&$('tfullT').textContent==='Back tank','a tap on the drawing opens it full screen, with the tank\'s name');
 (f.querySelector('svg .oil')||f.querySelector('svg')).dispatchEvent(new w.MouseEvent('click',{bubbles:true}));ok(!f.open,'a tap anywhere on it (the oil, say) closes it again');
 process.exit(fails?1:0)})();
