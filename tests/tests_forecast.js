// node tests/tests_forecast.js  - the seasonal model in firmware/common.js.html, without a browser
const fs=require('fs'),vm=require('vm'),path=require('path');
const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'..','firmware','common.js.html'),'utf8')+';this.analyse=analyse;this.hwShape=hwShape;this.heatShape=heatShape;this.wxHeat=wxHeat;this.wxKey=wxKey;this.WX_BASE=WX_BASE;this.howText=howText;this.yearFor=yearFor;this.fcBody=fcBody;this.combine=combine;this.holdIsolated=holdIsolated;this.flatten=flatten;',ctx);
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const DAY=86400,H=3600,T=(y,m,d)=>new Date(y,m,d,12).getTime()/1000;
// a household: hot water 0.85 L/day in August (+25 % in Feb), heating only Sep-May
function series(from,to,heat){const p=[];let L=1000;for(let t=from;t<to;t+=H){const d=new Date(t*1000),m=d.getMonth();
 L-=(0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(t)+(heat&&(m<5||m>7)?heat*ctx.heatShape(t):0))/24;p.push([t,L])}return p}
// 1. summer-only data: the forecast for next August is the measured baseline, not a heating guess
{const now=T(2026,8,1),A=ctx.analyse(series(T(2026,5,1),now,0),{now});
 ok(A.hw&&Math.abs(A.hw.perDay-0.85)<0.05,'summer baseline measured: '+(A.hw&&A.hw.perDay.toFixed(2))+' L/day');
 const aug=A.rate(T(2027,7,15)),jan=A.rate(T(2027,0,15));
 ok(Math.abs(aug-0.85)<0.1,'next August forecast '+aug.toFixed(2)+' L/day');
 ok(jan>4&&Number.isFinite(jan),'January still forecasts heating (typical share): '+jan.toFixed(1)+' L/day');
 ok(Number.isFinite(A.fc.ord||0),'no NaN with zero heating in the recent window')}
// 2. into the heating season: heating sized from recent use, summer still at the baseline
{const now=T(2026,10,16),A=ctx.analyse(series(T(2026,5,1),now,4),{now});
 ok(A.heatFit===1,'heating fitted from recent use');
 const jan=A.rate(T(2027,0,15)),exp=0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(T(2027,0,15))+4*ctx.heatShape(T(2027,0,15));
 ok(Math.abs(jan-exp)/exp<0.1,'January '+jan.toFixed(2)+' vs true '+exp.toFixed(2));
 ok(Math.abs(A.rate(T(2027,6,15))-0.85)<0.15,'July back to hot water only: '+A.rate(T(2027,6,15)).toFixed(2))}
// 3. no summer data yet: falls back to the typical 15 % share
{const now=T(2026,10,16),A=ctx.analyse(series(T(2026,9,1),now,4),{now});
 ok(!A.hw&&A.recent>0&&Number.isFinite(A.rate(T(2027,0,15))),'no baseline: typical-share model, finite forecast')}
// 4. June: a heating week then a missed 29 L top-up must not drag the baseline far from 1 L/day
{const p=[];let L=500;const t0=T(2026,5,1);for(let t=t0;t<t0+24*DAY;t+=H){const d=(t-t0)/DAY;L-=(d<7?4:1)/24;if(Math.abs(t-T(2026,5,9))<H/2)L+=29;p.push([t,L])}
 const A=ctx.analyse(p,{now:t0+24*DAY});ok(A.hw&&A.hw.perDay>=0.8,'odd June: baseline '+(A.hw&&A.hw.perDay.toFixed(2))+' L/day (true hot water 1.0) is not too low')}
// 5. oil warming/cooling: a steady +-2 L drift across a month (about 6 C on a 600 L tank) moves the baseline under 20 %.
//    (Known limit: a one-way 8 L drift in a month would read ~28 % low; summer air temperature rarely shifts that much.)
{const p=[];const t0=T(2026,6,1);for(let t=t0;t<t0+30*DAY;t+=H){const d=(t-t0)/DAY;p.push([t,600-d-2*Math.cos(Math.PI*d/30)])}
 const A=ctx.analyse(p,{now:t0+30*DAY});ok(A.hw&&A.hw.perDay>0.8,'drifting July: baseline '+(A.hw&&A.hw.perDay.toFixed(2))+' L/day (true 1.0)')}
