// node tests_setup_page.js firmware/  - the setup screen: a phone on the setup Wi-Fi with no home Wi-Fi yet sees only the
// setup steps (PIN, then Wi-Fi, then where to find the monitor), a wrong password is said there and then, and nothing else
// is shown until it's done. On the home network, or once connected, the page is as before.
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const dir=process.argv[2],common=fs.readFileSync(path.join(dir,'common.js.html'),'utf8');
const html=fs.readFileSync(path.join(dir,'ui.html'),'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const base=o=>Object.assign({tanks:[],found:[],primary:null,update:{version:'1.3.5',boot:1},pin_set:false,ssid:null,ip:null,ap:'HAWKi-Setup-ABCD',
 hostname:'hawki-pico',via_ap:true,wifi_saved:null,join:null},o||{});
function open(st,route,sess){const posts=[];const w=new JSDOM(html,{url:'http://192.168.4.1/',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){if(sess)w.localStorage.setItem('hawkiSession',sess);
 const s=w.setTimeout.bind(w);w.setTimeout=(f,ms)=>s(f,Math.min(ms||0,3000)/100);const si=w.setInterval.bind(w);w.setInterval=(f,ms)=>si(f,Math.max(5,(ms||0)/100));
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.alert=()=>0;w.confirm=()=>true;
 w.fetch=async(u,o)=>{const b=o&&o.body?JSON.parse(o.body):null;if(o&&o.method==='POST')posts.push([u,b,(o.headers||{})['X-Auth']]);
  const r=(route&&route(u,b,o))||(u.startsWith('/api/state')?{status:200,body:st()}:u==='/api/auth'?{status:200,body:{ok:false}}:{status:200,body:{}});
  return {ok:r.status<300,status:r.status,json:async()=>r.body,text:async()=>JSON.stringify(r.body),clone(){return this},arrayBuffer:async()=>new ArrayBuffer(0)}}}}).window;
 w.posts=posts;return w}
