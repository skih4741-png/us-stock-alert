/* 미국주식 알림 앱 — 1~4단계 (로그인 · 홈 · 후보 · 보유 · 상세 · 알림 · 성적·모의투자 · 설정) */
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
    data: null, alerts: [], perf: null, weekly: null, paper: [], ai: null, gap: null, profile: null, aiUsage: null, loading: false, error: "", filter: store.get("filter") || "all", lastSeenAlert: store.get("seenAlert") || "",
  };
  try { const c = JSON.parse(store.get("cache") || "null"); if (c) { S.data = c.daily; S.alerts = c.alerts || []; S.perf = c.perf || null; S.weekly = c.weekly || null; S.paper = c.paper || []; S.ai = c.ai || null; S.gap = c.gap || null; S.profile = c.profile || null; S.aiUsage = c.aiUsage || null; S.kis = c.kis || null; } } catch (e) {}

  function setSession(token, scope, keep) {
    store.del("token"); store.del("scope");
    S.token = token; S.scope = scope;
    if (!token) return;
    const where = keep ? localStorage : sessionStorage;
    store.set("token", token, where); store.set("scope", scope, where);
  }
  function clearAll() {
    setSession(null, null);
    store.del("cache"); S.data = null; S.alerts = []; S.perf = null; S.weekly = null; S.paper = [];
  }

  /* ---------- 서버 ---------- */
  async function api(action, body) {
    if (!CFG.API_URL) throw new Error("로그인 서버 주소가 아직 설정되지 않았어요 (config.js)");
    const payload = JSON.stringify(Object.assign({ action: action, device: deviceId(), label: deviceLabel() }, body || {}));
    let res, last;
    for (let i = 0; i < 3; i++) {  // 연결이 잠깐 끊겨도 두 번 더 시도
      try {
        res = await fetch(CFG.API_URL, {
          method: "POST", redirect: "follow", cache: "no-store", credentials: "omit",
          headers: { "Content-Type": "text/plain;charset=utf-8" }, body: payload,
        });
        break;
      } catch (e) { last = e; await new Promise(r => setTimeout(r, 800 * (i + 1))); }
    }
    if (!res) throw new Error("서버에 연결하지 못했어요. 인터넷 연결(와이파이·VPN·광고 차단 앱)을 확인하고 다시 시도해 주세요. (" + (last && last.message) + ")");
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
        S.data = j.daily; S.alerts = j.alerts || []; S.perf = j.perf || null; S.weekly = j.weekly || null; S.paper = j.paper || []; S.ai = j.ai || null; S.gap = j.gap || null; S.profile = j.profile || null; S.aiUsage = j.aiUsage || null; S.kis = j.kis || null;
        saveCache();
      } else if (!j.auth) S.error = j.error || "불러오지 못했어요";
    } catch (e) {
      S.error = navigator.onLine ? e.message : "인터넷이 없어요. 마지막으로 받은 내용을 보여드려요.";
    }
    S.loading = false;
    render();
  }

  function saveCache() {
    store.set("cache", JSON.stringify({ daily: S.data, alerts: S.alerts, perf: S.perf, weekly: S.weekly, paper: S.paper, ai: S.ai, gap: S.gap, profile: S.profile, aiUsage: S.aiUsage, kis: S.kis, at: Date.now() }));
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


  /* ---------- 2단계: 앱 푸시 ---------- */
  const KINDS = [["daily", "아침 리포트"], ["watch", "장중 경고 (손절선·급락)"], ["weekly", "주간 요약"]];
  const isStandalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
  const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  function b64ToBytes(b64) {
    const pad = "=".repeat((4 - b64.length % 4) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  }
  async function currentSub() {
    if (!pushSupported()) return null;
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  }
  async function renderPush() {
    const box = document.getElementById("pushBox");
    if (!box) return;
    if (isIOS() && !isStandalone()) {
      box.innerHTML = '<div class="card sub">아이폰은 <b>홈 화면에 추가한 앱</b>에서만 알림을 켤 수 있어요. 사파리 공유 버튼 → "홈 화면에 추가" 후, 홈 화면 아이콘으로 열어 주세요. (iOS 16.4 이상)</div>';
      return;
    }
    if (!pushSupported()) { box.innerHTML = '<div class="card sub">이 브라우저는 앱 알림을 지원하지 않아요. 슬랙으로는 계속 받아요.</div>'; return; }
    if (!CFG.VAPID_PUBLIC_KEY) { box.innerHTML = '<div class="card sub">알림 서버 준비 중이에요.</div>'; return; }
    if (Notification.permission === "denied") {
      box.innerHTML = '<div class="msg err">알림이 차단돼 있어요. 아이폰 설정 → 알림 → 주식알림에서 허용해 주세요.</div>';
      return;
    }
    const sub = await currentSub();
    let kinds = KINDS.map(k => k[0]), on = false;
    if (sub) {
      try { const j = await api("pushStatus", { token: S.token, endpoint: sub.endpoint }); on = j.ok && j.registered; if (on && j.kinds.length) kinds = j.kinds; } catch (e) {}
    }
    box.innerHTML = '<div class="card">' +
      '<div class="row between"><b>' + (on ? "알림 받는 중" : "알림 꺼짐") + '</b><span class="badge ' + (on ? "good" : "") + '">' + (on ? "켜짐" : "꺼짐") + "</span></div>" +
      KINDS.map(k => '<label class="check"><input type="checkbox" data-kind="' + k[0] + '"' + (kinds.indexOf(k[0]) >= 0 ? " checked" : "") + "> " + k[1] + "</label>").join("") +
      '<div class="small">알림을 누르면 앱의 해당 화면이 열려요. 슬랙으로도 그대로 와요.</div></div>' +
      (on ? '<button class="btn ghost" id="pushSave">알림 종류 저장</button><button class="btn danger" id="pushOff">이 기기 알림 끄기</button>'
          : '<button class="btn" id="pushOn">알림 켜기</button>') + '<div id="pushMsg"></div>';
    const chosen = () => [...box.querySelectorAll("input[data-kind]")].filter(x => x.checked).map(x => x.dataset.kind);
    const msg = (t, ok) => { document.getElementById("pushMsg").innerHTML = '<div class="msg ' + (ok ? "ok" : "err") + '">' + esc(t) + "</div>"; };
    const onBtn = document.getElementById("pushOn");
    if (onBtn) onBtn.onclick = async () => {
      onBtn.disabled = true;
      try {
        const perm = await Notification.requestPermission();
        if (perm !== "granted") { msg("알림을 허용해야 켤 수 있어요.", false); onBtn.disabled = false; return; }
        const reg = await navigator.serviceWorker.ready;
        const s2 = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(CFG.VAPID_PUBLIC_KEY) });
        const j = await api("savePush", { token: S.token, sub: s2.toJSON(), kinds: chosen() });
        if (!j.ok) { msg(j.error || "저장하지 못했어요", false); onBtn.disabled = false; return; }
        reg.showNotification("알림이 켜졌어요", { body: "아침 리포트·장중 경고가 이 휴대폰으로 와요.", icon: "icons/icon-192.png", tag: "welcome" });
        toast("알림을 켰어요"); renderPush();
      } catch (e) { msg("알림을 켜지 못했어요: " + e.message, false); onBtn.disabled = false; }
    };
    const save = document.getElementById("pushSave");
    if (save) save.onclick = async () => {
      const s2 = await currentSub();
      const j = await api("savePush", { token: S.token, sub: s2.toJSON(), kinds: chosen() });
      j.ok ? toast("알림 종류를 저장했어요") : msg(j.error, false);
    };
    const off = document.getElementById("pushOff");
    if (off) off.onclick = async () => {
      const s2 = await currentSub();
      if (s2) { try { await api("removePush", { token: S.token, endpoint: s2.endpoint }); } catch (e) {} await s2.unsubscribe(); }
      toast("이 기기 알림을 껐어요"); renderPush();
    };
  }

  /* ---------- 화면: 앱 ---------- */
  function appShell(tab, html) {
    $tabs.hidden = false;
    [...$tabs.querySelectorAll("a")].forEach(a => a.classList.toggle("on", a.dataset.tab === tab));
    $app.innerHTML = html;
    stickOffsets();
  }
  // 위에 고정되는 줄(뒤로·제목) 높이를 재서, 그 아래 탭·필터 줄이 겹치지 않게 붙여요
  function stickOffsets() {
    const top = $app.querySelector(":scope > .back, :scope > .head");
    document.documentElement.style.setProperty("--stickH", (top ? top.offsetHeight : 0) + "px");
  }
  window.addEventListener("resize", () => stickOffsets());
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

  function homeSimCard() {
    const m = S.perf && S.perf.sim;
    if (!m) return "";
    const today = (m.today || []).slice(0, 3);
    return '<a class="card" href="#/score" style="display:block;color:var(--ink)"><div class="row between"><span class="sub">자동 모의 ' + m.day + "/" + m.days +
      '일째 (가상 $' + fmt(m.budget, 0) + ')</span><b class="num ' + (m.ret >= 0 ? "good-t" : "bad-t") + '">$' + fmt(m.equity) + " " + pct(m.ret) + "</b></div>" +
      '<div class="small num">번 돈 ' + usd(m.gain) + " · 잃은 돈 " + usd(m.loss) + " · 오늘 밤 주문 " + (m.pending || []).length + "건</div>" +
      (today.length ? '<div class="small" style="margin-top:4px">' + today.map(esc).join("<br>") + "</div>" : '<div class="small">지난 거래일 체결·매도 없음</div>') + "</a>";
  }
  function homePaperCard() {
    if (!(S.paper || []).length) return "";
    const m = moneySummary(paperTrades()), net = m.gain + m.loss;
    return '<a class="card" href="#/score" style="display:block;color:var(--ink)"><div class="row between"><span class="sub">모의 계좌 (가상 $1,000)</span><b class="num ' +
      (net >= 0 ? "good-t" : "bad-t") + '">' + usd(net) + '</b></div><div class="small num">번 돈 ' + usd(m.gain) + " · 잃은 돈 " + usd(m.loss) + " · 성적 보기 →</div></a>";
  }
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
      (pushSupported() && isStandalone() && CFG.VAPID_PUBLIC_KEY && Notification.permission === "default"
        ? '<a class="card" href="#/settings" style="display:block;color:var(--ink)"><b>🔔 알림 켜기</b><div class="small">아침 리포트·장중 경고를 푸시로 받아요 →</div></a>' : "") +
      '<div class="band' + (d.market.rest_day ? " bad" : "") + '">' + esc(d.market.label) + (d.market.rest_day ? " · 오늘은 매수 쉬는 날" : " · 매수 기준 " + esc(d.market.threshold) + "점") + "</div>" +
      '<div class="card"><div class="sub">오늘 볼 것</div><div class="big num">매도 ' + (s.sell || 0) + " · 신규 매수 " + (s.new || 0) + "</div>" +
      '<div class="small">매수 후보 ' + (s.buy || 0) + "개 (개별 종목 " + (s.stock || 0) + "개)</div></div>" +
      (d.warnings && d.warnings.length ? d.warnings.map(w => '<div class="msg note">' + esc(w) + "</div>").join("") : "") +
      '<div class="quick"><a class="chip" href="#/ask">💬 AI에게 묻기</a><a class="chip" href="#/gap">장 전 갭' +
        (S.gap && (S.gap.items || []).some(x => x.cond) ? ' <span class="badge warn">' + S.gap.items.filter(x => x.cond).length + "</span>" : "") + "</a>" +
        (!S.profile || !Object.keys(S.profile).length ? '<a class="chip" href="#/profile">성향 인터뷰 하기</a>' : "") + "</div>" +
      briefCard() + homeSimCard() + homePaperCard() +
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
      "<h2>점수</h2>" + scoreBars(p.cats) + trendHtml(p.trend5) + earnHtml(p.t) + pmHtml(p.t) +
      '<h2>매수 계획</h2><div class="card"><dl class="kv num">' +
      "<dt>매수 구간</dt><dd>" + fmt(pl.zone_low) + " ~ " + fmt(pl.zone_high) + "</dd>" +
      "<dt>손절</dt><dd>" + fmt(pl.stop) + " (" + fmt(pl.risk_pct, 1) + "%)</dd>" +
      "<dt>1차 목표</dt><dd>" + fmt(pl.target) + " (손익비 " + fmt(pl.rr, 1) + ")</dd>" +
      "<dt>이 위로 시작하면 추격 금지</dt><dd>" + fmt(pl.skip_if_open_above) + "</dd>" +
      "<dt>유효 기한</dt><dd>" + esc(pl.valid_until || "") + "</dd></dl></div>" +
      paperAddHtml(p) +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    bindPaperAdd(p);
    const segs = {
      fin: finHtml(finFor(p.t)),
      pro: '<div class="card"><b>좋은 점</b><ul class="plain">' + (p.reasons || []).map(r => "<li>" + esc(r) + "</li>").join("") + "</ul>" +
        (p.desc ? '<div class="sub">' + esc(p.desc) + "</div>" : "") + "</div>" +
        '<div class="card"><b>걱정되는 점</b><ul class="plain">' + (cons.length ? cons.map(r => "<li>" + esc(r) + "</li>").join("") : "<li>오늘 규칙상 특별한 경고는 없어요</li>") + "</ul></div>",
      v4: b4Html(p.t),
      rep: repHtml(p.t),
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
      '<h2>재무 5초</h2>' + finHtml(finFor(h.t)) + earnHtml(h.t) +
      '<details class="sig"><summary><b>버핏 4관점</b></summary>' + b4Html(h.t) + "</details>" +
      '<details class="sig"><summary><b>쉬운 리포트</b></summary>' + repHtml(h.t) + "</details>" +
      '<h2>지금 상태</h2><div class="card"><dl class="kv num">' +
      "<dt>현재가</dt><dd>$" + fmt(h.price) + "</dd><dt>평단</dt><dd>$" + fmt(h.avg) + "</dd><dt>수량</dt><dd>" + fmt(h.qty, 0) + "</dd>" +
      "<dt>수익률</dt><dd>" + pct(h.gain_pct) + "</dd><dt>손절선</dt><dd>$" + fmt(h.stop) + " (" + (h.to_stop_pct == null ? "—" : fmt(h.to_stop_pct, 1) + "% 위") + ")</dd>" +
      "<dt>1차 목표</dt><dd>$" + fmt(h.target) + "</dd><dt>총점</dt><dd>" + (h.total == null ? "—" : fmt(h.total, 0)) + "</dd></dl></div>" +
      "<h2>매도 규칙 7개</h2>" + rulesHtml7(h) +
      (h.hits && h.hits.length ? '<div class="card"><b>걸린 이유</b><ul class="plain">' + h.hits.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul></div>" : "") +
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

  /* ---------- 3단계: 추세 합류 · 매도 규칙 7개 · 모의투자 · 성적 ---------- */
  const PAPER_START = 1000;
  function trendHtml(list) {
    if (!list || !list.length) return "";
    const n = list.filter(x => x[1]).length;
    return '<h2>추세 합류 ' + n + '/5 <span class="small">(참고용 · 점수에 안 섞어요)</span></h2><div class="card"><ul class="checks">' +
      list.map(x => '<li class="' + (x[1] ? "ok" : "no") + '">' + (x[1] ? "✓" : "–") + " " + esc(x[0]) + "</li>").join("") + "</ul></div>";
  }
  const RULES7 = [["stop", "손절선"], ["target", "1차 목표 (분할익절)"], ["trail", "이익 지키기 (추적 손절)"], ["stale", "제자리 (오래 안 오름)"],
    ["score", "점수 하락"], ["regime", "시장 국면 (하락장 전환)"], ["earnings", "실적 발표 전"]];
  function rulesHtml7(h) {
    if (!h.rules) return '<div class="card sub">규칙별 상태는 다음 아침 리포트부터 보여요.</div>';
    const hit = h.rules;
    return '<div class="card"><ul class="checks">' + RULES7.map(r => {
      const on = hit.indexOf(r[0]) >= 0;
      return '<li class="' + (on ? "hit" : "ok") + '">' + (on ? "●" : "✓") + " " + esc(r[1]) + '<span class="small"> · ' + (on ? "걸림" : "괜찮음") + "</span></li>";
    }).join("") + "</ul></div>";
  }
  function paperCash() {
    return (S.paper || []).reduce((c, x) => c - x.qty * x.price + (x.sold_date && x.sold_price ? x.qty * x.sold_price : 0), PAPER_START);
  }
  function suggestQty(p) {
    const pl = p.plan || {}, cash = paperCash();
    if (!p.price || p.price > cash) return 0;
    const risk = pl.stop && p.price > pl.stop ? p.price - pl.stop : p.price * 0.07;
    const byRisk = Math.floor(PAPER_START * 0.03 / risk);
    const byCap = Math.floor(cash * 0.6 / p.price);
    return Math.max(1, Math.min(byRisk, byCap));
  }
  function paperAddHtml(p) {
    const cash = paperCash(), q = suggestQty(p);
    const held = (S.paper || []).some(x => x.t === p.t && !x.sold_date);
    return '<h2>모의투자에 담기</h2><div class="card" id="paperAdd"><div class="small">가상 1,000달러 계좌 · 오늘 기준가 $' + fmt(p.price) +
      " (미국 " + esc(S.data.date) + " 종가) · 남은 현금 $" + fmt(cash) + "</div>" +
      (held ? '<div class="msg note">이미 모의 계좌에 담은 종목이에요. 더 담으면 따로 기록돼요.</div>' : "") +
      (q ? '<label for="pq">수량 (추천 ' + q + '주 · 한 번에 잃는 돈이 계좌의 3% 이내)</label><input id="pq" inputmode="numeric" value="' + q + '">' +
        '<div class="small num" id="pqc"></div><button class="btn" id="pqBtn">모의 계좌에 담기</button><div id="pqMsg"></div>'
        : '<div class="small">남은 현금보다 비싸서 담을 수 없어요.</div>') + "</div>";
  }
  function bindPaperAdd(p) {
    const inp = document.getElementById("pq"), btn = document.getElementById("pqBtn");
    if (!inp) return;
    const show = () => { const q = Math.floor(Number(inp.value) || 0); document.getElementById("pqc").textContent = q > 0 ? "금액 $" + fmt(q * p.price) : ""; };
    inp.addEventListener("input", show); show();
    btn.onclick = async () => {
      btn.disabled = true;
      const out = document.getElementById("pqMsg");
      try {
        const pl = p.plan || {};
        const j = await api("paperAdd", { token: S.token, t: p.t, qty: Math.floor(Number(inp.value) || 0), price: p.price, date: S.data.date, stop: pl.stop, target: pl.target });
        if (!j.ok) { out.innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; btn.disabled = false; return; }
        S.paper = j.paper || S.paper; saveCache();
        toast(p.t + " 모의 계좌에 담았어요"); go("#/score");
      } catch (e) { out.innerHTML = '<div class="msg err">' + esc(e.message) + "</div>"; btn.disabled = false; }
    };
  }
  function lastPrice(t) {
    const pr = S.perf && S.perf.prices && S.perf.prices[t];
    const pk = S.data && findPick(t);
    if (pk && S.data.date && (!pr || S.data.date >= pr.date)) return { close: pk.price, date: S.data.date };
    return pr || null;
  }
  function paperTrades() {
    const extra = {};
    ((S.perf && S.perf.paper && S.perf.paper.trades) || []).forEach(x => { extra[x.id] = x; });
    return (S.paper || []).map(x => {
      const e = extra[x.id] || {}, lp = x.sold_date ? null : lastPrice(x.t);
      const now = x.sold_date ? x.sold_price : (lp ? lp.close : null);
      const ret = now ? (now / x.price - 1) * 100 : null;
      return Object.assign({}, x, { now: now, nowDate: lp ? lp.date : x.sold_date, ret: ret, pnl: now ? x.qty * (now - x.price) : null,
        spy: e.spy, excess: e.excess, pred: e.pred || "", below: !x.sold_date && now && x.stop && now < x.stop });
    }).reverse();
  }
  const usd = v => v == null ? "—" : (v > 0 ? "+$" : v < 0 ? "-$" : "$") + fmt(Math.abs(v));
  function moneySummary(trades) {
    const t = trades.filter(x => x.pnl != null);
    const sum = f => t.filter(f).reduce((a, x) => a + x.pnl, 0);
    const best = t.slice().sort((a, b) => b.pnl - a.pnl)[0], worst = t.slice().sort((a, b) => a.pnl - b.pnl)[0];
    return { gain: sum(x => x.pnl > 0), loss: sum(x => x.pnl <= 0), wins: t.filter(x => x.pnl > 0).length, losses: t.filter(x => x.pnl <= 0).length,
      realized: sum(x => !!x.sold_date), unrealized: sum(x => !x.sold_date), best: best, worst: worst };
  }
  function moneyCard(m) {
    const net = m.gain + m.loss, w = Math.abs(m.gain) + Math.abs(m.loss) || 1;
    return '<div class="card"><div class="sub">얼마 벌고 얼마 잃었나</div>' +
      '<div class="pl"><div><div class="small">번 돈 (' + m.wins + '건)</div><div class="big num good-t">' + usd(m.gain) + "</div></div>" +
      '<div><div class="small">잃은 돈 (' + m.losses + '건)</div><div class="big num bad-t">' + usd(m.loss) + "</div></div></div>" +
      '<div class="plbar"><span class="g" style="width:' + (Math.abs(m.gain) / w * 100) + '%"></span><span class="l" style="width:' + (Math.abs(m.loss) / w * 100) + '%"></span></div>' +
      '<dl class="kv num"><dt>합계</dt><dd><b class="' + (net >= 0 ? "good-t" : "bad-t") + '">' + usd(net) + "</b></dd>" +
      "<dt>판 거래 (확정)</dt><dd>" + usd(m.realized) + "</dd><dt>보유 중 (아직 안 판 것)</dt><dd>" + usd(m.unrealized) + "</dd>" +
      (m.best ? "<dt>가장 많이 번 거래</dt><dd>" + esc(m.best.t) + " " + usd(m.best.pnl) + "</dd>" : "") +
      (m.worst && m.worst.pnl < 0 ? "<dt>가장 많이 잃은 거래</dt><dd>" + esc(m.worst.t) + " " + usd(m.worst.pnl) + "</dd>" : "") +
      "</dl><div class=\"small\">수수료·환전 비용은 빼지 않은 가상 숫자예요</div></div>";
  }
  const signTone = v => v == null ? "" : v > 0 ? "good" : v < 0 ? "bad" : "";
  function statRow(label, st, spy) {
    if (!st || !st.n) return "<dt>" + esc(label) + "</dt><dd>아직 없음</dd>";
    return "<dt>" + esc(label) + "</dt><dd>" + st.n + "개 · 평균 " + pct(st.avg) + " · 수익 비율 " + st.win + "%" +
      (spy != null ? " · SPY " + pct(spy) : "") + "</dd>";
  }

  function vetoTag(t) {
    const v = ((S.ai && S.ai.veto) || []).filter(x => x.t === t).slice(-1)[0];
    if (!v) return "";
    return '<br><span class="badge ' + (v.veto ? "bad" : "") + '">AI 거부권(기록만): ' + (v.veto ? "막을 이유 있음" : "통과") + "</span>" +
      (S.ai && S.ai.pm && S.ai.pm[t] ? ' <a class="link" href="#/pick/' + encodeURIComponent(t) + '">사전 부검 →</a>' : "");
  }
  function reportsHtml(reps) {
    if (!reps || !reps.length) return '<div class="card sub">일일 리포트는 다음 아침 리포트부터 여기에 쌓여요.</div>';
    const r0 = reps[0];
    return '<h2>오늘의 일일 리포트</h2><div class="card"><b>' + esc(r0.title) + '</b><div class="small">' + esc(whenText(r0.at)) + '</div><pre class="weekly">' + esc(r0.text) + "</pre></div>" +
      (reps.length > 1 ? '<details class="sig"><summary><b>지난 일일 리포트 ' + (reps.length - 1) + "개</b></summary>" +
        reps.slice(1).map(r => '<div class="card"><b>' + esc(r.title) + '</b><div class="small">' + esc(r.date) + '</div><pre class="weekly">' + esc(r.text) + "</pre></div>").join("") + "</details>" : "");
  }
  function kisHtml(k) {
    let h = '<h2>한국투자증권 모의투자 계좌 <span class="small">(같은 주문을 실제 모의계좌에)</span></h2>';
    if (!k) return h + '<div class="card sub">미국 장중 첫 감시 때부터 연결돼요. KIS 비밀 값과 KIS_MODE=paper가 필요해요.</div>';
    if (!k.on) return h + '<div class="card sub">꺼져 있어요: ' + esc(k.why || "") + "</div>";
    const today = (k.orders || []).slice().reverse().slice(0, 8);
    return h + '<div class="card">' + (k.err ? '<div class="msg err">' + esc(k.err) + "</div>" : "") +
      '<div class="small">' + esc(whenText(k.at)) + " 기준 · 보유 " + (k.holdings || []).length + "종목" + (k.summary && k.summary.pnl != null ? " · 평가손익 $" + fmt(k.summary.pnl) : "") + "</div>" +
      ((k.holdings || []).length ? '<ul class="plain">' + k.holdings.map(x => "<li>" + esc(x.t) + " " + x.qty + "주 @$" + fmt(x.avg) + " → $" + fmt(x.now) + "</li>").join("") + "</ul>" : "") +
      (today.length ? '<b>최근 주문</b><ul class="plain small">' + today.map(o => "<li>" + esc(o.date) + " " + esc(o.side) + " " + esc(o.t) + " " + o.qty + "주 @" + fmt(o.price) + " · " + esc(o.status) + "</li>").join("") + "</ul>" : '<div class="small">아직 주문 없음</div>') +
      "</div>";
  }
  function refSimHtml(r) {
    if (!r) return "";
    return '<h2>참고용 $' + fmt(r.budget, 0) + ' 모의 <span class="small">(같은 규칙, 판단에는 안 써요)</span></h2><div class="card"><dl class="kv num">' +
      "<dt>평가금액</dt><dd>$" + fmt(r.equity) + " (" + pct(r.ret) + ")</dd><dt>번 돈 · 잃은 돈</dt><dd>" + usd(r.gain) + " · " + usd(r.loss) + "</dd>" +
      "<dt>거래</dt><dd>" + (r.wins + r.losses) + "번 · 보유 " + (r.positions || []).length + "종목</dd><dt>최대 낙폭</dt><dd>" + fmt(r.mdd, 1) + "%</dd></dl>" +
      '<div class="small">금액에 따라 결과가 얼마나 달라지는지 비교하는 용도예요</div></div>';
  }
  function autoSimHtml(m) {
    if (!m) return '<div class="empty">자동 모의매매는 다음 아침 리포트부터 시작돼요</div>';
    const prog = Math.max(0, Math.min(100, m.day / m.days * 100));
    const net = m.gain + m.loss, w = Math.abs(m.gain) + Math.abs(m.loss) || 1;
    const passN = (m.checks || []).filter(c => c[1]).length;
    return '<div class="card"><div class="row between"><b>3개월 자동 모의매매</b><span class="badge info">모의 · 실제 주문 없음</span></div>' +
      '<div class="small">' + esc(m.start) + " ~ " + esc(m.end) + " · " + m.day + "/" + m.days + "일째 · 가상 $" + fmt(m.budget, 0) + " · 11장 규칙 그대로</div>" +
      '<div class="plbar" style="margin-top:8px"><span class="g" style="width:' + prog + '%;background:var(--accent)"></span></div>' +
      '<div class="big num">$' + fmt(m.equity) + ' <span class="badge ' + signTone(m.ret) + '">' + pct(m.ret) + "</span></div>" +
      '<div class="small num">현금 $' + fmt(m.cash) + " · 같은 기간 SPY " + pct(m.spy_ret) + " · 최대 낙폭 " + fmt(m.mdd, 1) + "%</div></div>" +
      '<div class="card"><div class="sub">얼마 벌고 얼마 잃었나 (수수료·환전 추정치 뺀 금액)</div>' +
      '<div class="pl"><div><div class="small">번 돈 (' + m.wins + '건)</div><div class="big num good-t">' + usd(m.gain) + "</div></div>" +
      '<div><div class="small">잃은 돈 (' + m.losses + '건)</div><div class="big num bad-t">' + usd(m.loss) + "</div></div></div>" +
      '<div class="plbar"><span class="g" style="width:' + (Math.abs(m.gain) / w * 100) + '%"></span><span class="l" style="width:' + (Math.abs(m.loss) / w * 100) + '%"></span></div>' +
      '<dl class="kv num"><dt>판 거래 합계</dt><dd><b class="' + (net >= 0 ? "good-t" : "bad-t") + '">' + usd(net) + "</b></dd></dl></div>" +
      reportsHtml(m.reports) +
      "<h2>지난 거래일에 한 일</h2>" + '<div class="card small">' + ((m.today || []).length ? m.today.map(esc).join("<br>") : "체결·매도 없음") + "</div>" +
      "<h2>지금 가진 종목</h2>" + ((m.positions || []).length ? '<div class="list">' + m.positions.map(p =>
        '<div class="item" style="cursor:default"><span class="tk">' + esc(p.t) + '</span><div class="grow small num">' + esc(p.date) + " · " + p.qty + "주 @$" + fmt(p.entry) +
        "<br>손절 " + fmt(p.stop) + " · 목표 " + fmt(p.target) + (p.half ? " · 절반 익절함" : "") + "</div></div>").join("") + "</div>" : '<div class="empty">없음</div>') +
      "<h2>다음 거래일 주문 계획</h2>" + ((m.pending || []).length ? '<div class="list">' + m.pending.map(o =>
        '<div class="item" style="cursor:default"><span class="tk">' + esc(o.t) + '</span><div class="grow small num">' + o.qty + "주 · 지정가 $" + fmt(o.limit) +
        " 이하 · 시작가 $" + fmt(o.skip_above) + " 위면 안 삼<br>" + esc(o.why) + vetoTag(o.t) + "</div></div>").join("") + "</div>"
        : '<div class="empty">없음 (조건에 맞는 후보가 없거나 자리가 찼어요)</div>') +
      "<h2>실전 기준 " + passN + "/" + (m.checks || []).length + " <span class=\"small\">(3개월 끝에 최종 판단 → 알림)</span></h2>" +
      '<div class="card"><ul class="checks">' + (m.checks || []).map(c => '<li class="' + (c[1] ? "ok" : "no") + '">' + (c[1] ? "✓ " : "– ") + esc(c[0]) +
        '<div class="small">' + esc(c[2]) + "</div></li>").join("") + "</ul></div>" +
      "<h2>판 거래</h2>" + ((m.closed || []).length ? '<div class="list">' + m.closed.map(c =>
        '<div class="item" style="cursor:default"><span class="tk">' + esc(c.t) + '</span><div class="grow small num">' + esc(c.date) + " → " + esc(c.exit_date) + " · " + esc(c.why) +
        '</div><b class="num ' + (c.pnl >= 0 ? "good-t" : "bad-t") + '">' + usd(c.pnl) + "</b></div>").join("") + "</div>" : '<div class="empty">아직 없음</div>') +
      "<h2>기록</h2>" + '<div class="card small">' + (m.log || []).map(esc).join("<br>") + "</div>";
  }

  function viewScore() {
    if (!S.token) return;
    const pf = (S.perf && S.perf.paper) || {}, sg = (S.perf && S.perf.signals) || {};
    const trades = paperTrades(), open = trades.filter(x => !x.sold_date), closed = trades.filter(x => x.sold_date);
    const cash = paperCash();
    const eq = cash + open.reduce((s, x) => s + x.qty * (x.now || x.price), 0);
    const ret = (eq / PAPER_START - 1) * 100;
    const seg = S.scoreSeg || "auto";
    const segBtn = (k, l) => '<button data-s="' + k + '"' + (seg === k ? ' class="on"' : "") + ">" + l + "</button>";
    let body = "";
    if (seg === "auto") {
      body = autoSimHtml(S.perf && S.perf.sim) + kisHtml(S.kis) + refSimHtml(S.perf && S.perf.sim_ref);
    } else if (seg === "acct") {
      body = '<div class="card"><div class="sub">모의 계좌 평가금액</div><div class="big num">$' + fmt(eq) + ' <span class="badge ' + signTone(ret) + '">' + pct(ret) + "</span></div>" +
        '<div class="small num">현금 $' + fmt(cash) + " · 보유 " + open.length + "종목 · 시작 $1,000" +
        (pf.excess_pct != null ? " · 같은 돈을 SPY에 넣었을 때보다 " + pct(pf.excess_pct) + "p" : "") + "</div></div>" +
        (trades.length ? moneyCard(moneySummary(trades)) : "") +
        (open.some(x => x.below) ? '<div class="band bad">손절선 아래 종목이 있어요. 규칙대로라면 팔 차례예요.</div>' : "") +
        "<h2>보유 중</h2>" + (open.length ? open.map(x =>
          '<div class="card"><div class="row between"><b>' + esc(x.t) + '</b><span class="badge ' + (x.below ? "bad" : signTone(x.ret)) + '">' + (x.below ? "손절선 아래" : pct(x.ret)) + "</span></div>" +
          '<div class="small num">' + esc(x.date) + " · " + fmt(x.qty, 0) + "주 × $" + fmt(x.price) + " → $" + fmt(x.now) + (x.nowDate ? " (" + esc(x.nowDate) + ")" : "") +
          " · 손절 " + fmt(x.stop) + " · 목표 " + fmt(x.target) + "</div>" +
          '<div class="num ' + (x.pnl >= 0 ? "good-t" : "bad-t") + '"><b>' + usd(x.pnl) + "</b> 평가손익</div>" +
          '<button class="btn ghost sm" data-sell="' + esc(x.id) + '">팔기</button><div id="sell' + esc(x.id) + '"></div></div>').join("")
          : '<div class="empty">아직 담은 종목이 없어요. 매수 후보 → 종목 상세 → "모의투자에 담기"</div>') +
        "<h2>판 거래 · 회고</h2>" + (closed.length ? closed.map(x =>
          '<div class="card"><div class="row between"><b>' + esc(x.t) + '</b><span class="badge ' + signTone(x.ret) + '">' + pct(x.ret) + "</span></div>" +
          '<div class="small num">' + esc(x.date) + " → " + esc(x.sold_date) + " · $" + fmt(x.price) + " → $" + fmt(x.sold_price) + " · " + esc(x.why || "") +
          (x.excess != null ? " · SPY 대비 " + pct(x.excess) + "p" : "") + "</div>" +
          '<div class="num ' + (x.pnl >= 0 ? "good-t" : "bad-t") + '"><b>' + usd(x.pnl) + "</b> " + (x.pnl >= 0 ? "벌었어요" : "잃었어요") + "</div>" +
          '<div class="note-row"><input type="text" maxlength="200" data-note="' + esc(x.id) + '" placeholder="회고 한 줄 (왜 샀고, 무엇을 배웠나)" value="' + esc(x.note || "") + '">' +
          '<button class="chip" data-save="' + esc(x.id) + '">저장</button></div></div>').join("")
          : '<div class="empty">판 거래가 생기면 여기에 회고를 남겨요</div>');
    } else if (seg === "skill") {
      const f = pf.first20 || {}, l = pf.last20 || {}, n = pf.n || trades.length;
      body = '<div class="card"><b>실력일까, 운일까</b><p class="sub">한두 번 번 것은 운일 수 있어요. 거래가 20번 넘게 쌓였을 때 아래 숫자가 SPY보다 꾸준히 나으면 실력 쪽에 가까워요.</p>' +
        '<dl class="kv num"><dt>거래 수</dt><dd>' + n + "번" + (n < 20 ? " (20번 전에는 판단 보류)" : "") + "</dd>" +
        "<dt>예상 적중 (목표가 먼저 닿음)</dt><dd>" + (pf.pred && pf.pred.n ? pf.pred.hit + "/" + pf.pred.n + " (" + pf.pred.rate + "%)" : "아직 없음") + "</dd>" +
        "<dt>평균 이익 ÷ 평균 손실</dt><dd>" + (pf.all && pf.all.pf != null ? fmt(pf.all.pf, 2) + (pf.all.pf >= 1.5 ? " ✓" : "") : "—") + "</dd>" +
        "<dt>거래당 SPY 대비</dt><dd>" + (pf.avg_excess != null ? pct(pf.avg_excess) + "p" : "—") + "</dd></dl></div>" +
        '<h2>처음 20번 vs 최근 20번</h2><div class="card"><table class="tbl num"><tr><th></th><th>처음</th><th>최근</th></tr>' +
        "<tr><td>거래</td><td>" + (f.n || 0) + "</td><td>" + (l.n || 0) + "</td></tr>" +
        "<tr><td>평균 수익</td><td>" + pct(f.avg) + "</td><td>" + pct(l.avg) + "</td></tr>" +
        "<tr><td>SPY 대비</td><td>" + pct(f.excess) + "</td><td>" + pct(l.excess) + "</td></tr>" +
        "<tr><td>수익 비율</td><td>" + (f.win == null ? "—" : f.win + "%") + "</td><td>" + (l.win == null ? "—" : l.win + "%") + "</td></tr></table>" +
        '<div class="small">' + (n < 40 ? "거래가 40번이 되기 전에는 두 묶음이 겹쳐요." : "최근이 처음보다 나빠지지 않는지가 증액 기준 중 하나예요(11장).") + "</div></div>" +
        '<p class="foot">숫자는 매일 아침 리포트 때 다시 계산돼요' + (S.perf && S.perf.at ? " · " + esc(whenText(S.perf.at)) : "") + "</p>";
    } else if (seg === "sig") {
      const hit = sg.hit || {};
      body = '<div class="card"><b>아침 후보를 그대로 샀다면</b><p class="sub">매일 아침 매수 후보를 기록해 두고, 5일·20일 뒤 수익률을 같은 기간 SPY와 비교해요.</p><dl class="kv num">' +
        statRow("5일 뒤", sg.d5, sg.d5 && sg.d5.spy) + statRow("20일 뒤", sg.d20, sg.d20 && sg.d20.spy) +
        "<dt>목표 먼저 / 손절 먼저</dt><dd>" + (hit.n ? hit.target + " / " + hit.stop + " (둘 다 안 닿음 " + hit.none + ")" : "아직 없음") + "</dd></dl>" +
        '<div class="small">기록 ' + (sg.n || 0) + "개" + (sg.since ? " · " + esc(sg.since) + "부터" : "") + "</div></div>" +
        [5, 20].map(n => { const d = sg["d" + n]; return d && d.n && d.usd_gain != null ? '<div class="card"><div class="sub">후보마다 100달러씩 사서 ' + n + "일 뒤 팔았다면</div>" +
          '<div class="pl"><div><div class="small">번 돈</div><div class="big num good-t">' + usd(d.usd_gain) + '</div></div><div><div class="small">잃은 돈</div><div class="big num bad-t">' + usd(d.usd_loss) + "</div></div></div>" +
          '<dl class="kv num"><dt>합계 (' + d.n + "번)</dt><dd><b class=\"" + (d.usd_net >= 0 ? "good-t" : "bad-t") + "\">" + usd(d.usd_net) + "</b></dd><dt>같은 돈으로 SPY</dt><dd>" + usd(d.spy * d.n) + "</dd></dl></div>" : ""; }).join("") +
        Object.keys(sg.groups || {}).map(k => (sg.groups[k] || []).length ? "<h2>" + esc(k) + "별 (5일 뒤)</h2><div class=\"card\"><dl class=\"kv num\">" +
          sg.groups[k].map(g => "<dt>" + esc(g.name) + "</dt><dd>" + g.n + "개 · " + pct(g.avg) + " · " + g.win + "%</dd>").join("") + "</dl></div>" : "").join("") +
        "<h2>최근 신호</h2><div class=\"list\">" + ((sg.recent || []).length ? sg.recent.map(r =>
          '<div class="item" style="cursor:default"><span class="tk">' + esc(r.t) + '</span><div class="grow small">' + esc(r.date) + " · " + esc(r.band || "") +
          "<br>5일 " + (r.r5 == null ? "—" : pct(r.r5)) + " · 20일 " + (r.r20 == null ? "—" : pct(r.r20)) + '</div><span class="badge ' +
          (r.result === "목표 먼저" ? "good" : r.result === "손절 먼저" ? "bad" : "") + '">' + esc(r.result || "진행 중") + "</span></div>").join("")
          : '<div class="empty">아직 기록이 없어요</div>') + "</div>";
    } else {
      const w = S.weekly;
      body = w && w.lines ? '<div class="card"><div class="small">' + esc(whenText(w.at)) + '</div><pre class="weekly">' + esc(w.lines.join("\n")) + "</pre></div>"
        : '<div class="empty">주간 리포트는 일요일에 만들어져요</div>';
    }
    appShell("score", '<div class="head"><div><h1>성적 · 모의투자</h1><div class="small">가상 1,000달러 · 실제 주문 없음</div></div></div>' + statusLine() +
      '<div class="segs">' + segBtn("auto", "자동 모의") + segBtn("acct", "내 계좌") + segBtn("skill", "실력·운") + segBtn("sig", "신호") + segBtn("week", "주간") + "</div>" +
      body + '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    $app.querySelectorAll(".segs button").forEach(b => b.addEventListener("click", () => { S.scoreSeg = b.dataset.s; viewScore(); }));
    $app.querySelectorAll("[data-sell]").forEach(b => b.addEventListener("click", () => {
      const x = open.find(o => o.id === b.dataset.sell), box = document.getElementById("sell" + x.id);
      box.innerHTML = '<label>판 가격 (최근 종가 기준, 바꿀 수 있어요)</label><input type="text" inputmode="decimal" id="sp' + x.id + '" value="' + (x.now ? x.now.toFixed(2) : "") + '">' +
        '<label>판 이유</label><select id="sw' + x.id + '"><option>손절선 아래</option><option>1차 목표 도달</option><option>매도 규칙 (점수·추세)</option><option>직접 판단</option></select>' +
        '<button class="btn" id="sb' + x.id + '">팔기 기록</button><div id="sm' + x.id + '"></div>';
      if (x.below) document.getElementById("sw" + x.id).value = "손절선 아래";
      document.getElementById("sb" + x.id).onclick = async ev => {
        ev.target.disabled = true;
        const price = Number(document.getElementById("sp" + x.id).value);
        const day = (x.nowDate && /^\d{4}-\d{2}-\d{2}$/.test(x.nowDate)) ? x.nowDate : new Date().toISOString().slice(0, 10);
        try {
          const j = await api("paperSell", { token: S.token, id: x.id, price: price, date: day, why: document.getElementById("sw" + x.id).value });
          if (!j.ok) { document.getElementById("sm" + x.id).innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; ev.target.disabled = false; return; }
          S.paper = j.paper; saveCache(); toast(x.t + " 팔기를 기록했어요. 회고 한 줄 남겨 주세요"); viewScore();
        } catch (e) { document.getElementById("sm" + x.id).innerHTML = '<div class="msg err">' + esc(e.message) + "</div>"; ev.target.disabled = false; }
      };
    }));
    $app.querySelectorAll("[data-save]").forEach(b => b.addEventListener("click", async () => {
      const id = b.dataset.save, inp = $app.querySelector('[data-note="' + id + '"]');
      b.disabled = true;
      try {
        const j = await api("paperNote", { token: S.token, id: id, note: inp.value });
        if (j.ok) { S.paper = j.paper; saveCache(); toast("회고를 저장했어요"); } else toast(j.error);
      } catch (e) { toast(e.message); }
      b.disabled = false;
    }));
  }

  /* ---------- 4단계: GPT 화면 · 장 전 갭 · 성향 인터뷰 · AI에게 묻기 ---------- */
  const checkNote = c => !c ? "" : (c.ok || !(c.issues || []).length) ? '<div class="small">검사관: 숫자 수정 없음</div>'
    : '<div class="small warn-t">검사관: ' + c.issues.length + "건 확인 필요 — " + esc(c.issues.map(i => (i["원래"] || "") + " → " + (i["고친 값"] || "")).join(" · ")) + "</div>";
  const tone3 = v => /통과|좋음|상회/.test(v || "") ? "good" : /탈락|나쁨|하회/.test(v || "") ? "bad" : "warn";
  function aiOff() {
    const a = S.ai;
    if (!a) return "GPT 기능은 다음 아침 리포트부터 채워져요.";
    if (a.off) return "GPT 기능이 꺼져 있어요: " + a.off + ". 매수·매도 규칙은 그대로 돌아가요.";
    return "";
  }
  function b4Html(t) {
    const x = S.ai && S.ai.b4 && S.ai.b4[t];
    if (!x) return '<div class="empty">' + esc(aiOff() || "이 종목의 4관점 점검은 아직 없어요(보유·후보 상위만, 7일마다).") + "</div>";
    return '<div class="card"><div class="row between"><b>종합</b><span class="badge ' + tone3(x["종합"]) + '">' + esc(x["종합"] || "") + "</span></div>" +
      (x["한 줄"] ? '<div class="sub">' + esc(x["한 줄"]) + "</div>" : "") + "</div>" +
      (x["관점"] || []).map(v => '<div class="card"><div class="row between"><b>' + esc(v["이름"]) + '</b><span class="badge ' + tone3(v["판정"]) + '">' + esc(v["판정"]) + "</span></div>" +
        '<ul class="plain">' + (v["근거"] || []).map(g => "<li>" + esc(g) + "</li>").join("") + "</ul></div>").join("") +
      '<div class="small">' + esc(x.date || "") + " · GPT 작성 · 숫자는 야후 재무 자료 기준</div>" + checkNote(x["_검사"]);
  }
  function repHtml(t) {
    const x = S.ai && S.ai.rep && S.ai.rep[t];
    if (!x) return '<div class="empty">' + esc(aiOff() || "이 종목의 쉬운 리포트는 아직 없어요(보유·후보 상위만, 7일마다).") + "</div>";
    return '<div class="card"><b>7줄 요약</b><ol class="plain">' + (x["7줄 요약"] || []).map(l => "<li>" + esc(l) + "</li>").join("") + "</ol></div>" +
      '<div class="card"><b>지표 신호</b><dl class="kv">' + (x["신호"] || []).map(g => "<dt>" + esc(g["지표"]) + '</dt><dd><span class="badge ' + tone3(g["좋음/나쁨"]) + '">' +
        esc(g["좋음/나쁨"]) + "</span> " + esc(g["값"]) + '<div class="small">' + esc(g["한 줄"]) + "</div></dd>").join("") + "</dl></div>" +
      (x["10년 주인이라면"] ? '<div class="card"><b>10년 가질 주인이라면</b><p class="sub">' + esc(x["10년 주인이라면"]) + "</p></div>" : "") +
      '<div class="small">' + esc(x.date || "") + " · GPT 작성</div>" + checkNote(x["_검사"]);
  }
  function earnHtml(t) {
    const x = S.ai && S.ai.earn && S.ai.earn[t];
    if (!x) return "";
    const v = x["판정"] || {};
    return '<h2>실적 카드 · ' + esc(x["분기"] || "") + '</h2><div class="card"><div class="row between"><span class="sub">' + esc(x["발표일"] || "") + "</span><span>" +
      '<span class="badge ' + tone3(v["실적"]) + '">실적 ' + esc(v["실적"] || "") + '</span> <span class="badge ' + tone3(v["가이던스"]) + '">가이던스 ' + esc(v["가이던스"] || "") + "</span></span></div>" +
      '<table class="tbl num"><tr><th></th><th>실제</th><th>예상</th><th>작년</th></tr>' + (x["표"] || []).map(r => "<tr><td>" + esc(r["항목"]) + "</td><td>" + esc(r["실제"]) +
        "</td><td>" + esc(r["예상(컨센서스)"]) + "</td><td>" + esc(r["작년 같은 분기"]) + "</td></tr>").join("") + "</table>" +
      '<dl class="kv"><dt>가이던스</dt><dd>' + esc(x["가이던스"]) + "</dd><dt>마진</dt><dd>" + esc(x["마진이 변한 이유"]) + "</dd><dt>현금흐름</dt><dd>" + esc(x["현금흐름"]) + "</dd></dl>" +
      (x["한 줄"] ? '<div class="sub">' + esc(x["한 줄"]) + "</div>" : "") + checkNote(x["_검사"]) + "</div>";
  }
  function pmHtml(t) {
    const x = S.ai && S.ai.pm && S.ai.pm[t];
    if (!x) return "";
    const v = x["막을 이유"] || {};
    return '<h2>사기 전에 실패부터 가정 (사전 부검)</h2><div class="card"><div class="small">6개월 뒤 30% 떨어졌다고 가정했을 때 · ' + esc(x.date || "") + "</div>" +
      (x["원인"] || []).map((c, i) => '<div style="margin-top:8px"><b>' + (i + 1) + ". " + esc(c["시나리오"]) + '</b> <span class="badge ' + (c["가능성"] === "상" ? "bad" : "warn") + '">' + esc(c["가능성"]) +
        '</span><div class="small">먼저 보일 신호: ' + esc(c["가장 먼저 보일 신호"]) + " · 지금 " + esc(c["지금 값"]) + " · 다음 확인 " + esc(c["다음 확인일"]) + "</div></div>").join("") +
      '<dl class="kv" style="margin-top:8px"><dt>이미 반영된 기대</dt><dd>' + esc(x["이미 반영된 기대"]) + "</dd><dt>큰 하락 이력</dt><dd>" + esc(x["큰 하락 이력"]) + "</dd></dl>" +
      '<b>맞으려면 필요한 조건</b><ul class="plain">' + (x["맞으려면 필요한 조건"] || []).map(c => "<li>" + esc(c) + "</li>").join("") + "</ul>" +
      '<div class="msg ' + (v["있음"] ? "err" : "note") + '">AI 거부권(기록만): ' + (v["있음"] ? "막을 이유 있음 — " + esc(v["이유"]) : "막을 이유 없음") + "</div>" + checkNote(x["_검사"]) + "</div>";
  }
  function briefCard() {
    const b = S.ai && S.ai.brief;
    if (!b || (!(b.items || []).length && !b.note)) return "";
    const imp = { "상": 0, "중": 1, "하": 2 };
    const items = (b.items || []).slice().sort((x, y) => (imp[x["중요도"]] ?? 3) - (imp[y["중요도"]] ?? 3));
    return '<h2>밤사이 브리핑 <span class="small">' + esc(b.date || "") + "</span></h2>" +
      (items.length ? items.map(x => '<div class="card"><div class="row between"><b>' + esc(x["종목"]) + '</b><span class="badge ' + (x["중요도"] === "상" ? "bad" : x["중요도"] === "중" ? "warn" : "") + '">' +
        esc(x["중요도"]) + "</span></div><div>" + esc(x["무슨 일"]) + '</div><div class="small">' + esc(x["닿는 곳"]) + " · " + esc(x["이유"]) + "</div>" +
        (x["링크"] ? '<a class="small link" href="' + esc(x["링크"]) + '" target="_blank" rel="noopener">출처 보기 →</a>' : "") + "</div>").join("")
        : '<div class="card sub">' + esc(b.note || "특이사항 없음") + "</div>");
  }

  function viewGap() {
    const g = S.gap;
    appShell("picks", '<button class="back" onclick="history.back()">← 뒤로</button><h1>장 전 갭</h1>' + statusLine() +
      (g ? '<div class="small">' + esc(whenText(g.at)) + " · " + esc(g.note || "") + "</div>" +
        '<div class="list">' + ((g.items || []).length ? g.items.map(x => '<div class="item"' + (x.pick ? ' onclick="location.hash=\'#/pick/' + encodeURIComponent(x.t) + '\'"' : ' style="cursor:default"') + '>' +
          '<span class="tk">' + esc(x.t) + '</span><div class="grow small">' + (x.held ? "보유 · " : "") + (x.pick ? "후보 · " : "") + "장 전 $" + fmt(x.pre) + " (전일 $" + fmt(x.prev) + ")" +
          (x.vol ? " · 거래량 " + fmt(x.vol, 0) : "") + (x.news ? "<br>" + esc(x.news) : "") + '</div><span class="badge ' + (x.cond ? (x.gap > 0 ? "warn" : "bad") : "") + '">' + pct(x.gap) + "</span></div>").join("")
          : '<div class="empty">오늘은 장 전 가격이 잡힌 종목이 없어요</div>') + "</div>" +
        '<p class="foot">갭 5% 이상·주가 3달러 이상·장 전 거래량 5만 주 이상이면 색으로 표시해요. 추격 금지선 위에서 시작하면 모의매매는 사지 않아요.</p>'
        : '<div class="empty">장 전 점검(미국 장 시작 1시간 전)이 한 번 돌면 여기에 나와요</div>'));
  }

  const PROFILE_Q = [
    ["투자 목적", ["배당·현금흐름", "장기 자산 늘리기", "몇 달 안의 수익"]],
    ["투자 기간", ["1년 미만", "1~3년", "3~10년", "10년 이상"]],
    ["보유 종목이 한 달에 20% 떨어지면", ["바로 판다", "규칙(손절선)대로 한다", "더 산다"]],
    ["한 달에 견딜 수 있는 손실", ["3%", "5%", "10%", "20% 이상"]],
    ["좋아하는 종목", ["배당주", "대형 우량주", "성장주", "저가·소형주"]],
    ["앱을 보는 횟수", ["아침에 한 번", "하루 몇 번", "주 1~2번"]],
    ["받고 싶은 알림", ["중요한 것만", "웬만한 것 다"]],
    ["더 알고 싶은 것", ["재무제표 읽기", "차트·추세", "시장 흐름", "기업 분석"]],
  ];
  function viewProfile() {
    const p = S.profile || {};
    appShell("settings", '<button class="back" onclick="history.back()">← 뒤로</button><h1>투자 성향 인터뷰</h1>' +
      '<div class="small">8문항 · 답은 \'AI에게 묻기\' 답변의 기준으로만 쓰고, 매수·매도 규칙은 바꾸지 않아요.</div><form id="pf">' +
      PROFILE_Q.map((q, i) => '<h2>' + (i + 1) + ". " + esc(q[0]) + '</h2><div class="chips wrap">' + q[1].map(o =>
        '<label class="chip' + (p[q[0]] === o ? " on" : "") + '"><input type="radio" name="q' + i + '" value="' + esc(o) + '"' + (p[q[0]] === o ? " checked" : "") + ' hidden>' + esc(o) + "</label>").join("") + "</div>").join("") +
      '<button class="btn" type="submit">저장</button><div class="out"></div></form>');
    $app.querySelectorAll(".chips.wrap").forEach(box => box.addEventListener("change", () => {
      box.querySelectorAll(".chip").forEach(c => c.classList.toggle("on", c.querySelector("input").checked));
    }));
    bindForm("pf", async (f, msg) => {
      const answers = {};
      PROFILE_Q.forEach((q, i) => { const v = f.querySelector('input[name="q' + i + '"]:checked'); if (v) answers[q[0]] = v.value; });
      const j = await api("saveProfile", { token: S.token, answers: answers });
      if (!j.ok) { msg.innerHTML = '<div class="msg err">' + esc(j.error) + "</div>"; return; }
      S.profile = j.profile; saveCache(); toast("성향을 저장했어요"); go("#/settings");
    });
  }

  function viewAsk() {
    S.ask = S.ask || { mode: "quick", hist: [] };
    const A = S.ask, u = S.aiUsage || {};
    const modes = [["quick", "급할 때"], ["big", "큰 결정"], ["fact", "붙인 글 사실 확인"]];
    const ansHtml = a => {
      if (!a) return "";
      if (a.err) return '<div class="msg err">' + esc(a.err) + "</div>";
      const x = a.answer || {};
      if (x["질문"]) return '<div class="card"><b>먼저 물어볼게요</b><div>' + esc(x["질문"]) + '</div><div class="small">' + esc(x["왜 묻나"] || "") + "</div></div>";
      let h = '<div class="card">';
      if ((x["가정"] || []).length) h += '<div class="small">가정: ' + esc(x["가정"].join(" · ")) + "</div>";
      if (x["결론"]) h += "<b>" + esc(x["결론"]) + "</b>";
      if ((x["근거"] || []).length) h += '<ul class="plain">' + x["근거"].map(g => "<li>" + esc(g["내용"] || g) + (g["출처"] ? ' <span class="small">(' + esc(g["출처"]) + ")</span>" : "") + "</li>").join("") + "</ul>";
      if ((x["주장"] || []).length) h += '<table class="tbl"><tr><th>주장</th><th>판정</th></tr>' + x["주장"].map(c => "<tr><td style=\"text-align:left\">" + esc(c["주장"]) +
        '<div class="small">' + esc(c["근거"] || "") + (c["다른 점"] ? " · " + esc(c["다른 점"]) : "") + '</div></td><td><span class="badge ' + tone3(c["판정"] === "맞음" ? "좋음" : c["판정"] === "틀림" ? "나쁨" : "") + '">' + esc(c["판정"]) + "</span></td></tr>").join("") + "</table>";
      if ((x["빠진 반대 근거"] || []).length) h += '<div class="small">빠진 반대 근거: ' + esc(x["빠진 반대 근거"].join(" · ")) + "</div>";
      if (x["보유 공개"]) h += '<div class="small">글쓴이 보유 공개: ' + esc(x["보유 공개"]) + "</div>";
      if ((x["확인 못 함"] || []).length) h += '<div class="small">확인 못 함: ' + esc(x["확인 못 함"].join(" · ")) + "</div>";
      h += checkNote(a.check ? { issues: a.check, ok: !a.check.length } : null);
      if ((a.sources || []).length) h += '<div class="small">찾은 자료: ' + esc(a.sources.map(s => s["제목"] + " (" + s["날짜"] + ")").join(" · ")) + "</div>";
      return h + "</div>";
    };
    appShell("home", '<button class="back" onclick="history.back()">← 뒤로</button><h1>AI에게 묻기</h1>' +
      '<div class="small">내 보유·후보·재무·쌓인 자료(RAG)에서 찾아 출처와 함께 답해요 · 이번 달 GPT $' + fmt(u.total) + " / $" + fmt(u.cap, 0) + "</div>" +
      (u.appKey === false ? '<div class="msg note">이 기능은 로그인 서버(Apps Script)의 스크립트 속성에 OPENAI_API_KEY가 있어야 해요. 설정 탭 안내를 봐 주세요.</div>' : "") +
      '<div class="chips">' + modes.map(m => '<button class="chip' + (A.mode === m[0] ? " on" : "") + '" data-m="' + m[0] + '">' + m[1] + "</button>").join("") + "</div>" +
      '<div class="small" style="margin:6px 0">' + (A.mode === "quick" ? "사소한 질문 없이 바로 답하고, 가정은 맨 위에 적어요." : A.mode === "big" ? "답을 바꾸는 질문만 하나씩, 최대 5개 묻고 답해요." : "리포트·커뮤니티 글을 붙이면 주장마다 맞음·틀림·기준이 다름·확인 못 함으로 가려요.") + "</div>" +
      (A.hist || []).map(h => h.role === "me" ? '<div class="bubble me">' + esc(h.text) + "</div>" : ansHtml(h.a)).join("") +
      '<form id="af">' + (A.mode === "fact" ? '<label>붙인 글</label><textarea id="ap" rows="6" maxlength="12000" placeholder="여기에 글을 붙여 넣어요"></textarea>' : "") +
      '<label>' + (A.mode === "fact" ? "더 물을 것 (선택)" : "질문") + '</label><textarea id="aq" rows="3" maxlength="4000" placeholder="예: MO 지금 배당은 안전한가?"></textarea>' +
      '<button class="btn" type="submit">묻기</button><div class="out"></div></form>' +
      ((A.hist || []).length ? '<button class="btn ghost" id="aclear">새로 묻기</button>' : "") +
      '<p class="foot">AI 답은 참고용이에요. 숫자는 검사관이 한 번 더 확인해요. ' + esc(DISCLAIMER) + "</p>");
    $app.querySelectorAll("[data-m]").forEach(b => b.addEventListener("click", () => { A.mode = b.dataset.m; A.hist = []; viewAsk(); }));
    const cl = document.getElementById("aclear"); if (cl) cl.onclick = () => { A.hist = []; viewAsk(); };
    bindForm("af", async (f, msg) => {
      const q = f.querySelector("#aq").value.trim(), pasted = (f.querySelector("#ap") || {}).value || "";
      if (!q && !pasted) { msg.innerHTML = '<div class="msg err">질문을 적어 주세요.</div>'; return; }
      msg.innerHTML = '<div class="small">찾아보고 검사하는 중… (20~40초)</div>';
      const history = (A.hist || []).map(h => ({ role: h.role === "me" ? "me" : "ai", text: h.role === "me" ? h.text : JSON.stringify((h.a || {}).answer || {}) }));
      const j = await api("askAI", { token: S.token, mode: A.mode, q: q, pasted: pasted, history: history });
      A.hist.push({ role: "me", text: q || "(붙인 글 사실 확인)" });
      A.hist.push({ role: "ai", a: j.ok ? j : { err: j.error } });
      if (j.usage) S.aiUsage = Object.assign({}, S.aiUsage || {}, j.usage);
      viewAsk();
    });
  }

  function aiSettingsHtml() {
    const u = S.aiUsage || {}, st = (S.ai && S.ai.status) || {};
    const w = u.cap ? Math.min(100, (u.total || 0) / u.cap * 100) : 0;
    return '<h2>GPT 사용량 (' + esc(u.month || "") + ")</h2><div class=\"card\"><div class=\"row between\"><b class=\"num\">$" + fmt(u.total) + " / $" + fmt(u.cap, 0) + "</b>" +
      '<span class="badge ' + (S.ai && S.ai.off ? "warn" : "good") + '">' + (S.ai && S.ai.off ? "꺼짐" : "켜짐") + "</span></div>" +
      '<div class="plbar"><span class="g" style="width:' + w + '%;background:' + (w >= 80 ? "var(--bad)" : "var(--accent)") + '"></span></div>' +
      '<dl class="kv num"><dt>아침 분석(브리핑·리포트 등)</dt><dd>$' + fmt(u.program) + "</dd><dt>앱 질문</dt><dd>$" + fmt(u.app) + "</dd>" +
      (S.ai && S.ai.off ? "<dt>꺼진 이유</dt><dd>" + esc(S.ai.off) + "</dd>" : "") + "</dl>" +
      '<div class="small">80%·100%·크레딧 소진 때 푸시로 알려요. 한도는 구글 시트 \'설정\' 탭 \'AI 월 한도(달러)\'. 한도에 닿으면 GPT 없이 규칙만으로 돌아가요.</div>' +
      (u.appKey === false ? '<div class="msg note">앱 \'AI에게 묻기\'를 쓰려면 Apps Script → 프로젝트 설정 → 스크립트 속성에 OPENAI_API_KEY를 직접 넣어 주세요.</div>' : "") + "</div>" +
      '<a class="btn ghost" href="#/ask">AI에게 묻기</a><a class="btn ghost" href="#/profile">투자 성향 인터뷰' + (S.profile && Object.keys(S.profile).length ? " (다시 하기)" : "") + "</a>";
  }

  function viewSettings() {
    appShell("settings", '<div class="head"><h1>설정</h1></div>' +
      '<div class="card"><div class="row between"><span>앱 버전</span><span class="sub">' + esc(CFG.VERSION || "") + '</span></div>' +
      '<div class="row between"><span>이 기기</span><span class="sub">' + esc(deviceLabel()) + "</span></div></div>" +
      '<h2>알림</h2><div id="pushBox"><div class="small">확인 중…</div></div>' +
      aiSettingsHtml() +
      '<h2>계정</h2><a class="btn ghost" href="#/password">비밀번호 바꾸기</a>' +
      '<button class="btn ghost" id="hist">최근 로그인 기록</button><div id="histOut"></div>' +
      '<button class="btn ghost" id="out">로그아웃</button><button class="btn danger" id="outAll">모든 기기 로그아웃</button>' +
      '<h2>표시 설정</h2><div class="card sub">보여줄 개수, ETF 개수, 최대 손실 같은 기준은 구글 시트 \'설정\' 탭에서 바꿔요. 다음 리포트부터 적용돼요.</div>' +
      '<h2>설치</h2><div class="card sub">아이폰: 사파리 공유 버튼 → "홈 화면에 추가". 홈 화면 아이콘으로 열면 주소창 없이 앱처럼 열려요.</div>' +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    renderPush();
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
      case "gap": return viewGap();
      case "ask": return viewAsk();
      case "profile": return viewProfile();
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