// 6. under 21 summer days: no baseline yet
{const p=[];const t0=T(2026,6,1);for(let t=t0;t<t0+16*DAY;t+=H)p.push([t,600-(t-t0)/DAY]);ok(!ctx.analyse(p,{now:t0+16*DAY}).hw,'16 summer days: no baseline yet')}
// 7. a second year using a steady 10 % more (older boiler): the forecast carries the 10 % on
{const p=[];let L=5000;const t0=T(2024,8,1),t1=T(2026,2,1);
 for(let t=t0;t<t1;t+=H){const yr2=t>=T(2025,8,1),d=new Date(t*1000),m=d.getMonth();
  const base=0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(t)+(m<5||m>7?6*ctx.heatShape(t):0);
  L-=base*(yr2?1.1:1)/24;if(L<300)L+=3000;p.push([t,L])}
 const A=ctx.analyse(p,{now:t1});
 ok(A.useOwn&&Math.abs(A.k-1.1)<0.03&&A.kDays>100,'steady +10 % year: scaled by '+(A.k&&A.k.toFixed(3))+' over '+A.kDays+' days');
 const tt=T(2026,3,15),want=1.1*(0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(tt)+6*ctx.heatShape(tt));
 ok(Math.abs(A.rate(tt)/want-1)<0.08,'April forecast '+A.rate(tt).toFixed(2)+' vs this year\'s rate '+want.toFixed(2)+' L/day');
 ok(A.fc&&A.fc.dry>t1,'one forecast, no extra margin added')}