const $=(w,id)=>w.document.getElementById(id);
const vis=(w,id)=>{let e=typeof id==='string'?$(w,id):id;for(;e&&e.tagName!=='HTML';e=e.parentElement)if(w.getComputedStyle(e).display==='none')return false;return true};  /* (as shown: page styles can beat the hidden flag) */
const until=async(f,ms=3000)=>{for(let t=0;t<ms;t+=20){if(f())return true;await wait(20)}return false};
(async()=>{
 /* 1. a new monitor, phone on the setup Wi-Fi: only the setup screen, starting with a PIN */
 let K1=null,st=base(),scan=[{ssid:'HomeNet',rssi:-55},{ssid:'HomeNet 5G',rssi:-60},{ssid:'BT-Next door',rssi:-85}];
 const w=open(()=>st,(u,b)=>{if(u==='/api/pin/set')return {status:200,body:{session:'S1'}};if(u==='/api/wifi/scan')return {status:200,body:scan};
  if(u==='/api/wifi/try'){K1=b.k;st=base({pin_set:true,join:{ssid:b.ssid,state:'trying',k:b.k}});return {status:200,body:st.join}}
  if(u==='/api/setup/done')return {status:200,body:'ok'};return null});
 ok(await until(()=>vis(w,'s_pin')),'the setup screen opens at the PIN step');
 ok(!vis(w,'p_dash')&&!vis(w,'p_cfg')&&!vis(w,'p_tanks')&&!vis(w,w.document.querySelector('.tabs')),'nothing else: no tabs, no dashboard, no config');
 ok(/Set up your oil monitor/.test(w.document.querySelector('h1').textContent),'the heading says it is setting up');
 $(w,'s_p1').value='1234';$(w,'s_p2').value='1235';w.suPin({preventDefault(){}});await wait(20);
 ok(/don't match/.test($(w,'s_pinE').textContent)&&vis(w,'s_pin'),'PINs that differ: says so, stays');
 $(w,'s_p2').value='1234';await w.suPin({preventDefault(){}});
 ok(w.posts.some(p=>p[0]==='/api/pin/set'&&p[1].pin==='1234'),'the PIN is saved on the monitor');
 ok(await until(()=>vis(w,'s_wifi')&&w.document.querySelectorAll('input[name=s_net]').length===3),'then the Wi-Fi step, listing what it can see');
 ok(/Strong/.test($(w,'s_nets').textContent)&&/Very weak/.test($(w,'s_nets').textContent),'each with its signal in words');
 /* 2. a password too short: said before trying */
 {const r=w.document.querySelector('input[name=s_net][value="HomeNet"]');r.checked=true;r.onchange()}
 ok($(w,'s_own').value==='HomeNet','tapping a network fills in its name');$(w,'s_pw').value='short';await w.suJoin({preventDefault(){}});
 ok(/8 to 63/.test($(w,'s_wifiE').textContent)&&!w.posts.some(p=>p[0]==='/api/wifi/try'),'a too-short password: said straight away, nothing sent');
 /* 3. a wrong password: back to the Wi-Fi step, saying so */
 $(w,'s_pw').value='wrongpassword';await w.suJoin({preventDefault(){}});
 const t=w.posts.find(p=>p[0]==='/api/wifi/try');
 ok(t&&t[1].ssid==='HomeNet'&&t[1].pw==='wrongpassword'&&t[2]==='S1','tries the network, signed in with the new PIN');
 ok(vis(w,'s_try')&&/Connecting to HomeNet/.test($(w,'s_tryT').textContent),'"Connecting to HomeNet…"');
 st=base({pin_set:true,join:{ssid:'HomeNet',state:'password',k:K1}});
 ok(await until(()=>vis(w,'s_wifi')),'the monitor says the password was wrong: back to the Wi-Fi step');
 ok(/password didn't work for HomeNet/.test($(w,'s_wifiE').textContent),'...saying so: "'+$(w,'s_wifiE').textContent+'"');
 ok(w.document.querySelector('input[name=s_net]:checked').value==='HomeNet'&&$(w,'s_own').value==='HomeNet','...with the network still picked');
 /* 4. the right one: where to find it */
 $(w,'s_pw').value='rightpassword';await w.suJoin({preventDefault(){}});
 st=base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57',k:K1}});
 ok(await until(()=>vis(w,'s_done')),'connected: the done step');
 ok($(w,'s_addr').textContent==='http://192.168.1.57/'&&$(w,'s_addr').href==='http://192.168.1.57/'&&$(w,'s_addr').target==='_blank','the address is a link that opens in a new tab: "'+$(w,'s_addr').textContent+'"');
 {const a=$(w,'s_addr2').querySelector('a');ok(a&&a.href==='http://hawki-pico.local/'&&a.target==='_blank','...and the .local name too, as a link');}
 ok($(w,'s_addr3').href==='http://192.168.1.57/','"All done" links to it as well');
 ok(/goes back to HomeNet/.test($(w,'s_done').textContent),'and that the phone goes back to the home Wi-Fi');
 ok(/take a screenshot of this screen, or press and hold the address/.test($(w,'s_shot').textContent)&&w.getComputedStyle($(w,'s_shot')).color!==w.getComputedStyle($(w,'s_addr2')).color,'...and, in red, to screenshot it or press and hold the address to copy it, before Finish');
 ok(!vis(w,'p_dash')&&!vis(w,w.document.querySelector('.tabs')),'still only the setup screen, though the monitor is now on the home Wi-Fi');
 await w.suFinish();ok(w.posts.some(p=>p[0]==='/api/setup/done')&&vis(w,'s_bye'),'Finish: the setup Wi-Fi is told to go, "All done"');
 await wait(100);ok(vis(w,'s_bye'),'...and it stays at "All done"');
 /* 5. the setup network not answering for a moment while it joins */
 {let st2=base({pin_set:true,join:{ssid:'HomeNet',state:'trying'}}),down=false;
  const w2=open(()=>st2,u=>u.startsWith('/api/state')&&down?{status:0,body:null,throw:1}:null);
  w2.fetch=(f=>async(u,o)=>{if(down&&u.startsWith('/api/state'))throw new TypeError('Failed to fetch');return f(u,o)})(w2.fetch);
  ok(await until(()=>vis(w2,'s_try')),'reopened while joining: carries on at "Connecting"');
  down=true;ok(await until(()=>/Waiting for the monitor/.test($(w2,'s_tryM').textContent)),'the phone off the setup Wi-Fi a moment: says it is waiting, not "cannot reach"');
  down=false;st2=base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}});
  ok(await until(()=>vis(w2,'s_done')),'back again: on to the done step')}
 /* 6. a PIN already set (Wi-Fi changed): asks for it, once */
 {const w3=open(()=>base({pin_set:true,wifi_saved:'OldRouter'}),u=>u==='/api/pin/login'?{status:200,body:{session:'S2'}}:u==='/api/wifi/scan'?{status:200,body:[{ssid:'OldRouter',rssi:-70}]}:null);
  ok(await until(()=>vis(w3,'s_pin')),'a PIN already set: the first step asks for it');
  ok(/enter the PIN/.test($(w3,'s_pinT').textContent)&&!vis(w3,'s_p2l'),'"enter the PIN", no "type it again"');
  $(w3,'s_p1').value='4321';await w3.suPin({preventDefault(){}});
  ok(w3.posts.some(p=>p[0]==='/api/pin/login')&&await until(()=>vis(w3,'s_wifi')),'signs in, then the Wi-Fi step');
  ok(await until(()=>{const c=w3.document.querySelector('input[name=s_net]:checked');return c&&c.value==='OldRouter'&&$(w3,'s_own').value==='OldRouter'}),'the saved network is picked already')}
 /* a network not in the list: typed */
 {let tried=null;const w5=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:u==='/api/wifi/try'?(tried=b,{status:200,body:{ssid:b.ssid,state:'trying'}}):null,'S3');
  ok(await until(()=>vis(w5,'s_wifi')&&/No networks found/.test($(w5,'s_nets').textContent)),'signed in already: straight to Wi-Fi; nothing found says what to do');
  ok(vis(w5,'s_own'),'the name box is always there');
  $(w5,'s_own').value='Hidden net';$(w5,'s_pw').value='password1';await w5.suJoin({preventDefault(){}});
  ok(tried&&tried.ssid==='Hidden net','a typed name is tried')}
 /* Finish not getting through: says so, can be tapped again */
 {let n=0;const w6=open(()=>base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/setup/done'?(++n<2?{status:500,body:'x'}:{status:200,body:'ok'}):null,'S4');
  ok(await until(()=>vis(w6,'s_done')),'reopened after joining: the done step');await w6.suFinish();
  ok(vis(w6,'s_done')&&/didn't answer/.test($(w6,'s_finE').textContent)&&!$(w6,'s_fin').disabled,'Finish fails: says so, button still there');
  await w6.suFinish();ok(vis(w6,'s_bye'),'tapped again: done')}
 /* an old "connected" with no connection now (the home Wi-Fi went later): the Wi-Fi step, never "connected" */
 {const w7=open(()=>base({pin_set:true,wifi_saved:'HomeNet',join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S5');
  ok(await until(()=>vis(w7,'s_wifi'))&&!vis(w7,'s_done'),'a stale success with no connection: back to choosing Wi-Fi')}
 /* a listed name with a space at the end: sent exactly */
 {let tried=null;const w8=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[{ssid:'Flat 2 ',rssi:-60}]}:u==='/api/wifi/try'?(tried=b,{status:200,body:{ssid:b.ssid,state:'trying'}}):null,'S6');
  await until(()=>w8.document.querySelector('input[name=s_net]'));const r=w8.document.querySelector('input[name=s_net]');r.checked=true;r.onchange();
  $(w8,'s_pw').value='password1';await w8.suJoin({preventDefault(){}});ok(tried&&tried.ssid==='Flat 2 ','a listed name with a trailing space: sent as it is ('+JSON.stringify(tried&&tried.ssid)+')')}
 /* the home Wi-Fi coming back by itself while the setup screen is open: back to the normal page */
 {let st9=base({pin_set:true,wifi_saved:'HomeNet'});const w9=open(()=>st9,u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S7');
  ok(await until(()=>vis(w9,'s_wifi')),'home Wi-Fi down: the setup screen');
  st9=base({pin_set:true,wifi_saved:'HomeNet',ssid:'HomeNet',ip:'192.168.1.57'});await w9.load();
  ok(!vis(w9,'p_setup')&&vis(w9,'p_tanks')&&vis(w9,w9.document.querySelector('.tabs'))&&/Oil Tanks/.test(w9.document.querySelector('h1').textContent),'it came back by itself: the normal page again')}
 /* "Connected", then the connection goes (the keeper forgets the join): back to choosing Wi-Fi, saying so */
 {let st10=base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}});
  const w10=open(()=>st10,u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S8');
  ok(await until(()=>vis(w10,'s_done'))&&$(w10,'s_addr').textContent==='http://192.168.1.57/','reopened at "connected": the address shows at once');st10=base({pin_set:true,wifi_saved:'HomeNet'});await w10.load();
  ok(vis(w10,'s_wifi')&&/lost HomeNet/.test($(w10,'s_wifiE').textContent),'the connection lost: back to Wi-Fi, saying so: "'+$(w10,'s_wifiE').textContent+'"')}
 /* reopened mid-join while the old network is still connected: still setting up, not the dashboard */
 {const w11=open(()=>base({pin_set:true,ssid:'Old',ip:'192.168.1.9',join:{ssid:'HomeNet',state:'trying'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:null,'S9');
  ok(await until(()=>vis(w11,'s_try'))&&!vis(w11,'p_dash'),'mid-join with the old network still up: "Connecting", not the dashboard')}
 /* a typed name ending in a space: sent exactly; scanning again keeps it */
 {let tried=null;const w12=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:u==='/api/wifi/try'?(tried=b,{status:200,body:{ssid:b.ssid,state:'trying'}}):null,'S10');
  await until(()=>vis(w12,'s_wifi')&&/No networks/.test($(w12,'s_nets').textContent));$(w12,'s_own').value='Hidden ';await w12.suScan();
  ok($(w12,'s_own').value==='Hidden ','scanning again keeps the typed name as it is');$(w12,'s_pw').value='password1';await w12.suJoin({preventDefault(){}});
  ok(tried&&tried.ssid==='Hidden ','a typed name with a trailing space: sent exactly')}
 /* the join reaches the monitor but its answer never reaches the phone: the page follows the monitor anyway */
 {let st13=base({pin_set:true});const w13=open(()=>st13,(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[{ssid:'HomeNet',rssi:-50}]}:null,'S11');
  await until(()=>w13.document.querySelector('input[name=s_net]'));
  let K13=null;w13.fetch=(f=>async(u,o)=>{if(u==='/api/wifi/try'){K13=JSON.parse(o.body).k;st13=base({pin_set:true,join:{ssid:'HomeNet',state:'trying',k:K13}});throw new TypeError('Failed to fetch')}return f(u,o)})(w13.fetch);
  $(w13,'s_own').value='HomeNet';$(w13,'s_pw').value='password1';await w13.suJoin({preventDefault(){}});
  ok(vis(w13,'s_try')&&!$(w13,'s_wifiE').textContent,'the answer lost: "Connecting" anyway, no error (it may well have got there)');
  await w13.load();ok(vis(w13,'s_try'),'...the monitor says it is trying: still "Connecting"');
  st13=base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57',k:K13}});
  ok(await until(()=>vis(w13,'s_done')),'...and on to the done step')}
 /* no address known (should not happen): the .local name, never "http://undefined/" */
 {const w14=open(()=>base({pin_set:true,ssid:'HomeNet',join:{ssid:'HomeNet',state:'ok'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:null,'S12');
  ok(await until(()=>vis(w14,'s_done'))&&$(w14,'s_addr').textContent==='http://hawki-pico.local/'&&!$(w14,'s_addr2').textContent,'no address: the .local name alone')}
 /* the normal page with no tanks yet: opens on Tanks, listing the sensors it can hear with Add buttons */
 {const f=[{mac:'aa:bb:cc:00:00:09',name:'HAWKi',rssi:-60,age:5,level:700}];
  const w15=open(()=>base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true,found:f}));
  ok(await until(()=>vis(w15,'p_tanks')),'no tanks: opens on the Tanks page');
  ok(w15.location.hash==='#tanks'&&vis(w15,'tk0')&&!vis(w15,'tk1')&&/No tanks yet/.test($(w15,'tk0').textContent),'...saying there are none yet');
  ok(vis(w15,'found2')&&$(w15,'found2').querySelector('button.pri')&&/HAWKi/.test($(w15,'found2').textContent),'...with the sensors nearby and an Add button right there');
  const w16=open(()=>base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true,tanks:[{mac:'aa:bb:cc:00:00:01',name:'Tank 1',level:700,litres:611,percent:46,age:60,cfg:{capacity_l:1323,reserve_l:200,height_cm:130}}]}));
  await until(()=>/Updated/.test($(w16,'status').textContent));await wait(60);
  ok(vis(w16,'p_dash')&&$(w16,'tk0').hidden&&!$(w16,'tk1').hidden&&/Updated/.test($(w16,'status').textContent),'with a tank: the dashboard as before; connected, so not "Setup mode" though the setup Wi-Fi is up')}
 /* the phone jumps back to its home Wi-Fi mid-join (an iPad did): found again by name there */
 {let away=false,asked=[],sentK=null;const w17=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[{ssid:'HomeNet',rssi:-50}]}:u==='/api/wifi/try'?{status:200,body:{ssid:'HomeNet',state:'trying'}}:null,'S13');
  w17.fetch=(f=>async(u,o)=>{if(/^http:\/\/hawki-pico\.local\//.test(u)){asked.push(u);const k=decodeURIComponent(u.split('k=')[1]||'');return {ok:true,status:200,json:async()=>(k?{ssid:'HomeNet',state:'ok',ip:'192.168.1.57',k,via_ap:false}:null)}}
   if(u==='/api/wifi/try'&&o&&o.body)sentK=JSON.parse(o.body).k;
   if(away&&u.startsWith('/api/'))throw new TypeError('Load failed');return f(u,o)})(w17.fetch);
  await until(()=>w17.document.querySelector('input[name=s_net]'));$(w17,'s_own').value='HomeNet';$(w17,'s_pw').value='password1';await w17.suJoin({preventDefault(){}});
  ok(vis(w17,'s_try'),'connecting');away=true;
  ok(await until(()=>vis(w17,'s_done')),'the setup Wi-Fi gone from the phone: found by name on the home Wi-Fi, "Connected"');
  ok(sentK&&sentK.length>=6&&asked[0]==='http://hawki-pico.local/api/setup/status?k='+sentK,'...asking http://hawki-pico.local/api/setup/status with this attempt\'s own key ('+asked[0]+')');
  ok($(w17,'s_addr').textContent==='http://192.168.1.57/'&&!vis(w17,'s_fin')&&!vis(w17,'s_li1')&&/already back on HomeNet/.test($(w17,'s_far').textContent),'...with the address, no Finish to tap (it can\'t reach the setup Wi-Fi), saying the phone is back home');
  await wait(100);ok(vis(w17,'s_done')&&!/Cannot reach/.test($(w17,'status').textContent),'...and stays there, no "cannot reach"')}
 /* the name answering with someone else's setup (another network): not taken */
 {let away18=false,asked18=0;const w18=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:u==='/api/wifi/try'?{status:200,body:{ssid:'HomeNet',state:'trying'}}:null,'S14');
  w18.fetch=(f=>async(u,o)=>{if(/\.local\//.test(u)){asked18++;return {ok:true,status:200,json:async()=>({ssid:'HomeNet',state:'ok',ip:'10.0.0.2',k:'someoneelse',via_ap:false})}}if(away18&&u.startsWith('/api/'))throw new TypeError('x');return f(u,o)})(w18.fetch);
  await until(()=>vis(w18,'s_wifi'));$(w18,'s_own').value='HomeNet';$(w18,'s_pw').value='password1';await w18.suJoin({preventDefault(){}});away18=true;
  await until(()=>asked18>0);await wait(150);ok(asked18>0&&vis(w18,'s_try'),'an answer about another attempt (another monitor by that name): asked, but still waiting ('+asked18+' asks)')}
 /* the name led back to the setup Wi-Fi (its DNS answers every name): "Connected" with Finish, as usual */
 {let away=false,k19=null;const w19=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:u==='/api/wifi/try'?(k19=b.k,{status:200,body:{ssid:'HomeNet',state:'trying',k:b.k}}):null,'S15');
  w19.fetch=(f=>async(u,o)=>{if(/\.local\//.test(u))return {ok:true,status:200,json:async()=>({ssid:'HomeNet',state:'ok',ip:'192.168.1.57',k:k19,via_ap:true})};if(away&&u.startsWith('/api/state'))throw new TypeError('x');return f(u,o)})(w19.fetch);
  await until(()=>vis(w19,'s_wifi'));$(w19,'s_own').value='HomeNet';$(w19,'s_pw').value='password1';await w19.suJoin({preventDefault(){}});away=true;
  ok(await until(()=>vis(w19,'s_done'))&&vis(w19,'s_fin')&&!vis(w19,'s_far'),'found by name but still on the setup Wi-Fi: "Connected" with Finish, not "already back home"')}
 /* no answer at all for 75 seconds: back to the Wi-Fi step, saying so (never "Connecting…" for ever) */
 {let away=false,now=Date.now();const w20=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:u==='/api/wifi/try'?{status:200,body:{ssid:'HomeNet',state:'trying',k:b.k}}:null,'S16');
  w20.Date.now=()=>now;w20.fetch=(f=>async(u,o)=>{if(away&&(u.startsWith('/api/state')||/\.local\//.test(u)))throw new TypeError('x');return f(u,o)})(w20.fetch);
  await until(()=>vis(w20,'s_wifi'));$(w20,'s_own').value='HomeNet';$(w20,'s_pw').value='password1';await w20.suJoin({preventDefault(){}});away=true;
  await wait(100);ok(vis(w20,'s_try'),'no answer for a while: still "Connecting"');now+=76000;
  ok(await until(()=>vis(w20,'s_wifi'))&&/stopped answering/.test($(w20,'s_wifiE').textContent),'after 75 s: back to Wi-Fi: "'+$(w20,'s_wifiE').textContent+'"')}
 /* an earlier attempt's failure still showing while this one's request went missing: not taken as this one's */
 {let st21=base({pin_set:true,join:{ssid:'HomeNet',state:'password',k:'old'}});const w21=open(()=>st21,(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S17');
  w21.fetch=(f=>async(u,o)=>{if(u==='/api/wifi/try')throw new TypeError('x');return f(u,o)})(w21.fetch);
  await until(()=>vis(w21,'s_wifi'));$(w21,'s_own').value='HomeNet';$(w21,'s_pw').value='password1';await w21.suJoin({preventDefault(){}});
  await w21.load();ok(vis(w21,'s_try')&&!$(w21,'s_wifiE').textContent,'an older attempt\'s "wrong password": not shown for this one')}
 /* the request hangs (the setup Wi-Fi gone): "Connecting" at once, so the 75 s limit applies; never stuck on the form */
 {let now=Date.now();const w22=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S18');
  w22.Date.now=()=>now;w22.fetch=(f=>async(u,o)=>{if(u==='/api/wifi/try'||u.startsWith('/api/state')||/\.local\//.test(u))return new Promise(()=>{});return f(u,o)})(w22.fetch);
  await until(()=>vis(w22,'s_wifi'));$(w22,'s_own').value='HomeNet';$(w22,'s_pw').value='password1';w22.suJoin({preventDefault(){}});
  ok(vis(w22,'s_try'),'request hanging: "Connecting" straight away');now+=76000;
  ok(await until(()=>vis(w22,'s_wifi'))&&/stopped answering/.test($(w22,'s_wifiE').textContent),'...and after 75 s back to Wi-Fi, saying so')}
 /* the answer cut off mid-body: still "Connecting", the monitor decides */
 {const w23=open(()=>base({pin_set:true,join:{ssid:'HomeNet',state:'trying'}}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S19');
  w23.fetch=(f=>async(u,o)=>{if(u==='/api/wifi/try')return {ok:true,status:200,json:async()=>{throw new TypeError('cut off')},text:async()=>{throw 0}};return f(u,o)})(w23.fetch);
  await until(()=>vis(w23,'s_try'));}
 {const w24=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S20');
  w24.fetch=(f=>async(u,o)=>{if(u==='/api/wifi/try')return {ok:true,status:200,json:async()=>{throw new TypeError('cut off')},text:async()=>{throw 0}};return f(u,o)})(w24.fetch);
  await until(()=>vis(w24,'s_wifi'));$(w24,'s_own').value='HomeNet';$(w24,'s_pw').value='password1';await w24.suJoin({preventDefault(){}});
  ok(vis(w24,'s_try')&&!$(w24,'s_wifiE').textContent,'the answer cut off mid-way: still "Connecting", no error')}
 /* a clear refusal: back to the form with its reason */
 {const w25=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:u==='/api/wifi/try'?{status:409,body:'Already trying a network: wait a moment'}:null,'S21');
  await until(()=>vis(w25,'s_wifi'));$(w25,'s_own').value='HomeNet';$(w25,'s_pw').value='password1';await w25.suJoin({preventDefault(){}});
  ok(vis(w25,'s_wifi')&&/Already trying/.test($(w25,'s_wifiE').textContent),'refused: back to the form with the reason: "'+$(w25,'s_wifiE').textContent+'"')}
 /* a slow by-name answer for an older attempt arriving during a newer one: not taken */
 {let now=Date.now(),keys=[],hold=null;const w26=open(()=>base({pin_set:true}),(u,b)=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/wifi/scan'?{status:200,body:[]}:null,'S22');
  w26.Date.now=()=>now;w26.fetch=(f=>async(u,o)=>{if(u==='/api/wifi/try'){keys.push(JSON.parse(o.body).k);throw new TypeError('x')}if(u.startsWith('/api/state'))throw new TypeError('x');
   if(/\.local\//.test(u)){const k=decodeURIComponent(u.split('k=')[1]);if(k===keys[0]&&!hold)return new Promise(r=>{hold=()=>r({ok:true,status:200,json:async()=>({ssid:'A',state:'ok',ip:'192.168.1.5',k,via_ap:false})})});throw new TypeError('x')}return f(u,o)})(w26.fetch);
  await until(()=>vis(w26,'s_wifi'));$(w26,'s_own').value='A';$(w26,'s_pw').value='password1';await w26.suJoin({preventDefault(){}});
  await until(()=>hold);now+=76000;await until(()=>vis(w26,'s_wifi'));$(w26,'s_own').value='B';await w26.suJoin({preventDefault(){}});
  hold();await wait(100);ok(vis(w26,'s_try')&&!/Connected to A/.test($(w26,'s_doneT').textContent),'A\'s late answer during B: ignored, still connecting to B')}
 /* after Finish: waits for the NEW start (boot number), then opens the monitor at its address */
 {let now=Date.now(),boot=1,down=false,went=null;const w27=open(()=>base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',mac:'28:cd:c1:00:00:01',update:{version:'1.3.5',boot:1},join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/setup/done'?{status:200,body:'ok'}:null,'S23');
  w27.Date.now=()=>now;w27.suGo=u=>{went=u};
  w27.fetch=(f=>async(u,o)=>{if(/^http:\/\/(192\.168\.1\.57|hawki-pico\.local)\/api\/setup\/status/.test(u)){if(down||u.includes('.local'))throw new TypeError('x');return {ok:true,status:200,json:async()=>({boot,id:'28:cd:c1:00:00:01'})}}return f(u,o)})(w27.fetch);
  await until(()=>vis(w27,'s_done'));await w27.suFinish();
  ok(vis(w27,'s_bye')&&/Restarting/.test($(w27,'s_byeM').textContent),'Finish: "Restarting…"');
  down=true;await wait(100);down=false;await wait(150);ok(!went,'a missed check, then the OLD start answering again: not opened');
  now+=60000;await wait(150);ok(!went,'the old start still answering a minute on (an update holding the restart): not opened');
  down=true;await wait(100);boot=2;down=false;ok(await until(()=>went),'the new start answers: opens it');ok(went==='http://192.168.1.57/','...at its address on the home Wi-Fi ('+went+')')}
 {let now=Date.now(),went=null;const w29=open(()=>base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',mac:'28:cd:c1:00:00:01',update:{version:'1.3.5',boot:1},join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/setup/done'?{status:200,body:'ok'}:null,'S25');
  w29.Date.now=()=>now;w29.suGo=u=>{went=u};
  w29.fetch=(f=>async(u,o)=>{if(u.startsWith('http://192.168.1.57/'))throw new TypeError('x');if(u.startsWith('http://hawki-pico.local/api/setup/status'))return {ok:true,status:200,json:async()=>({boot:2,id:'28:cd:c1:00:00:01'})};return f(u,o)})(w29.fetch);
  await until(()=>vis(w29,'s_done'));await w29.suFinish();ok(await until(()=>went)&&went==='http://hawki-pico.local/','back at a new address: found by name, opened there ('+went+')')}
 /* another monitor by the same name, on a different start: not taken for this one */
 {let went=null;const w30=open(()=>base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',mac:'28:cd:c1:00:00:01',update:{version:'1.3.5',boot:10},join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/setup/done'?{status:200,body:'ok'}:null,'S26');
  w30.suGo=u=>{went=u};w30.fetch=(f=>async(u,o)=>{if(u.startsWith('http://192.168.1.57/'))return {ok:true,status:200,json:async()=>({boot:10,id:'28:cd:c1:00:00:01'})};if(u.includes('.local/'))return {ok:true,status:200,json:async()=>({boot:42,id:'28:cd:c1:00:00:99'})};return f(u,o)})(w30.fetch);
  await until(()=>vis(w30,'s_done'));await w30.suFinish();await wait(200);ok(!went,'another monitor answering to the name (its own start number): not opened')}
 {let now=Date.now(),went=null;const w28=open(()=>base({pin_set:true,ssid:'HomeNet',ip:'192.168.1.57',mac:'28:cd:c1:00:00:01',update:{version:'1.3.5',boot:1},join:{ssid:'HomeNet',state:'ok',ip:'192.168.1.57'}}),u=>u==='/api/auth'?{status:200,body:{ok:true}}:u==='/api/setup/done'?{status:200,body:'ok'}:null,'S24');
  w28.Date.now=()=>now;w28.suGo=u=>{went=u};w28.fetch=(f=>async(u,o)=>{if(u.startsWith('http://192.168.1.57/')||u.includes('.local/'))throw new TypeError('x');return f(u,o)})(w28.fetch);
  await until(()=>vis(w28,'s_done'));await w28.suFinish();await wait(100);now+=181000;
  ok(await until(()=>/hasn't come back yet/.test($(w28,'s_byeM').textContent))&&!went,'never back within 3 minutes: says so, with the address to tap')}
 /* Config, On your phone: the widget script copied with one tap (fetched beforehand: iPhones only copy during the tap) */
 {const w31=open(()=>base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true}),u=>u==='/widget.js'?{status:200,body:'const PICO = 1; // widget'}:null);
  w31.fetch=(f=>async(u,o)=>{if(u==='/widget.js')return {ok:true,status:200,text:async()=>'const PICO = 1; // widget'};return f(u,o)})(w31.fetch);
  let copied=null;w31.document.execCommand=c=>{if(c==='copy'){copied=w31.document.activeElement&&w31.document.activeElement.value;return true}return false};
  await until(()=>/Updated/.test($(w31,'status').textContent));
  ok(vis(w31,'p_tanks')||vis(w31,'p_dash'),'(starts on its usual page)');
  w31.tab('ntf');await wait(50);
  ok(/On your phone/.test($(w31,'p_ntf').textContent)&&/Add to Home Screen/.test($(w31,'p_ntf').textContent)&&/Scriptable/.test($(w31,'p_ntf').textContent),'Notifications has an On your phone card: the icon and the widget, step by step');
  {const h=id=>[...$(w31,id).querySelectorAll('h2')].map(e=>e.textContent).join(' | '),nav=[...w31.document.querySelectorAll('.tabs button,.tabs a')].map(b=>b.textContent).join(' | '),sb=[...w31.document.querySelectorAll('.sub button')].map(b=>b.textContent).join(' | ');
   ok(nav==='Dashboard | Tanks | Forecast | Config'&&sb==='Config | Forecast | Notifications','the tabs: '+nav+'; Config\'s sub-tabs: '+sb);
   ok(h('p_fc')==='Forecast | Weather | Oil prices | Earlier readings'&&h('p_ntf')==='Notifications | On your phone | Home Assistant'&&h('p_sys')==='Sensors nearby | Software | Wi-Fi & network | Security | Backup | Share for support','each tab\'s cards, Sensors nearby first on Config (needed when setting up): '+[h('p_fc'),h('p_ntf'),h('p_sys')].join(' / '));
   w31.tab('fc');ok(!$(w31,'p_cfg').hidden&&!$(w31,'p_fc').hidden&&$(w31,'p_sys').hidden&&$(w31,'p_ntf').hidden&&w31.document.querySelector('.sub button[data-s="fc"]').getAttribute('aria-pressed')==='true','#fc (an old link): Config, on its Forecast sub-tab, the others hidden');
   w31.sub('sys');ok(!$(w31,'p_sys').hidden&&$(w31,'p_fc').hidden&&w31.location.hash==='#cfg','a sub-tab tapped: shows alone, the address says #cfg');
   w31.tab('dash');w31.tab('cfg');ok(!$(w31,'p_sys').hidden,'Config opens on the sub-tab used last');
   ok(/^\/history/.test(w31.document.getElementById('navHist').getAttribute('href'))&&!w31.document.getElementById('d_hist'),'Forecast (the history page) is a tab along the top (the dashboard\'s link moved up there)');
   {const hr=js=>{w31.eval(js+';navHist()');return w31.document.getElementById('navHist').getAttribute('href')};w31.eval('var S0=S');
    const h1=hr("S=Object.assign({},S0,{primary:'all',tanks:[{mac:'aa:bb:cc:00:00:01',cfg:{mode:'off'}},{mac:'aa:bb:cc:00:00:02',cfg:{}}]})"),h2=hr("S.primary='aa:bb:cc:00:00:01'"),h3=hr("S=Object.assign({},S0,{tanks:[],primary:null})");w31.eval('S=S0');
    ok(h1==='/history?mac=aa:bb:cc:00:00:02'&&h2==='/history?mac=aa:bb:cc:00:00:01'&&h3==='/history','Forecast (the history page) follows what the dashboard shows, on every refresh: '+[h1,h2,h3].join(', '))}w31.tab('ntf')}
  w31.copyWidget();ok(copied==='const PICO = 1; // widget'&&/Copied/.test($(w31,'wjst').textContent),'Copy the widget script: copied there and then ("'+$(w31,'wjst').textContent+'")');
  w31.document.execCommand=()=>false;w31.copyWidget();ok(/press and hold the text/.test($(w31,'wjst').textContent),'a browser that won\'t copy: says how to copy it from Show it');
  ok($(w31,'p_ntf').querySelector('a[href="/widget.js"]'),'...with a Show it link to the script')}
 {const w32=open(()=>base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true}));let n=0;
  w32.fetch=(f=>async(u,o)=>{if(u==='/widget.js'){n++;throw new TypeError('x')}return f(u,o)})(w32.fetch);
  await until(()=>/Updated/.test($(w32,'status').textContent));w32.tab('ntf');await wait(50);w32.copyWidget();
  ok(/tap Copy again/.test($(w32,'wjst').textContent)&&n>=2,'not fetched yet (or it failed): says to tap again, and fetches it ('+n+' tries)')}
 /* renamed after the script was fetched: fetched again, with the new name; a late failure of an old fetch doesn't wipe it */
 {let st33=base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true,hostname:'hawki-pico'}),hold=[];const w33=open(()=>st33);
  w33.fetch=(f=>async(u,o)=>{if(u==='/widget.js'){const h=st33.hostname;return new Promise((res,rej)=>hold.push({res:()=>res({ok:true,status:200,text:async()=>'name '+h}),rej:()=>rej(new TypeError('x'))}))}return f(u,o)})(w33.fetch);
  let copied=null;w33.document.execCommand=c=>{copied=w33.document.activeElement&&w33.document.activeElement.value;return true};
  await until(()=>/Updated/.test($(w33,'status').textContent));w33.tab('ntf');await wait(20);
  w33.copyWidget();w33.copyWidget();ok(hold.length===1,'taps while it is still fetching: one fetch, not one per tap ('+hold.length+')');
  hold[0].res();await wait(20);w33.copyWidget();ok(copied==='name hawki-pico','fetched: copies it');
  st33=base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true,hostname:'oil-shed'});await w33.load();w33.copyWidget();await wait(20);
  ok(hold.length===2,'renamed: fetched again');hold[1].res();await wait(20);w33.copyWidget();ok(copied==='name oil-shed','...and the copy has the new name ('+copied+')')}
 /* opened straight onto Notifications (#ntf): the first tap copies */
 {let n=0;const w34=new (require('jsdom').JSDOM)(html,{url:'http://192.168.1.57/#ntf',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
   w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
   w.fetch=async u=>{if(u==='/widget.js'){n++;return {ok:true,status:200,text:async()=>'script'}}const b=u.startsWith('/api/state')?base({via_ap:false,ssid:'HomeNet',ip:'192.168.1.57',pin_set:true}):{};
    return {ok:true,status:200,json:async()=>b,text:async()=>JSON.stringify(b),clone(){return this}}}}}).window;
  let copied=null;w34.document.execCommand=()=>{copied=w34.document.activeElement&&w34.document.activeElement.value;return true};
  await until(()=>/Updated/.test(w34.document.getElementById('status').textContent));await wait(50);w34.copyWidget();
  ok(copied==='script'&&n===1,'opened straight onto Config: the first tap copies, fetched once ('+n+')')}
 /* 7. not the setup Wi-Fi, or already connected: the page as before */
 for(const [o,why] of [[{via_ap:false},'on the home network'],[{ssid:'HomeNet',ip:'192.168.1.57',pin_set:true},'connected already']]){
  const w4=open(()=>base(o));await until(()=>/Updated|Setup/.test($(w4,'status').textContent));await wait(60);
  ok(!vis(w4,'p_setup')&&vis(w4,'p_tanks')&&vis(w4,w4.document.querySelector('.tabs')),why+': the normal page, no setup screen')}
 process.exit(fails?1:0)})();
