/* 미국주식 알림 앱 — 1단계 (로그인 · 홈 · 후보 · 보유 · 상세 · 알림 · 설정) */
(function () {
  "use strict";
  const CFG = window.APP_CONFIG || {};
  const $app = document.getElementById("app");
  const $tabs = document.getElementById("tabs");
  const DISCLAIMER = "규칙에 따른 검토 후보이며 투자 판단과 책임은 본인에게 있습니다. 자동 주문은 하지 않아요.";

  /* ---------- 저장 (실패해도 앱은 돌아가게) ---------- */
  const store = {
    get(k, where) { try { return (where || localStorage).getItem(k); } catch (e) { return null; } },
    set(k, v, where) { try { (where || localStorage).setItem(k, v); } catch (e) {} },
    del(k) { try { localStorage.removeItem(k); sessionStorage.removeItem(k); } catch (e) {} },
  };
  function deviceId() {
    let d = store.get("device");
    if (!d) { d = Math.random().toString(36).slice(2) + Date.now().toString(36); store.set("device", d); }
    return d;
  }
  function deviceLabel() {
    const ua = navigator.userAgent;
    const os = /iPhone/.test(ua) ? "아이폰" : /iPad/.test(ua) ? "아이패드" : /Android/.test(ua) ? "안드로이드" : /Mac/.test(ua) ? "맥" : /Windows/.test(ua) ? "윈도우 PC" : "기기";
    const mode = matchMedia("(display-mode: standalone)").matches || navigator.standalone ? "홈 화면 앱" : "브라우저";
    return os + " · " + mode;
  }
  const S = {
    token: store.get("token") || store.get("token", sessionStorage),
    scope: store.get("scope") || store.get("scope", sessionStorage),
    data: null, alerts: [], loading: false, error: "", filter: store.get("filter") || "all", lastSeenAlert: store.get("seenAlert") || "",
  };
  try { const c = JSON.parse(store.get("cache") || "null"); if (c) { S.data = c.daily; S.alerts = c.alerts || []; } } catch (e) {}

  function setSession(token, scope, keep) {
    store.del("token"); store.del("scope");
    S.token = token; S.scope = scope;
    if (!token) return;
    const where = keep ? localStorage : sessionStorage;
    store.set("token", token, where); store.set("scope", scope, where);
  }
  function clearAll() {
    setSession(null, null);
    store.del("cache"); S.data = null; S.alerts = [];
  }

  /* ---------- 서버 ---------- */
  async function api(action, body) {
    if (!CFG.API_URL) throw new Error("로그인 서버 주소가 아직 설정되지 않았어요 (config.js)");
    const res = await fetch(CFG.API_URL, {
      method: "POST", redirect: "follow",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify(Object.assign({ action: action, device: deviceId(), label: deviceLabel() }, body || {})),
    });
    if (!res.ok) throw new Error("서버 응답 오류 (" + res.status + ")");
    const j = await res.json();
    if (j.auth) { clearAll(); go("#/login"); }
    return j;
  }

  /* ---------- 도구 ---------- */
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n, d) => n == null || isNaN(n) ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d });
  const pct = n => n == null ? "—" : (n > 0 ? "+" : "") + fmt(n, 1) + "%";
  function toast(t) {
    const el = document.getElementById("toast");
    el.textContent = t; el.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => { el.hidden = true; }, 2600);
  }
  function go(h) { if (location.hash !== h) location.hash = h; else render(); }
  function whenText(iso) {
    if (!iso) return "";
    const d = new Date(iso); if (isNaN(d)) return iso;
    const p = n => String(n).padStart(2, "0");
    return (d.getMonth() + 1) + "월 " + d.getDate() + "일 " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  const tagTone = t => /손절|위험|보류|출렁임/.test(t) ? "bad" : /실적|급등|참고/.test(t) ? "warn" : /신규/.test(t) ? "info" : "";
  const tags = arr => (arr && arr.length) ? '<div class="tags">' + arr.map(t => '<span class="badge ' + tagTone(t) + '">' + esc(t) + "</span>").join("") + "</div>" : "";
  function pwRules(pw, id) {
    pw = pw || "";
    return [
      [pw.length >= 10, "10자 이상"],
      [/[A-Za-z]/.test(pw) && /[0-9]/.test(pw), "영문·숫자 섞기"],
      [!!pw && (!id || pw.toLowerCase().indexOf(String(id).toLowerCase()) < 0), "아이디를 넣지 않기"],
    ];
  }
  const rulesHtml = (pw, id) => '<ul class="rules">' + pwRules(pw, id).map(r => '<li class="' + (r[0] ? "ok" : "") + '">' + r[1] + "</li>").join("") + "</ul>";

  /* ---------- 데이터 ---------- */
  async function refresh(silent) {
    if (!S.token || S.scope !== "full" || S.loading) return;
    S.loading = true; S.error = "";
    if (!silent) render();
    try {
      const j = await api("data", { token: S.token });
      if (j.ok) {
        S.data = j.daily; S.alerts = j.alerts || [];
        store.set("cache", JSON.stringify({ daily: S.data, alerts: S.alerts, at: Date.now() }));
      } else if (!j.auth) S.error = j.error || "불러오지 못했어요";
    } catch (e) {
      S.error = navigator.onLine ? e.message : "인터넷이 없어요. 마지막으로 받은 내용을 보여드려요.";
    }
    S.loading = false;
    render();
  }

  /* ---------- 화면: 로그인 계열 ---------- */
  function authShell(inner) {
    $tabs.hidden = true;
    $app.innerHTML = '<div class="auth"><img class="logo" src="icons/icon-192.png" alt="">' + inner + "</div>";
  }
  function bindForm(id, handler) {
    const f = document.getElementById(id);
    f.addEventListener("submit", async ev => {
      ev.preventDefault();
      const btn = f.querySelector("button[type=submit]"); const msg = f.querySelector(".out");
      btn.disabled = true; msg.innerHTML = "";
      try { await handler(f, msg); } catch (e) { msg.innerHTML = '<div class="msg err">' + esc(e.message) + "</div>"; }
      btn.disabled = false;
    });
  }

  function viewLogin() {
    authShell('<h1>미국주식 알림</h1><form id="f" autocomplete="on">' +
      '<label for="id">아이디</label><input id="id" name="username" type="text" autocomplete="username" autocapitalize="off" spellcheck="false" required>' +
      '<label for="pw">비밀번호</label><input id="pw" name="password" type="password" autocomplete="current-password" required>' +
      '<label class="check"><input id="keep" type="checkbox" checked> 로그인 유지 (30일)</label>' +
      '<button class="btn" type="submit">로그인</button><div class="out"></div></form>' +
      '<a class="link" href="#/forgot">비밀번호를 잊었어요</a><p class="foot">5번 틀리면 15분 동안 잠겨요</p>');
    bindForm("f", async (f, msg) => {
      const keep = f.keep.checked;
      const j = await api("login", { id: f.id.value.trim(), pw: f.pw.value, keep: keep });
      if (!j.ok) { msg.innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; if (j.setup) go("#/setup"); return; }
      setSession(j.token, j.scope, keep);
      store.set("keepPref", keep ? "1" : "0");
      if (j.mustChange) go("#/reset"); else { go("#/home"); refresh(); }
    });
  }

  function viewForgot() {
    authShell('<button class="back" onclick="history.back()">← 로그인</button><h1>비밀번호 찾기</h1>' +
      '<p class="sub">아이디와 메일이 맞으면 임시 비밀번호를 메일로 보내 드려요. 30분 안에 한 번만 쓸 수 있어요.</p>' +
      '<form id="f"><label for="id">아이디</label><input id="id" type="text" autocomplete="username" autocapitalize="off" required>' +
      '<label for="em">메일 주소</label><input id="em" type="email" autocomplete="email" required>' +
      '<button class="btn" type="submit">임시 비밀번호 받기</button><div class="out"></div></form>');
    bindForm("f", async (f, msg) => {
      const j = await api("forgot", { id: f.id.value.trim(), email: f.em.value.trim() });
      msg.innerHTML = j.ok ? '<div class="msg ok">' + esc(j.message) + '</div><a class="btn ghost" href="#/login">로그인하러 가기</a>'
        : '<div class="msg err">' + esc(j.error) + "</div>";
    });
  }

  function viewReset() {
    if (!S.token) return go("#/login");
    authShell('<h1>새 비밀번호 정하기</h1><div class="msg note">임시 비밀번호로 들어왔어요. 새 비밀번호를 정해야 앱을 쓸 수 있어요.</div>' +
      '<form id="f"><label for="n1">새 비밀번호</label><input id="n1" type="password" autocomplete="new-password" required>' +
      '<div id="rules">' + rulesHtml("") + "</div>" +
      '<label for="n2">한 번 더</label><input id="n2" type="password" autocomplete="new-password" required>' +
      '<button class="btn" type="submit">바꾸고 시작하기</button><div class="out"></div></form>' +
      '<p class="foot">바꾸면 다른 기기는 모두 로그아웃돼요</p>');
    const f = document.getElementById("f");
    f.n1.addEventListener("input", () => { document.getElementById("rules").innerHTML = rulesHtml(f.n1.value); });
    bindForm("f", async (f, msg) => {
      if (f.n1.value !== f.n2.value) { msg.innerHTML = '<div class="msg err">두 비밀번호가 달라요.</div>'; return; }
      const keep = store.get("keepPref") !== "0";
      const j = await api("setPassword", { token: S.token, newPw: f.n1.value, keep: keep });
      if (!j.ok) { msg.innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; return; }
      setSession(j.token, j.scope, keep);
      toast("비밀번호를 바꿨어요");
      go("#/home"); refresh();
    });
  }

  function viewSetup() {
    authShell('<h1>처음 설정</h1><p class="sub">이 앱은 계정 하나만 만들 수 있어요. 먼저 등록된 메일로 설정 코드를 받아 주세요.</p>' +
      '<form id="c"><button class="btn ghost" type="submit">설정 코드 메일로 받기</button><div class="out"></div></form>' +
      '<form id="f"><label for="code">설정 코드 (6자리)</label><input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required>' +
      '<label for="id">아이디 (영문·숫자 4~20자)</label><input id="id" type="text" autocomplete="username" autocapitalize="off" required>' +
      '<label for="n1">비밀번호</label><input id="n1" type="password" autocomplete="new-password" required><div id="rules">' + rulesHtml("") + "</div>" +
      '<label for="n2">비밀번호 한 번 더</label><input id="n2" type="password" autocomplete="new-password" required>' +
      '<button class="btn" type="submit">계정 만들기</button><div class="out"></div></form>');
    const f = document.getElementById("f");
    const upd = () => { document.getElementById("rules").innerHTML = rulesHtml(f.n1.value, f.id.value); };
    f.n1.addEventListener("input", upd); f.id.addEventListener("input", upd);
    bindForm("c", async (c, msg) => {
      const j = await api("sendSetupCode");
      msg.innerHTML = '<div class="msg ' + (j.ok ? "ok" : "err") + '">' + esc(j.ok ? j.message : j.error) + "</div>";
    });
    bindForm("f", async (f, msg) => {
      if (f.n1.value !== f.n2.value) { msg.innerHTML = '<div class="msg err">두 비밀번호가 달라요.</div>'; return; }
      const j = await api("createAccount", { code: f.code.value.trim(), id: f.id.value.trim(), pw: f.n1.value, keep: true });
      if (!j.ok) { msg.innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; return; }
      setSession(j.token, j.scope, true);
      toast("계정을 만들었어요");
      go("#/home"); refresh();
    });
  }


  /* ---------- 쉬운 재무제표 (F-1~F-5) ---------- */
  const TERMS = {
    "체력 점수": "피오트로스키 점수예요. 돈을 버는지, 빚이 줄고 있는지, 효율이 좋아지는지를 예/아니오 9개로 본 점수예요. 7 이상이면 튼튼, 4~6 보통, 3 이하 약함.",
    "버핏 체크": "워런 버핏이 '오래 돈을 잘 버는 회사'의 흔적으로 보는 재무 습관 8개예요. 참고용이고 절대 기준은 아니에요.",
    "영업이익률": "물건을 팔아 회사 운영비까지 빼고 남는 비율이에요. 100달러 팔아 18달러가 남으면 18%.",
    "순이익률": "세금·이자까지 다 빼고 최종으로 남는 비율이에요.",
    "순이익": "1년 동안 모든 비용과 세금을 빼고 남은 돈이에요(장부상).",
    "매출 연평균 성장률": "매출이 1년에 평균 몇 %씩 커졌는지예요.",
    "최근 매출": "가장 최근 1년 동안 판 금액이에요.",
    "부채비율(빚÷주주 몫)": "갚아야 할 빚이 주주 몫(자본)의 몇 %인지예요. 100%면 빚과 주주 몫이 같아요. 보통 100~200%를 흔한 범위로 봐요(업종마다 달라요).",
    "이자보상배율": "영업으로 번 돈이 이자의 몇 배인지예요. 1보다 작으면 번 돈으로 이자도 못 내요.",
    "부도 위험 점수(알트만 Z)": "망할 위험을 보는 점수예요. 2.99 넘으면 안전, 1.81~2.99 회색, 1.81 아래면 위험 구간이에요. 금융사에는 쓰지 않아요.",
    "영업현금흐름": "장사로 실제 통장에 들어온 현금이에요. 장부상 이익보다 속이기 어려워요.",
    "자유현금흐름": "장사로 번 현금에서 공장·설비 투자를 빼고 남은 현금이에요. 배당·자사주·빚 갚기에 쓸 수 있는 돈이에요.",
    "주식 수 변화(1년)": "주식 수가 늘면 같은 회사를 더 많은 사람이 나눠 가져서 내 몫이 줄어요.",
    "배당": "회사가 1년 동안 주주에게 나눠 준 현금이에요.",
    "자사주 매입": "회사가 자기 주식을 사들인 금액이에요. 주식 수가 줄면 내 몫이 커져요.",
    "가진 것": "회사가 가진 모든 재산(자산)이에요. 현금, 공장, 받을 돈 등.",
    "빚": "회사가 갚아야 할 돈(부채)이에요.",
    "주주 몫": "재산에서 빚을 빼고 주주에게 남는 몫(자본)이에요.",
  };
  const toneColor = { good: "var(--good)", warn: "var(--warn)", bad: "var(--bad)", info: "var(--sub)", none: "var(--line)" };
  const ti = k => '<button class="tip" data-term="' + esc(k) + '" aria-label="' + esc(k) + ' 뜻">ⓘ</button>';
  const big = v => {
    if (v == null) return "—";
    const a = Math.abs(v), sg = v < 0 ? "-" : "";
    if (a >= 1e12) return sg + "$" + (a / 1e12).toFixed(1) + "조";
    if (a >= 1e8) return sg + "$" + Math.round(a / 1e8).toLocaleString() + "억";
    if (a >= 1e4) return sg + "$" + Math.round(a / 1e4).toLocaleString() + "만";
    return sg + "$" + Math.round(a).toLocaleString();
  };
  function finFor(t) {
    const f = S.data && S.data.fin ? S.data.fin : {};
    return f[t] || f[String(t).replace(".", "-")] || null;
  }
  function finHtml(f) {
    if (!f) return '<div class="card sub">이 종목의 재무제표는 다음 아침 리포트부터 나와요.</div>';
    if (!f.available) return '<div class="card sub">' + esc(f.reason || "재무 자료가 없어요") + "</div>";
    const bandCls = { good: "band good", warn: "band warn", bad: "band bad" }[f.verdict] || "band";
    let h = '<div class="' + bandCls + '"><b>' + esc(f.verdict_text) + '</b><div class="small" style="color:inherit">' + esc(f.reason) + "</div></div>";
    h += '<div class="small" style="margin:8px 0 4px">체력 ' + f.fscore + "/" + f.fscore_max + " " + ti("체력 점수") +
      " · 버핏 체크 " + f.buffett_pass + "/" + f.buffett_max + " " + ti("버핏 체크") + " · " + esc((f.fy || "").slice(0, 4)) + "년 연간 공시</div>";
    h += '<div class="list">' + f.signals.map(sg =>
      '<details class="sig"><summary><span class="sdot" style="background:' + (toneColor[sg.tone] || "var(--line)") + '"></span><span class="grow"><b>' + esc(sg.title) +
      '</b><span class="small">' + esc(sg.text) + '</span></span><span class="small">숫자 ▾</span></summary><dl class="kv num">' +
      Object.entries(sg.nums || {}).map(([k, v]) => "<dt>" + esc(k) + " " + (TERMS[k] ? ti(k) : "") + "</dt><dd>" +
        (v == null ? "—" : esc(typeof v === "number" ? (/%|률|비율|변화/.test(k) && !/배율/.test(k) ? v + "%" : v) : v)) + "</dd>").join("") +
      "</dl></details>").join("") + "</div>";
    // F-2 100달러를 팔면
    if (f.flow100) {
      const parts = f.flow100.parts, shades = ["var(--seg1)", "var(--seg2)", "var(--seg3)"];
      const last = parts[parts.length - 1], loss = last.per100 < 0;
      h += '<h2>100달러를 팔면 (최근 1년 매출 ' + esc(f.flow100.revenue) + ")</h2>";
      h += '<div class="flowbar">' + parts.map((p, i) => {
        const w = Math.max(0, p.per100);
        const col = i === parts.length - 1 ? (loss ? "var(--bad)" : "var(--accent)") : shades[i % 3];
        return w > 0 ? '<span style="width:' + w + "%;background:" + col + '"></span>' : "";
      }).join("") + "</div>";
      h += '<div class="legend">' + parts.map((p, i) => {
        const col = i === parts.length - 1 ? (loss ? "var(--bad)" : "var(--accent)") : shades[i % 3];
        return '<div><span class="sdot" style="background:' + col + '"></span>' + esc(p.label) + ' <b class="num">$' + Math.abs(p.per100).toFixed(0) + "</b></div>";
      }).join("") + "</div>";
    }
    // 5년 추세
    const tr = f.trend || {}, rv = tr.revenue || [], opv = tr.op || [];
    const mx = Math.max(1, ...rv.filter(x => x != null).map(Math.abs), ...opv.filter(x => x != null).map(Math.abs));
    if (rv.filter(x => x != null).length >= 2) {
      const first = rv.find(x => x != null), lastv = rv[rv.length - 1];
      const ch = first && lastv ? (lastv / first - 1) * 100 : null;
      h += "<h2>" + esc(f.years[0] || "") + "→" + esc(f.years[f.years.length - 1] || "") + " 매출·영업이익</h2><div class=\"trend\">" +
        rv.map((v, i) => '<div class="tcol"><div class="tbars"><span class="tb rev" style="height:' + (v == null ? 0 : Math.max(2, Math.abs(v) / mx * 100)) + '%"></span>' +
          '<span class="tb op' + ((opv[i] || 0) < 0 ? " neg" : "") + '" style="height:' + (opv[i] == null ? 0 : Math.max(2, Math.abs(opv[i]) / mx * 100)) + '%"></span></div>' +
          '<div class="small">' + esc((f.years[i] || "").slice(2)) + "</div></div>").join("") + "</div>" +
        '<div class="small"><span class="sdot" style="background:var(--seg1)"></span>매출 <span class="sdot" style="background:var(--accent)"></span>영업이익' +
        (ch == null ? "" : " · 매출 " + (ch >= 0 ? "+" : "") + ch.toFixed(0) + "% (" + esc(f.years[0]) + "년 대비)") + "</div>";
    }
    // F-3 회사 살림
    const b = f.balance || {};
    if (b.assets) {
      const lh = Math.max(0, Math.min(100, (b.liab || 0) / b.assets * 100)), eh = Math.max(0, 100 - lh);
      h += "<h2>회사 살림 (가진 것 = 빚 + 주주 몫)</h2><div class=\"bal\">" +
        '<div class="bcol"><div class="bstack"><span style="height:100%;background:var(--accent-bg);border-color:var(--accent)"></span></div><div class="small">가진 것 ' + ti("가진 것") + "<br><b>" + big(b.assets) + "</b></div></div>" +
        '<div class="bcol"><div class="bstack"><span style="height:' + eh + '%;background:var(--good-bg);border-color:var(--good)"></span><span style="height:' + lh + '%;background:var(--bad-bg);border-color:var(--bad)"></span></div>' +
        '<div class="small">주주 몫 ' + ti("주주 몫") + " <b>" + big(b.equity) + "</b><br>빚 " + ti("빚") + " <b>" + big(b.liab) + "</b></div></div></div>";
    }
    const c = f.cash || {};
    if (c.ocf != null) {
      h += '<h2>1년 통장 입출금</h2><div class="card"><dl class="kv num">' +
        "<dt>+ 장사로 들어온 돈 " + ti("영업현금흐름") + '</dt><dd style="color:' + (c.ocf >= 0 ? "var(--good)" : "var(--bad)") + '">' + big(c.ocf) + "</dd>" +
        (c.capex != null ? "<dt>− 공장·설비에 쓴 돈</dt><dd>" + big(-Math.abs(c.capex)) + "</dd>" : "") +
        (c.dividends ? "<dt>− 주주에게 배당</dt><dd>" + big(-Math.abs(c.dividends)) + "</dd>" : "") +
        (c.buyback ? "<dt>− 자사주 매입</dt><dd>" + big(-Math.abs(c.buyback)) + "</dd>" : "") +
        (c.debt_repay ? "<dt>− 빚 갚기</dt><dd>" + big(-Math.abs(c.debt_repay)) + "</dd>" : "") +
        "<dt>= 남는 현금 " + ti("자유현금흐름") + "</dt><dd><b>" + big(c.fcf) + "</b></dd></dl></div>";
    }
    // F-4 버핏 체크
    h += '<h2>버핏 체크 ' + f.buffett_pass + "/" + f.buffett_max + " " + ti("버핏 체크") + '</h2><div class="list">' + (f.buffett || []).map(x =>
      '<div class="item" style="cursor:default;align-items:flex-start"><span class="bk ' + (x.ok === true ? "ok" : x.ok === false ? "no" : "na") + '">' +
      (x.ok === true ? "✓" : x.ok === false ? "✕" : "—") + '</span><div class="grow"><b>' + esc(x.title) + "</b>" +
      (x.value != null ? ' <span class="small num">(' + esc(x.value) + ")</span>" : "") +
      '<div class="small">' + esc(x.why) + "</div></div></div>").join("") + "</div>";
    if (f.financial_company) h += '<div class="msg note">금융·리츠·BDC는 빚을 장사 도구로 써요. 부채비율 대신 배당을 이익·현금으로 감당하는지를 보세요.</div>';
    h += '<p class="foot">' + esc(f.source || "") + " · 지난 숫자예요. 재무가 좋아도 비싸게 사면 손해를 볼 수 있어요.</p>";
    return h;
  }
  document.addEventListener("click", ev => {
    const b = ev.target.closest && ev.target.closest(".tip");
    if (!b) return;
    ev.preventDefault(); ev.stopPropagation();
    const k = b.dataset.term, sh = document.getElementById("sheet");
    sh.innerHTML = '<div class="sheet-in"><b>' + esc(k) + '</b><p>' + esc(TERMS[k] || "") + '</p><button class="btn ghost" id="sheetClose">닫기</button></div>';
    sh.hidden = false;
    document.getElementById("sheetClose").onclick = () => { sh.hidden = true; };
  });

  /* ---------- 화면: 앱 ---------- */
  function appShell(tab, html) {
    $tabs.hidden = false;
    [...$tabs.querySelectorAll("a")].forEach(a => a.classList.toggle("on", a.dataset.tab === tab));
    $app.innerHTML = html;
  }
  function statusLine() {
    let s = "";
    if (S.loading) s += '<div class="small">새로 불러오는 중…</div>';
    if (S.error) s += '<div class="msg err">' + esc(S.error) + "</div>";
    return s;
  }
  function needData(tab) {
    if (S.data) return false;
    appShell(tab, statusLine() + (S.loading || !S.error ? '<div class="skel"></div><div class="skel"></div><div class="skel"></div>'
      : '<div class="empty">아직 받은 리포트가 없어요. 아침 리포트가 한 번 돌면 여기에 나와요.</div>'));
    return true;
  }
  const allPicks = () => (S.data.bands || []).flatMap(b => b.picks.concat(b.etf_picks || []));
  const findPick = t => allPicks().find(p => p.t === t);
  const findHold = t => (S.data.holdings || []).find(h => h.t === t);

  function viewHome() {
    if (needData("home")) return;
    const d = S.data, s = d.summary || {};
    const newest = (S.alerts[0] || {}).at || "";
    const hasNew = newest && newest !== S.lastSeenAlert;
    const hold = (d.holdings || []).slice(0, 4);
    const top = allPicks().filter(p => !p.etf).sort((a, b) => b.total - a.total).slice(0, 3);
    appShell("home",
      '<div class="head"><div><h1>오늘 · ' + esc(d.date_label || "") + '</h1><div class="small">미국 ' + esc(d.date) + " 종가 기준 · " + esc(whenText(d.run_at)) + "</div></div>" +
      '<button class="iconbtn" aria-label="알림" onclick="location.hash=\'#/alerts\'">🔔' + (hasNew ? '<span class="dot"></span>' : "") + "</button></div>" +
      statusLine() +
      '<div class="band' + (d.market.rest_day ? " bad" : "") + '">' + esc(d.market.label) + (d.market.rest_day ? " · 오늘은 매수 쉬는 날" : " · 매수 기준 " + esc(d.market.threshold) + "점") + "</div>" +
      '<div class="card"><div class="sub">오늘 볼 것</div><div class="big num">매도 ' + (s.sell || 0) + " · 신규 매수 " + (s.new || 0) + "</div>" +
      '<div class="small">매수 후보 ' + (s.buy || 0) + "개 (개별 종목 " + (s.stock || 0) + "개)</div></div>" +
      (d.warnings && d.warnings.length ? d.warnings.map(w => '<div class="msg note">' + esc(w) + "</div>").join("") : "") +
      '<h2>내 보유 한 줄 결론</h2><div class="list">' +
      (hold.length ? hold.map(h => '<div class="item" onclick="location.hash=\'#/hold/' + encodeURIComponent(h.t) + '\'"><span class="tk">' + esc(h.t) +
        '</span><span class="grow small num">' + pct(h.gain_pct) + '</span><span class="badge ' + esc(h.tone) + '">' + esc(h.conclusion) + "</span></div>").join("")
        : '<div class="empty">보유 종목이 없어요</div>') + "</div>" +
      ((d.holdings || []).length > 4 ? '<a class="link" href="#/holdings">보유 전체 보기 →</a>' : "") +
      '<h2>매수 후보 상위 (개별 종목)</h2><div class="list">' +
      (top.length ? top.map(p => '<div class="item" onclick="location.hash=\'#/pick/' + encodeURIComponent(p.t) + '\'"><span class="tk">' + esc(p.t) +
        '</span><span class="grow small">' + esc(p.band) + '</span><span class="num"><b>' + fmt(p.total, 0) + "</b>점</span></div>").join("")
        : '<div class="empty">' + (d.market.rest_day ? "매수 쉬는 날이라 후보가 없어요" : "오늘은 조건에 맞는 종목이 없어요") + "</div>") + "</div>" +
      '<a class="link" href="#/picks">전체 후보 보기 →</a><p class="foot">' + esc(DISCLAIMER) + "</p>");
  }

  function pickCard(p) {
    const pl = p.plan || {};
    return '<div class="card tap' + (p.etf ? " dash" : "") + '" onclick="location.hash=\'#/pick/' + encodeURIComponent(p.t) + '\'">' +
      '<div class="row between"><span><b>' + esc(p.t) + '</b> <span class="num">· ' + fmt(p.total, 0) + '점</span></span><span class="num">$' + fmt(p.price) + "</span></div>" +
      '<div class="small">' + esc((p.name || "").slice(0, 46)) + "</div>" +
      '<div class="small num">구간 ' + fmt(pl.zone_low) + "~" + fmt(pl.zone_high) + " · 손절 " + fmt(pl.stop) + " · 목표 " + fmt(pl.target) + "</div>" +
      tags(p.tags) + "</div>";
  }
  function viewPicks() {
    if (needData("picks")) return;
    const d = S.data;
    const limits = { all: Infinity, "10": 10, "30": 30, "50": 50, "100": 100 };
    const lim = limits[S.filter] || Infinity;
    const bands = (d.bands || []).filter(b => {
      const lo = parseFloat(b.name); return isNaN(lo) || lo < lim;
    }).filter(b => b.picks.length || (b.etf_picks || []).length || (b.dropped || []).length);
    appShell("picks", '<div class="head"><h1>매수 후보</h1></div>' + statusLine() +
      '<div class="chips">' + [["all", "전체"], ["10", "10달러 이하"], ["30", "30달러 이하"], ["50", "50달러 이하"], ["100", "100달러 이하"]]
        .map(c => '<button class="chip' + (S.filter === c[0] ? " on" : "") + '" data-f="' + c[0] + '">' + c[1] + "</button>").join("") + "</div>" +
      (d.market.rest_day ? '<div class="msg note">오늘은 매수 쉬는 날이에요. 아래 목록은 참고용이에요.</div>' : "") +
      (bands.length ? bands.map(b =>
        "<h2>" + esc(b.name) + " · 조건 맞음 " + b.count + " · 종목 " + b.picks.length + " · ETF " + (b.etf_picks || []).length + "</h2>" +
        b.picks.map(pickCard).join("") +
        ((b.etf_picks || []).length ? '<div class="small" style="margin-top:10px">ETF·펀드 (따로 순위)</div>' + b.etf_picks.map(pickCard).join("") : "") +
        ((b.dropped || []).length ? '<div class="small">어제에서 빠짐: ' + esc(b.dropped.join(", ")) + "</div>" : "")
      ).join("") : '<div class="empty">이 가격대에는 오늘 후보가 없어요</div>') +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    $app.querySelectorAll(".chip").forEach(b => b.addEventListener("click", () => { S.filter = b.dataset.f; store.set("filter", S.filter); viewPicks(); }));
  }

  function scoreBars(cats) {
    return ["추세", "가치", "성장", "안전"].map(k => {
      const v = cats ? cats[k] : null;
      const w = v == null ? 0 : Math.max(0, Math.min(100, v / 25 * 100));
      return '<div class="bar"><span class="l">' + k + '</span><span class="t"><span class="f" style="width:' + w + '%;display:block"></span></span><span class="v num">' + (v == null ? "—" : fmt(v, 0)) + "</span></div>";
    }).join("") + '<div class="small">항목마다 25점 만점 · ETF·펀드는 가치·성장 점수가 없어요</div>';
  }
  function viewPick(t) {
    if (needData("picks")) return;
    const p = findPick(t);
    if (!p) return appShell("picks", '<button class="back" onclick="history.back()">← 뒤로</button><div class="empty">오늘 목록에 없는 종목이에요</div>');
    const pl = p.plan || {};
    const cons = (p.tags || []).filter(x => /실적|보류|출렁임|위험|참고/.test(x)).concat(p.caution ? [p.caution] : []).concat(p.warn ? [p.warn] : []);
    appShell("picks", '<button class="back" onclick="history.back()">← 뒤로</button>' +
      '<div class="row between"><h1>' + esc(p.t) + '</h1><span class="sub num">총점 <b>' + fmt(p.total, 0) + "</b></span></div>" +
      '<div class="sub">' + esc(p.name) + "</div>" +
      '<div class="big num" style="margin-top:6px">$' + fmt(p.price) + "</div>" +
      '<div class="small">' + esc(p.band) + " · " + (p.streak > 1 ? "연속 " + p.streak + "일" : "신규") + (p.etf ? " · ETF·펀드" : "") + "</div>" +
      tags(p.tags) +
      '<div class="segs"><button class="on" data-s="fin">재무 5초</button><button data-s="pro">찬반 근거</button><button data-s="v4">4관점</button><button data-s="rep">쉬운 리포트</button></div><div id="seg"></div>' +
      "<h2>점수</h2>" + scoreBars(p.cats) +
      '<h2>매수 계획</h2><div class="card"><dl class="kv num">' +
      "<dt>매수 구간</dt><dd>" + fmt(pl.zone_low) + " ~ " + fmt(pl.zone_high) + "</dd>" +
      "<dt>손절</dt><dd>" + fmt(pl.stop) + " (" + fmt(pl.risk_pct, 1) + "%)</dd>" +
      "<dt>1차 목표</dt><dd>" + fmt(pl.target) + " (손익비 " + fmt(pl.rr, 1) + ")</dd>" +
      "<dt>이 위로 시작하면 추격 금지</dt><dd>" + fmt(pl.skip_if_open_above) + "</dd>" +
      "<dt>유효 기한</dt><dd>" + esc(pl.valid_until || "") + "</dd></dl></div>" +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    const segs = {
      fin: finHtml(finFor(p.t)),
      pro: '<div class="card"><b>좋은 점</b><ul class="plain">' + (p.reasons || []).map(r => "<li>" + esc(r) + "</li>").join("") + "</ul>" +
        (p.desc ? '<div class="sub">' + esc(p.desc) + "</div>" : "") + "</div>" +
        '<div class="card"><b>걱정되는 점</b><ul class="plain">' + (cons.length ? cons.map(r => "<li>" + esc(r) + "</li>").join("") : "<li>오늘 규칙상 특별한 경고는 없어요</li>") + "</ul></div>",
      v4: '<div class="empty">버핏식 4관점 점검은 4단계에서 열려요</div>',
      rep: '<div class="empty">쉬운 기업 리포트는 4단계에서 열려요</div>',
    };
    const seg = document.getElementById("seg");
    seg.innerHTML = segs.fin;
    $app.querySelectorAll(".segs button").forEach(b => b.addEventListener("click", () => {
      $app.querySelectorAll(".segs button").forEach(x => x.classList.toggle("on", x === b)); seg.innerHTML = segs[b.dataset.s];
    }));
  }

  function viewHoldings() {
    if (needData("holdings")) return;
    const hs = S.data.holdings || [];
    const flagged = hs.filter(h => h.tone !== "good").length;
    appShell("holdings", '<div class="head"><h1>내 보유 · ' + hs.length + '종목</h1><span class="small">' + esc(whenText(S.data.run_at)) + "</span></div>" + statusLine() +
      (flagged ? '<div class="band bad">매도 규칙을 확인할 종목 ' + flagged + "개</div>" : '<div class="band">모든 종목이 원칙대로예요</div>') +
      '<div class="list" style="margin-top:8px">' + (hs.length ? hs.map(h =>
        '<div class="item" onclick="location.hash=\'#/hold/' + encodeURIComponent(h.t) + '\'"><div class="grow"><div class="row between"><span class="tk">' + esc(h.t) +
        '</span><span class="badge ' + esc(h.tone) + '">' + esc(h.conclusion) + "</span></div>" +
        '<div class="small num">수익률 ' + pct(h.gain_pct) + " · 손절선까지 " + (h.to_stop_pct == null ? "—" : fmt(h.to_stop_pct, 1) + "%") + "</div></div></div>").join("")
        : '<div class="empty">보유 종목이 없어요. 배당 대시보드 시트의 내 종목을 읽어요.</div>') + "</div>" +
      '<p class="foot">보유 종목은 구글 시트에서 읽어요 · ' + esc(DISCLAIMER) + "</p>");
  }

  function viewHold(t) {
    if (needData("holdings")) return;
    const h = findHold(t);
    if (!h) return appShell("holdings", '<button class="back" onclick="history.back()">← 뒤로</button><div class="empty">보유 목록에 없는 종목이에요</div>');
    appShell("holdings", '<button class="back" onclick="history.back()">← 뒤로</button>' +
      '<div class="row between"><h1>' + esc(h.t) + '</h1><span class="badge ' + esc(h.tone) + '">' + esc(h.conclusion) + "</span></div>" +
      '<div class="sub">' + esc(h.name || "") + "</div>" +
      (h.action ? '<div class="msg ' + (h.tone === "bad" ? "err" : "note") + '">규칙상 할 일: <b>' + esc(h.action) + "</b></div>" : "") +
      '<h2>재무 5초</h2>' + finHtml(finFor(h.t)) +
      '<h2>지금 상태</h2><div class="card"><dl class="kv num">' +
      "<dt>현재가</dt><dd>$" + fmt(h.price) + "</dd><dt>평단</dt><dd>$" + fmt(h.avg) + "</dd><dt>수량</dt><dd>" + fmt(h.qty, 0) + "</dd>" +
      "<dt>수익률</dt><dd>" + pct(h.gain_pct) + "</dd><dt>손절선</dt><dd>$" + fmt(h.stop) + " (" + (h.to_stop_pct == null ? "—" : fmt(h.to_stop_pct, 1) + "% 위") + ")</dd>" +
      "<dt>1차 목표</dt><dd>$" + fmt(h.target) + "</dd><dt>총점</dt><dd>" + (h.total == null ? "—" : fmt(h.total, 0)) + "</dd></dl></div>" +
      "<h2>걸린 매도 규칙</h2>" + (h.hits && h.hits.length ? '<div class="card"><ul class="plain">' + h.hits.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul></div>"
        : '<div class="card">걸린 규칙이 없어요. 원칙대로 보유하면 돼요.</div>') +
      (h.cats && Object.keys(h.cats).length ? "<h2>점수</h2>" + scoreBars(h.cats) : "") +
      (h.reasons && h.reasons.length ? '<h2>좋은 점</h2><div class="card"><ul class="plain">' + h.reasons.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul></div>" : "") +
      '<p class="foot">손절선을 바꾸려면 구글 시트 \'보유 종목\' 탭에 적어 주세요 · ' + esc(DISCLAIMER) + "</p>");
  }

  function viewAlerts() {
    const items = S.alerts || [];
    if (items[0]) { S.lastSeenAlert = items[0].at; store.set("seenAlert", S.lastSeenAlert); }
    const tone = { bad: "var(--bad)", warn: "var(--warn)", info: "var(--accent)" };
    appShell("home", '<button class="back" onclick="history.back()">← 홈</button><h1>알림</h1>' + statusLine() +
      '<div class="small">푸시·슬랙으로 보낸 것과 같은 내용이에요 (최근 200개)</div><div class="list">' +
      (items.length ? items.map(a => '<div class="item" style="cursor:default"><span style="width:10px;height:10px;border-radius:5px;background:' + (tone[a.tone] || tone.info) +
        '"></span><div class="grow"><div class="row between"><b>' + esc(a.title) + '</b><span class="small">' + esc(whenText(a.at)) + '</span></div><div class="small">' + esc(a.body) + "</div></div></div>").join("")
        : '<div class="empty">아직 알림이 없어요</div>') + "</div>");
  }

  function viewScore() {
    appShell("score", '<div class="head"><h1>성적 · 모의투자</h1></div><div class="card"><b>3단계에서 열려요</b>' +
      '<p class="sub">모의 계좌, SPY 대비 성적, "처음 20번 vs 최근 20번" 비교, 회고 한 줄이 들어올 자리예요. 그전까지 신호 성적은 일요일 주간 요약(슬랙)으로 받아요.</p></div>');
  }

  function viewSettings() {
    appShell("settings", '<div class="head"><h1>설정</h1></div>' +
      '<div class="card"><div class="row between"><span>앱 버전</span><span class="sub">' + esc(CFG.VERSION || "") + '</span></div>' +
      '<div class="row between"><span>이 기기</span><span class="sub">' + esc(deviceLabel()) + "</span></div></div>" +
      '<h2>계정</h2><a class="btn ghost" href="#/password">비밀번호 바꾸기</a>' +
      '<button class="btn ghost" id="hist">최근 로그인 기록</button><div id="histOut"></div>' +
      '<button class="btn ghost" id="out">로그아웃</button><button class="btn danger" id="outAll">모든 기기 로그아웃</button>' +
      '<h2>표시 설정</h2><div class="card sub">보여줄 개수, ETF 개수, 최대 손실 같은 기준은 구글 시트 \'설정\' 탭에서 바꿔요. 다음 리포트부터 적용돼요.</div>' +
      '<h2>설치</h2><div class="card sub">아이폰: 사파리 공유 버튼 → "홈 화면에 추가". 홈 화면 아이콘으로 열면 주소창 없이 앱처럼 열려요.</div>' +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    document.getElementById("hist").onclick = async () => {
      const o = document.getElementById("histOut"); o.innerHTML = '<div class="small">불러오는 중…</div>';
      try {
        const j = await api("history", { token: S.token });
        o.innerHTML = j.ok ? '<div class="list">' + (j.logins || []).map(l => '<div class="item" style="cursor:default"><div class="grow"><b>' + esc(l.what) +
          '</b><div class="small">' + esc(whenText(l.at)) + " · " + esc(l.label) + "</div></div></div>").join("") + "</div>" : '<div class="msg err">' + esc(j.error) + "</div>";
      } catch (e) { o.innerHTML = '<div class="msg err">' + esc(e.message) + "</div>"; }
    };
    document.getElementById("out").onclick = async () => {
      try { await api("logout", { token: S.token }); } catch (e) {}
      clearAll(); go("#/login");
    };
    document.getElementById("outAll").onclick = async () => {
      if (!confirm("모든 기기에서 로그아웃할까요? 이 기기도 다시 로그인해야 해요.")) return;
      try { await api("logoutAll", { token: S.token }); } catch (e) {}
      clearAll(); go("#/login");
    };
  }

  function viewPassword() {
    appShell("settings", '<button class="back" onclick="history.back()">← 설정</button><h1>비밀번호 바꾸기</h1>' +
      '<form id="f"><label for="cur">지금 비밀번호</label><input id="cur" type="password" autocomplete="current-password" required>' +
      '<label for="n1">새 비밀번호</label><input id="n1" type="password" autocomplete="new-password" required><div id="rules">' + rulesHtml("") + "</div>" +
      '<label for="n2">한 번 더</label><input id="n2" type="password" autocomplete="new-password" required>' +
      '<button class="btn" type="submit">바꾸기</button><div class="out"></div></form><p class="foot">바꾸면 다른 기기는 모두 로그아웃돼요</p>');
    const f = document.getElementById("f");
    f.n1.addEventListener("input", () => { document.getElementById("rules").innerHTML = rulesHtml(f.n1.value); });
    bindForm("f", async (f, msg) => {
      if (f.n1.value !== f.n2.value) { msg.innerHTML = '<div class="msg err">두 비밀번호가 달라요.</div>'; return; }
      const keep = store.get("keepPref") !== "0";
      const j = await api("setPassword", { token: S.token, currentPw: f.cur.value, newPw: f.n1.value, keep: keep });
      if (!j.ok) { msg.innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; return; }
      setSession(j.token, j.scope, keep);
      toast("비밀번호를 바꿨어요"); go("#/settings");
    });
  }

  /* ---------- 길 찾기 ---------- */
  let checkedAccount = false;
  async function render() {
    const h = location.hash || "#/home";
    const [, route, arg] = h.split("/");
    const open = ["login", "forgot", "setup"];
    if (!S.token) {
      if (open.indexOf(route) < 0) {
        if (!checkedAccount && CFG.API_URL) {
          checkedAccount = true;
          try { const j = await api("status"); return go(j.hasAccount ? "#/login" : "#/setup"); } catch (e) {}
        }
        return go("#/login");
      }
    } else if (S.scope === "reset" && route !== "reset") {
      return go("#/reset");
    }
    window.scrollTo(0, 0);
    const sh = document.getElementById("sheet"); if (sh) sh.hidden = true;
    switch (route) {
      case "login": return viewLogin();
      case "forgot": return viewForgot();
      case "setup": return viewSetup();
      case "reset": return viewReset();
      case "picks": return viewPicks();
      case "pick": return viewPick(decodeURIComponent(arg || ""));
      case "holdings": return viewHoldings();
      case "hold": return viewHold(decodeURIComponent(arg || ""));
      case "alerts": return viewAlerts();
      case "score": return viewScore();
      case "settings": return viewSettings();
      case "password": return viewPassword();
      default: return viewHome();
    }
  }
  window.addEventListener("hashchange", render);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
  window.addEventListener("online", () => refresh(true));
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  render();
  refresh(true);
})();
