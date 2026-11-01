const assert=require('node:assert/strict'),D=require('../docs/desk.js');
const S={data:{date:'2026-10-30',run_at:'2026-10-31T07:00:00+09:00',market:{label:'상승장'},bands:[{picks:[{t:'TEST',price:10,total:75,elite:true,plan:{stop:9,target:12}}]}],holdings:[{t:'OLD',price:20,qty:2,tone:'warn'}]},
  watchlist:['TEST'],deskNotes:[{t:'TEST',reason:'<img src=x onerror=alert(1)>',waitBelow:11,invalidBelow:8,status:'유지',snapshot:{date:'2026-10-01',price:9,total:70}}],
  perf:{sim:{selection:{total:3,planned:1},review:{team_comparison:{n:1,actual_pnl:-2,kept_pnl:0},trades:[{t:'TEST',pnl:-2,fees:.1,entry_context:{date:'2026-10-01',team:{views:[]}}}]}}},
  paper:[{t:'TEST',qty:1,price:10,sold_price:12}],ai:{team:{TEST:{date:'2026-10-30',views:[{name:'가치',stance:'주의',reason:'근거',risk:'위험',invalidate:'조건',sources:['재무']}]}}}};
for(const route of ['home','picks','pick','hold','stock','watch','holdings','score','cal','news','gap','profile','settings','glossary','search','ask','alerts']) {
 for(const state of [{},S]) {
  const html=D.render(route,{S:state,t:'TEST',version:'2.19.0'});
  assert.ok(html.length>20,route);assert.ok(!html.includes('<img src=x'),route+' escaped notes');
 }
}
assert.ok(D.render('pick',{S,t:'TEST'}).includes('&lt;img'));
assert.equal(D.condition(S.deskNotes[0],7),'무효 가격 도달 · 재검토');
assert.equal(D.condition(S.deskNotes[0],10),'관찰 가격 도달 · 매수 확정 아님');
assert.ok(D.render('score',{S,seg:'acct'}).includes('수동 모의 · 선택한 이유'));
assert.ok(D.render('score',{S,seg:'fund'}).includes('연구 제안 비교'));
assert.equal(D.snapshot(S,'TEST').policy,'balanced-2.19.0');
console.log('PASS: all 17 screen contexts, old/missing data, note escaping, price conditions, account/fund panels');
