// node tests/tests_forecast.js  - the seasonal model in firmware/common.js.html, without a browser
const fs=require('fs'),vm=require('vm'),path=require('path');
const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'..','firmware','common.js.html'),'utf8')+';this.analyse=analyse;this.hwShape=hwShape;this.heatShape=heatShape;this.wxHeat=wxHeat;this.windFit=windFit;this.wxParseW=wxParseW;this.wxKey=wxKey;this.WX_BASE=WX_BASE;this.howText=howText;this.likeText=likeText;this.hasFc=hasFc;this.yearFor=yearFor;this.fcBody=fcBody;this.combine=combine;this.holdIsolated=holdIsolated;this.flatten=flatten;',ctx);
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
// a new monitor, one night of readings, with a typical year given: a forecast straight away, from the figure alone
{const now=T(2026,10,20),p=[];for(let t=now-14*H,L=900;t<=now;t+=H,L-=0.4)p.push([t,L]);
 const A=ctx.analyse(p,{now,yearL:2100,reserve:200}),A0=ctx.analyse(p,{now,reserve:200});
 ok(A.recent==null&&A.fromYear&&ctx.hasFc(A)&&A.fc.ord>now+30*DAY&&A.fc.ord<now+200*DAY,'one night + 2,100 L a year: order by '+(A.fc&&new Date(A.fc.ord*1000).toDateString()));
 const jan=A.rate(T(2027,0,15)),jul=A.rate(T(2027,6,15));
 ok(jan>jul*2&&Math.abs(Object.values(A.fmonths).reduce((a,b)=>a+b,0)/400*365-2100)<300,'...spread by the weather: January '+jan.toFixed(1)+' L/day, July '+jul.toFixed(1)+', about 2,100 a year');
 ok(/used as it is/.test(ctx.howText(A))&&!/NaN|undefined/.test(ctx.howText(A)),'...and says it is the figure as given: '+ctx.howText(A).slice(0,90)+'…');
 ok(!ctx.hasFc(A0)&&!A0.fc,'no figure given: no forecast until 2 days of readings, as before')}
