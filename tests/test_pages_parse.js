// node tests/test_pages_parse.js - every <script> in the pages must parse (a stray // comment in a
// one-line function silently switches the rest of the page off).
const fs = require('fs'), path = require('path'), vm = require('vm');
let bad = 0;
for (const f of ['ui.html', 'hist.html', 'common.js.html']) {
  const s = fs.readFileSync(path.join(__dirname, '..', 'firmware', f), 'utf8');
  const parts = f === 'common.js.html' ? [s] : [...s.matchAll(/<script(?![^>]*src=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  parts.forEach((code, i) => {
    try { new vm.Script(code, { filename: f + '#' + i }); console.log('ok   ' + f + ' script ' + i); }
    catch (e) { bad++; console.log('FAIL ' + f + ' script ' + i + ': ' + e.message); }
  });
}
process.exit(bad ? 1 : 0);