// 8. heating follows the real weather: a fortnight 6 C colder than usual just before 'now'
{const norm=[9,8.5,7.5,5.5,3,1,0.3,0.4,1.5,4,6.5,8.5],now=T(2026,10,16);  /* usual degree days a day, by month */
 const rec={},fc={};const usualT=t=>{const m=new Date(t*1000).getMonth();return WX(norm[m])};function WX(dd){return ctx.WX_BASE-dd}
 for(let t=T(2026,5,1);t<now;t+=DAY){const tm=usualT(t)-(t>now-14*DAY?6:0);rec[ctx.wxKey(t)]=[tm-3,tm+3]}
 for(let t=now;t<now+16*DAY;t+=DAY){const tm=usualT(t);fc[ctx.wxKey(t)]=[tm-3,tm+3]}  /* the forecast: back to normal */
 const h=ctx.wxHeat(rec,fc,norm);ok(typeof h==='function','wxHeat builds from 12 monthly averages');
 ok(ctx.wxHeat(rec,fc,[1,2])===null&&ctx.wxHeat(rec,fc,null)===null,'no usable averages: no weather model (built-in UK shape instead)');
 /* true use: 0.85 L/day hot water + 0.5 L per degree day */
 const per=0.5,p=[];let L=1200;for(let t=T(2026,5,1);t<now;t+=H){const v=rec[ctx.wxKey(t)],dd=Math.max(0,ctx.WX_BASE-(v[0]+v[1])/2);
  const m=new Date(t*1000).getMonth();L-=(0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(t)+(m<5||m>7?per*dd:0))/24;p.push([t,L])}
 const A=ctx.analyse(p,{now,heat:h,wxName:'Coleraine'}),B=ctx.analyse(p,{now});
 const tj=T(2027,0,15),want=0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(tj)+per*norm[0];
 ok(Math.abs(A.rate(tj)/want-1)<0.12,'after a cold snap, January with the weather: '+A.rate(tj).toFixed(2)+' vs true '+want.toFixed(2)+' (built-in UK shape says '+B.rate(tj).toFixed(2)+')');
 ok(A.rate(tj)<B.rate(tj),'the cold fortnight is not taken as the new normal');
 const t5=now+5*DAY,w5=0.85/ctx.hwShape(T(2026,7,15))*ctx.hwShape(t5)+per*norm[10];
 ok(Math.abs(A.rate(t5)/w5-1)<0.15,'next week follows the forecast: '+A.rate(t5).toFixed(2)+' vs '+w5.toFixed(2));
 ok(/Coleraine's weather: the next 16 days/.test(ctx.howText(A))&&/typical UK year/.test(ctx.howText(B)),'the words name the source: '+ctx.howText(A).slice(0,160))}
// 9. recent days missing their weather: the fit would be skewed, so the built-in shape is used instead
{const norm=[9,8.5,7.5,5.5,3,1,0.3,0.4,1.5,4,6.5,8.5],now=T(2026,10,16),rec={},fc={};
 for(let t=T(2026,5,1);t<now-7*DAY;t+=DAY)rec[ctx.wxKey(t)]=[2,8];
 const p=[];let L=900;for(let t=T(2026,5,1);t<now;t+=H){L-=3/24;p.push([t,L])}
 const A=ctx.analyse(p,{now,heat:ctx.wxHeat(rec,fc,norm),wxName:'Coleraine'});
 ok(A.wx===null&&/typical UK year/.test(ctx.howText(A)),'a week of missing weather: built-in shape, and the words say so')}
// 10. two tanks: one in use (6 L/day, in 3.5 L steps), one idle and jittering 0 / 2 / 7 L, starting later
{const now=T(2026,10,17),q=v=>Math.round(v/3.5)*3.5,a=[],b=[];let L=600;
 for(let t=now-20*DAY;t<=now;t+=H){L-=6/24*(new Date(t*1000).getHours()<7?0.2:1.3);a.push([t,q(L)])}
 const jit=[2.1,7.4,0,2.1,7.4,2.1,7.4,7.4,2.1,0];let i=0;for(let t=now-DAY;t<=now;t+=H)b.push([t+60,jit[i++%jit.length]]);
 const A1=ctx.analyse(a,{now}),AC=ctx.analyse(ctx.combine([a,b]),{now});
 ok(Math.abs(AC.avgs[3]-A1.avgs[3])<0.3&&Math.abs(AC.avgs[7]-A1.avgs[7])<0.3,'idle tank jitter does not move the combined use: 3-day '+AC.avgs[3].toFixed(2)+' vs '+A1.avgs[3].toFixed(2)+', 7-day '+AC.avgs[7].toFixed(2)+' vs '+A1.avgs[7].toFixed(2));
 ok(Math.abs(A1.avgs[3]-6)<0.6,'3-day use from a line through the readings, not two end readings: '+A1.avgs[3].toFixed(2)+' L/day (true 6)');
 const slow=[];let S2=500;for(let t=now-10*DAY;t<=now;t+=H){S2-=0.9/24;slow.push([t,q(S2)])}
 const fl=ctx.flatten(slow);ok(fl[0][1]-fl[fl.length-1][1]>5,'a tank slowly in use (0.9 L/day, summer hot water) is not flattened: '+(fl[0][1]-fl[fl.length-1][1]).toFixed(1)+' L over 10 days')}
// 11. full-day averages match the chart's bars; an isolated tank never counts as use but its deliveries do
{const now=T(2026,10,17)+3*H,p=[];let L=800;const per=[9,9,9,9,8.7,6.4,7.0];  /* the last three days: 8.7, 6.4, 7.0 */
 for(let d=0;d<per.length;d++)for(let h=0;h<24;h++){p.push([T(2026,10,10+d)-12*H+h*H,L]);L-=per[d]/24}p.push([now,L]);
 const A=ctx.analyse(p,{now});ok(Math.abs(A.avgs[3]-(8.7+6.4+7.0)/3)<0.25,'3-day average = the last 3 full days: '+A.avgs[3].toFixed(2)+' (bars 8.7, 6.4, 7.0 -> 7.37)');
 const a=p.map(x=>[x[0],x[1]]),b=p.map((x,i)=>[x[0]+60,(i%3?2.1:7.4)+(i>40?500:0)]);  /* isolated: jitter, and a 500 L delivery */
 const C=ctx.analyse(ctx.combine([a,b],[false,true]),{now});
 ok(Math.abs(C.avgs[3]-A.avgs[3])<0.2,'isolated tank jitter not counted: '+C.avgs[3].toFixed(2)+' vs '+A.avgs[3].toFixed(2));
 ok(C.fills.length===1&&Math.abs(C.fills[0].add-500)<10,'a delivery into the isolated tank still shows: '+(C.fills[0]&&Math.round(C.fills[0].add))+' L')}
// 12. isolated since a time: readings before it are left alone (marking it today must not rewrite past use)
{const now=T(2026,10,15),p=[];for(let i=0;i<=336;i++)p.push([now-14*DAY+i*H,600-2*i/24]);const cut=now;
 const h=ctx.holdIsolated(p,cut);ok(h.every((x,i)=>x[1]===p[i][1]),'isolated from now: none of the 14 days of use before it is changed');
 const h2=ctx.holdIsolated(p.concat([[now+H,572.3],[now+2*H,571.8]]),cut);ok(Math.abs(h2[h2.length-1][1]-(572+572.3+571.8)/3)<0.01,'readings from the isolation time on are held: '+h2[h2.length-1][1].toFixed(2));
 const all=ctx.holdIsolated(p,true);ok(all[all.length-1][1]>580,'true (older settings) still holds every reading');
 const C=ctx.analyse(ctx.combine([p],[cut]),{now});ok(C.recent>1.5,'use before the isolation time still counts: '+(C.recent||0).toFixed(2)+' L/day')}
// 13. right after a delivery the forecast starts from the new level, not the old one (median of the last 4 readings
//     straddled the delivery for the first 2 readings: 'Order now' straight after a fill)
{const now=T(2026,10,16),p=[];let L=200;for(let t=now-20*DAY;t<now-2*H;t+=H){L-=8/24;p.push([t,L])}const low=L;
 for(const k of [1,2,3]){const q=p.slice();for(let j=k;j>=1;j--)q.push([now-(j-1)*H,low+900-(k-j)*8/24]);
  const A=ctx.analyse(q,{now,reserve:200});
  ok(A.fills.length===1&&Math.abs(A.cur-(low+900))<5&&A.fc&&A.fc.ord>now+30*DAY,k+' reading(s) after a +900 L delivery: starts from '+Math.round(A.cur)+' L (real '+Math.round(low+900)+'), order '+(A.fc&&A.fc.ord?Math.round((A.fc.ord-now)/DAY)+' days away':'-'))}}
{const now=T(2026,10,16),p=[];let L=200;for(let t=now-20*DAY;t<now-2*H;t+=H){L-=8/24;p.push([t,L])}const low=L;
 p.push([now-H,low+400],[now,low+900]);const A=ctx.analyse(p,{now,reserve:200});  /* read once while the tanker was still pumping */
 ok(Math.abs(A.cur-(low+900))<5,'a delivery read part-way: starts from the full level '+Math.round(A.cur)+' L (real '+Math.round(low+900)+')')}
// A typical year's oil given in Config stands in for LAST YEAR: each month is forecast from its curve, scaled by how
// this year is running against it; a month with real readings from an earlier year goes by those alone, never mixed.
{const J=(y)=>T(y,0,15),monthSum=(f,y,m)=>{let s=0;const n=new Date(y,m+1,0).getDate();for(let d=1;d<=n;d++)s+=f(T(y,m,d));return s};
 /* a house: hot water 0.9 L/day in August (more in winter), and the rest of 2,100 L a year on heating; under(f) = that heating x f */
 const hwD=t=>0.9*ctx.hwShape(t),heatD=t=>(2100-0.9*1.125*365)/365*ctx.heatShape(t),curve=t=>hwD(t)+heatD(t),summer=t=>{const m=new Date(t*1000).getMonth();return m>=5&&m<=7},under=f=>t=>hwD(t)+(summer(t)?0:f*heatD(t)),  /* (heating off June to August, so August is hot water alone) */plain=t=>2100/365*(0.15*ctx.hwShape(t)/1.125+0.85*ctx.heatShape(t));
 const run=(from,to,f)=>{const p=[];let L=9000;for(let t=from;t<=to;t+=H){L-=f(t)/24;p.push([t,L])}return p};
 {const now=T(2026,10,18),A=ctx.analyse(run(T(2026,7,6),now,t=>under(0.8)(t)),{now,yearL:2100}),A0=ctx.analyse(run(T(2026,7,6),now,t=>under(0.8)(t)),{now});
  ok(Math.abs(A.kS-0.8)<0.03&&A.kSHw&&Math.abs(A.hw.perDay-0.9)<0.05&&A.kSDays>40&&A.kSDays<70,'hot water measured in August (0.9 L/day), heating a fifth under the figure since: '+Math.round(A.kS*100)+'% over '+A.kSDays+' days');
  const jan=monthSum(A.rate,2027,0),fig=monthSum(curve,2027,0);
  ok(Math.abs(jan-monthSum(under(0.8),2027,0))<8&&jan<0.83*fig,'January: your hot water as it is + four fifths of the figure\'s heating: '+Math.round(jan)+' L (figure '+Math.round(fig)+')');
  ok(Math.abs(monthSum(A.avg,2027,0)-fig)<2&&A.avgSrc(J(2027))==='given','the average-year line is the figure itself: '+Math.round(monthSum(A.avg,2027,0)));
  ok(/Last year stands in.*2,100 L.*hot water is your own: 0\.9\d L\/day.*heating is scaled.*(79|80|81)% over the \d+ days of the heating season so far/.test(ctx.howText(A)),'and the words say so: '+ctx.howText(A).slice(0,150))}
 {const now=T(2026,7,16),A=ctx.analyse(run(T(2026,7,6),now,t=>0.5*curve(t)),{now,yearL:2100});
  ok(A.kS===1&&!A.kSHw&&Math.abs(A.rate(J(2027))-plain(J(2027)))<0.01,'under 14 days of readings: the figure as it is ('+A.rate(J(2027)).toFixed(1)+' L/day in January)')}
 {const now=T(2026,10,18),A=ctx.analyse(run(T(2026,7,6),now,under(0.1)),{now,yearL:2100});
  ok(A.kS===0.3,'a figure far too high: its heating is followed down only to 30%')}
 {const now=T(2026,8,5),A=ctx.analyse(run(T(2026,7,6),now,under(0.8)),{now,yearL:2100});
  ok(A.kSHw&&A.kS===1,'summer only: hot water measured, but no heating yet to compare, so the figure\'s heating as it is')}
 {const now=T(2026,10,18),A=ctx.analyse(run(T(2026,8,20),now,t=>0.8*plain(t)),{now,yearL:2100});
  ok(!A.kSHw&&Math.abs(A.kS-0.8)<0.02&&Math.abs(A.rate(J(2027))-0.8*plain(J(2027)))<0.15,'no summer month of readings: hot water stays at 15% and the whole figure is scaled ('+Math.round(A.kS*100)+'%)')}
 /* summer only, whatever was used: nothing to say about the heating, so the figure's winter stands, and it does not jump the day the hot water is first measured */
 for(const use of [0,0.9,4]){const jan=d=>{const now=T(2026,7,1)+d*DAY,A=ctx.analyse(run(T(2026,7,1),now,()=>use),{now,yearL:2100});return [monthSum(A.rate,2027,0),A.kS,A.kSHw]};
  const b=jan(20),a=jan(23),far=jan(29);/* (4 L/day of hot water is most of the figure: once measured, less of it is left for heating, so January rightly comes down; the scale itself never moves) */
  ok(b[1]===1&&a[1]===1&&far[1]===1&&(use===4?a[0]<b[0]&&a[0]>200:Math.abs(a[0]-b[0])<0.16*b[0])&&b[0]>280,use+' L/day all August: January '+Math.round(b[0])+' L before the hot water is measured, '+Math.round(a[0])+' after ('+(a[2]?'measured':'not')+'), '+Math.round(far[0])+' at the end')}
 {const A=ctx.analyse(run(T(2026,5,1),T(2026,5,30),()=>0.9),{now:T(2026,5,30),yearL:2100});ok(A.kS===1&&monthSum(A.rate,2027,0)>300,'hot water only all June: the winter forecast is not cut ('+Math.round(monthSum(A.rate,2027,0))+' L in January)')}
 {const j=y=>{const now=T(2026,8,1),A=ctx.analyse(run(T(2026,7,1),now,()=>0.9),{now,yearL:y});return [monthSum(A.rate,2027,0),A.kSHwCap,ctx.howText(A)]},a=j(615),b=j(616),c=j(100);
  ok(Math.abs(a[0]-b[0])<1&&a[1]&&!b[1],'a figure about the size of your hot water alone: no jump as it crosses 60% ('+a[0].toFixed(1)+' -> '+b[0].toFixed(1)+' L in January)');
  ok(c[0]>0&&isFinite(c[0])&&/looks too small/.test(c[2])&&!/0\.90 L\/day/.test(c[2]),'a figure far too small: a sane rate, and the words say it looks too small')}
 /* the worked example: figure Jan 340; Jan 2027 really 240 -> Jan 2028 is forecast from 240, not from an average with 340 */
 {const now=T(2027,10,18),use=t=>(t>=T(2027,0,1)-DAY/2&&t<T(2027,1,1)-DAY/2?240/31:under(0.8)(t)),p=run(T(2026,7,6),now,use),A=ctx.analyse(p,{now,yearL:2100});
  const j28=monthSum(A.rate,2028,0);
  ok(A.useOwn&&Math.abs(A.k-1)<0.03,'second winter: compared with your own last year ('+Math.round(A.k*100)+'%)');
  ok(Math.abs(j28-240)<14,'January 2028 goes by the 240 L of January 2027, not an average with the figure\'s 340: '+Math.round(j28)+' L');
  ok(Math.abs(monthSum(A.avg,2028,0)-240)<14&&A.avgSrc(J(2028))==='own','and the average-year line for January is that 240 L: '+Math.round(monthSum(A.avg,2028,0)));
  ok(A.avgSrc(T(2027,6,15))==='given'&&Math.abs(monthSum(A.avg,2027,6)-monthSum(curve,2027,6))<1,'July, before the readings began: still the figure, as it is');
  ok(/Dates with no earlier year of your own yet go by the 2,100 L/.test(ctx.howText(A)),'and the words say so')}
 /* readings from January, now November of the same year: next January goes by the real January already */
 {const now=T(2026,10,18),use=t=>new Date(t*1000).getMonth()===0?240/31:under(0.8)(t),A=ctx.analyse(run(T(2026,0,1),now,use),{now,yearL:2100}),j=monthSum(A.rate,2027,0);
  ok(!A.useOwn&&Math.abs(j-240)<14,'a first year that began in January: next January is the real 240 L, not the figure ('+Math.round(j)+' L)')}
 /* a third year: the average of the two real Januaries only */
 {const now=T(2028,10,18),use=t=>{const d=new Date(t*1000);return d.getMonth()===0?(d.getFullYear()===2027?240:235)/31:under(0.8)(t)},A=ctx.analyse(run(T(2026,7,6),now,use),{now,yearL:2100});
  const a=monthSum(A.avg,2029,0);ok(Math.abs(a-237.5)<12,'two real Januaries (240, 235): the average is theirs alone, '+Math.round(a)+' L, never pulled up by the figure\'s 340')}
 /* no figure given: nothing here changes a forecast with no earlier years */
 {const now=T(2026,10,18),p=run(T(2026,7,6),now,t=>under(0.8)(t)),A=ctx.analyse(p,{now});ok(A.kS===null&&A.yearL===null&&A.avgSrc(J(2027))==='model','no figure: the forecast is your own readings and the weather, as before')}
 ok(ctx.yearFor({year_l:2100,tanks:[{mac:'a',cfg:{}},{mac:'b',cfg:{mode:'off'}}]},['a'])===2100&&ctx.yearFor({year_l:2100,tanks:[{mac:'a',cfg:{}},{mac:'b',cfg:{}}]},['a'])===null&&ctx.yearFor({tanks:[]},[])===null,'the figure is the whole house\'s: used only for a view holding every tank in use');
 ok(ctx.yearFor({year_l:2100,tanks:[{mac:'a',cfg:{mode:'standby'}}]},['a'])===null,'no tank in use: the figure is not applied')}
process.exit(fails?1:0);