// A typical year given, and the real weather: a cold spell reads as a cold spell, not as this house using more
{const norm=[9,8.5,7.5,5.5,3,1,0.3,0.4,1.5,4,6.5,8.5],now=T(2026,10,20),WX=dd=>ctx.WX_BASE-dd,uT=t=>WX(norm[new Date(t*1000).getMonth()]);
 const mk=(dT,fT)=>{const rec={},fc={};for(let t=T(2026,6,1);t<now;t+=DAY){const tm=uT(t)-(t>now-28*DAY?dT:0);rec[ctx.wxKey(t)]=[tm-3,tm+3]}
  for(let t=now;t<now+16*DAY;t+=DAY){const tm=uT(t)-fT;fc[ctx.wxKey(t)]=[tm-3,tm+3]}return [rec,fc,ctx.wxHeat(rec,fc,norm)]};
 const yr=2100,hw=0.9,heatY=(yr-hw*1.125*365)/365;
 /* the house: hot water 0.9 L/day (more in winter), heating 70% of the figure's, in the weather it really had */
 const house=(rec,h)=>{const p=[];let L=1500;for(let t=T(2026,6,6);t<=now;t+=H){const m=new Date(t*1000).getMonth();L-=(hw*ctx.hwShape(t)+(m>=5&&m<=7?0:0.7*heatY*h(t)))/24;p.push([t,L])}return p};
 const [r1,f1,h1]=mk(4,4),A=ctx.analyse(house(r1,h1),{now,heat:h1,wxName:'Coleraine',yearL:yr,reserve:200});
 ok(Math.abs(A.kS-0.7)<0.04,'four weeks 4 C colder than usual: still 70% of the figure\'s heating ('+Math.round(A.kS*100)+'%), not more');
 const t5=now+5*DAY,t40=now+40*DAY;
 ok(Math.abs(A.rate(t5)-(hw*ctx.hwShape(t5)+0.7*heatY*h1(t5)))<0.3,'the next 16 days follow the forecast: '+A.rate(t5).toFixed(2)+' L/day');
 ok(Math.abs(A.rate(t40)-(hw*ctx.hwShape(t40)+0.7*heatY*h1.usual(t40)))<0.3,'after that, the usual weather: '+A.rate(t40).toFixed(2)+' L/day');
 ok(A.like&&A.like.r>1.15&&A.like.ord<A.fc.ord,'"if it stays like this": '+(A.like&&A.like.r.toFixed(2))+' x the usual, order '+(A.like?Math.round((A.fc.ord-A.like.ord)/DAY):'-')+' days sooner');
 const [r2,f2,h2]=mk(-3,-3),M=ctx.analyse(house(r2,h2),{now,heat:h2,wxName:'Coleraine',yearL:yr,reserve:200});
 ok(Math.abs(M.kS-0.7)<0.04&&M.like&&M.like.r<0.9&&M.like.ord>M.fc.ord,'a mild spell works the other way: '+Math.round(M.kS*100)+'%, staying mild orders later');
 const N=ctx.analyse(house(r1,h1),{now,yearL:yr,reserve:200});
 ok(N.like==null&&N.kS>0.75,'no weather for the place: as before, the usual weather throughout ('+Math.round(N.kS*100)+'%), no second view');
 const [r3,f3]=mk(4,4);for(let t=now-10*DAY;t<now;t+=DAY)delete r3[ctx.wxKey(t)];const h3=ctx.wxHeat(r3,f3,norm),G=ctx.analyse(house(r1,h1),{now,heat:h3,yearL:yr,reserve:200});
 ok(G.like==null,'10 of the last 28 days without weather: no "if it stays like this" (it needs 21)')
 {const K=ctx.analyse(house(r1,h1),{now,heat:h3,wxName:'Coleraine',yearL:yr,reserve:200});
  ok(Math.abs(K.kS-A.kS)<0.05,'the last 10 days without weather: the comparison still uses the place\'s weather ('+Math.round(K.kS*100)+'% vs '+Math.round(A.kS*100)+'%), no jump')}
 ok(Math.abs(A.like.seen-1.6)<0.15&&/(5\d|6\d)% colder than usual/.test(ctx.howText(A)),'the words give the weeks as they were ('+Math.round((A.like.seen-1)*100)+'%), not the 50% cap the date uses');
 {const L2={fc:{ord:1},like:{r:1.3,seen:1.3,ord:1}};ok(ctx.likeText(L2,String)===''&&!/second date/.test(ctx.howText(Object.assign({},A,L2))),'the same date either way: no second date, and the words don\'t mention one')}
 ok(/\d+% colder than usual.*the second date/.test(ctx.howText(A))&&/stays this cold/.test(ctx.likeText(A,String)),'the words: '+ctx.likeText(A,()=>'D')+' / '+ctx.howText(A).slice(-150));
 {const nowS=T(2026,6,25),rec={},fc={};for(let t=T(2026,4,1);t<nowS;t+=DAY){const tm=uT(t)-5;rec[ctx.wxKey(t)]=[tm-3,tm+3]}const hS=ctx.wxHeat(rec,fc,norm);
  const p=[];let L=1500;for(let t=T(2026,4,1);t<=nowS;t+=H){L-=1/24;p.push([t,L])}const S=ctx.analyse(p,{now:nowS,heat:hS,yearL:yr,reserve:200});
  ok(S.like==null&&ctx.likeText(S,String)==='','a cold July: no "if it stays this cold" outside the heating season')}}
