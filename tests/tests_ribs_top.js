// Ribs are typed by their top edge but saved as centres (ribs_cm).
// NODE_PATH=<dir>/node_modules node tests/tests_ribs_top.js firmware/ui.html
const {JSDOM}=require('jsdom');const fs=require('fs');const path=require('path');
const common=fs.readFileSync(path.join(path.dirname(process.argv[2]),'common.js.html'),'utf8');
const html=fs.readFileSync(process.argv[2],'utf8').replace('<script src="/common.js"></script>',()=>'<script>'+common+'</script>');
const state={tanks:[{mac:'aa:bb:cc:00:00:01',name:'Back tank',level:701,litres:617.2,percent:46.7,battery:62,rssi:-70,age:3,
  cfg:{shape:'cuboid',height_cm:123,length_cm:173,width_cm:69,tank_l:1306,windows:2,window_model:'measured',outlet_cm:9.5,
  win_bottom_cm:45,win_top_cm:79,win_outer_w_cm:39,win_inner_w_cm:17,win_inner_h_cm:14,ribs_cm:[31.5,62.5,93.5],rib_h_cm:12.5,rib_depth_cm:1.5}}],found:[],ssid:'x',ip:'1.2.3.4',ap:null};
let posted=null,fail=0;
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
  w.fetch=async(u,o)=>{if(o&&o.body&&/tank/.test(u))posted=JSON.parse(o.body);return {ok:true,json:async()=>state}};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
  w.alert=m=>{console.log('ALERT',m);fail++};w.onerror=m=>{console.log('ERR',m);fail++}}});
const eq=(a,b,what)=>{const ok=JSON.stringify(a)===JSON.stringify(b);console.log(ok?'ok  ':'FAIL',what,JSON.stringify(a));if(!ok)fail++};
setTimeout(async()=>{const w=dom.window,d=w.document,ins=()=>[...d.querySelectorAll('#ribbox input')];
  w.edit('aa:bb:cc:00:00:01');
  eq(ins().map(i=>i.value),['37.75','68.75','99.75'],'stored centres shown as tops');
  eq(ins().every(i=>i.checkValidity()),true,'tops pass the form validation');
  eq(w.ribVals(),[31.5,62.5,93.5],'tops read back as the same centres');
  eq(d.querySelector('#viz').textContent.includes('37.8'),true,'drawing labels the top edge');
  d.getElementById('m_nr').value='4';w.ribInputs();ins()[3].value='110';
  eq(w.ribVals(),[31.5,62.5,93.5,103.75],'adding a rib keeps the typed tops');
  d.getElementById('m_rh').value='10';eq(w.ribVals(),[32.75,63.75,94.75,105],'band change keeps tops, moves centres');
  d.getElementById('m_rh').value='';eq(w.ribVals()[0],31.75,'blank band uses 12 cm');
  d.getElementById('m_rh').value='12.5';d.getElementById('m_nr').value='3';w.ribInputs();
  ins()[0].value='4';const f0=fail;posted=null;await w.saveTank({preventDefault(){}});await new Promise(r=>setTimeout(r,50));
  eq(fail===f0+1&&posted===null,true,'top below the band height is refused');fail=f0;ins()[0].value='37.75';
  await w.saveTank({preventDefault(){}});await new Promise(r=>setTimeout(r,50));
  eq(posted&&posted.ribs_cm,[31.5,62.5,93.5],'saved as centres');
  console.log(fail?fail+' FAILED':'all passed');process.exit(fail?1:0)},300);
