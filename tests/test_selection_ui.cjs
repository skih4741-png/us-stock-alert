const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('docs/app.js','utf8');
function extract(name,next){return src.slice(src.indexOf('  function '+name+'('),src.indexOf('  function '+next+'('));}
const c={esc:s=>String(s).replaceAll('<','&lt;')};vm.createContext(c);
vm.runInContext(extract('candidateFilterHtml','scoreBars')+extract('simSelectionHtml','simReviewHtml'),c);
let html=c.candidateFilterHtml([{elite:true},{elite:false,entry_exclusion:'셋업 없음'},{elite:false,entry_exclusion:'셋업 없음'},{elite:false}]);
assert.ok(html.includes('셋업 없음 · 2개'));assert.ok(html.includes('새 기준 재계산 대기 · 1개'));
assert.ok(c.simSelectionHtml(null).includes('다음 아침'));
html=c.simSelectionHtml({date:'2026-11-01',total:3,planned:0,pause:'하락장',excluded:{}});
assert.ok(html.includes('새 주문 계획 중지: 하락장'));
html=c.simSelectionHtml({date:'2026-11-01',total:3,planned:1,excluded:{'표본 부족':2}});
assert.ok(html.includes('주문 계획 1개'));assert.ok(html.includes('표본 부족 · 2개'));
console.log('PASS: candidate exclusion counts, legacy-data notice, and simulator pause/reason display');

c.fmt=(n)=>String(n); c.usd=(n)=>String(n); c.pct=(n)=>String(n);
vm.runInContext(extract('brokerCard','ticketHtml'),c);
html=c.brokerCard({equity:1000,budget:1000,cash:950,ret:0,curve:[],positions:[],valuation:{ok:false},equity_asof:'2026-10-02'},null);
assert.ok(html.includes('평가 확인 대기') && html.includes('2026-10-02'));
assert.ok(!html.includes('주식 $50'));