// weather only for the last few weeks (a new place, or a gap): the weather's way blends in from 14 to 28 days of it, no jump
{const norm=Array(12).fill(5),run=(end,from)=>{const rec={},fc={};for(let t=from;t<end;t+=DAY)rec[ctx.wxKey(t)]=[3.5,3.5];for(let t=end;t<end+16*DAY;t+=DAY)fc[ctx.wxKey(t)]=[3.5,3.5];
  const p=[];let L=800+6*45;for(let t=end-45*DAY;t<=end;t+=H){L-=6/24;p.push([t,L])}return ctx.analyse(p,{now:end,heat:ctx.wxHeat(rec,fc,norm),wxName:'X',yearL:2100,reserve:200})};
 const from=T(2026,9,31);let prev=null,worst=0,wks=0;for(let d=0;d<20;d++){const e=T(2026,10,8)+d*DAY,A=run(e,from),o=A.fc.ord;if(prev!=null){worst=Math.max(worst,Math.abs(A.kS-prev[0]));wks=Math.max(wks,Math.abs((o-prev[1])/DAY))}prev=[A.kS,o]}
 ok(worst<0.08&&wks<12,'blending in day by day: the scale moves at most '+worst.toFixed(3)+' a day, the order date '+wks.toFixed(0)+' days')}
