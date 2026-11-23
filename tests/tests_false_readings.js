// node tests/tests_false_readings.js  - parse() (common.js) leaves out a false reading: one far from the readings either
// side that agree with each other (a lone 'nearly empty' code 16382 in a part-full tank, say), and nothing else.
const fs=require('fs'),vm=require('vm'),path=require('path');
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'..','firmware','common.js.html'),'utf8')+';this.parse=parse;',ctx);
let fails=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)fails++};
const H=3600,T=1795000000;
const buf=r=>{const b=Buffer.alloc(r.length*6);r.forEach(([t,mm],i)=>{b.writeUInt32LE(t,i*6);b.writeUInt16LE(mm,i*6+4)});return b.buffer.slice(b.byteOffset,b.byteOffset+b.length)};
const hourly=(mm,n,t0=T)=>Array.from({length:n},(_,k)=>[t0+k*H+37,mm(k)]);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
/* the friend's: hourly, 867 mm, then 16382 at 22:24, then 867 again */
let r=hourly(k=>k===5?16382:867+(k>8?5:0),12);
ok(same(ctx.parse(buf(r)),r.filter((_,k)=>k!==5)),'a lone 16382 between two normal readings: left out');
r=hourly(k=>k===5?600:867,12);ok(ctx.parse(buf(r)).length===12,'a real jump and straight back (oil pumped out and put back): kept, only the code is ever left out');
r=[[T,900],[T+H,600],[T+2*H,900],[T+3*H,300],[T+4*H,300]];ok(ctx.parse(buf(r)).length===5,'mid-fill readings, even odd ones: all kept');
r=[0,1,2,3,4].map(k=>[T+5*k,k%2?16382:867]);ok(same(ctx.parse(buf(r)).map(x=>x[1]),[867,867,867]),'a burst seconds apart, codes between good readings: the codes go, every good reading stays');
r=hourly(k=>k===5?16382:k<5?300:600,12);ok(ctx.parse(buf(r)).length===12,'a code between readings that disagree (a delivery under way): kept');
r=hourly(k=>k<5?867:367,12);ok(ctx.parse(buf(r)).length===12,'a delivery (50 cm up, and it stays): every reading kept');
r=hourly(k=>k===5?16382:k===6?16382:867,12);ok(ctx.parse(buf(r)).length===12,'two nearly-empty codes running: kept (believed)');
r=hourly(k=>k<11?1150:16382,12);ok(ctx.parse(buf(r)).length===12,'the newest reading a nearly-empty code: kept (the Pico only saves it when it believes it)');
r=[[T,700],[T+3*86400,16382],[T+6*86400,690]];ok(ctx.parse(buf(r)).length===3,'readings days apart (imported history): never judged');
r=hourly(k=>867+(k===5?60:0),12);ok(ctx.parse(buf(r)).length===12,'a 6 cm wobble (warm oil, a ripple): kept');
r=hourly(k=>k===5?16382:k<5?867:880,12);ok(ctx.parse(buf(r)).length===11,'readings either side 13 mm apart: still agree, the code left out');
r=hourly(k=>k===0?16382:867,5);ok(ctx.parse(buf(r)).length===5,'the very first reading: nothing before it to judge by, kept');
r=hourly(k=>k===5?16382:1100,12);ok(ctx.parse(buf(r),1170).length===12&&ctx.parse(buf(r),1300).length===11,'with 7 cm of oil either side: the code kept, as the Pico believes it there; with 20 cm: left out');
r=[[T,867],[T+4*H,16382],[T+10*H,867],[T+16*H,867]];ok(ctx.parse(buf(r),1170).length===4,'the reading before over 3 hours old: the code kept, as the Pico believes it then');
process.exit(fails?1:0)
