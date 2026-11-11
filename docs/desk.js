/* 판단 근거·주문 상태·복기를 모든 화면에 연결. 점수/정렬/자동 주문 결정은 바꾸지 않아요. */
(function (root) {
  'use strict';
  const E = x => String(x == null ? '' : x).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const N = x => x == null || !Number.isFinite(Number(x)) ? '—' : Number(x).toLocaleString('en-US',{maximumFractionDigits:2});
  const arr = x => Array.isArray(x) ? x : [];
  const card = (title, body) => '<section class="card desk-card"><h2>' + E(title) + '</h2>' + body + '</section>';
  const link = (route, label) => '<a class="chip" href="#/' + E(route) + '">' + E(label) + '</a>';
  const list = xs => '<ul class="plain small">' + xs.map(x=>'<li>'+E(x)+'</li>').join('')+'</ul>';
  const table = (heads, rows) => '<div class="tblwrap"><table class="tbl"><thead><tr>'+heads.map(x=>'<th>'+E(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+E(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  const safeLink = (url, text) => /^https?:\/\//i.test(url || '') ? '<a class="link" href="'+E(url)+'" target="_blank" rel="noopener noreferrer">'+E(text)+'</a>' : '<span class="small">원문 확인 못 함</span>';
  function picks(S) { return arr(S.data && S.data.bands).flatMap(b=>arr(b.picks)); }
  function entity(S,t) { return arr(S.data && S.data.holdings).find(p=>p.t===t) || picks(S).find(p=>p.t===t) || {t,price:S.watch?.items?.[t]?.px}; }
  function notes(S) { return arr(S.deskNotes); }
  function noteFor(S,t) { return notes(S).find(n=>n.t===t) || {}; }
  function condition(n, price) {
    if (n.status==='무효') return '내 가설 무효';
    if (n.invalidBelow > 0 && price > 0 && price <= n.invalidBelow) return '무효 가격 도달 · 재검토';
    if (n.waitBelow > 0 && price > 0 && price <= n.waitBelow) return '관찰 가격 도달 · 매수 확정 아님';
    return n.status==='재검토' ? '내 가설 재검토' : n.reason ? '내 가설 유지 · 조건 직접 확인' : '가설 기록 없음';
  }
  function snapshot(S,t) {
    const p=entity(S,t), team=(S.ai && S.ai.team || {})[t];
    return {t, date:S.data && S.data.date, price:p.price, total:p.total, setup:p.setup,
      edge:p.edge, stop:p.stop || p.plan && p.plan.stop, target:p.target || p.plan && p.plan.target,
      team:team ? {date:team.date,version:team.version,views:arr(team.views),conflict:team.conflict} : null,
      policy:'balanced-2.19.0'};
  }
  function fresh(S) {
    const date=S.data && S.data.run_at;
    const age=date ? (Date.now()-Date.parse(date))/36e5 : NaN;
    return S.error ? '서버 연결 실패 · 저장된 자료 표시' : !Number.isFinite(age) ? '자료 기준일 확인 대기' : age>36 ? '마지막 리포트 36시간 경과 · 휴장/실행 상태 확인' : '마지막 리포트 '+String(date).slice(0,16).replace('T',' ');
  }
  function home(S) {
    // '오늘의 판단 데스크' 카드 제거 — 검토 후보가 거의 항상 0이고 홈의 다른 카드와 중복돼 사용자 요청으로 뺌.
    return '';
  }
  function teamHtml(S,t) {
    const tm=(S.ai && S.ai.team || {})[t] || {}, p=entity(S,t), fin=(S.data && S.data.fin || {})[t] || {};
    const fallback=[['재무',fin.signals && fin.signals[0] && fin.signals[0].text,'앱 재무 요약',fin.fy],['차트',p.setup,'일봉 셋업',S.data?.date],
      ['가치평가',null,'버핏 4관점에서 확인'],['뉴스',null,'뉴스 탭에서 확인'],['심리',null,'독립 심리 자료 미연결'],
      ['성장',arr(fin.signals).find(x=>x.key==='growth')?.text,'앱 재무 요약',fin.fy],['시장 국면',S.data?.market?.label,'아침 시장 판정',S.data?.date]];
    const signals=arr(tm.signals).length ? tm.signals.map(s=>[s.name,s.available?s.text:'자료 부족',s.source,s.date || '—']) : fallback.map(s=>[s[0],s[1] || '자료 부족',s[2],s[3] || '기준일 확인 못 함']);
    let body='<div class="small">자료 7종 · 확인된 자료만 표시</div>'+table(['자료','확인 내용','출처','기준일'],signals);
    body+='<h3>AI 검토 네 관점</h3><p class="small">동일 자료를 함께 읽는 관점이며 독립된 전문가 투표가 아니에요. 합의율은 승률이 아니며 주문을 바꾸지 않아요.</p>';
    body+=arr(tm.views).length ? table(['관점','판단','근거·자료','주의점 / 틀릴 조건'],tm.views.map(v=>[v.name,v.stance,
      v.reason+' · '+arr(v.sources).join(', '),v.risk+' / '+v.invalidate]))+'<p class="small">의견이 갈리는 지점: '+E(tm.conflict || '확인 못 함')+' · 검토일 '+E(tm.date)+'</p>' : '<p class="small">AI 네 관점은 다음 아침 분석부터 상위 최대 3종목을 주 1회 검토해요. 자료가 없으면 자료 부족으로 표시해요.</p>';
    return '<details class="sig desk-evidence"><summary><b>자료 7종과 AI 네 관점</b></summary>'+body+'</details>';
  }
  function thesis(S,t) {
    const p=entity(S,t), n=noteFor(S,t), old=n.snapshot || {};
    return card(t+' · 내 판단 기록', '<p class="small">'+E(condition(n,p.price))+'</p>'+
      (n.reason ? '<p>'+E(n.reason)+'</p>' : '')+
      (old.date ? table(['기록 당시','지금'],[[old.date,S.data?.date || '—'],['$'+N(old.price),'$'+N(p.price)],['점수 '+N(old.total),'점수 '+N(p.total)]]) : '')+
      '<details><summary>관심 이유·기다리는 조건 기록</summary><form data-desk-note="'+E(t)+'">'+
      '<label>관심·매수 이유<textarea name="reason" maxlength="500">'+E(n.reason)+'</textarea></label>'+
      '<label>기다리는 조건<textarea name="wait" maxlength="300">'+E(n.wait)+'</textarea></label>'+
      '<label>가설이 틀리는 조건<textarea name="invalid" maxlength="300">'+E(n.invalid)+'</textarea></label>'+
      '<div class="desk-grid"><label>이 가격 이하 관찰<input type="number" step="0.01" min="0" name="waitBelow" value="'+E(n.waitBelow || '')+'"></label>'+
      '<label>이 가격 이하 재검토<input type="number" step="0.01" min="0" name="invalidBelow" value="'+E(n.invalidBelow || '')+'"></label></div>'+
      '<label>다음 확인일<input type="date" name="next" value="'+E(n.next)+'"></label>'+
      '<label>내 가설 상태<select name="status">'+['유지','재검토','무효'].map(x=>'<option'+(n.status===x?' selected':'')+'>'+x+'</option>').join('')+'</select></label>'+
      '<button class="btn" type="submit">기록 저장</button><p class="small" data-desk-result></p></form></details>'+
      '<p class="small">가격 조건은 마지막으로 받은 시세와 비교해요. 문장으로 쓴 조건은 직접 확인해야 하며 자동 주문 조건으로 쓰지 않아요.</p>');
  }
  function entityHtml(S,t) {
    const p=entity(S,t), reason=arr(p.reasons)[0] || p.setup || '확인된 근거 없음';
    const risk=arr(p.tags).find(x=>/주의|실적|위험|보류|출렁임/.test(x)) || p.conclusion || p.entry_exclusion || '자료·주문 조건 추가 확인';
    return card(t+' · 검토 요약', '<p><b>근거</b> '+E(reason)+'</p><p><b>주의</b> '+E(risk)+'</p>'+
      '<p class="small">'+E(S.data?.date || '자료 기준일 없음')+' · '+E(p.elite?'엄선 기준 통과 · 주문 전 검사 별도':p.entry_exclusion || '자동 모의 대상 여부 확인 대기')+'</p>'+
      '<button class="chip" data-desk-ask="'+E(t)+'">이 자료로 AI에게 묻기</button>'+link('cal','일정 확인'))+teamHtml(S,t)+thesis(S,t);
  }
  function watch(S) {
    return card('관심종목 · 기다리는 이유',table(['종목','상태','기다리는 조건','다음 확인일'],arr(S.watchlist).map(t=>{const n=noteFor(S,t);return [t,condition(n,entity(S,t).price),n.wait || '종목 상세에서 조건 기록',n.next || '미지정'];}))+
      '<p class="small">종목 상세의 내 판단 기록에서 조건·다음 확인일을 저장할 수 있어요.</p>');
  }
  function holdings(S) {
    // '보유 가설·쏠림 점검' 카드 제거 — 비중·업종 쏠림은 아래 '내 포트폴리오 진단'(portHtml)과 중복,
    // '내 가설' 열은 기록이 없으면 항상 '가설 기록 없음'만 떠서 사용자 요청으로 뺌.
    return '';
  }
  function comparison(S) {
    const r=S.perf?.sim?.review || {}, c=r.team_comparison || {};
    const entries=arr(r.trades).filter(t=>t.entry_context).slice(0,12).map(t=>'<details class="sig"><summary>'+E(t.t)+' · '+E(t.entry_context.date)+' 매수 기록</summary>'+list([
      '전략 '+t.entry_context.policy,'확정손익 $'+N(t.pnl)+' · 비용 추정 $'+N(t.fees),
      '청산 이유: '+arr(t.exit_reasons).join(' / '),'미끄러짐은 체결가에 포함되며 비용과 별도로 분리 측정하지 않았어요.'])+
      table(['매수 당시 관점','판단','근거'],arr(t.entry_context.team?.views).map(v=>[v.name,v.stance,v.reason]))+'</details>').join('');
    return card('AI 의견을 따랐다면?',(c.n ? table(['같은 날 의견이 기록된 완료 거래',c.n+'건'],[
      ['실제 거래 손익','$'+N(c.actual_pnl)],['AI 주의 거래를 뺀 손익','$'+N(c.kept_pnl)],['피했을 손실','$'+N(c.avoided_losses)],['놓쳤을 이익','$'+N(c.missed_gains)]])+'<p class="small">'+E(c.note)+'</p>' : '<p class="small">진입 당일 AI 의견이 있는 거래가 전량 청산되면 비교해요. 지금부터 기록을 쌓으며 과거 거래의 의견을 소급해 만들지 않아요.</p>')+entries);
  }
  function score(S,seg) {
    const sim=S.perf?.sim || {}, k=S.kis || {}, s=sim.selection || {}, ts=sim.ticket_stats || {};
    let body=card('후보에서 체결까지',table(['단계','개수·상태'],[['아침 목록',s.total ?? '재계산 대기'],['주문 계획',s.planned ?? '재계산 대기'],
      ['내부 장부 채점 (누적)',ts.n==null?'대기':ts.n+'건 중 '+ts.filled+'건 체결'],
      ['증권사 모의',k.on ? k.err || '연결 설정됨 · 아래 체결 확인' : k.why || '미연결']])+
      '<p class="small">서로 다른 기간·계좌의 숫자예요. 주문 계획·주문 접수·체결은 다르며 실전 주문은 비활성입니다.</p>');
    if(seg==='fund') {
      const w=S.ai?.fund?.weights || {}, hs=arr(S.data?.holdings), total=hs.reduce((s,h)=>s+h.qty*h.price,0);
      body+=card('현재 비중과 연구 제안 비교',table(['종목','현재 주식 내 비중','MeanRisk 연구 비중'],arr(w.assets).map(t=>{const h=hs.find(x=>x.t===t);return [t,total?N((h?h.qty*h.price:0)/total*100)+'%':'—',w.meanrisk?.[t]==null?'—':N(w.meanrisk[t]*100)+'%'];}))+
        '<p class="small">기준일과 현금 포함 여부가 다를 수 있어요. 연구 배분을 자동 주문으로 복사하지 않아요.</p>');
    }
    body+=comparison(S);
    if(k.guard || k.order_summary) body+=card('증권사 모의 · 주문 직전 검사',list([
      '평가 기준: '+(k.guard?.base_note || '확인 대기'), '확정손익 추정 $'+N(k.guard?.pnl)+' / 손실 한도 $'+N(k.guard?.loss_limit),
      '접수 포함 매수 횟수 '+N(k.guard?.buys)+' / '+N(k.guard?.max_trades),
      k.guard?.verified ? '계좌 검사 완료 · 각 주문에서 다시 확인' : '계좌·주문 확인 필요: '+(k.guard?.unverified_reason || k.reconcile?.note || '조회 대기')])+
      table(['상태','개수'],Object.entries(k.order_summary || {}))+'<p class="small">증권사 확인 체결만 반영해요. 불확실한 전송은 중복 전송하지 않으며 주문 내역을 직접 확인해야 해요. 접수 중인 매도 수량은 다른 매도에서 제외해요.</p>');
    return body;
  }
  function calendar(S) {
    const mine=new Set(arr(S.data?.holdings).map(x=>x.t)), pending=new Set(arr(S.perf?.sim?.pending).map(x=>x.t));
    const events=arr(S.cal?.earnings).map(x=>({...x,kind:'실적',date:x.date})).concat(arr(S.cal?.dividends).map(x=>({...x,kind:'배당락',date:x.exdate})));
    const relevant=events.filter(x=>mine.has(x.t)||pending.has(x.t)).sort((a,b)=>String(a.date).localeCompare(String(b.date)));
    return card('내 보유·주문과 겹치는 일정',relevant.length?table(['종목','일정','내 상태'],relevant.map(x=>[x.t,x.kind+' '+x.date,pending.has(x.t)?'주문 계획 확인':'보유 점검'])):'<p class="small">현재 연결된 일정에서 겹치는 항목이 없어요. 일정 누락 가능성이 있어 실적일은 원자료도 확인해요.</p>');
  }
  function news(S) {
    const mine=new Set(arr(S.data?.holdings).map(x=>x.t).concat(picks(S).map(x=>x.t)));
    const items=arr(S.ai?.brief?.items).filter(x=>mine.has(x['종목']));
    return card('내 종목에 연결된 사실·확인할 것',items.length?items.slice(0,8).map(x=>'<article class="desk-news"><b>'+E(x['종목'])+'</b><p>자료에 보고된 내용: '+E(x['무슨 일'])+'</p><p class="small">영향 해석: '+E(x['닿는 곳'])+' · '+E(x['이유'])+'</p>'+safeLink(x['링크'],'원문 확인')+'<p class="small">'+E(x['시각'])+' · 다음 확인: 원문 날짜와 관련 지표를 종목 상세에서 확인</p></article>').join(''):'<p class="small">새로 연결된 개별 종목 브리핑이 없어요. 뉴스 부재가 위험 부재를 뜻하지 않아요.</p>');
  }
  function gap(S) {
    return card('추격 여부를 주문 계획과 비교',table(['종목','장 전 가격','추격 금지선','현재 비교'],arr(S.gap?.items).map(g=>{
      const p=entity(S,g.t), ceiling=p.plan?.skip_if_open_above;
      return [g.t,'$'+N(g.pre),ceiling?'$'+N(ceiling):'계획 없음',!ceiling || !g.pre?'확인 대기':g.pre>ceiling?'추격 금지선 위':'금지선 이내 · 체결 확정 아님'];
    }))+'<p class="small">실제 주문 직전 가격과 계좌 상태를 다시 확인해요.</p>');
  }
  function profile(S) {
    const p=S.profile || {};
    const daily=p['앱을 보는 횟수'];
    return card('내가 운영할 수 있는 모의 방식',list(['현재 응답: '+(p['투자 기간'] || '기간 미응답')+' · 감당할 월 손실 '+(p['한 달에 견딜 수 있는 손실'] || '미응답'),
      daily==='주 1~2번'?'비교할 방식: 주간 검토 중심의 모의 기록': '비교할 방식: 아침 점검과 규칙 기반 스윙 모의 기록',
      '현재 자동 모의 결과와 새 전략의 거래 횟수·낙폭·비용을 같은 기간에 비교해야 해요. 응답만으로 손실 한도나 주문 규칙은 바꾸지 않아요.']));
  }
  function settings(S,version) {
    return card('운영 모드·전략 버전',list(['앱 '+version+' · 전략 balanced-2.19.0',
      '내부 자동 모의: '+(S.perf?.sim?'가상 장부 운영':'초기화 대기'),
      '증권사 모의: '+(S.kis?.on?'연결 설정됨 (실제 상태는 체결 기록에서 확인)':'미연결'),
      '실전 주문: 비활성 · 점수와 가격순 정렬 유지',
      'AI: 상위 최대 3종목 · 주 1회 네 관점 기록 · 주문 영향 없음',fresh(S)])+link('score','계좌별 상태')+link('alerts/runs','실행 근거'));
  }
  function glossary() {
    return card('판단 데스크 용어',table(['말','뜻'],[['셋업','정해 둔 차트 조건이 생긴 자리'],['엣지','비용을 뺀 과거 결과에서 유리함이 있었는지'],['관찰 의견','주문을 바꾸지 않고 결과를 비교할 AI 기록'],['접수 / 체결','주문을 받았다는 응답 / 실제 수량이 거래됨'],['부분체결','주문 수량 중 일부만 거래됨'],['1R','매수 당시 정한 손절 위험금액'],['가설 무효','처음 생각한 이유를 다시 검토할 조건']])+link('picks','후보에서 보기')+link('score','주문과 복기에서 보기'));
  }
  function render(route,C) {
    const S=C.S || {}, t=C.t;
    if(['pick','hold','stock'].includes(route) && t) return entityHtml(S,t);
    if(route==='home') return home(S);
    if(route==='picks') return card('관찰·주의·주문 제한을 구분해요',list(['관찰: 아직 셋업이 없거나 표본을 모으는 종목','주의: AI 의견 차이·자료 부족은 검토 정보이며 추가 차단 조건이 아니에요','주문 제한: 현금·손절 위험금액·일일 한도·정수 수량을 코드가 다시 검사해요']));
    if(route==='watch') return watch(S);
    if(route==='holdings') return holdings(S);
    if(route==='score') return score(S,C.seg || 'auto');
    if(route==='cal') return calendar(S);
    if(route==='news') return news(S);
    if(route==='gap') return gap(S);
    if(route==='profile') return profile(S);
    if(route==='settings') return settings(S,C.version || '');
    if(route==='glossary') return glossary();
    if(route==='search') return card('검색과 매수 자격은 달라요','<p class="small">검색한 종목의 자료는 볼 수 있지만, 자동 모의매수는 아침 후보와 주문 검사를 통과한 종목만 대상이에요.</p>');
    if(route==='ask') return card('답변의 기준 자료',C.askContext?.t?'<p>'+E(C.askContext.t)+' · '+E(C.askContext.date)+' 자료에서 시작한 질문</p>'+link((['hold','pick','stock'].includes(C.askContext.from)?C.askContext.from:arr(S.data?.holdings).some(x=>x.t===C.askContext.t)?'hold':picks(S).some(x=>x.t===C.askContext.t)?'pick':'stock')+'/'+encodeURIComponent(C.askContext.t),'근거 화면으로 돌아가기'):'<p class="small">종목 상세의 ‘이 자료로 AI에게 묻기’를 누르면 종목과 자료 기준일을 연결할 수 있어요.</p>');
    if(route==='alerts') return card('변화를 확인하는 순서',list(['주문 확인 필요·실패 → 위험 조건 도달 → 확인된 체결 → 새로운 근거 순으로 확인해요.','같은 날·종류·제목·본문의 반복 알림은 합쳐 저장하며, 체결 수량과 주문 번호는 증권사 기록에서 확인해요.'])+table(['반복 알림','묶인 횟수'],arr(S.alerts).filter(x=>x.repeats>1).slice(0,5).map(x=>[x.title,x.repeats]))+link('score','주문 상태 보기'));
    return '';
  }
  function mount(el,C) {
    const html=render(C.route,C);if(!html) return;
    const host=document.createElement('div');host.className='desk-panel';host.innerHTML=html;
    let head=el.querySelector(':scope > .head, :scope > h1, :scope > [data-livehead]');
    if(!head) {head=el.querySelector('h1');while(head && head.parentElement!==el) head=head.parentElement;}
    if(head) head.after(host);else el.prepend(host);
    host.querySelectorAll('[data-desk-ask]').forEach(b=>b.onclick=()=>C.ask(b.dataset.deskAsk));
    host.querySelectorAll('[data-desk-note]').forEach(f=>f.onsubmit=async ev=>{
      ev.preventDefault();const out=f.querySelector('[data-desk-result]'),button=f.querySelector('button');button.disabled=true;
      const data=Object.fromEntries(new FormData(f));data.t=f.dataset.deskNote;data.snapshot=noteFor(C.S,data.t).snapshot || snapshot(C.S,data.t);
      data.waitBelow=Number(data.waitBelow)||0;data.invalidBelow=Number(data.invalidBelow)||0;
      try {await C.saveNote(data);out.textContent='저장했어요. 다른 화면에서도 같은 기록을 볼 수 있어요.';}catch(e){out.textContent='저장 실패: '+e.message;}
      button.disabled=false;
    });
  }
  const api={render,mount,snapshot,condition,entity,table,teamHtml};
  root.TradeDesk=api;
  if(typeof module!=='undefined') module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

