// node tests/tests_forecast.js  - the seasonal model in firmware/common.js.html, without a browser
const fs=require('fs'),vm=require('vm'),path=require('path');
const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'..','firmware','common.js.html'),'utf8')+';this.analyse=analyse;this.hwShape=hwShape;this.heatShape=heatShape;this.wxHeat=wxHeat;this.wxKey=wxKey;this.WX_BASE=WX_BASE;this.howText=howText;',ctx);
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
process.exit(fails?1:0);
