// node tests/tests_forecast.js  - the seasonal model in firmware/common.js.html, without a browser
const fs=require('fs'),vm=require('vm'),path=require('path');
const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'..','firmware','common.js.html'),'utf8')+';this.analyse=analyse;this.hwShape=hwShape;this.heatShape=heatShape;',ctx);
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
 ok(Number.isFinite(A.likely.ord||0),'no NaN with zero heating in the recent window')}
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
process.exit(fails?1:0);
