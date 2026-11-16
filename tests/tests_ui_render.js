const {JSDOM}=require('jsdom');const fs=require('fs');
const html=fs.readFileSync(process.argv[2],'utf8');
const state={tanks:[{mac:'aa:bb:cc:00:00:01',name:'Back tank',level:701,litres:617.2,percent:46.7,litres_standard:null,battery:62,rssi:-70,age:3,
  cfg:{shape:'cuboid',height_cm:130,length_cm:178,width_cm:75,capacity_l:1323,windows:2,window_model:'measured',outlet_cm:10,win_bottom_cm:57,win_top_cm:80,win_outer_w_cm:30,ribs_cm:[30,68,null]}}],found:[],ssid:'HomeWiFi',ip:'192.168.1.50',ap:null};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
  w.fetch=async()=>({ok:true,json:async()=>state});w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
  w.alert=m=>console.log('ALERT',m);w.onerror=(m)=>console.log('ERR',m)}});
setTimeout(()=>{const w=dom.window;
  w.edit('aa:bb:cc:00:00:01');
  const d=w.document;console.log('meas visible:',d.getElementById('meas').style.display!=='none','rib inputs:',d.querySelectorAll('#ribbox input').length);
  d.getElementById('m_wo').dispatchEvent(new w.FocusEvent('focusin',{bubbles:true}));
  const svg=d.getElementById('viz').outerHTML.replace('<svg ','<svg xmlns="http://www.w3.org/2000/svg" width="800" height="460" ');
  // inline the CSS vars (light theme) so the rasteriser can draw it
  let css=d.querySelector('style').textContent.match(/#viz[^}]*}/g).join('\n').replace(/var\(--fg\)/g,'#1d2433').replace(/var\(--mut\)/g,'#6b7385').replace(/var\(--card\)/g,'#fff').replace(/var\(--oil\)/g,'#c9a43f').replace(/var\(--bg\)/g,'#f4f5f7').replace(/var\(--line\)/g,'#e2e5ea');
  fs.writeFileSync(process.argv[3],svg.replace('>',`><style>${css}</style><rect width="100%" height="100%" fill="#f4f5f7"/>`));
  // save path: rib with missing value must be refused
  w.saveTank({preventDefault(){}});setTimeout(()=>process.exit(0),50);
},300);