// earlier years are put to the weather (v1.3.22): a cold winter last year is not next winter's forecast, nor a cold spell now a change in use
{const norm=[9,8.5,7.5,5.5,3,1,0.3,0.4,1.5,4,6.5,8.5],per=0.5,hw0=0.85/ctx.hwShape(T(2026,7,15));
 const usT=t=>ctx.WX_BASE-norm[new Date(t*1000).getMonth()];
 /* cold: degree days above the usual on a day (the actual weather) */
 const mk=(from,now,cold)=>{const rec={},fc={};for(let t=from;t<now+16*DAY;t+=DAY){const tm=usT(t)-cold(t);(t<now?rec:fc)[ctx.wxKey(t)]=[tm-3,tm+3]}
  const p=[];let L=1500;for(let t=from;t<now;t+=H){const v=rec[ctx.wxKey(t)]||fc[ctx.wxKey(t)],dd=Math.max(0,ctx.WX_BASE-(v[0]+v[1])/2),m=new Date(t*1000).getMonth();
   L-=(hw0*ctx.hwShape(t)+(m<5||m>7?per*dd:0))/24;if(L<400)L+=1000;p.push([t,L])}
  return{p,h:ctx.wxHeat(rec,fc,norm)}};
 const true_=t=>hw0*ctx.hwShape(t)+per*norm[new Date(t*1000).getMonth()];
 {const now=T(2026,11,1),cold=t=>t>=T(2025,11,1)&&t<T(2026,2,1)?3:t>=now-21*DAY?2:0,{p,h}=mk(T(2025,5,1),now,cold);
  const A=ctx.analyse(p,{now,heat:h,wxName:'X'}),B=ctx.analyse(p,{now}),tj=T(2027,0,15);
  ok(A.useOwn&&Math.abs(A.k-1)<0.05,'a cold 3 weeks now, against last year put to the same weather: '+Math.round(A.k*100)+'% (no weather: '+Math.round(B.k*100)+'%)');
  ok(Math.abs(A.rate(tj)/true_(tj)-1)<0.08,'last January 3 degree days colder than usual: next January '+A.rate(tj).toFixed(2)+' vs usual-weather '+true_(tj).toFixed(2)+' (as it was: '+B.rate(tj).toFixed(2)+')');
  ok(B.rate(tj)>1.15*true_(tj),'...where taking it as it was would have forecast it high');
  const t5=now+5*DAY;ok(Math.abs(A.rate(t5)/(hw0*ctx.hwShape(t5)+per*(norm[11]+2))-1)<0.1,'the next 16 days follow the forecast (still cold): '+A.rate(t5).toFixed(2));
  ok(Math.abs(A.rate(T(2027,6,15))-hw0*ctx.hwShape(T(2027,6,15)))<0.15,'summer: hot water as it was');
  ok(A.like&&A.like.ord<A.fc.ord,'"if it stays this cold" also on earlier years: '+(A.like&&new Date(A.like.ord*1000).toDateString()));
  ok(/its heating put to X's weather/.test(ctx.howText(A)),'and the words say so')}
 {/* one year with a typical-year figure: next January goes by this January, put to the usual weather */
  const now=T(2026,10,15),cold=t=>t<T(2026,2,1)?3:0,{p,h}=mk(T(2025,11,1),now,cold);
  const A=ctx.analyse(p,{now,heat:h,wxName:'X',yearL:2500}),tj=T(2027,0,15);
  ok(!A.useOwn&&Math.abs(A.rate(tj)/true_(tj)-1)<0.08,'a figure and a cold January of your own: next January '+A.rate(tj).toFixed(2)+' vs usual-weather '+true_(tj).toFixed(2))}}
// one old reading pasted in (Earlier readings), then the Pico's own hourly readings from 3 weeks later: a rate from those
{const t0=T(2026,10,19),p=[[T(2026,9,29),524]];for(let t=t0,L=310;t<t0+4*DAY;t+=H){L-=9.5/24;p.push([t,L])}
 const A=ctx.analyse(p,{now:t0+4*DAY});ok(A.recent!=null&&Math.abs(A.recent-9.5)<0.6&&A.span>=2&&ctx.hasFc(A),'an old pasted reading 3 weeks before: still a rate from the 4 days since ('+(A.recent&&A.recent.toFixed(2))+' L/day, true 9.5)')}
{/* only one reading after the gap, or under 2 days since it: no rate yet (as for a first start), never NaN */
 const a=T(2026,9,29),b=T(2026,10,19);let A=ctx.analyse([[a,710],[b,500]],{now:b});ok(A.recent==null&&!ctx.hasFc(A),'one reading 3 weeks after another: no rate yet');
 const p=[[a,710]];for(let t=b;t<b+30*H;t+=H)p.push([t,500-10*(t-b)/DAY]);A=ctx.analyse(p,{now:b+30*H});ok(A.recent==null,'30 hours of readings after the gap: not yet');
 const y=ctx.analyse([[a,710],[b,500]],{now:b,yearL:2000});ok(y.fc&&Number.isFinite(y.rate(b+DAY))&&Number.isFinite(y.fc.ord||0),'...with a typical year given: that forecast, finite')}
// the steady fall (v1.3.43): readings flickering a 5 mm step (3.6 L) up and down give no negative days and the same total
{const t0=T(2026,10,10)-12*H,p=[];for(let k=0;k<10*24;k++){const t=t0+k*H,lv=800-7*k/24,q=Math.floor(lv/3.6)*3.6+(k%5===2?3.6:0);p.push([t,q])}
 const A=ctx.analyse(p,{now:p[p.length-1][0]}),d=Object.values(A.days);
 ok(d.length>=8&&d.every(v=>v>=0),'flicker: no day reads as oil gained ('+d.map(v=>v.toFixed(1)).join(' ')+')');
 ok(Math.abs(d.slice(1,-1).reduce((a,b)=>a+b,0)/(d.length-2)-7)<1.5,'flicker: about the 7 L a day used');
 ok(A.fit.length===p.length&&A.fit.every((f,k)=>!k||f[1]<=A.fit[k-1][1]+1e-9),'out.fit: one per reading, never rising without a delivery')}
// deliveries under 30 L (a jerry can): only once 2 more readings confirm them; a single spike, or the newest reading alone, never
{const h=T(2026,10,10),mk=a=>a.map((v,k)=>[h+k*H,v]);
 ok(!ctx.analyse(mk([500,500,500,500,520]),{now:h+5*H}).fills.length,'the newest reading 20 L up: not a delivery yet');
 ok(!ctx.analyse(mk([500,500,520,500,500,500]),{now:h+6*H}).fills.length,'one reading 20 L up between others: not a delivery');
 const A=ctx.analyse(mk([500,500,500,520,520,520,520]),{now:h+7*H});ok(A.fills.length===1&&Math.abs(A.fills[0].add-20)<1,'20 L that holds: a delivery of 20 L');
 ok(ctx.analyse(mk([500,500,500,560]),{now:h+4*H}).fills.length===1,'60 L: a delivery at once, as before')}
// 12. wind: a house that loses heat faster on windy days (each km/h over the usual counts as 0.25 C colder)
{const norm=[9,8.5,7.5,5.5,3,1,0.3,0.4,1.5,4,6.5,8.5],normw=[22,21,20,18,16,15,14,14,16,18,20,21],now=T(2026,10,16),rec={},fc={},wind={},fwind={};let sd=7;const rnd=()=>(sd=(sd*16807)%2147483647)/2147483647;
 const uw=t=>{const m=new Date(t*1000).getMonth();return normw[m]};  /* (the test's usual wind: the month's; the page blends between months, close enough for k) */
 for(let t=T(2026,5,1);t<now+16*DAY;t+=DAY){const m=new Date(t*1000).getMonth(),tm=ctx.WX_BASE-norm[m]+(rnd()-0.5)*8,k=ctx.wxKey(t);(t<now?rec:fc)[k]=[tm-3,tm+3];(t<now?wind:fwind)[k]=Math.round((uw(t)-12+rnd()*24)*10)/10}
 fc[ctx.wxKey(now+3*DAY)]=fc[ctx.wxKey(now+4*DAY)].slice();fwind[ctx.wxKey(now+3*DAY)]=45;fwind[ctx.wxKey(now+4*DAY)]=5;  /* two forecast days alike but for the wind */
 const H0=ctx.wxHeat(rec,fc,norm,wind,fwind,normw),run=(kTrue,fw)=>{const p=[];let L=1500;for(let t=T(2026,5,1);t<now;t+=H){const k=ctx.wxKey(t),v=rec[k],dd=Math.max(0,ctx.WX_BASE-(v[0]+v[1])/2+kTrue*(wind[k]-H0.wref(t)));
   L-=(0.85+0.5*dd)/24;p.push([t,L])}return ctx.analyse(p,{now,heat:ctx.wxHeat(rec,fc,norm,wind,fw||fwind,normw),wxName:'Coleraine'})};
 const A=run(0.25),B=run(0),C=ctx.analyse([[now-30*DAY,900],[now,800]],{now,heat:ctx.wxHeat(rec,fc,norm,wind,fwind,null)});
 ok(A.wind&&Math.abs(A.wind.k-0.25)<=0.04&&A.wind.n>=28,'windy days cost this house more: fitted '+(A.wind&&A.wind.k.toFixed(2))+' C per km/h (true 0.25) from '+(A.wind&&A.wind.n)+' days');
 ok(A.rate(now+3*DAY)-A.rate(now+4*DAY)>0.5*0.25*40*0.6,'a windy forecast day (45 km/h) forecasts more than a calm one (5 km/h) as cold, near the 5 L a day it truly costs: '+A.rate(now+3*DAY).toFixed(2)+' vs '+A.rate(now+4*DAY).toFixed(2));
 ok(B.wind&&B.wind.k===0&&Math.abs(B.rate(now+3*DAY)-B.rate(now+4*DAY))<0.01,'a house the wind makes no difference to: none counted ('+(B.wind&&B.wind.gain.toFixed(2))+')');
 ok(!(C.wind&&C.wind.k)&&ctx.wxHeat(rec,fc,norm,wind,fwind,null).withWind===undefined&&ctx.wxHeat(rec,fc,norm,wind,fwind,[1,2]).withWind===undefined,'no usual wind yet (an older Pico, a shared view, the 10 years still coming): temperature alone');
 const fw2={...fwind};for(const k in fw2)fw2[k]=60;const A2=run(0.25,fw2),tp=now-20*DAY,t30=now+30*DAY;
 ok(A2.wind.k===A.wind.k&&A2.wxh(tp)===A.wxh(tp)&&Math.abs(A2.rate(t30)-A.rate(t30))<1e-9,'a stormier forecast changes neither the fit, nor how past days count, nor the forecast past its 16 days');
 const recA={...rec};delete recA[ctx.wxKey(now-DAY)];const fcA={...fc,[ctx.wxKey(now-DAY)]:rec[ctx.wxKey(now-DAY)]},wA={...wind,[ctx.wxKey(now-DAY)]:99},fwA={...fwind,[ctx.wxKey(now-DAY)]:7};
 ok(ctx.wxHeat(recA,fcA,norm,wA,fwA,normw).wind(now-DAY)===7,'a day the archive hasn\'t got yet: its wind from the forecast, as its temperature');
 const b=new ArrayBuffer(8),v=new DataView(b);v.setUint16(0,9800,true);v.setUint16(2,234,true);v.setUint16(4,9801,true);v.setUint16(6,65535,true);
 const pw=ctx.wxParseW(b);ok(Object.keys(pw).length===1&&Object.values(pw)[0]===23.4,'wind file: km/h x10, 65535 = none')}
// 13. a clock change: the 23-hour day in March is a whole day for the wind fit
{const norm=Array(12).fill(10),normw=Array(12).fill(20),rec={},wind={},days={},gap={};
 for(let i=0;i<28;i++){const t=new Date(2026,2,2+i).getTime()/1000,k=ctx.wxKey(t+DAY/2),tm=3+i%5;rec[k]=[tm,tm];wind[k]=i%2?30:10;days[t]=2+ctx.WX_BASE-tm+0.2*(wind[k]-20)}
 const h=ctx.wxHeat(rec,{},norm,wind,{},normw),f=ctx.windFit(days,gap,h,new Date(2026,2,30).getTime()/1000);
 ok(f.n===28&&Math.abs(f.k-0.2)<0.021,'28 days across the spring clock change all count: '+f.n+' days, k '+f.k)}
// 14. the average year in the weather a day really had (the monthly chart's "allowing for the weather")
{const norm=[9,8.5,7.5,5.5,3,1,0.3,0.4,1.5,4,6.5,8.5],now=T(2026,10,20),rec={},fc={};
 for(let t=T(2026,5,1);t<now;t+=DAY){const m=new Date(t*1000).getMonth(),tm=ctx.WX_BASE-norm[m]*(m===10?1.5:1);rec[ctx.wxKey(t)]=[tm-2,tm+2]}  /* November half as cold again as usual */
 const h=ctx.wxHeat(rec,fc,norm),p=[];let L=1500;for(let t=T(2026,5,1);t<now;t+=H){L-=2/24;p.push([t,L])}
 const A=ctx.analyse(p,{now,heat:h,yearL:2000}),tn=T(2026,10,10),to=T(2026,9,16);  /* (mid-month: the usual weather is the month's own, not blended with the next) */
 ok(A.avgWx(to)>0&&Math.abs(A.avgWx(to)/A.avg(to)-1)<0.01,'a day of usual weather: the same as the average year ('+A.avgWx(to).toFixed(2)+' vs '+A.avg(to).toFixed(2)+')');
 ok(A.avgWx(tn)>A.avg(tn)*1.3,'a day half as cold again: the average year needs more heating that day ('+A.avgWx(tn).toFixed(2)+' vs '+A.avg(tn).toFixed(2)+')');
 ok(A.avgWx(now+30*DAY)===null&&ctx.analyse(p,{now,yearL:2000}).avgWx(tn)===null,'no weather that day (to come, or none set): none')
 const rec2={...rec};for(let t=now-7*DAY;t<now;t+=DAY)delete rec2[ctx.wxKey(t)];const A2=ctx.analyse(p,{now,heat:ctx.wxHeat(rec2,fc,norm)});
 ok(A2.avgWx(to)===null,'no typical year, and the last week without weather (the model falls back to the built-in shape): none, never a different baseline')}
process.exit(fails?1:0);
