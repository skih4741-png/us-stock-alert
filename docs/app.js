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
    data: null, alerts: [], perf: null, weekly: null, paper: [], ai: null, gap: null, profile: null, aiUsage: null, watch: null, watchlist: [], cal: null, palerts: {}, loading: false, error: "", filter: store.get("filter") || "all", lastSeenAlert: store.get("seenAlert") || "",
  };
  try { const c = JSON.parse(store.get("cache") || "null"); if (c) { S.data = c.daily; S.alerts = c.alerts || []; S.perf = c.perf || null; S.weekly = c.weekly || null; S.paper = c.paper || []; S.ai = c.ai || null; S.gap = c.gap || null; S.profile = c.profile || null; S.aiUsage = c.aiUsage || null; S.kis = c.kis || null; S.watch = c.watch || null; S.watchlist = c.watchlist || []; S.cal = c.cal || null; S.palerts = c.palerts || {}; } } catch (e) {}

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
  // GPT가 문장 대신 {자료, 날짜, 수치} 같은 묶음을 주면 "[object Object]" 대신 읽을 수 있는 글로 바꿔요
  const tx = v => {
    if (v == null) return "";
    if (Array.isArray(v)) return v.map(tx).filter(Boolean).join(" · ");
    if (typeof v === "object") {
      const main = v["수치"] ?? v["내용"] ?? v["값"] ?? v["사실"] ?? v["text"] ?? v["설명"];
      const src = [v["자료"] || v["출처"], v["날짜"]].filter(x => x && typeof x !== "object").join(", ");
      const body = main != null ? tx(main) : Object.entries(v).filter(([k, x]) => x !== "" && typeof x !== "boolean" && !/^_/.test(k)).map(([k, x]) => k + ": " + tx(x)).join(" · ");
      return body + (main != null && src ? " (" + src + ")" : "");
    }
    return String(v);
  };
  const esc = s => tx(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
  // 엠프티 스테이트: 제목 + 설명 + 다음 행동 (IBM Carbon 기준 · 막다른 화면 금지)
  const emp = (icon, title, body, href, label) => '<div class="empty"><div class="eicon">' + icon + '</div><b>' + esc(title) + "</b>" +
    (body ? '<div class="small">' + esc(body) + "</div>" : "") + (href ? '<a class="chip" href="' + href + '">' + esc(label || "보러 가기") + " →</a>" : "") + "</div>";
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
        S.data = j.daily; S.alerts = j.alerts || []; S.perf = j.perf || null; S.weekly = j.weekly || null; S.paper = j.paper || []; S.ai = j.ai || null; S.gap = j.gap || null; S.profile = j.profile || null; S.aiUsage = j.aiUsage || null; S.kis = j.kis || null; S.watch = j.watch || null; S.watchlist = j.watchlist || []; S.cal = j.cal || null; S.palerts = j.palerts || {};
        saveCache();
      } else if (!j.auth) S.error = j.error || "불러오지 못했어요";
    } catch (e) {
      S.error = navigator.onLine ? e.message : "인터넷이 없어요. 마지막으로 받은 내용을 보여드려요.";
    }
    S.loading = false;
    render();
  }

  function saveCache() {
    store.set("cache", JSON.stringify({ daily: S.data, alerts: S.alerts, perf: S.perf, weekly: S.weekly, paper: S.paper, ai: S.ai, gap: S.gap, profile: S.profile, aiUsage: S.aiUsage, kis: S.kis, watch: S.watch, watchlist: S.watchlist, cal: S.cal, palerts: S.palerts, at: Date.now() }));
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
      const label = btn.innerHTML;
      btn.disabled = true; btn.classList.add("loading"); btn.innerHTML = '<span class="spin"></span> 처리 중…'; msg.innerHTML = "";
      try { await handler(f, msg); } catch (e) { msg.innerHTML = '<div class="msg err">' + esc(e.message) + "</div>"; }
      if (btn.isConnected) { btn.disabled = false; btn.classList.remove("loading"); btn.innerHTML = label; }
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
    const sigRow = sg => '<details class="sig"><summary><span class="sdot" style="background:' + (toneColor[sg.tone] || "var(--line)") + '"></span><span class="grow"><b>' + esc(sg.title) +
      '</b><span class="small">' + esc(sg.text) + '</span></span><span class="small">숫자 ▾</span></summary><dl class="kv num">' +
      Object.entries(sg.nums || {}).map(([k, v]) => "<dt>" + esc(k) + " " + (TERMS[k] ? ti(k) : "") + "</dt><dd>" +
        (v == null ? "—" : esc(typeof v === "number" ? (/%|률|비율|변화/.test(k) && !/배율/.test(k) ? v + "%" : v) : v)) + "</dd>").join("") + "</dl></details>";
    const byKey = {}; (f.signals || []).forEach(sg => { byKey[sg.key] = sg; });
    const used = {};
    [["성장성", ["growth"]], ["수익성", ["profit", "cash"]], ["안정성", ["debt", "shares"]]].forEach(g => {
      const rows = g[1].map(k => byKey[k]).filter(Boolean);
      rows.forEach(sg => { used[sg.key] = 1; });
      if (rows.length) h += "<h2>" + g[0] + '</h2><div class="list">' + rows.map(sigRow).join("") + "</div>";
    });
    const rest = (f.signals || []).filter(sg => !used[sg.key]);
    if (rest.length) h += '<h2>그 밖에</h2><div class="list">' + rest.map(sigRow).join("") + "</div>";
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
    tabBadges(tab);
    [...$tabs.querySelectorAll("a")].forEach(a => a.classList.toggle("on", a.dataset.tab === tab));
    $app.innerHTML = html;
    stickOffsets();
    // 접근성: 새 화면으로 이동했을 때만 제목으로 포커스 (배경 새로고침 땐 그대로 둬요)
    if (appShell._h !== location.hash) {
      appShell._h = location.hash;
      const head = $app.querySelector("h1, .head h1, h2");
      if (head) { head.setAttribute("tabindex", "-1"); try { head.focus({ preventScroll: true }); } catch (e) {} }
    }
  }
  // 위에 고정되는 줄(뒤로·제목) 높이를 재서, 그 아래 탭·필터 줄이 겹치지 않게 붙여요
  function stickOffsets() {
    const top = $app.querySelector(":scope > .back, :scope > .head");
    document.documentElement.style.setProperty("--stickH", (top ? top.offsetHeight : 0) + "px");
  }
  window.addEventListener("resize", () => stickOffsets());
  window.__retry = () => { refresh(); };
  function statusLine() {
    let s = "";
    if (S.loading) s += '<div class="small">새로 불러오는 중…</div>';
    if (S.error) s += '<div class="msg err" role="alert">' + esc(S.error) +
      ' <button class="btn ghost" style="width:auto;margin:6px 0 0;padding:6px 12px" onclick="window.__retry()">다시 시도</button></div>';
    return s;
  }
  function needData(tab) {
    if (S.data) return false;
    appShell(tab, statusLine() + (S.loading || !S.error ? '<div class="skel"></div><div class="skel"></div><div class="skel"></div>'
      : emp("🌅", "아침 리포트를 기다리는 중이에요", "평일 아침 7시쯤 첫 리포트가 오면 여기에 채워져요. 그동안 경제뉴스를 볼 수 있어요.", "#/news", "경제뉴스 보기")));
    return true;
  }
  const allPicks = () => (S.data.bands || []).flatMap(b => b.picks.concat(b.etf_picks || []));
  const findPick = t => allPicks().find(p => p.t === t);
  const findHold = t => (S.data.holdings || []).find(h => h.t === t);

  // 오늘 아침 리포트가 늦으면 알려줘요 (화~토 한국 9시 이후인데 예전 것이면)
  function freshBanner() {
    const d = S.data; if (!d || !d.run_at) return "";
    const now = new Date(), kst = new Date(now.getTime() + (now.getTimezoneOffset() + 540) * 60000);
    const today = kst.toISOString().slice(0, 10), dow = kst.getUTCDay(), hr = kst.getUTCHours();
    if (String(d.run_at).slice(0, 10) >= today || dow === 0 || dow === 1 || hr < 9) return "";
    return '<div class="msg note">오늘 아침 리포트가 아직 안 왔어요. 지금 화면은 ' + esc(whenText(d.run_at)) + " 기준이에요. 깃허브 예약 실행이 몇 시간 밀리는 날이 있어요.</div>";
  }
  // 토스처럼 내 자산을 먼저: 보유 종목 평가금액·손익
  function assetCard() {
    const hs = (S.data.holdings || []).filter(h => h.qty && h.avg && h.price);
    if (!hs.length) return "";
    const val = hs.reduce((a, h) => a + h.qty * h.price, 0), cost = hs.reduce((a, h) => a + h.qty * h.avg, 0), pl = val - cost;
    const up = hs.filter(h => h.price >= h.avg).length;
    return '<a class="card" href="#/holdings" style="display:block;color:var(--ink)"><div class="sub">내 미국주식 (' + hs.length + "종목 · 종가 기준)</div>" +
      '<div class="row between"><span class="big num">$' + fmt(val) + '</span><b class="num ' + (pl >= 0 ? "good-t" : "bad-t") + '">' + usd(pl) + " (" + pct(cost ? pl / cost * 100 : 0) + ")</b></div>" +
      '<div class="small">수익 ' + up + "종목 · 손실 " + (hs.length - up) + "종목 · 보유 탭에서 자세히 →</div></a>";
  }
  // 홈 맨 위: 지금 모의투자가 돌아가고 있다는 걸 한눈에
  function homeSimCard() {
    const m = S.perf && S.perf.sim;
    if (!m) return '<a class="card simlive" href="#/score"><div class="row between"><b><span class="live off"></span>모의투자 준비 중</b><span class="badge info">가상 $1,000</span></div>' +
      '<div class="small">다음 아침 리포트부터 3개월 자동 모의투자가 시작돼요</div></a>';
    const prog = Math.max(0, Math.min(100, m.day / m.days * 100));
    const pos = m.positions || [], pend = m.pending || [], up = m.ret >= 0, gain = m.equity - m.budget;
    const c = m.curve || [];
    let today = "";
    if (c.length >= 2) {
      const d = c[c.length - 1][1] - c[c.length - 2][1], base = c[c.length - 2][1];
      today = "오늘 " + (d >= 0 ? "▲" : "▼") + " " + usd(d) + (base ? " (" + pct(d / base * 100) + ")" : "");
    }
    return '<a class="card simlive" href="#/score"><div class="row between"><span class="sub"><span class="live"></span>모의 평가금액 <span class="small">· 가상 $' + fmt(m.budget, 0) + "</span></span>" +
      '<span class="radial" style="--p:' + prog.toFixed(1) + '" title="' + m.day + "/" + m.days + '일째"><span>' + m.day + "<small>/" + m.days + "일</small></span></span></div>" +
      '<div class="broker-eq num">$' + fmt(m.equity) + "</div>" +
      '<div class="broker-ret num ' + (up ? "good-t" : "bad-t") + '">' + (up ? "▲" : "▼") + " " + usd(gain) + " (" + pct(m.ret) + ")" +
      (today ? ' <span class="small" style="color:var(--sub)">· ' + today + "</span>" : "") + "</div>" +
      '<div class="small num">현금 $' + fmt(m.cash) + " · 주식 $" + fmt(m.equity - m.cash) + " · " + pos.length + "종목 · 같은 기간 SPY " + pct(m.spy_ret) + "</div>" +
      '<div class="small" style="margin-top:6px"><b>보유</b> ' + (pos.length ? pos.map(p => esc(p.t) + " " + p.qty + "주").join(", ") : "없음") +
      " · <b>다음 주문</b> " + (pend.length ? pend.map(o => esc(o.t)).join(", ") : "없음") + " · 자세히 →</div></a>";
  }
  function homePaperCard() {
    if (!(S.paper || []).length) return "";
    const m = moneySummary(paperTrades()), net = m.gain + m.loss;
    return '<a class="card" href="#/score" style="display:block;color:var(--ink)"><div class="row between"><span class="sub">모의 계좌 (가상 $1,000)</span><b class="num ' +
      (net >= 0 ? "good-t" : "bad-t") + '">' + usd(net) + '</b></div><div class="small num">번 돈 ' + usd(m.gain) + " · 잃은 돈 " + usd(m.loss) + " · 성적 보기 →</div></a>";
  }
  /* ---------- 관심종목 (사지 않았지만 지켜볼 종목) ---------- */
  const isWatched = t => (S.watchlist || []).indexOf(String(t).toUpperCase()) >= 0;
  async function watchDo(action, t) {
    try {
      const j = await api(action, { token: S.token, t: String(t).toUpperCase() });
      if (j && j.watchlist) { S.watchlist = j.watchlist; saveCache(); render(); }
      else if (j && j.error) toast(j.error);
      else if (j && j.auth) { clearAll(); go("#/login"); }
    } catch (e) { toast("관심종목을 바꾸지 못했어요"); }
  }
  function priceAlertCard(t) {
    const p = (S.palerts && S.palerts[t]) || {}, set = p.above != null || p.below != null;
    const inp = (cls, ph, v) => '<input type="number" step="any" inputmode="decimal" class="' + cls + '" placeholder="' + ph + '" value="' + (v != null ? v : "") +
      '" style="width:100%;padding:9px;border:1px solid var(--line2);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit">';
    return '<div class="card"><div class="row between"><b>🔔 가격 알림</b>' + (set ? '<span class="badge info">설정됨</span>' : "") + "</div>" +
      '<div class="small" style="margin:4px 0 8px">정한 가격에 닿으면 알림·푸시가 와요 (장중·아침 확인)</div>' +
      '<form class="paform" data-t="' + esc(t) + '"><div class="row" style="gap:8px;align-items:flex-end">' +
      '<label class="small" style="flex:1">위로 ▲ 목표가<br>' + inp("pa-above", "예: 200", p.above) + "</label>" +
      '<label class="small" style="flex:1">아래로 ▼ 지정가<br>' + inp("pa-below", "예: 150", p.below) + "</label></div>" +
      '<div class="row" style="gap:6px;margin-top:8px"><button type="submit" class="btn" style="width:auto;margin:0;padding:9px 16px">저장</button>' +
      (set ? '<button type="button" class="btn ghost pa-clear" style="width:auto;margin:0;padding:9px 16px">해제</button>' : "") + "</div></form></div>";
  }
  async function savePriceAlert(t, above, below) {
    try {
      const j = await api("priceAlertSet", { token: S.token, t: t, above: above, below: below });
      if (j && j.ok) { S.palerts = j.palerts || {}; saveCache(); toast(above || below ? "가격 알림을 저장했어요" : "가격 알림을 해제했어요"); render(); }
      else if (j && j.error) toast(j.error);
      else if (j && j.auth) { clearAll(); go("#/login"); }
    } catch (e) { toast("저장하지 못했어요"); }
  }
  function bindPriceAlert() {
    $app.querySelectorAll(".paform").forEach(f => {
      f.onsubmit = e => { e.preventDefault(); savePriceAlert(f.dataset.t, parseFloat(f.querySelector(".pa-above").value) || 0, parseFloat(f.querySelector(".pa-below").value) || 0); };
      const clr = f.querySelector(".pa-clear");
      if (clr) clr.onclick = () => savePriceAlert(f.dataset.t, 0, 0);
    });
  }
  function detailHash(t) {
    if (((S.data && S.data.holdings) || []).some(h => h.t === t)) return "#/hold/" + encodeURIComponent(t);
    if (allPicks().some(p => p.t === t)) return "#/pick/" + encodeURIComponent(t);
    return "#/stock/" + encodeURIComponent(t);
  }
  function bindWatch() {
    $app.querySelectorAll("[data-wdel]").forEach(b => b.onclick = e => { e.stopPropagation(); watchDo("watchDel", b.dataset.wdel); });
    $app.querySelectorAll("[data-wadd]").forEach(b => b.onclick = e => { e.stopPropagation(); watchDo("watchAdd", b.dataset.wadd); });
    const f = $app.querySelector("#waddForm");
    if (f) f.onsubmit = e => { e.preventDefault(); const i = $app.querySelector("#waddInput"); const t = (i.value || "").trim().toUpperCase(); if (t) { i.value = ""; watchDo("watchAdd", t); } };
  }
  function watchBody() {
    const list = S.watchlist || [], w = (S.watch && S.watch.items) || {};
    const rows = list.map(t => { const q = w[t] || {}, chg = q.chg;
      return '<div class="item" style="cursor:pointer" onclick="location.hash=\'' + detailHash(t) + '\'"><span class="tk">' + esc(t) + "</span>" +
        '<span class="grow small num">' + (q.px != null ? "$" + fmt(q.px) : "시세 준비 중") +
        (chg != null ? ' <span class="' + (chg >= 0 ? "good-t" : "bad-t") + '">' + (chg >= 0 ? "▲" : "▼") + " " + Math.abs(chg) + "%</span>" : "") + "</span>" +
        '<button class="iconbtn" data-wdel="' + esc(t) + '" aria-label="관심에서 빼기" style="min-width:38px;min-height:38px;font-size:15px">✕</button></div>';
    }).join("");
    return '<div class="card">' +
      (list.length ? '<div class="list">' + rows + "</div>" : '<div class="small">지켜볼 종목을 담아보세요. 종목 화면에서 ☆를 누르거나 아래에 코드를 넣어요.</div>') +
      '<form id="waddForm" class="row" style="margin-top:10px;gap:6px"><input id="waddInput" placeholder="예: TSLA" autocapitalize="characters" autocomplete="off" style="flex:1;min-width:0;padding:10px;border:1px solid var(--line2);border-radius:10px;background:var(--bg);color:var(--ink);font:inherit"><button type="submit" class="btn" style="width:auto;margin:0;padding:10px 16px">추가</button></form>' +
      '<div class="small" style="margin-top:6px">시세는 아침·장중 자동 실행 때 갱신돼요 (실시간 아님).</div></div>';
  }
  function watchCard() {
    const n = (S.watchlist || []).length;
    return "<h2>관심종목" + (n ? " " + n : "") + "</h2>" + watchBody();
  }
  function viewWatch() {
    if (!S.token) return;
    const at = S.watch && S.watch.at;
    appShell("watch", '<div class="head"><div><h1>관심종목</h1><div class="small">' + (at ? "시세 " + esc(whenText(at)) + " 기준" : "지켜볼 종목을 모아봐요") + "</div></div></div>" +
      statusLine() + watchBody() +
      '<p class="foot">종목을 누르면 상세(실시간 차트·시세)를 봐요 · ☆로도 담을 수 있어요 · ' + esc(DISCLAIMER) + "</p>");
    bindWatch();
  }
  // 관심 종목(보유·후보 아님) 가벼운 상세 — 실시간 캔들·시세·52주
  function viewStock(t) {
    if (!S.token) return;
    const w = (S.watch && S.watch.items && S.watch.items[t]) || {}, watched = isWatched(t);
    appShell("watch", '<button class="back" onclick="history.back()">← 뒤로</button>' +
      stockHeader(t, "", w.px, '<span class="badge info">관심</span>') +
      '<button class="btn ghost" style="width:auto;margin:8px 0 0;padding:8px 14px" data-' + (watched ? "wdel" : "wadd") + '="' + esc(t) + '">' + (watched ? "★ 관심 중" : "☆ 관심 추가") + "</button>" +
      liveChartBox(t, null) +
      quoteSumCard(t) +
      statsCard(t) +
      priceAlertCard(t) +
      '<p class="foot">관심 종목도 시세·투자지표·실적·배당을 실시간으로 볼 수 있어요. AI 리포트·재무 신호 전체 분석은 보유·후보 상위만 계산해요. · ' + esc(DISCLAIMER) + "</p>");
    bindWatch();
    bindPriceAlert();
    liveStock(t);
    mountQuoteSum(t);
    mountStats(t);
  }

  function idxBar() { return '<div id="idxbar" class="idxbar"><div class="idxchip sub" style="min-width:auto;border:0;padding:8px 2px">지수 불러오는 중…</div></div>'; }
  async function mountIndices() {
    const el = document.getElementById("idxbar"); if (!el) return;
    try {
      const j = await api("indices");
      if (!j || !j.ok || !(j.items || []).length) { el.remove(); return; }
      el.innerHTML = j.items.map(x => '<div class="idxchip"><span class="inm">' + esc(x.name) + '</span><span class="ipx num">' + fmt(x.price) + "</span>" +
        (x.chg == null ? "" : '<span class="num ' + (x.chg >= 0 ? "good-t" : "bad-t") + '">' + (x.chg >= 0 ? "▲" : "▼") + fmt(Math.abs(x.chg), 2) + "%</span>") + "</div>").join("");
    } catch (e) { el.remove(); }
  }
  function rankCard() {
    const ch = (S.ai && S.ai.chart) || {}, uni = {};
    (S.data.holdings || []).forEach(h => uni[h.t] = 1);
    (S.watchlist || []).forEach(t => uni[t] = 1);
    allPicks().forEach(p => uni[p.t] = 1);
    const rows = Object.keys(uni).map(t => ({ t: t, chg: (ch[t] || {}).chg })).filter(x => x.chg != null);
    if (rows.length < 3) return "";
    const held = t => (S.data.holdings || []).some(h => h.t === t);
    const line = x => '<div class="item" onclick="location.hash=\'' + (held(x.t) ? "#/hold/" : "#/pick/") + encodeURIComponent(x.t) + '\'"><span class="tk">' + esc(x.t) +
      '</span><span class="grow"></span><span class="num ' + (x.chg >= 0 ? "good-t" : "bad-t") + '">' + (x.chg >= 0 ? "▲ " : "▼ ") + fmt(Math.abs(x.chg), 2) + "%</span></div>";
    const up = rows.slice().sort((a, b) => b.chg - a.chg).slice(0, 5);
    const dn = rows.slice().sort((a, b) => a.chg - b.chg).slice(0, 5);
    return '<h2>내 종목 급등·급락 (종가 기준)</h2><div class="row" style="gap:10px;align-items:flex-start">' +
      '<div class="card grow" style="margin:0"><div class="sub" style="margin-bottom:4px">급등 Top</div><div class="list">' + up.map(line).join("") + "</div></div>" +
      '<div class="card grow" style="margin:0"><div class="sub" style="margin-bottom:4px">급락 Top</div><div class="list">' + dn.map(line).join("") + "</div></div></div>";
  }
  function dLabel(days) { return days <= 0 ? "D-DAY" : "D-" + days; }
  function calRow(days, t, extra) {
    const soon = days <= 3;
    return '<div class="item" style="cursor:pointer" onclick="location.hash=\'' + detailHash(t) + '\'"><span class="badge ' + (soon ? "warn" : "info") +
      '" style="min-width:48px;text-align:center">' + dLabel(days) + '</span><span class="tk" style="margin-left:8px">' + esc(t) + '</span><span class="grow small" style="text-align:right">' + extra + "</span></div>";
  }
  function divYield(y) { return y == null ? "" : fmt(y < 1 ? y * 100 : y, 2) + "%"; }
  function homeCalCard() {
    const c = S.cal; if (!c) return "";
    const e = (c.earnings || []).slice(0, 3), d = (c.dividends || []).slice(0, 2);
    if (!e.length && !d.length) return "";
    return '<h2>📅 다가오는 실적·배당</h2><div class="card"><div class="list">' +
      e.map(x => calRow(x.days, x.t, "실적 발표 · " + x.date)).join("") +
      d.map(x => calRow(x.days, x.t, "배당락 · " + x.exdate + (x.yield != null ? " · " + divYield(x.yield) : ""))).join("") +
      '</div><a class="link" href="#/cal">전체 캘린더 보기 →</a></div>';
  }
  function viewCal() {
    if (needData("home")) return;
    const c = S.cal || { earnings: [], dividends: [] }, e = c.earnings || [], d = c.dividends || [];
    appShell("home", '<button class="back" onclick="history.back()">← 뒤로</button><h1>📅 실적·배당 캘린더</h1>' +
      '<div class="small" style="margin-bottom:8px">보유·관심 종목의 다가오는 일정 · 누르면 종목 상세</div>' +
      '<h2>실적 발표</h2><div class="card"><div class="list">' +
      (e.length ? e.map(x => calRow(x.days, x.t, "실적 발표 · " + x.date)).join("") : '<div class="small">다가오는 실적 발표가 없어요</div>') + "</div></div>" +
      '<h2>배당락일</h2><div class="card"><div class="list">' +
      (d.length ? d.map(x => calRow(x.days, x.t, "배당락 · " + x.exdate + (x.amount != null ? " · 주당 $" + fmt(x.amount) : "") + (x.yield != null ? " · " + divYield(x.yield) : ""))).join("")
        : '<div class="small">다가오는 배당락일이 없어요</div>') + "</div></div>" +
      '<p class="foot">야후 자료 기준이라 날짜는 바뀔 수 있어요 · 배당은 배당락일 전에 사야 받아요 · ' + esc(DISCLAIMER) + "</p>");
  }
  function viewSearch() {
    if (!S.token) { go("#/login"); return; }
    appShell("home", '<button class="back" onclick="history.back()">← 뒤로</button><h1>🔍 종목 검색</h1>' +
      '<form id="srchForm" class="row" style="gap:6px;margin:8px 0"><input id="srchInput" placeholder="종목명 또는 코드 (예: Apple, NVDA, SCHD)" autocapitalize="characters" autocomplete="off" style="flex:1;min-width:0;padding:11px;border:1px solid var(--line2);border-radius:10px;background:var(--bg);color:var(--ink);font:inherit"><button type="submit" class="btn" style="width:auto;margin:0;padding:11px 16px">검색</button></form>' +
      '<div id="srchResults" class="list"></div>' +
      '<p class="foot">미국 주식·ETF를 찾아 상세(실시간 차트·시세)로 들어가요 · 전체 종목 대상 · ' + esc(DISCLAIMER) + "</p>");
    const el = () => document.getElementById("srchResults");
    async function doSearch(q) {
      el().innerHTML = '<div class="small" style="padding:12px">검색 중…</div>';
      try {
        const j = await api("search", { q: q });
        const rs = (j && j.results) || [];
        el().innerHTML = rs.length ? rs.map(x => '<div class="item" style="cursor:pointer" onclick="location.hash=\'' + detailHash(x.t) + '\'"><span class="tk">' + esc(x.t) +
          '</span><span class="grow small" style="margin-left:8px">' + esc(x.name) + "</span>" + (x.type ? '<span class="badge info">' + esc(x.type) + "</span>" : "") +
          '<span class="small" style="margin-left:6px">' + esc(x.exch) + "</span></div>").join("") : '<div class="empty">검색 결과가 없어요</div>';
      } catch (e) { el().innerHTML = '<div class="empty">검색을 못 했어요. 잠시 후 다시 시도해 주세요.</div>'; }
    }
    const f = $app.querySelector("#srchForm");
    f.onsubmit = e => { e.preventDefault(); const q = ($app.querySelector("#srchInput").value || "").trim(); if (q) doSearch(q); };
    const i = $app.querySelector("#srchInput"); if (i) i.focus();
  }
  function viewHome() {
    if (needData("home")) return;
    const d = S.data, s = d.summary || {};
    const newest = (S.alerts[0] || {}).at || "";
    const hasNew = newest && newest !== S.lastSeenAlert, needN = needsYou().length;
    const hold = (d.holdings || []).slice(0, 4);
    const top = allPicks().filter(p => !p.etf).sort((a, b) => b.total - a.total).slice(0, 3);
    appShell("home",
      '<div class="head"><div><h1>오늘 · ' + esc(d.date_label || "") + '</h1><div class="small">미국 ' + esc(d.date) + " 종가 기준 · " + esc(whenText(d.run_at)) + "</div></div>" +
      '<span><button class="iconbtn" aria-label="알림" onclick="location.hash=\'#/alerts\'">🔔' + (needN ? '<span class="cnt">' + needN + "</span>" : hasNew ? '<span class="dot"></span>' : "") + "</button>" +
      '<button class="iconbtn" aria-label="설정" onclick="location.hash=\'#/settings\'">⚙️</button></span></div>' +
      idxBar() +
      statusLine() + homeRunLine() + homeNeedsCard() + whatsNewCard() + homeCalCard() + homeSimCard() + watchCard() + homeNewsCard() +
      (pushSupported() && isStandalone() && CFG.VAPID_PUBLIC_KEY && Notification.permission === "default"
        ? '<a class="card" href="#/settings" style="display:block;color:var(--ink)"><b>🔔 알림 켜기</b><div class="small">아침 리포트·장중 경고를 푸시로 받아요 →</div></a>' : "") +
      '<div class="band' + (d.market.rest_day ? " bad" : "") + '">' + esc(d.market.label) + (d.market.rest_day ? " · 오늘은 매수 쉬는 날" : " · 매수 기준 " + esc(d.market.threshold) + "점") + "</div>" +
      '<div class="card"><div class="sub">오늘 볼 것</div><div class="big num">매도 ' + (s.sell || 0) + " · 신규 매수 " + (s.new || 0) + "</div>" +
      '<div class="small">매수 후보 ' + (s.buy || 0) + "개 (개별 종목 " + (s.stock || 0) + "개)</div></div>" +
      (d.warnings && d.warnings.length ? d.warnings.map(w => '<div class="msg note">' + esc(w) + "</div>").join("") : "") +
      '<div class="quick"><a class="chip" href="#/search">🔍 종목 검색</a><a class="chip" href="#/ask">💬 AI에게 묻기</a><a class="chip" href="#/gap">장 전 갭' +
        (S.gap && (S.gap.items || []).some(x => x.cond) ? ' <span class="badge warn">' + S.gap.items.filter(x => x.cond).length + "</span>" : "") + "</a>" +
        (!S.profile || !Object.keys(S.profile).length ? '<a class="chip" href="#/profile">성향 인터뷰 하기</a>' : "") + "</div>" +
      freshBanner() + assetCard() + briefCard() + homePaperCard() + rankCard() +
      '<h2>내 보유 한 줄 결론</h2><div class="list">' +
      (hold.length ? hold.map(h => '<div class="item" onclick="location.hash=\'#/hold/' + encodeURIComponent(h.t) + '\'"><span class="tk">' + esc(h.t) +
        '</span><span class="grow small num">' + pct(h.gain_pct) + '</span><span class="badge ' + esc(h.tone) + '">' + esc(h.conclusion) + "</span></div>").join("")
        : emp("📭", "보유 종목을 연결해 시작해요", "구글 시트 '보유 종목' 탭(또는 배당 대시보드 '내 종목')을 읽어요.", "#/picks", "오늘 후보 보기")) + "</div>" +
      ((d.holdings || []).length > 4 ? '<a class="link" href="#/holdings">보유 전체 보기 →</a>' : "") +
      '<h2>매수 후보 상위 (개별 종목)</h2><div class="list">' +
      (top.length ? top.map(p => '<div class="item" onclick="location.hash=\'#/pick/' + encodeURIComponent(p.t) + '\'"><span class="tk">' + esc(p.t) +
        '</span><span class="grow small">' + esc(p.band) + '</span><span class="num"><b>' + fmt(p.total, 0) + "</b>점</span></div>").join("")
        : '<div class="empty">' + (d.market.rest_day ? "매수 쉬는 날이라 후보가 없어요" : "오늘은 조건에 맞는 종목이 없어요") + "</div>") + "</div>" +
      '<a class="link" href="#/picks">전체 후보 보기 →</a><p class="foot">' + esc(DISCLAIMER) + "</p>");
    bindWatch();
    mountIndices();
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
    const q = (S.q || "").trim().toUpperCase();
    const hit = p => !q || p.t.toUpperCase().indexOf(q) >= 0 || String(p.name || "").toUpperCase().indexOf(q) >= 0;
    const bands = (d.bands || []).filter(b => {
      const lo = parseFloat(b.name); return isNaN(lo) || lo < lim;
    }).map(b => q ? Object.assign({}, b, { picks: b.picks.filter(hit), etf_picks: (b.etf_picks || []).filter(hit), dropped: [] }) : b)
      .filter(b => b.picks.length || (b.etf_picks || []).length || (b.dropped || []).length);
    appShell("picks", '<div class="head"><div><h1>매수 후보</h1><div class="small">미국 ' + esc(d.date) + ' 종가 기준 · 실제 체결가는 다를 수 있어요</div></div></div>' + statusLine() +
      '<input type="text" id="pq" class="search" placeholder="종목 코드·이름 찾기 (예: MO)" value="' + esc(S.q || "") + '" autocomplete="off">' +
      '<div class="chips">' + [["all", "전체"], ["10", "10달러 이하"], ["30", "30달러 이하"], ["50", "50달러 이하"], ["100", "100달러 이하"]]
        .map(c => '<button class="chip' + (S.filter === c[0] ? " on" : "") + '" data-f="' + c[0] + '">' + c[1] + "</button>").join("") + "</div>" +
      (d.market.rest_day ? '<div class="msg note">오늘은 매수 쉬는 날이에요. 아래 목록은 참고용이에요.</div>' : "") +
      (bands.length ? bands.map(b =>
        "<h2>" + esc(b.name) + " · 조건 맞음 " + b.count + " · 종목 " + b.picks.length + " · ETF " + (b.etf_picks || []).length + "</h2>" +
        b.picks.map(pickCard).join("") +
        ((b.etf_picks || []).length ? '<div class="small" style="margin-top:10px">ETF·펀드 (따로 순위)</div>' + b.etf_picks.map(pickCard).join("") : "") +
        ((b.dropped || []).length ? '<div class="small">어제에서 빠짐: ' + esc(b.dropped.join(", ")) + "</div>" : "")
      ).join("") : emp("🔎", "이 가격대는 오늘 조건에 맞는 종목이 없어요", "다른 가격대나 '전체'를 눌러 보세요.", "", "")) +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    $app.querySelectorAll(".chip").forEach(b => b.addEventListener("click", () => { S.filter = b.dataset.f; store.set("filter", S.filter); viewPicks(); }));
    const qi = document.getElementById("pq");
    qi.addEventListener("input", () => { clearTimeout(viewPicks._t); viewPicks._t = setTimeout(() => { S.q = qi.value; viewPicks(); const n = document.getElementById("pq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 250); });
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
      stockHeader(p.t, p.name, p.price, '<span class="badge info">총점 ' + fmt(p.total, 0) + "</span>") +
      '<div class="small" style="margin-top:4px">' + esc(p.band) + " · " + (p.streak > 1 ? "연속 " + p.streak + "일" : "신규") + (p.etf ? " · ETF·펀드" : "") + "</div>" +
      tags(p.tags) + quoteSumCard(p.t) + statsCard(p.t) + priceAlertCard(p.t) +
      '<div class="segs"><button class="on" data-s="fin">재무 5초</button><button data-s="pro">찬반 근거</button><button data-s="chart">차트</button><button data-s="v4">4관점</button><button data-s="rep">쉬운 리포트</button></div><div id="seg"></div>' +
      "<h2>점수</h2>" + scoreBars(p.cats) + trendHtml(p.trend5) + earnHtml(p.t) + pmHtml(p.t) +
      '<h2>매수 계획</h2><div class="card"><dl class="kv num">' +
      "<dt>매수 구간</dt><dd>" + fmt(pl.zone_low) + " ~ " + fmt(pl.zone_high) + "</dd>" +
      "<dt>손절</dt><dd>" + fmt(pl.stop) + " (" + fmt(pl.risk_pct, 1) + "%)</dd>" +
      "<dt>1차 목표</dt><dd>" + fmt(pl.target) + " (손익비 " + fmt(pl.rr, 1) + ")</dd>" +
      "<dt>이 위로 시작하면 추격 금지</dt><dd>" + fmt(pl.skip_if_open_above) + "</dd>" +
      "<dt>유효 기한</dt><dd>" + esc(pl.valid_until || "") + "</dd></dl></div>" +
      paperAddHtml(p) +
      '<details class="sig"><summary><b>📓 이 종목 일지 (알림·모의 거래)</b></summary>' + tickerLogHtml(p.t) + "</details>" +
      '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    bindPaperAdd(p);
    const segs = {
      fin: finHtml(finFor(p.t)),
      pro: '<div class="card"><b>좋은 점</b><ul class="plain">' + (p.reasons || []).map(r => "<li>" + esc(r) + "</li>").join("") + "</ul>" +
        (p.desc ? '<div class="sub">' + esc(p.desc) + "</div>" : "") + "</div>" +
        '<div class="card"><b>걱정되는 점</b><ul class="plain">' + (cons.length ? cons.map(r => "<li>" + esc(r) + "</li>").join("") : "<li>오늘 규칙상 특별한 경고는 없어요</li>") + "</ul></div>",
      chart: chartHtml(p.t),
      v4: b4Html(p.t),
      rep: repHtml(p.t),
    };
    const seg = document.getElementById("seg");
    seg.innerHTML = segs.fin;
    $app.querySelectorAll(".segs button").forEach(b => b.addEventListener("click", () => {
      $app.querySelectorAll(".segs button").forEach(x => x.classList.toggle("on", x === b));
      seg.innerHTML = segs[b.dataset.s];
      if (b.dataset.s === "chart") mountChartBox(p.t);
    }));
    bindPriceAlert();
    liveStock(p.t);
    mountQuoteSum(p.t);
    mountStats(p.t);
  }

  function viewHoldings() {
    if (needData("holdings")) return;
    const hs = S.data.holdings || [];
    const flagged = hs.filter(h => h.tone !== "good").length;
    appShell("holdings", '<div class="head"><h1>내 보유 · ' + hs.length + '종목</h1><span class="small">' + esc(whenText(S.data.run_at)) + "</span></div>" + statusLine() +
      (flagged ? '<div class="band bad">매도 규칙을 확인할 종목 ' + flagged + "개</div>" : '<div class="band">모든 종목이 원칙대로예요</div>') + portHtml() + "<h2>종목</h2>" +
      '<div class="list" style="margin-top:8px">' + (hs.length ? hs.map(h =>
        '<div class="item" onclick="location.hash=\'#/hold/' + encodeURIComponent(h.t) + '\'"><div class="grow"><div class="row between"><span class="tk">' + esc(h.t) +
        '</span><span class="badge ' + esc(h.tone) + '">' + esc(h.conclusion) + "</span></div>" +
        '<div class="small num">수익률 ' + pct(h.gain_pct) + " · 손절선까지 " + (h.to_stop_pct == null ? "—" : fmt(h.to_stop_pct, 1) + "%") + "</div></div></div>").join("")
        : emp("📭", "보유 종목을 연결해 시작해요", "구글 시트 '보유 종목' 탭(또는 배당 대시보드 '내 종목')에 적으면 다음 리포트부터 보여요.", "#/picks", "오늘 후보 보기")) + "</div>" +
      '<p class="foot">보유 종목은 구글 시트에서 읽어요 · ' + esc(DISCLAIMER) + "</p>");
  }

  function dayChg(t) {
    const c = S.ai && S.ai.chart && S.ai.chart[t];
    if (!c || c.chg == null) return "";
    return ' <span class="' + (c.chg >= 0 ? "good-t" : "bad-t") + '" style="font-size:15px;font-weight:600">' + (c.chg >= 0 ? "▲" : "▼") + " " + fmt(Math.abs(c.chg), 2) +
      '%</span><span class="sub" style="font-size:12px;font-weight:400"> 전일대비</span>';
  }
  // 종목 상세(보유·후보) 공통 머리글 — 종목·이름·오른쪽 배지 + 종가·전일대비
  function stockHeader(t, name, price, rightHtml) {
    return '<div class="row between"><div class="grow"><h1 style="margin:0">' + esc(t) + '</h1><div class="sub">' + esc(name || "") + "</div></div>" +
      (rightHtml || "") + "</div>" +
      '<div class="big num" data-livehead="' + esc(t) + '" style="margin-top:4px">$' + fmt(price) + dayChg(t) + "</div>";
  }
  function viewHold(t) {
    if (needData("holdings")) return;
    const h = findHold(t);
    if (!h) return appShell("holdings", '<button class="back" onclick="history.back()">← 뒤로</button><div class="empty">보유 목록에 없는 종목이에요</div>');
    // 자세히 분석 — 흩어진 6개 섹션을 탭 하나로 (차트·실적·재무·가치·쉬운 리포트·분기 공시)
    const panes = [["차트", chartHtml(h.t)], ["실적", earnTabHtml(h.t)], ["재무", finHtml(finFor(h.t))],
                   ["가치(버핏)", b4Html(h.t)], ["쉬운 리포트", repHtml(h.t)], ["분기 공시", secqHtml(h.t)]];
    const dtabs = '<div class="segs dtabs">' + panes.map((p, i) => '<button data-dt="' + i + '"' + (i === 0 ? ' class="on"' : "") + ">" + esc(p[0]) + "</button>").join("") + "</div>" +
      '<div class="dpanes">' + panes.map((p, i) => '<div class="dpane"' + (i ? " hidden" : "") + ">" + p[1] + "</div>").join("") + "</div>";
    appShell("holdings", '<button class="back" onclick="history.back()">← 뒤로</button>' +
      // 상단: 종목·현재가·결론 (후보 상세와 공통 머리글)
      stockHeader(h.t, h.name, h.price, '<span class="badge ' + esc(h.tone) + '">' + esc(h.conclusion) + "</span>") +
      '<button class="btn ghost" style="width:auto;margin:8px 0 0;padding:8px 14px" data-' + (isWatched(h.t) ? "wdel" : "wadd") + '="' + esc(h.t) + '">' + (isWatched(h.t) ? "★ 관심 중" : "☆ 관심 추가") + "</button>" +
      quoteSumCard(h.t) +
      statsCard(h.t) +
      priceAlertCard(h.t) +
      // 내 평가손익
      '<div class="card"><div class="sub">내 평가손익</div>' +
      '<div class="big num ' + (h.gain_pct >= 0 ? "good-t" : "bad-t") + '" style="font-size:26px">' + (h.gain_pct >= 0 ? "▲ " : "▼ ") + pct(h.gain_pct) + "</div>" +
      '<div class="small num">평단 $' + fmt(h.avg) + " → 현재 $" + fmt(h.price) + " · " + fmt(h.qty, 0) + "주 · 손절 $" + fmt(h.stop) +
      (h.to_stop_pct == null ? "" : " (" + fmt(h.to_stop_pct, 1) + "% 위)") + " · 목표 $" + fmt(h.target) + "</div></div>" +
      // 할 일
      (h.action ? '<div class="msg ' + (h.tone === "bad" ? "err" : "note") + '">📌 지금 할 일: <b>' + esc(h.action) + "</b></div>"
                : '<div class="msg ok">✓ 지금 할 일 없음 — 원칙대로예요</div>') +
      // 왜
      ((h.hits && h.hits.length) || (h.reasons && h.reasons.length)
        ? '<h2>왜 이 결론인가</h2><div class="card"><ul class="plain">' +
          (h.hits || []).map(x => "<li>" + esc(x) + "</li>").join("") +
          (h.reasons || []).slice(0, 3).map(x => "<li>" + esc(x) + "</li>").join("") + "</ul></div>" : "") +
      // 총점
      (h.total == null ? "" : "<h2>총점 " + fmt(h.total, 0) + "</h2>" + (h.cats && Object.keys(h.cats).length ? scoreBars(h.cats) : "")) +
      // 자세히 분석
      "<h2>자세히 분석</h2>" + dtabs +
      // 접은 항목
      '<details class="sig"><summary><b>매도 규칙 7개</b></summary>' + rulesHtml7(h) + "</details>" +
      '<details class="sig"><summary><b>📓 이 종목 일지 (알림·모의 거래)</b></summary>' + tickerLogHtml(h.t) + "</details>" +
      '<p class="foot">손절선을 바꾸려면 구글 시트 \'보유 종목\' 탭에 적어 주세요 · ' + esc(DISCLAIMER) + "</p>");
    // 자세히 분석 탭 전환
    $app.querySelectorAll(".dtabs button").forEach(b => b.addEventListener("click", () => {
      const i = b.dataset.dt;
      $app.querySelectorAll(".dtabs button").forEach(x => x.classList.toggle("on", x === b));
      $app.querySelectorAll(".dpane").forEach((p, j) => { p.hidden = String(j) !== i; });
    }));
    bindWatch();
    bindPriceAlert();
    liveStock(h.t);
    mountQuoteSum(h.t);
    mountStats(h.t);
    if (!(S.ai && S.ai.earn && S.ai.earn[h.t])) mountEarnTab(h.t);
  }

  /* ---------- symphony-kanban에서 가져온 것 ----------
     ① 실행 증거(proof of work): 실행마다 '무엇이 바뀌었나 + 자동 점검 통과?'를 남기고 보여 줘요. 점검 안 한 건 '통과'로 꾸미지 않아요.
     ② 활동 피드: 전체 · 내가 볼 것 · 진행 중 · 실행 기록 4칸. 🔔에는 '내가 볼 것' 개수.
     ③ 오래된 자료: 와야 할 아침 실행이 안 왔으면 숫자를 '오늘 것'처럼 보여 주지 않고 먼저 알려요.
     ④ 종목 일지: 알림·모의 체결·주문표를 종목마다 모아 쌓아요. */
  const runsOf = () => (S.perf && S.perf.runs) || [];
  // 아침 실행은 매주 화~토 07:00(한국) 예약 — GitHub 예약 실행은 붐비면 2~5시간 늦게 시작해서(실측 07:57~11:45) 6시간 여유를 둬요
  function expectedDaily(now) {
    for (let d = 0; d < 9; d++) {
      const k = new Date(now + 9 * 36e5 - d * 864e5), dow = k.getUTCDay();
      const t = Date.UTC(k.getUTCFullYear(), k.getUTCMonth(), k.getUTCDate(), 7) - 9 * 36e5;
      if (dow >= 2 && dow <= 6 && t + 6 * 36e5 <= now) return t;
    }
    return 0;
  }
  function staleInfo() {
    const r = runsOf().find(x => x.kind === "daily");
    const at = (r && r.at) || (S.data && S.data.run_at);
    if (!at) return null;
    const last = Date.parse(at), exp = expectedDaily(Date.now());
    if (!last || !exp || last >= exp - 30 * 6e4) return null;
    return { at: at, hours: Math.round((Date.now() - last) / 36e5) };
  }
  const RUN_TONE = { true: ["good", "성공"], warn: ["warn", "점검 실패 있음"], false: ["bad", "실패"], skip: ["info", "건너뜀"] };
  function runTone(r) { return RUN_TONE[String(r.ok)] || ["info", String(r.ok)]; }
  function checkLine(c) {
    const mk = c.ok === true ? ["ok", "✓"] : c.ok === false ? ["no bad-t", "✕"] : ["no", "–"];
    return '<li class="' + mk[0] + '">' + mk[1] + " " + esc(c.n) + (c.ok == null ? ' <span class="small">(점검 안 함)</span>' : "") +
      (c.d ? '<div class="small">' + esc(c.d) + "</div>" : "") + "</li>";
  }
  function runCard(r, open) {
    const t = runTone(r), cs = r.checks || [];
    const pass = cs.filter(c => c.ok === true).length, fail = cs.filter(c => c.ok === false).length, none = cs.length - pass - fail;
    const one = (r.changed || []).slice(0, 2).join(" · ");
    return '<details class="sig run"' + (open ? " open" : "") + '><summary><div class="row between"><b>' + esc(r.label || r.kind) + '</b><span class="badge ' + t[0] + '">' + t[1] + "</span></div>" +
      '<div class="small">' + esc(whenText(r.at)) + (r.took != null ? " · " + r.took + "초" : "") + (cs.length ? " · 점검 " + pass + "통과" + (fail ? " " + fail + "실패" : "") + (none ? " " + none + "안 함" : "") : "") + "</div>" +
      (one ? '<div class="small">' + esc(one) + "</div>" : "") + "</summary>" +
      ((r.changed || []).length ? '<b class="small">바뀐 것</b><ul class="plain small">' + r.changed.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
      (cs.length ? '<b class="small">자동 점검</b><ul class="checks">' + cs.map(checkLine).join("") + "</ul>" : '<div class="small">이 실행은 점검 항목이 없어요</div>') +
      (r.err ? '<b class="small">멈춘 곳 (마지막 줄)</b><pre class="errtail">' + esc(String(r.err).trim().split("\n").slice(-6).join("\n")) + "</pre>" : "") + "</details>";
  }
  // 홈 한 줄: 마지막 실행의 증거 — "아침 리포트 성공 · 점검 8/8"
  function homeRunLine() {
    const r = runsOf()[0];
    if (!r) return "";
    const t = runTone(r), cs = r.checks || [], fail = cs.filter(c => c.ok === false).length;
    return '<a class="runline" href="#/alerts/runs"><span class="badge ' + t[0] + '">' + esc(r.label) + " " + t[1] + "</span>" +
      '<span class="small">' + esc(whenText(r.at)) + (cs.length ? " · 점검 " + (cs.length - fail) + "/" + cs.length + (fail ? " (실패 " + fail + ")" : "") : "") + " ›</span></a>";
  }
  function needsYou() {
    const out = [], st = staleInfo();
    if (st) out.push({ i: "⏳", tone: "warn", t: "자료가 오래됐어요 — 마지막 아침 실행 " + st.hours + "시간 전",
      b: "와야 할 아침 리포트가 아직 안 왔어요. 화면의 숫자는 " + whenText(st.at) + " 기준이에요. GitHub Actions 실행 기록을 확인해 주세요.", h: "#/alerts", seg: "runs" });
    const seen = {};
    runsOf().forEach(r => {
      if (seen[r.kind]) return; seen[r.kind] = 1;
      if ((Date.now() - Date.parse(r.at)) > 3 * 864e5) return;
      if (r.ok === false) out.push({ i: "🛑", tone: "bad", t: r.label + " 실패", b: (r.changed || [])[0] || "멈춘 곳을 실행 기록에서 확인해 주세요", h: "#/alerts", seg: "runs" });
      else if (r.ok === "warn") {
        const f = (r.checks || []).filter(c => c.ok === false);
        out.push({ i: "⚠️", tone: "warn", t: r.label + " · 점검 " + f.length + "개 실패", b: f.map(c => c.n + (c.d ? " — " + c.d : "")).join(" / "), h: "#/alerts", seg: "runs" });
      }
    });
    ((S.data && S.data.holdings) || []).filter(h => h.action).forEach(h =>
      out.push({ i: h.tone === "bad" ? "🔴" : "🟠", tone: h.tone === "bad" ? "bad" : "warn", t: h.t + " · " + h.conclusion, b: "규칙상 할 일: " + h.action, h: "#/hold/" + encodeURIComponent(h.t) }));
    ((S.perf && S.perf.paper && S.perf.paper.trades) || []).filter(x => x.below_stop).forEach(x =>
      out.push({ i: "🧪", tone: "warn", t: "모의 계좌 " + x.t + " 손절선 아래", b: "직접 담은 모의 종목이에요. 성적 탭에서 팔지 정해 주세요.", h: "#/score" }));
    const u = S.aiUsage || {};
    if (u.cap && u.total / u.cap >= 0.8) out.push({ i: "💸", tone: "warn", t: "GPT 사용량 " + Math.round(u.total / u.cap * 100) + "%", b: "$" + fmt(u.total) + " / $" + fmt(u.cap, 0) + " — 한도에 닿으면 규칙만으로 돌아가요", h: "#/settings" });
    return out;
  }
  function needItem(x) {
    return '<a class="item need ' + x.tone + '" href="' + x.h + (x.seg ? "/" + x.seg : "") + '"><span class="ic">' + x.i + '</span><div class="grow"><b>' + esc(x.t) + '</b><div class="small">' + esc(x.b) + "</div></div><span class=\"small\">›</span></a>";
  }
  function homeNeedsCard() {
    const n = needsYou();
    if (!n.length) return "";
    return '<div class="card needcard"><div class="row between"><b>👀 내가 볼 것 ' + n.length + "</b>" + '<a class="small link" href="#/alerts/need">모두 보기 ›</a></div>' +
      '<div class="list">' + n.slice(0, 3).map(needItem).join("") + "</div></div>";
  }
  function runningHtml() {
    const m = S.perf && S.perf.sim, rows = [];
    if (m) {
      (m.positions || []).forEach(p => rows.push(["🟢", "모의 보유 " + p.t + " " + p.qty + "주", "손절 $" + fmt(p.stop) + " · 목표 $" + fmt(p.target) + (p.half ? " · 절반 익절함" : ""), "#/score"]));
      (m.pending || []).forEach(o => rows.push(["⏱️", "다음 거래일 주문 " + o.t + " " + o.qty + "주", "지정가 $" + fmt(o.limit) + " 이하 · $" + fmt(o.skip_above) + " 위로 시작하면 안 삼", "#/score"]));
    }
    const now = Date.now();
    let nextDaily = 0;
    for (let d = 0; d < 8 && !nextDaily; d++) { const x = new Date(now + 9 * 36e5 + d * 864e5); const t = Date.UTC(x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate(), 7) - 9 * 36e5; if (x.getUTCDay() >= 2 && x.getUTCDay() <= 6 && t > now) nextDaily = t; }
    const sched = [["🌅", "다음 아침 리포트", nextDaily ? new Date(nextDaily).toLocaleString("ko-KR", { weekday: "short", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—"],
      ["⏰", "장중 감시", "미국 장이 열린 동안 매시간 · 5분봉 모의 체결 + 손절선 경고"],
      ["📅", "주간 요약", "매주 일요일"]];
    const u = S.aiUsage || {}, w = u.cap ? Math.min(100, (u.total || 0) / u.cap * 100) : 0;
    return (rows.length ? '<div class="list">' + rows.map(r => '<a class="item" href="' + r[3] + '"><span class="ic">' + r[0] + '</span><div class="grow"><b>' + esc(r[1]) + '</b><div class="small">' + esc(r[2]) + "</div></div></a>").join("") + "</div>"
        : emp("🫙", "지금 돌아가는 모의 주문·보유가 없어요", "아침 리포트 뒤에 조건에 맞는 후보가 있으면 다음 거래일 주문이 생겨요.", "#/score", "자동 모의 보기")) +
      "<h2>예정된 실행</h2><div class=\"list\">" + sched.map(x => '<div class="item" style="cursor:default"><span class="ic">' + x[0] + '</span><div class="grow"><b>' + esc(x[1]) + '</b><div class="small">' + esc(x[2]) + "</div></div></div>").join("") + "</div>" +
      '<h2>남은 여유</h2><div class="card"><div class="row"><span class="radial" style="--p:' + (100 - w).toFixed(1) + '"><span>' + Math.round(100 - w) + '<small>%</small></span></span>' +
      '<div class="grow" style="margin-left:12px"><b>GPT 이번 달 남은 한도</b><div class="small num">$' + fmt(u.total) + " 씀 / $" + fmt(u.cap || 5, 0) + " · 아침 분석 $" + fmt(u.program) + " · 앱 질문 $" + fmt(u.app) + "</div></div></div></div>";
  }
  /* ---------- 펀드매니저 4단계 (Kronos 예측 · skfolio 배분 · NautilusTrader 백테스트 · 보고서) ---------- */
  const FUND_NAME = { meanrisk: "MeanRisk", hrp: "HRP", equal: "균등", spy: "SPY 보유" };
  function sparkSvg(series) {
    const all = series.flatMap(x => (x.c || []).map(p => p[1]));
    if (!all.length) return "";
    const lo = Math.min(...all), hi = Math.max(...all), W = 320, H = 120, n = Math.max(...series.map(x => (x.c || []).length)) - 1 || 1;
    const path = c => c.map((p, i) => (i ? "L" : "M") + (i / n * W).toFixed(1) + "," + (H - (p[1] - lo) / ((hi - lo) || 1) * (H - 8) - 4).toFixed(1)).join("");
    return '<svg viewBox="0 0 ' + W + " " + H + '" class="fundspark" role="img" aria-label="누적 평가액">' +
      series.map(x => '<path d="' + path(x.c || []) + '" fill="none" stroke="' + x.col + '" stroke-width="' + (x.w || 1.6) + '"' + (x.dash ? ' stroke-dasharray="4 3"' : "") + "/>").join("") + "</svg>" +
      '<div class="small legend">' + series.map(x => '<span><i style="background:' + x.col + '"></i>' + esc(x.n) + "</span>").join("") + "</div>";
  }
  function fundHtml(f) {
    if (!f) return emp("🧑‍💼", "펀드매니저 4단계는 일요일에 돌아요", "보유·모의·후보 종목으로 예측(Kronos) → 비중(skfolio) → 매주 리밸런싱 백테스트(NautilusTrader) → 한 장 보고서를 만들어요.", "#/score", "자동 모의 보기");
    const st = f.steps || {}, fc = (f.forecast && f.forecast.items) || {}, w = f.weights || {}, bt = f.backtest || {}, sc = f.forecast_score || {};
    let h = '<div class="card"><div class="row between"><b>🧑‍💼 이번 주 펀드매니저</b><span class="small">' + esc(whenText(f.at)) + "</span></div>" +
      '<ul class="checks">' + Object.keys(st).map(k => checkLine({ n: k, ok: st[k].ok, d: st[k].d })).join("") + "</ul>" +
      '<div class="small">실제 주문 없음 · 예측과 과거 검증은 수익을 보장하지 않아요</div></div>';
    if (f.why) return h + '<div class="msg note">' + esc(f.why) + "</div>";
    const r = f.report;
    if (r) h += '<h2>📝 한 장 보고서</h2><div class="card">' + (r["한 줄"] ? "<b>" + esc(r["한 줄"]) + "</b>" : "") +
      ["무엇이 통했나", "위험", "다음 주에 바꿔 볼 것"].map(k => (r[k] || []).length ? '<div class="sub" style="margin-top:8px">' + esc(k) + '</div><ul class="plain">' + r[k].map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "").join("") +
      (r["예시"] ? '<div class="ex">💡 ' + esc(r["예시"]) + "</div>" : "") + checkNote(r["_검사"]) + "</div>";
    if (f.vibe) h += '<details class="sig"><summary><b>🤖 Vibe-Trading 보고서</b></summary><pre class="weekly">' + esc(f.vibe) + "</pre></details>";
    const T = Object.keys(fc);
    h += '<h2>① 예측 · Kronos (다음 5거래일)</h2>' + (T.length ? '<div class="card"><div class="tblwrap"><table class="tbl num"><tr><th>종목</th><th>지금</th><th>5일 뒤</th><th>예상</th></tr>' +
      T.sort((a, b) => fc[b].exp_ret - fc[a].exp_ret).map(t => "<tr><td><b>" + esc(t) + "</b></td><td>$" + fmt(fc[t].last) + "</td><td>$" + fmt((fc[t].pred || []).slice(-1)[0]) +
        '</td><td class="' + (fc[t].exp_ret >= 0 ? "good-t" : "bad-t") + '">' + pct(fc[t].exp_ret * 100) + "</td></tr>").join("") + "</table></div>" +
      '<div class="small">' + esc(f.forecast.model || "") + " · 표본 " + esc(f.forecast.samples || "") + "번 평균 · " + esc(f.forecast.date || "") + " 종가 기준</div></div>"
      : '<div class="msg note">이번 주 예측이 없어요 — 비중은 과거 1년 평균으로 계산했어요.</div>');
    h += '<h2>🎯 지난 예측 채점</h2><div class="card">' + (sc.n ? '<div class="row between"><b>방향 적중 ' + sc.hit + '%</b><span class="small">' + sc.n + "건 · 평균 오차 " + fmt(sc.mae) + "%p</span></div>" +
      '<div class="small">50% 근처면 동전 던지기와 비슷해요. 표본이 쌓일수록 믿을 만해져요.</div>'
      : '<div class="small">예측한 5거래일이 지나면 실제 종가와 비교해 여기에 채점해요.</div>') + "</div>";
    const A = (w.assets || []);
    if (A.length) h += '<h2>② 비중 · skfolio</h2><div class="card"><div class="tblwrap"><table class="tbl num"><tr><th>종목</th><th>MeanRisk</th><th>HRP</th><th>균등</th></tr>' +
      A.map(t => "<tr><td><b>" + esc(t) + "</b></td>" + ["meanrisk", "hrp", "equal"].map(k => "<td>" + (w[k] && w[k][t] ? Math.round(w[k][t] * 100) + "%" : "—") + "</td>").join("") + "</tr>").join("") +
      '</table></div><div class="small">MeanRisk 기준: ' + esc(w.prior || "") + " · 한 종목 최대 " + Math.round(Math.min(100, Math.max(25, 100 / A.length + 5))) + "%</div></div>";
    const K = ["meanrisk", "hrp", "equal", "spy"].filter(k => bt[k] && bt[k].ret != null);
    if (K.length) h += '<h2>③ 실행 · NautilusTrader 백테스트</h2><div class="card">' +
      sparkSvg([{ n: "MeanRisk", c: (bt.meanrisk || {}).curve, col: "var(--accent)", w: 2.2 }, { n: "HRP", c: (bt.hrp || {}).curve, col: "var(--good)" },
        { n: "균등", c: (bt.equal || {}).curve, col: "var(--warn)" }, { n: "SPY", c: (bt.spy || {}).curve, col: "var(--sub)", dash: 1 }].filter(x => (x.c || []).length)) +
      '<div class="tblwrap"><table class="tbl num"><tr><th>방법</th><th>수익</th><th>샤프</th><th>최대 낙폭</th><th>거래</th></tr>' +
      K.map(k => "<tr><td>" + esc(FUND_NAME[k]) + '</td><td class="' + (bt[k].ret >= 0 ? "good-t" : "bad-t") + '">' + pct(bt[k].ret) + "</td><td>" + (bt[k].sharpe == null ? "—" : fmt(bt[k].sharpe)) +
        "</td><td>" + pct(bt[k].mdd) + "</td><td>" + (bt[k].trades == null ? "—" : bt[k].trades) + "</td></tr>").join("") + "</table></div>" +
      '<div class="small">' + esc(bt.start || "") + "부터 · 매주 첫 거래일에 그때까지의 1년 자료로만 비중을 다시 계산(미래 정보 없음) · 수수료 " + esc(bt.fee || "") + " · " + esc(bt.engine || "") + "</div></div>";
    else if (bt.skip) h += '<div class="msg note">' + esc(bt.skip) + "</div>";
    return h + '<p class="foot">가이드: Claude 펀드매니저 4단계 (Kronos · skfolio · NautilusTrader · Vibe-Trading) · 오픈소스 각 저장소의 라이선스를 따라요</p>';
  }
  function viewAlerts() {
    const items = S.alerts || [];
    if (items[0]) { S.lastSeenAlert = items[0].at; store.set("seenAlert", S.lastSeenAlert); }
    const seg = S.actSeg || "all", need = needsYou(), runs = runsOf();
    const tone = { bad: "var(--bad)", warn: "var(--warn)", info: "var(--accent)" };
    const segBtn = (k, l) => '<button data-s="' + k + '"' + (seg === k ? ' class="on"' : "") + ">" + l + "</button>";
    let body = "";
    if (seg === "need") body = need.length ? '<div class="list">' + need.map(needItem).join("") + "</div>"
      : emp("✅", "지금 손댈 것이 없어요", "규칙에 걸린 보유 종목·실패한 실행·오래된 자료가 생기면 여기에 모여요.", "#/home", "홈으로");
    else if (seg === "run") body = runningHtml();
    else if (seg === "runs") body = '<div class="small" style="margin:4px 0 8px">실행마다 바뀐 것과 자동 점검 결과를 남겨요. 프로그램의 "잘 됐어요"가 아니라 점검 결과가 증거예요 · 최근 ' + runs.length + "번</div>" +
      (runs.length ? runs.map((r, i) => runCard(r, i === 0)).join("") : emp("🧾", "실행 기록이 아직 없어요", "다음 아침 리포트(평일 아침 7시쯤)부터 쌓여요.", "#/home", "홈으로"));
    else body = '<div class="small">푸시·슬랙으로 보낸 것과 같은 내용이에요 (최근 200개)</div><div class="list">' +
      (items.length ? items.map(a => '<div class="item" style="cursor:default"><span style="width:10px;height:10px;border-radius:5px;background:' + (tone[a.tone] || tone.info) +
        '"></span><div class="grow"><div class="row between"><b>' + esc(a.title) + '</b><span class="small">' + esc(whenText(a.at)) + '</span></div><div class="small">' + esc(a.body) + "</div></div></div>").join("")
        : emp("🔔", "새 알림이 오면 여기에 모여요", "아침 리포트·장중 체결·업데이트 소식이 푸시와 함께 쌓여요.", "#/settings", "푸시 알림 설정")) + "</div>";
    appShell("home", '<button class="back" onclick="history.back()">← 홈</button><h1>활동</h1>' + statusLine() +
      '<div class="segs act">' + segBtn("all", "전체") + segBtn("need", "내가 볼 것" + (need.length ? " " + need.length : "")) + segBtn("run", "진행 중") + segBtn("runs", "실행 기록") + "</div>" + body);
    $app.querySelectorAll(".segs.act button").forEach(b => b.addEventListener("click", () => { S.actSeg = b.dataset.s; history.replaceState(null, "", "#/alerts/" + b.dataset.s); viewAlerts(); window.scrollTo(0, 0); }));
  }
  // ④ 종목 일지: 이 종목에 대해 앱이 한 일을 시간순으로
  function tickerLogHtml(t) {
    const re = new RegExp("(^|[^A-Z])" + String(t).replace(/[.\-]/g, "[.\\-]") + "([^A-Z]|$)");
    const rows = [];
    (S.alerts || []).forEach(a => { if (re.test((a.title || "") + " " + (a.body || ""))) rows.push([a.at, "🔔", a.title + " — " + a.body]); });
    const m = S.perf && S.perf.sim;
    if (m) {
      (m.closed || []).filter(c => c.t === t).forEach(c => rows.push([c.exit_date, "🧾", "모의 매도 " + c.date + " → " + c.exit_date + " · " + c.why + " · " + usd(c.pnl)]));
      (m.positions || []).filter(p => p.t === t).forEach(p => rows.push([p.date, "🟢", "모의 매수 " + p.qty + "주 @$" + fmt(p.entry) + " · 지금 보유 중"]));
      (m.tickets || []).filter(x => x.t === t).forEach(x => rows.push([x.date || x.at || "", "🎯", "주문표 " + (x.side || "") + " · " + (x.result || x.status || "") + (x.price ? " @$" + fmt(x.price) : "")]));
    }
    (S.paper || []).filter(x => x.t === t).forEach(x => rows.push([x.date || "", "🧪", "직접 담은 모의 " + x.qty + "주 @$" + fmt(x.price) + (x.sold_date ? " → " + x.sold_date + " 판매 @$" + fmt(x.sold_price) : "")]));
    rows.sort((a, b) => String(b[0]).localeCompare(String(a[0])));
    return rows.length ? '<ul class="plain small tlog">' + rows.slice(0, 30).map(r => "<li><span class=\"num\">" + esc(String(r[0]).slice(0, 16).replace("T", " ")) + "</span> " + r[1] + " " + esc(r[2]) + "</li>").join("") + "</ul>"
      : '<div class="small">아직 이 종목에 대한 알림·모의 거래가 없어요. 생기면 여기에 쌓여요.</div>';
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
  const signTone = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
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
    const h = "";
    const calm = why => h + '<div class="card small">' + esc(why) + "<br>위의 3개월 자동 모의투자는 증권사 연결 없이 가상 장부로 <b>정상 진행 중</b>이에요. 실전 직전에 연결해 봐도 충분해요.</div>";
    if (!k) return calm("아직 연결 안 함.");
    if (!k.on) return calm("꺼져 있어요.");
    if (k.disabled) return calm("자동으로 꺼 뒀어요: " + (k.disabled.why || "") + ". 모의투자용 앱키로 바꾸면 자동으로 다시 켜져요.");
    if (k.err && !(k.orders || []).length && !(k.holdings || []).length) return calm("연결 시도 중 오류: " + k.err);
    const today = (k.orders || []).slice().reverse().slice(0, 8);
    return h + '<div class="card">' + (k.err ? '<div class="msg err">' + esc(k.err) + "</div>" : "") +
      '<div class="small">' + esc(whenText(k.at)) + " 기준 · 보유 " + (k.holdings || []).length + "종목" + (k.summary && k.summary.pnl != null ? " · 평가손익 $" + fmt(k.summary.pnl) : "") + "</div>" +
      ((k.holdings || []).length ? '<ul class="plain">' + k.holdings.map(x => "<li>" + esc(x.t) + " " + x.qty + "주 @$" + fmt(x.avg) + " → $" + fmt(x.now) + "</li>").join("") + "</ul>" : "") +
      (today.length ? '<b>최근 주문</b><ul class="plain small">' + today.map(o => "<li>" + esc(o.date) + " " + esc(o.side) + " " + esc(o.t) + " " + o.qty + "주 @" + fmt(o.price) + " · " + esc(o.status) + "</li>").join("") + "</ul>" : '<div class="small">아직 주문 없음</div>') +
      "</div>";
  }
  // 증권사 앱처럼 "평가금액 · 수익률"을 맨 위에 크게 (자동 모의 기준)
  function brokerCard(m, ref) {
    const gain = m.equity - m.budget;
    const up = m.ret >= 0;
    const c = m.curve || [];
    let today = "";
    if (c.length >= 2) {
      const d = c[c.length - 1][1] - c[c.length - 2][1], base = c[c.length - 2][1];
      today = '<div class="broker-today small num">오늘 ' + (d >= 0 ? "▲" : "▼") + " " + usd(d) + (base ? " (" + pct(d / base * 100) + ")" : "") + "</div>";
    }
    const gapp = (m.ret != null && m.spy_ret != null) ? m.ret - m.spy_ret : null;
    return '<div class="card broker">' +
      '<div class="row between"><span class="sub">모의 평가금액</span><span class="badge info">가상 $' + fmt(m.budget, 0) + " · 실제 주문 없음</span></div>" +
      '<div class="broker-eq num">$' + fmt(m.equity) + "</div>" +
      '<div class="broker-ret num ' + (up ? "good-t" : "bad-t") + '">' + (up ? "▲" : "▼") + " " + usd(gain) + " (" + pct(m.ret) + ")</div>" +
      today +
      '<div class="broker-row small num">현금 $' + fmt(m.cash) + " · 주식 $" + fmt(m.equity - m.cash) + " · " + (m.positions || []).length + "종목</div>" +
      (m.spy_ret != null ? '<div class="small num">같은 기간 SPY ' + pct(m.spy_ret) + (gapp != null ? " · " + (gapp >= 0 ? "+" : "") + fmt(gapp, 1) + "%p " + (gapp >= 0 ? "앞서요" : "뒤처져요") : "") + "</div>" : "") +
      (ref ? '<div class="small broker-ref">참고: 같은 규칙으로 ' + (ref.max_pos || 2) + "종목만 집중했다면 " + pct(ref.ret) + "</div>" : "") + "</div>";
  }
  // 리허설 주문표: 증권사 앱에 그대로 넣는다면 + 채점(체결률)
  function ticketHtml(m) {
    const ts = m.ticket_stats || {}, pend = m.pending || [], pos = m.positions || [];
    const rows = pend.map(o => "매수 " + o.t + " " + o.qty + "주 · 지정가 $" + fmt(o.limit) + " · 당일 유효 · 시작가 $" + fmt(o.skip_above) + " 위면 취소")
      .concat(pos.map(p => "매도 " + p.t + " " + p.qty + "주 · 손절 $" + fmt(p.stop) + " 이하" + (p.half ? " (본전 손절)" : " · 목표 $" + fmt(p.target) + "에 절반 지정가")));
    const RES = { "체결": "good", "미체결": "warn", "대기": "info" };
    const tk = (m.tickets || []).slice(0, 10);
    return '<h2>🧾 오늘의 리허설 주문표 <span class="small">(증권사 앱에 넣는다면)</span></h2><div class="card">' +
      (rows.length ? '<ol class="plain small" style="padding-left:18px;list-style:decimal">' + rows.map(r => "<li>" + esc(r) + "</li>").join("") + "</ol>" +
        '<button class="btn ghost" id="tkcopy" type="button">주문표 복사</button>' : '<div class="small">오늘은 낼 주문이 없어요</div>') +
      '<div class="small" style="margin-top:6px">미국 장중 매시간 5분봉으로 증권사처럼 체결해요 · 지정가는 0.1% 넘어서야 체결 · 손절은 0.15% 불리하게' + (m.intra_at ? " · 마지막 확인 " + esc(m.intra_at) : "") + "</div></div>" +
      '<h2>🎯 주문표 채점</h2><div class="card"><div class="row between"><b>체결률 ' + (ts.rate != null ? Math.round(ts.rate * 100) + "%" : "—") + '</b><span class="small">' +
      (ts.n || 0) + "건 중 " + (ts.filled || 0) + "건 체결 · 안 냄 " + (ts.skipped || 0) + "건</span></div>" +
      '<div class="plbar" style="margin:6px 0"><span class="g" style="width:' + Math.round((ts.rate || 0) * 100) + '%;background:var(--accent)"></span></div>' +
      '<div class="small">실전 기준: 10건 이상 · 체결률 60% 이상' + (ts.avg_vs_limit != null ? " · 체결가는 지정가 대비 평균 " + (ts.avg_vs_limit >= 0 ? "+" : "") + fmt(ts.avg_vs_limit) + "%" : "") + "</div>" +
      (tk.length ? '<div class="list" style="margin-top:6px">' + tk.map(x => '<div class="item" style="cursor:default"><span class="tk">' + esc(x.t) + '</span><span class="grow small num">' +
        esc(x.day || x.signal) + " · " + (x.qty || "") + "주 지정가 $" + fmt(x.limit) + (x.fill_px ? " → $" + fmt(x.fill_px) + " (" + esc(x.at || "") + ")" : "") + '</span><span class="badge ' +
        (RES[x.result] || "") + '">' + esc(x.result) + "</span></div>").join("") + "</div>" : '<div class="small">첫 주문표 결과는 다음 거래일부터 쌓여요</div>') + "</div>";
  }
  function autoSimHtml(m, ref) {
    if (!m) return emp("🧪", "자동 모의투자를 준비하고 있어요", "다음 아침 리포트부터 가상 1,000달러로 시작해요.", "#/picks", "오늘 후보 보기");
    const prog = Math.max(0, Math.min(100, m.day / m.days * 100));
    const net = m.gain + m.loss, w = Math.abs(m.gain) + Math.abs(m.loss) || 1;
    const passN = (m.checks || []).filter(c => c[1]).length;
    // ── 맨 위: 증권사처럼 평가금액·수익률 한눈에 ──
    return brokerCard(m, ref) +
      '<div class="card"><div class="row between"><span class="sub">3개월 자동 모의매매</span><span class="small">' + m.day + "/" + m.days + "일째</span></div>" +
      '<div class="plbar" style="margin:6px 0"><span class="g" style="width:' + prog + '%;background:var(--accent)"></span></div>' +
      '<div class="small">' + esc(m.start) + " ~ " + esc(m.end) + " · 11장 규칙 그대로 자동 매매 · 최대 낙폭 " + fmt(m.mdd, 1) + "%</div></div>" +
      // ── 보유 종목 ──
      "<h2>지금 가진 종목</h2>" + ((m.positions || []).length ? '<div class="list">' + m.positions.map(p =>
        '<div class="item" style="cursor:default"><span class="tk">' + esc(p.t) + '</span><div class="grow small num">' + esc(p.date) + " · " + p.qty + "주 @$" + fmt(p.entry) +
        "<br>손절 " + fmt(p.stop) + " · 목표 " + fmt(p.target) + (p.half ? " · 절반 익절함" : "") + (p.fill_time ? " · 체결 " + esc(p.fill_time) : "") + "</div></div>").join("") + "</div>" : emp("🫙", "지금 가진 종목은 없어요", "아래 '다음 거래일 주문 계획'이 체결되면 여기에 나와요.", "", "")) +
      "<h2>다음 거래일 주문 계획</h2>" + ((m.pending || []).length ? '<div class="list">' + m.pending.map(o =>
        '<div class="item" style="cursor:default"><span class="tk">' + esc(o.t) + '</span><div class="grow small num">' + o.qty + "주 · 지정가 $" + fmt(o.limit) +
        " 이하 · 시작가 $" + fmt(o.skip_above) + " 위면 안 삼<br>" + esc(o.why) + vetoTag(o.t) + "</div></div>").join("") + "</div>"
        : emp("🗓️", "다음 거래일엔 주문을 쉬어요", "조건에 맞는 후보가 없거나 보유 자리가 찼어요. 쉬는 것도 규칙이에요.", "#/picks", "오늘 후보 보기")) +
      // ── 자세히: 손익·주문표·실전 기준·판 거래·기록 ──
      '<details class="sig"><summary><b>💰 얼마 벌고 얼마 잃었나</b></summary>' +
      '<div class="card"><div class="sub">수수료·환전 추정치 뺀 금액</div>' +
      '<div class="pl"><div><div class="small">번 돈 (' + m.wins + '건)</div><div class="big num good-t">' + usd(m.gain) + "</div></div>" +
      '<div><div class="small">잃은 돈 (' + m.losses + '건)</div><div class="big num bad-t">' + usd(m.loss) + "</div></div></div>" +
      '<div class="plbar"><span class="g" style="width:' + (Math.abs(m.gain) / w * 100) + '%"></span><span class="l" style="width:' + (Math.abs(m.loss) / w * 100) + '%"></span></div>' +
      '<dl class="kv num"><dt>판 거래 합계</dt><dd><b class="' + (net >= 0 ? "good-t" : "bad-t") + '">' + usd(net) + "</b></dd>" +
      (m.fees != null ? "<dt>수수료·환전 비용(추정, 포함됨)</dt><dd>$" + fmt(m.fees) + "</dd>" : "") + "</dl></div></details>" +
      '<details class="sig"><summary><b>🧾 주문표 · 체결률</b></summary>' +
      '<div class="card small">지난 거래일에 한 일<br>' + ((m.today || []).length ? m.today.map(esc).join("<br>") : "체결·매도 없음") + "</div>" + ticketHtml(m) + "</details>" +
      '<details class="sig"><summary><b>🎯 실전 기준 ' + passN + "/" + (m.checks || []).length + ' <span class="small">(3개월 끝에 최종 판단)</span></b></summary>' +
      '<div class="card"><ul class="checks">' + (m.checks || []).map(c => '<li class="' + (c[1] ? "ok" : "no") + '">' + (c[1] ? "✓ " : "– ") + esc(c[0]) +
        '<div class="small">' + esc(c[2]) + "</div></li>").join("") + "</ul></div></details>" +
      '<details class="sig"><summary><b>🧾 판 거래 · 기록</b></summary>' + reportsHtml(m.reports) +
      ((m.closed || []).length ? '<div class="list">' + m.closed.map(c =>
        '<div class="item" style="cursor:default"><span class="tk">' + esc(c.t) + '</span><div class="grow small num">' + esc(c.date) + " → " + esc(c.exit_date) + " · " + esc(c.why) +
        '</div><b class="num ' + (c.pnl >= 0 ? "good-t" : "bad-t") + '">' + usd(c.pnl) + "</b></div>").join("") + "</div>" : '<div class="small">아직 판 거래가 없어요</div>') +
      '<div class="card small" style="margin-top:8px">' + (m.log || []).map(esc).join("<br>") + "</div></details>";
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
      body = autoSimHtml(S.perf && S.perf.sim, S.perf && S.perf.sim_ref) + '<details class="sig"><summary><b>🔌 증권사 모의계좌 연결 (선택)</b></summary>' + kisHtml(S.kis) + "</details>";
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
          : emp("🧺", "직접 고른 종목으로 연습해 보세요", "후보 종목 화면의 '모의투자에 담기'를 누르면 가상 1,000달러 계좌에 담겨요.", "#/picks", "후보 보러 가기")) +
        "<h2>판 거래 · 회고</h2>" + (closed.length ? closed.map(x =>
          '<div class="card"><div class="row between"><b>' + esc(x.t) + '</b><span class="badge ' + signTone(x.ret) + '">' + pct(x.ret) + "</span></div>" +
          '<div class="small num">' + esc(x.date) + " → " + esc(x.sold_date) + " · $" + fmt(x.price) + " → $" + fmt(x.sold_price) + " · " + esc(x.why || "") +
          (x.excess != null ? " · SPY 대비 " + pct(x.excess) + "p" : "") + "</div>" +
          '<div class="num ' + (x.pnl >= 0 ? "good-t" : "bad-t") + '"><b>' + usd(x.pnl) + "</b> " + (x.pnl >= 0 ? "벌었어요" : "잃었어요") + "</div>" +
          '<div class="note-row"><input type="text" maxlength="200" data-note="' + esc(x.id) + '" placeholder="회고 한 줄 (왜 샀고, 무엇을 배웠나)" value="' + esc(x.note || "") + '">' +
          '<button class="chip" data-save="' + esc(x.id) + '">저장</button></div></div>').join("")
          : emp("📝", "판 거래가 생기면 회고를 남겨요", "잘한 점·아쉬운 점을 적어 두면 다음 판단에 도움이 돼요.", "", ""));
    } else if (seg === "skill") {
      const f = pf.first20 || {}, l = pf.last20 || {}, n = pf.n || trades.length;
      body = '<div class="card"><b>실력일까, 운일까</b><p class="sub">한두 번 번 것은 운일 수 있어요. 거래가 20번 넘게 쌓였을 때 아래 숫자가 SPY보다 꾸준히 나으면 실력 쪽에 가까워요.</p>' +
        '<dl class="kv num"><dt>거래 수</dt><dd>' + n + "번" + (n < 20 ? " (20번 전에는 판단 보류)" : "") + "</dd>" +
        "<dt>예상 적중 (목표가 먼저 닿음)</dt><dd>" + (pf.pred && pf.pred.n ? pf.pred.hit + "/" + pf.pred.n + " (" + pf.pred.rate + "%)" : "아직 없음") + "</dd>" +
        "<dt>평균 이익 ÷ 평균 손실</dt><dd>" + (pf.all && pf.all.pf != null ? fmt(pf.all.pf, 2) + (pf.all.pf >= 1.5 ? " ✓" : "") : "—") + "</dd>" +
        "<dt>거래당 SPY 대비</dt><dd>" + (pf.avg_excess != null ? pct(pf.avg_excess) + "p" : "—") + "</dd></dl></div>" +
        '<h2>처음 20번 vs 최근 20번</h2><div class="card"><div class="tblwrap"><table class="tbl num"><tr><th></th><th>처음</th><th>최근</th></tr>' +
        "<tr><td>거래</td><td>" + (f.n || 0) + "</td><td>" + (l.n || 0) + "</td></tr>" +
        "<tr><td>평균 수익</td><td>" + pct(f.avg) + "</td><td>" + pct(l.avg) + "</td></tr>" +
        "<tr><td>SPY 대비</td><td>" + pct(f.excess) + "</td><td>" + pct(l.excess) + "</td></tr>" +
        "<tr><td>수익 비율</td><td>" + (f.win == null ? "—" : f.win + "%") + "</td><td>" + (l.win == null ? "—" : l.win + "%") + "</td></tr></table></div>" +
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
          : emp("📊", "신호 기록이 쌓이는 중이에요", "아침 후보가 5일·20일 지나면 결과가 채워져요.", "", "")) + "</div>";
    } else if (seg === "fund") {
      body = fundHtml(S.ai && S.ai.fund);
    } else {
      const w = S.weekly;
      body = w && w.lines ? '<div class="card"><div class="small">' + esc(whenText(w.at)) + '</div><pre class="weekly">' + esc(w.lines.join("\n")) + "</pre></div>"
        : emp("📅", "주간 리포트는 일요일에 와요", "한 주의 모의투자·신호 성적을 정리해 드려요.", "#/news", "그동안 경제뉴스 보기");
    }
    appShell("score", '<div class="head"><div><h1>모의투자 · 성적</h1><div class="small">모두 가상 돈 · 실제 주문 없음</div></div></div>' + statusLine() +
      '<div class="segs">' + segBtn("auto", "자동 모의") + segBtn("acct", "내 계좌") + segBtn("skill", "실력·운") + segBtn("sig", "신호") + segBtn("week", "주간") + segBtn("fund", "펀드매니저") + "</div>" +
      body + '<p class="foot">' + esc(DISCLAIMER) + "</p>");
    $app.querySelectorAll(".segs button").forEach(b => b.addEventListener("click", () => { S.scoreSeg = b.dataset.s; viewScore(); }));
    const tc = document.getElementById("tkcopy");
    if (tc) tc.onclick = () => { const t = [...$app.querySelectorAll("ol.plain li")].map((li, i) => (i + 1) + ". " + li.textContent).join("\n");
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(() => toast("주문표를 복사했어요"), () => toast("복사가 안 돼요. 길게 눌러 복사해 주세요")); };
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
  const checkNote = c => !c ? "" : c.ok === null ? '<div class="small warn-t">🔍 ' + esc(c.note || "검사관이 확인하지 못했어요") + "</div>" : (c.ok || !(c.issues || []).length) ? '<div class="small">🔍 검사관: 확인된 수정 사항 없음</div>'
    : '<details class="sig"><summary><span class="small warn-t">🔍 ' + esc(c.note || ("검사관이 " + c.issues.length + "곳을 확인했어요")) + ' ▾</span></summary><ul class="plain small">' +
      c.issues.map(i => "<li>[" + esc(i["종류"] || "숫자") + "] " + esc(i["원래"] || "") + " → <b>" + esc(i["고친 값"] || "삭제(확인 못 함)") + "</b>" + (i["근거"] ? " · " + esc(i["근거"]) : "") + "</li>").join("") + "</ul></details>";
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
      '<div class="card"><b>지표 신호</b><div class="sigrows">' + (x["신호"] || []).map(g =>
        '<div class="sigrow"><div class="row between"><span class="signame">' + esc(g["지표"]) + '</span><span class="badge ' + tone3(g["좋음/나쁨"]) + '">' +
        esc(g["좋음/나쁨"]) + '</span></div><div class="sigval">' + esc(g["값"]) + "</div>" +
        (g["한 줄"] ? '<div class="small">' + esc(g["한 줄"]) + "</div>" : "") + "</div>").join("") + "</div></div>" +
      (x["10년 주인이라면"] ? '<div class="card"><b>10년 가질 주인이라면</b><p class="sub">' + esc(x["10년 주인이라면"]) + "</p></div>" : "") +
      '<div class="small">' + esc(x.date || "") + " · GPT 작성</div>" + checkNote(x["_검사"]);
  }
  function qbars(items, field, big) {
    const vals = items.map(x => x[field]).filter(v => v != null);
    if (vals.length < 2) return "";
    const max = Math.max.apply(null, vals.map(Math.abs)) || 1;
    const money = v => big ? (Math.abs(v) >= 1e12 ? fmt(v / 1e12, 1) + "조" : Math.abs(v) >= 1e8 ? fmt(v / 1e8, 0) + "억" : fmt(v / 1e6, 0) + "백만") : fmt(v, 2);
    return '<div class="qbars">' + items.map(x => {
      const v = x[field], hgt = v == null ? 0 : Math.max(3, Math.abs(v) / max * 100), col = (v || 0) >= 0 ? "var(--up)" : "var(--down)";
      return '<div class="qcol"><div class="qbarwrap"><span class="qbar" style="height:' + hgt + "%;background:" + col + '"></span></div><div class="qval num">' +
        (v == null ? "—" : money(v)) + '</div><div class="small">' + esc((x.q || "").slice(2, 7)) + "</div></div>";
    }).join("") + "</div>";
  }
  function earnHtml(t) {
    const x = S.ai && S.ai.earn && S.ai.earn[t];
    if (!x) return "";
    const v = x["판정"] || {}, qs = x["분기들"] || [];
    const bars = qs.length >= 2
      ? '<div class="card"><div class="row between"><b>분기 매출</b><span class="small">억/조 달러</span></div>' + qbars(qs, "rev", true) + "</div>" +
        '<div class="card"><div class="row between"><b>분기 EPS</b><span class="small">주당순이익 $</span></div>' + qbars(qs, "eps", false) + "</div>"
      : "";
    return '<h2>실적 카드 · ' + esc(x["분기"] || "") + '</h2>' + bars + '<div class="card"><div class="row between"><span class="sub">' + esc(x["발표일"] || "") + "</span><span>" +
      '<span class="badge ' + tone3(v["실적"]) + '">실적 ' + esc(v["실적"] || "") + '</span> <span class="badge ' + tone3(v["가이던스"]) + '">가이던스 ' + esc(v["가이던스"] || "") + "</span></span></div>" +
      '<div class="tblwrap"><table class="tbl num"><tr><th></th><th>실제</th><th>예상</th><th>직전 분기</th><th>작년</th></tr>' + (x["표"] || []).map(r => "<tr><td>" + esc(r["항목"]) + "</td><td>" + esc(r["실제"]) +
        "</td><td>" + esc(r["예상(컨센서스)"]) + "</td><td>" + esc(r["직전 분기"] || "—") + "</td><td>" + esc(r["작년 같은 분기"]) + "</td></tr>").join("") + "</table></div>" +
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
      ((x["가설이 틀렸다고 볼 조건"] || []).length ? '<b>내 투자 가설이 틀렸다고 볼 조건</b><ul class="plain">' + x["가설이 틀렸다고 볼 조건"].map(c => "<li>" + esc(c) + "</li>").join("") + "</ul>" : "") +
      '<div class="msg ' + (v["있음"] ? "err" : "note") + '">AI 거부권(기록만): ' + (v["있음"] ? "막을 이유 있음 — " + esc(v["이유"]) : "막을 이유 없음") + "</div>" + checkNote(x["_검사"]) + "</div>";
  }
  // 차트 분석 (파이썬 계산 · GPT 없음)
  // 토스식 라인 차트 (라이브러리 없이 가벼운 SVG). 상승 빨강/하락 파랑.
  function sparkSvg(vals) {
    if (!vals || vals.length < 2) return '<div class="small" style="padding:28px 0;text-align:center">차트 데이터가 아직 없어요</div>';
    const W = 320, H = 120, pad = 6, n = vals.length;
    const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals), rng = (max - min) || 1;
    const up = vals[n - 1] >= vals[0], col = up ? "var(--up)" : "var(--down)";
    const pts = vals.map((v, i) => (pad + (W - 2 * pad) * i / (n - 1)).toFixed(1) + "," + (pad + (H - 2 * pad) * (1 - (v - min) / rng)).toFixed(1));
    const id = "cg" + Math.random().toString(36).slice(2, 7);
    const area = "M" + pts[0] + " L" + pts.join(" L") + " L" + (W - pad).toFixed(1) + "," + (H - pad) + " L" + pad + "," + (H - pad) + " Z";
    return '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" style="width:100%;height:150px;display:block">' +
      '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + col + '" stop-opacity="0.18"/><stop offset="1" stop-color="' + col + '" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="' + area + '" fill="url(#' + id + ')"/>' +
      '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + col + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>' +
      '<div class="row between small" style="margin-top:4px"><span>저점 $' + fmt(min) + "</span><span>고점 $" + fmt(max) + "</span></div>";
  }
  function infoCard(c) {
    const f = c.info || {};
    const money = v => v == null ? "—" : v >= 1e12 ? "$" + fmt(v / 1e12, 2) + "조" : v >= 1e8 ? "$" + fmt(v / 1e8, 0) + "억" : "$" + fmt(v / 1e6, 0) + "백만";
    let d = f.div; if (d != null) d = d < 1 ? d * 100 : d;
    const rows = [["시가총액", money(f.mktcap)], ["PER", f.per != null ? fmt(f.per, 1) + "배" : "—"],
      ["PBR", f.pbr != null ? fmt(f.pbr, 1) + "배" : "—"], ["배당수익률", d != null ? fmt(d, 2) + "%" : "—"],
      ["52주 최고·최저", (c.hi52 != null ? "$" + fmt(c.hi52) : "—") + " · " + (c.lo52 != null ? "$" + fmt(c.lo52) : "—")],
      ["업종", f.sector || "—"]];
    return '<div class="card"><b>종목 정보</b><dl class="kv">' + rows.map(r => "<dt>" + r[0] + "</dt><dd>" + esc(String(r[1])) + "</dd>").join("") + "</dl></div>";
  }
  // 토스식 시세 요약 — 라이브 시세 meta(당일·52주 범위, 시가·거래량)로 그려요. GPT·재무 계산 없음.
  function rangeBar(lo, cur, hi) {
    if (lo == null || hi == null || cur == null || hi <= lo) return "";
    const p = Math.max(0, Math.min(100, (cur - lo) / (hi - lo) * 100));
    return '<div class="rbar"><span class="rfill" style="width:' + p.toFixed(1) + '%"></span><span class="rdot" style="left:' + p.toFixed(1) + '%"></span></div>';
  }
  function quoteSumCard(t) {
    return '<div class="card qsum" id="qsum-' + esc(t) + '"><div class="small" style="padding:12px 0;text-align:center">시세 불러오는 중…</div></div>';
  }
  function bigVol(v) { return v == null ? "—" : v >= 1e8 ? fmt(v / 1e8, 1) + "억주" : v >= 1e4 ? fmt(v / 1e4, 0) + "만주" : fmt(v, 0) + "주"; }
  function bigMoney(v) { return v == null ? "—" : v >= 1e12 ? "$" + fmt(v / 1e12, 1) + "조" : v >= 1e8 ? "$" + fmt(v / 1e8, 1) + "억" : v >= 1e4 ? "$" + fmt(v / 1e4, 0) + "만" : "$" + fmt(v, 0); }
  async function mountQuoteSum(t) {
    const el = document.getElementById("qsum-" + t); if (!el) return;
    const usd = v => v == null ? "—" : "$" + fmt(v);
    let q = null;
    try { q = await fetchQuote(t, "3mo"); } catch (e) {}
    if (!q || !q.ok) { el.innerHTML = '<div class="small" style="text-align:center;padding:12px 0">시세를 불러오지 못했어요</div>'; return; }
    const cur = q.price, val = (q.vol != null && cur != null) ? q.vol * cur : null;
    const bars = q.bars || [], openPx = q.open != null ? q.open : (bars.length ? bars[bars.length - 1][1] : null);
    let h = '<b>시세 요약</b>';
    if (q.dayLo != null && q.dayHi != null && q.dayHi > q.dayLo)
      h += '<div class="rlab"><span>1일 저 ' + usd(q.dayLo) + '</span><span>고 ' + usd(q.dayHi) + '</span></div>' + rangeBar(q.dayLo, cur, q.dayHi);
    if (q.lo52 != null && q.hi52 != null && q.hi52 > q.lo52)
      h += '<div class="rlab"><span>52주 저 ' + usd(q.lo52) + '</span><span>고 ' + usd(q.hi52) + '</span></div>' + rangeBar(q.lo52, cur, q.hi52);
    h += '<div class="statgrid"><div class="sc"><div class="k">시가</div><div class="v num">' + usd(openPx) + '</div></div>' +
      '<div class="sc"><div class="k">현재가</div><div class="v num">' + usd(cur) + '</div></div>' +
      '<div class="sc"><div class="k">거래량</div><div class="v num">' + bigVol(q.vol) + '</div></div>' +
      '<div class="sc"><div class="k">거래대금</div><div class="v num">' + bigMoney(val) + '</div></div></div>';
    el.innerHTML = h;
  }
  // 종목 정보 — 투자지표·실적·배당·회사정보 (야후 quoteSummary 프록시, 실시간 조회. GPT·재무 계산 없음)
  const SCACHE = {};
  async function fetchStats(t) {
    if (SCACHE[t]) return SCACHE[t];
    const j = await api("stats", { t: t });
    if (j && j.ok) SCACHE[t] = j;
    return j;
  }
  function statsCard(t) {
    return '<div id="stats-' + esc(t) + '"><div class="card sub" style="text-align:center;padding:16px">종목 정보 불러오는 중…</div></div>';
  }
  // 실적(분기 매출 막대 + EPS 실제/예상) — stats 데이터로 렌더. 투자지표 카드와 실적 탭에서 공용.
  function earnBarsHtml(j) {
    if (!j || ((!j.revQ || j.revQ.length < 2) && (!j.epsQ || j.epsQ.length < 2))) return "";
    let h = "";
    if (j.revQ && j.revQ.length >= 2) h += '<div class="row between" style="margin:8px 0 2px"><span class="small">분기 매출</span><span class="small">억/조 달러</span></div>' + statRevBars(j.revQ);
    if (j.epsQ && j.epsQ.length >= 2) {
      h += '<div class="small" style="margin-top:12px">분기 EPS · 실제 vs 예상(컨센서스)</div><div class="tblwrap"><table class="tbl num"><tr><th>분기</th><th>실제</th><th>예상</th><th>차이</th></tr>' +
        j.epsQ.slice().reverse().map(function (x) {
          var diff = (x.act != null && x.est != null) ? x.act - x.est : null;
          var flat = diff != null && Math.abs(diff) < 0.005, dc = diff == null || flat ? "" : diff > 0 ? "good-t" : "bad-t";
          var ds = diff == null ? "—" : flat ? "0.00" : (diff > 0 ? "+" : "") + fmt(diff, 2);
          var lab = String(x.q || "").replace(/(\dQ)(\d{2})(\d{2})/, "$3 $1");
          return "<tr><td>" + esc(lab) + "</td><td>" + (x.act == null ? "—" : "$" + fmt(x.act, 2)) + "</td><td>" + (x.est == null ? "—" : "$" + fmt(x.est, 2)) +
            '</td><td class="' + dc + '">' + ds + "</td></tr>";
        }).join("") + "</table></div>";
    }
    return h;
  }
  // 보유/후보 상세의 '실적' 탭 — AI 실적 카드가 있으면 그것, 없으면 실시간 실적(분기 매출·EPS)로 채워요.
  function earnTabHtml(t) {
    const ai = S.ai && S.ai.earn && S.ai.earn[t];
    if (ai) return earnHtml(t);
    return '<div id="earntab-' + esc(t) + '"><div class="card sub" style="text-align:center;padding:16px">실적 불러오는 중…</div></div>';
  }
  async function mountEarnTab(t) {
    const el = document.getElementById("earntab-" + t); if (!el) return;
    let j = null; try { j = await fetchStats(t); } catch (e) {}
    const bars = j && j.ok ? earnBarsHtml(j) : "";
    if (!bars) { el.innerHTML = '<div class="card sub">이 종목은 분기 실적 자료가 없어요 (ETF·일부 종목). AI 실적 분석은 보유·후보 상위만 매일 아침 생성돼요.</div>'; return; }
    el.innerHTML = '<div class="card"><div class="row between"><b>실적</b><span class="small">실시간 · 야후</span></div>' + bars +
      '<div class="small" style="margin-top:6px">상세 AI 실적 분석(가이던스·마진·현금흐름)은 보유·후보 상위 종목만 매일 아침 생성돼요.</div></div>';
  }
  function statRevBars(items) {
    var vals = items.map(function (x) { return x.rev; }).filter(function (v) { return v != null; });
    if (vals.length < 2) return "";
    var max = Math.max.apply(null, vals.map(Math.abs)) || 1;
    var money = function (v) { return Math.abs(v) >= 1e12 ? fmt(v / 1e12, 1) + "조" : Math.abs(v) >= 1e8 ? fmt(v / 1e8, 0) + "억" : fmt(v / 1e6, 0) + "백만"; };
    return '<div class="qbars">' + items.map(function (x) {
      var v = x.rev, h = v == null ? 0 : Math.max(3, Math.abs(v) / max * 100);
      var lab = String(x.q || "").replace(/(\dQ)(\d{2})(\d{2})/, "$3 $1");
      return '<div class="qcol"><div class="qbarwrap"><span class="qbar" style="height:' + h + '%;background:var(--up)"></span></div><div class="qval num">' +
        (v == null ? "—" : "$" + money(v)) + '</div><div class="small">' + esc(lab) + "</div></div>";
    }).join("") + "</div>";
  }
  async function mountStats(t) {
    var el = document.getElementById("stats-" + t); if (!el) return;
    var j = null; try { j = await fetchStats(t); } catch (e) {}
    if (!j || !j.ok) { el.innerHTML = '<div class="card"><b>종목 정보</b><div class="small" style="padding:8px 0">지표를 불러오지 못했어요. 잠시 후 다시 열어 주세요.</div></div>'; return; }
    var money = function (v) { return v == null ? "—" : v >= 1e12 ? "$" + fmt(v / 1e12, 1) + "조" : v >= 1e8 ? "$" + fmt(v / 1e8, 0) + "억" : v >= 1e4 ? "$" + fmt(v / 1e4, 0) + "만" : "$" + fmt(v, 0); };
    var mult = function (v) { return v == null ? "—" : fmt(v, 1) + "배"; };
    var asPct = function (v) { return v == null ? "—" : fmt(v * 100, 2) + "%"; };
    var grid = [["시가총액", money(j.mktcap)], ["PER", mult(j.per)], ["PBR", mult(j.pbr)],
      ["PSR", mult(j.psr)], ["ROE", asPct(j.roe)], ["배당수익률", j.divYield != null ? asPct(j.divYield) : "—"]];
    var h = '<div class="card"><b>투자지표</b><div class="statgrid g3" style="margin-top:12px">' +
      grid.map(function (g) { return '<div class="sc"><div class="k">' + g[0] + '</div><div class="v num">' + g[1] + "</div></div>"; }).join("") + "</div></div>";
    // 실적 — 분기 매출 막대 + EPS 실제/예상
    var earnH = earnBarsHtml(j);
    if (earnH) h += '<div class="card"><b>실적</b>' + earnH + "</div>";
    // 배당 소식 — 요약 + 월/분기별 지급 이력
    var hist = j.divHist || [];
    if (j.divRate != null || j.divYield != null || j.exDiv || hist.length) {
      h += '<div class="card"><div class="row between"><b>배당 소식</b>' +
        (j.divCount12 ? '<span class="small">최근 12개월</span>' : "") + "</div>";
      if (j.divCount12) {
        var mons = (j.divMonths || []).slice().sort(function (a, b) { return a - b; }).map(function (m) { return m + "월"; }).join(", ");
        h += '<div class="statgrid" style="margin-top:10px">' +
          '<div class="sc"><div class="k">지급 횟수</div><div class="v num">' + j.divCount12 + "번</div>" + (mons ? '<div class="small" style="margin-top:2px">' + esc(mons) + "</div>" : "") + "</div>" +
          '<div class="sc"><div class="k">최근 1년 배당</div><div class="v num">' + (j.divSum12 != null ? "$" + fmt(j.divSum12) : "—") + "</div></div></div>";
      }
      h += '<dl class="kv num" style="margin-top:10px">' +
        (j.divRate != null ? "<dt>1주당 배당금 (연)</dt><dd>$" + fmt(j.divRate) + "</dd>" : "") +
        (j.divYield != null ? "<dt>배당수익률</dt><dd>" + asPct(j.divYield) + "</dd>" : "") +
        (j.exDiv ? "<dt>다음 배당락일</dt><dd>" + esc(j.exDiv) + "</dd>" : "") + "</dl>";
      if (hist.length) {
        h += '<details class="sig"><summary><b>지난 배당 내역</b> <span class="small">' + hist.length + "건</span></summary>" +
          '<div class="tblwrap"><table class="tbl num"><tr><th>지급일(배당락)</th><th>1주당</th></tr>' +
          hist.map(function (x) { return "<tr><td>" + esc(x.date) + "</td><td>$" + fmt(x.amt) + "</td></tr>"; }).join("") + "</table></div></details>";
      }
      h += "</div>";
    }
    // 회사 정보
    if (j.sector || j.desc || j.nextEarnings) {
      h += '<div class="card"><b>회사 정보</b><dl class="kv"><dt>업종</dt><dd>' + esc(j.sector || "—") + (j.industry ? " · " + esc(j.industry) : "") + "</dd>" +
        (j.country ? "<dt>국가</dt><dd>" + esc(j.country) + "</dd>" : "") +
        (j.nextEarnings ? "<dt>실적 발표일</dt><dd>" + esc(j.nextEarnings) + "</dd>" : "") +
        (j.targetPrice != null ? "<dt>애널리스트 목표가</dt><dd class='num'>$" + fmt(j.targetPrice) + "</dd>" : "") + "</dl>" +
        (j.desc ? '<div class="sub" style="margin-top:6px">' + esc(j.desc) + "</div>" : "") + "</div>";
    }
    // 재무제표 보기 (탭하면 로드)
    h += '<div class="card"><button class="btn ghost" data-fin="' + esc(t) + '" style="width:auto;padding:9px 14px;margin:0">📑 재무제표 보기</button><div id="fin-' + esc(t) + '"></div></div>';
    h += '<div class="small" style="margin-top:2px">야후 자료 · 투자지표·실적·배당·재무제표는 실시간 조회 (GPT 아님)</div>';
    el.innerHTML = h;
    var fb = el.querySelector("[data-fin]");
    if (fb) fb.addEventListener("click", function () { fb.style.display = "none"; mountFin(t); });
  }
  function finMoney(v) { return v == null ? "—" : Math.abs(v) >= 1e12 ? fmt(v / 1e12, 2) + "조" : Math.abs(v) >= 1e8 ? fmt(v / 1e8, 0) + "억" : Math.abs(v) >= 1e6 ? fmt(v / 1e6, 0) + "백만" : fmt(v, 0); }
  function finTableHtml(tb) {
    if (!tb || !tb.cols || !tb.cols.length) return '<div class="small" style="padding:8px 0">자료 없음</div>';
    return '<div class="tblwrap"><table class="tbl num"><tr><th></th>' + tb.cols.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") + "</tr>" +
      tb.rows.map(function (r) { return "<tr><td>" + esc(r.label) + "</td>" + r.vals.map(function (v) { return '<td class="' + (v < 0 ? "bad-t" : "") + '">' + finMoney(v) + "</td>"; }).join("") + "</tr>"; }).join("") + "</table></div>";
  }
  async function mountFin(t) {
    var el = document.getElementById("fin-" + t); if (!el) return;
    el.innerHTML = '<div class="small" style="padding:10px 0">재무제표 불러오는 중…</div>';
    var j = null; try { j = await api("fin", { t: t }); } catch (e) {}
    if (!j || !j.ok) { el.innerHTML = '<div class="small" style="padding:10px 0">' + esc((j && j.error) || "재무제표를 못 받았어요") + "</div>"; return; }
    var tabs = [["손익계산서", j.inc], ["재무상태표", j.bal], ["현금흐름표", j.cf]];
    el.innerHTML = '<div class="segs dtabs" style="margin:12px 0 6px">' + tabs.map(function (p, i) { return '<button data-ft="' + i + '"' + (i === 0 ? ' class="on"' : "") + ">" + esc(p[0]) + "</button>"; }).join("") +
      '</div><div class="small" style="margin-bottom:4px">단위: 백만/억/조 달러 · 최근 분기</div><div class="finpanes">' +
      tabs.map(function (p, i) { return '<div class="finpane"' + (i ? " hidden" : "") + ">" + finTableHtml(p[1]) + "</div>"; }).join("") + "</div>";
    el.querySelectorAll(".dtabs button").forEach(function (b) {
      b.addEventListener("click", function () {
        var i = b.dataset.ft;
        el.querySelectorAll(".dtabs button").forEach(function (x) { x.classList.toggle("on", x === b); });
        el.querySelectorAll(".finpane").forEach(function (p, j2) { p.hidden = String(j2) !== i; });
      });
    });
  }
  // ---- 실시간 캔들 차트 (Apps Script 프록시로 야후 시세를 받아 그림) ----
  const QCACHE = {};
  async function fetchQuote(t, range) {
    const k = t + "|" + range;
    if (QCACHE[k]) return QCACHE[k];
    const j = await api("quote", { t: t, range: range });
    if (!j || !j.ok) throw new Error((j && j.error) || "시세 실패");
    QCACHE[k] = j; return j;
  }
  function candleSvg(bars) {
    if (!bars || bars.length < 2) return '<div class="small" style="padding:32px 0;text-align:center">시세를 불러오지 못했어요</div>';
    const W = 320, Hc = 120, Hv = 26, gap = 8, pad = 4, n = bars.length;
    const lo = Math.min.apply(null, bars.map(b => b[3])), hi = Math.max.apply(null, bars.map(b => b[2])), rng = (hi - lo) || 1;
    const vmax = Math.max.apply(null, bars.map(b => b[5] || 0)) || 1;
    const cw = (W - 2 * pad) / n, bw = Math.max(1, Math.min(cw * 0.7, 11));
    const y = v => pad + (Hc - 2 * pad) * (1 - (v - lo) / rng);
    let g = "";
    bars.forEach((b, i) => {
      const o = b[1], h = b[2], l = b[3], c = b[4], vol = b[5] || 0;
      const col = c >= o ? "var(--up)" : "var(--down)", cx = pad + cw * (i + 0.5);
      const top = Math.min(y(o), y(c)), bh = Math.max(1, Math.abs(y(c) - y(o)));
      g += '<line x1="' + cx.toFixed(1) + '" x2="' + cx.toFixed(1) + '" y1="' + y(h).toFixed(1) + '" y2="' + y(l).toFixed(1) + '" stroke="' + col + '" stroke-width="1"/>' +
        '<rect x="' + (cx - bw / 2).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" fill="' + col + '"/>' +
        '<rect x="' + (cx - bw / 2).toFixed(1) + '" y="' + (Hc + gap + (Hv - (vol / vmax) * Hv)).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + ((vol / vmax) * Hv).toFixed(1) + '" fill="' + col + '" opacity="0.32"/>';
    });
    return '<svg viewBox="0 0 ' + W + " " + (Hc + gap + Hv) + '" style="width:100%;height:auto;display:block">' + g + "</svg>" +
      '<div class="row between small" style="margin-top:4px"><span>저 $' + fmt(lo) + "</span><span>고 $" + fmt(hi) + "</span></div>";
  }
  const CRANGE = [["5d", "1일"], ["1mo", "1달"], ["3mo", "3달"], ["1y", "1년"]];
  function liveChartBox(t, c) {
    const tabs = CRANGE.map(p => '<button data-crange="' + p[0] + '"' + (p[0] === "3mo" ? ' class="on"' : "") + ">" + p[1] + "</button>").join("");
    const init = (c && c.series) ? sparkSvg(c.series["3M"]) : '<div class="small" style="padding:32px 0;text-align:center">차트 불러오는 중…</div>';
    return '<div class="card livechart" data-t="' + esc(t) + '"><div class="segs ctabs">' + tabs + '</div><div class="cbox">' + init + "</div></div>";
  }
  function updateLiveHead(t, q) {
    if (!q || q.price == null) return;
    const chg = q.chg;
    document.querySelectorAll('[data-livehead="' + t + '"]').forEach(el => {
      el.innerHTML = "$" + fmt(q.price) + (chg == null ? "" : ' <span class="' + (chg >= 0 ? "good-t" : "bad-t") + '" style="font-size:15px;font-weight:600">' +
        (chg >= 0 ? "▲" : "▼") + " " + fmt(Math.abs(chg), 2) + '%</span><span class="sub" style="font-size:12px;font-weight:400"> 전일대비</span>');
    });
  }
  async function drawRange(box, t, range) {
    const cb = box.querySelector(".cbox");
    try { const q = await fetchQuote(t, range); cb.innerHTML = candleSvg(q.bars); } catch (e) {}
  }
  function mountChartBox(t) {
    document.querySelectorAll('.livechart[data-t="' + t + '"]').forEach(box => {
      if (box.dataset.m) return; box.dataset.m = "1";
      box.querySelectorAll(".ctabs button").forEach(b => b.addEventListener("click", () => {
        box.querySelectorAll(".ctabs button").forEach(x => x.classList.toggle("on", x === b));
        drawRange(box, t, b.dataset.crange);
      }));
      drawRange(box, t, box.querySelector('.ctabs button.on') ? box.querySelector('.ctabs button.on').dataset.crange : "3mo");
    });
  }
  async function liveStock(t) {
    let q = null;
    try { q = await fetchQuote(t, "3mo"); } catch (e) {}
    updateLiveHead(t, q);
    mountChartBox(t);
  }
  function chartHtml(t) {
    const c = S.ai && S.ai.chart && S.ai.chart[t];
    const box = liveChartBox(t, c);
    if (!c) return box;
    const m = c.macd || {}, ma = c.ma || {};
    const tr = c.trend === "상승 추세" ? "good" : c.trend === "하락 추세" ? "bad" : "warn";
    return box + (c.info ? infoCard(c) : "") +
      '<div class="card"><div class="row between"><b>차트 한눈에</b><span class="badge ' + tr + '">' + esc(c.trend) + "</span></div>" +
      '<ul class="plain">' + (c.lines || []).map(l => "<li>" + esc(l) + "</li>").join("") + "</ul>" +
      '<dl class="kv num"><dt>지지선 (아래 받쳐 주는 값)</dt><dd>' + ((c.support || []).map(v => "$" + fmt(v)).join(" · ") || "—") + "</dd>" +
      "<dt>저항선 (위에서 막는 값)</dt><dd>" + ((c.resist || []).map(v => "$" + fmt(v)).join(" · ") || "—") + "</dd>" +
      "<dt>이동평균 20·60·120일</dt><dd>$" + fmt(ma["20"]) + " · $" + fmt(ma["60"]) + " · $" + fmt(ma["120"]) + "</dd>" +
      "<dt>RSI(14)</dt><dd>" + (c.rsi == null ? "—" : fmt(c.rsi, 0)) + "</dd><dt>MACD · 신호선</dt><dd>" + fmt(m.macd, 2) + " · " + fmt(m.signal, 2) + "</dd>" +
      "<dt>거래량 (5일 ÷ 60일)</dt><dd>" + (c.vol_ratio == null ? "—" : fmt(c.vol_ratio, 1) + "배") + "</dd></dl>" +
      '<div class="sub" style="margin-top:6px">📈 오르는 경우: ' + esc(c.up) + '</div><div class="sub">📉 내리는 경우: ' + esc(c.down) + "</div>" +
      '<div class="small">' + esc(c.at) + " 종가 기준 · 1년 일봉으로 직접 계산 (GPT 아님) · 차트는 과거 흐름이라 앞날을 보장하지 않아요</div></div>";
  }
  // 분기 공시 비교 (SEC XBRL 숫자 · 파이썬 계산)
  function secqHtml(t) {
    const q = S.ai && S.ai.secq && S.ai.secq[t];
    if (!q) return '<div class="empty">' + esc((S.ai && S.ai.secq_off) || "이 종목은 SEC 분기 숫자가 없어요 (ETF·외국 회사 등)") + "</div>";
    const big = v => v == null ? "—" : Math.abs(v) >= 1e9 ? fmt(v / 1e9, 2) + "B" : Math.abs(v) >= 1e6 ? fmt(v / 1e6, 1) + "M" : fmt(v, 2);
    return '<div class="card"><div class="small">' + esc(q.quarter) + " · " + esc(q.form || "") + " · 신고일 " + esc(q.filed || "") + "</div>" +
      ((q.changes || []).length ? '<b>직전 분기와 달라진 점</b><ol class="plain" style="padding-left:18px;list-style:decimal">' + q.changes.map(x => "<li>" + esc(x) + "</li>").join("") + "</ol>" : "") +
      '<div class="tblwrap"><table class="tbl num"><tr><th></th><th>이번</th><th>직전</th><th>작년</th></tr>' + (q.rows || []).map(r => "<tr><td>" + esc(r["항목"]) + "</td><td>" + big(r["이번 분기"]) + "</td><td>" + big(r["직전 분기"]) +
        "</td><td>" + big(r["작년 같은 분기"]) + "</td></tr>").join("") + "</table></div>" +
      '<div class="small">'+ (q.via === "yahoo" ? "야후가 10-Q에서 옮긴 분기 재무제표로 비교" : "SEC EDGAR XBRL 숫자를 직접 비교") + ' (GPT 아님) · 고객·공급망·소송 같은 문장 내용은 포함 안 됨 · <a class="link" href="' + esc(q.src) + '" target="_blank" rel="noopener">원문 공시</a></div></div>';
  }
  // 포트폴리오 진단 (숫자는 파이썬, 풀이만 GPT)
  function portHtml() {
    const p = S.ai && S.ai.port;
    if (!p) return "";
    const a = p.ai || {}, pt = p.port || {};
    const secs = Object.entries(p.sectors || {});
    return '<h2>🧺 내 포트폴리오 진단</h2><div class="card">' + (a["한 줄"] ? "<b>" + esc(a["한 줄"]) + "</b>" : "") +
      '<div class="nums3" style="margin-top:6px"><div class="card"><div class="small">출렁임(연 변동성)</div><div class="big num">' + (pt.vol == null ? "—" : fmt(pt.vol, 1) + "%") + '</div><div class="small">SPY ' + (pt.spy_vol == null ? "—" : fmt(pt.spy_vol, 1) + "%") + "</div></div>" +
      '<div class="card"><div class="small">시장 대비 움직임(베타)</div><div class="big num">' + (pt.beta == null ? "—" : fmt(pt.beta, 2)) + '</div><div class="small">1이면 시장만큼</div></div>' +
      '<div class="card"><div class="small">최근 6개월 최대 낙폭</div><div class="big num">' + (pt.mdd_6m == null ? "—" : fmt(pt.mdd_6m, 1) + "%") + "</div></div></div>" +
      '<div class="sub" style="margin-top:8px">업종 비중</div><div class="plbar" style="height:14px">' + secs.map(([k, v], i) => '<span title="' + esc(k) + '" style="width:' + v + '%;background:var(--seg' + (i % 3 + 1) + ')"></span>').join("") + "</div>" +
      '<div class="small">' + secs.map(([k, v]) => esc(k) + " " + fmt(v, 0) + "%").join(" · ") + "</div>" +
      '<div class="sub" style="margin-top:8px">종목 비중</div><div class="small">' + (p.items || []).map(i => esc(i.t) + " " + fmt(i.weight, 0) + "%").join(" · ") + "</div>" +
      '<div class="sub" style="margin-top:8px">⚠️ 눈여겨볼 점</div><ul class="plain">' + (p.flags || []).map(f => "<li>" + esc(f) + "</li>").join("") + "</ul>" +
      ((p.pairs || []).length ? '<div class="small">가장 같이 움직이는 쌍: ' + p.pairs.slice(0, 3).map(x => esc(x.a + "·" + x.b) + " " + fmt(x.corr, 2)).join(" · ") +
        " / 가장 따로 움직이는 쌍: " + (p.low_pairs || []).slice(0, 2).map(x => esc(x.a + "·" + x.b) + " " + fmt(x.corr, 2)).join(" · ") + " (상관 1=똑같이, 0=따로)</div>" : "") +
      ((a["주요 리스크"] || []).length ? '<details class="sig"><summary><b>AI 풀이 · 주요 리스크 3가지 · 검토 포인트</b></summary>' +
        (a["예시"] ? '<div class="ex">💡 ' + esc(a["예시"]) + "</div>" : "") +
        '<ul class="plain">' + a["주요 리스크"].map(r => "<li><b>" + esc(r["이름"]) + "</b> — " + esc(r["설명"]) + (r["숫자"] ? ' <span class="small">(' + esc(r["숫자"]) + ")</span>" : "") + "</li>").join("") + "</ul>" +
        ((a["좋은 점"] || []).length ? '<div class="sub">👍 좋은 점</div><ul class="plain">' + a["좋은 점"].map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
        '<div class="sub">🔎 검토 포인트 (권유 아님)</div><ul class="plain">' + (a["검토 포인트"] || []).map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" + checkNote(a["_검사"]) + "</details>" : "") +
      '<div class="small">' + esc(p.date || "") + " · 숫자는 1년 일봉으로 직접 계산 · 풀이는 GPT(주 1회)</div></div>";
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
          : emp("🌙", "오늘은 장 전 가격이 잡힌 종목이 없어요", "보유·후보·모의 주문 종목만 확인해요.", "#/holdings", "보유 보기")) + "</div>" +
        '<p class="foot">갭 5% 이상·주가 3달러 이상·장 전 거래량 5만 주 이상이면 색으로 표시해요. 추격 금지선 위에서 시작하면 모의매매는 사지 않아요.</p>'
        : emp("⏰", "장 전 점검을 기다리는 중이에요", "미국 장 시작 1시간 전(한국 밤 10시 반쯤)에 채워져요.", "#/news", "경제뉴스 보기")));
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


  /* ---------- 경제뉴스 → 미국주식 트렌드 (초등학생도 5초에) ---------- */
  const DOT = { "초록": "🟢", "노랑": "🟡", "빨강": "🔴" };
  const WEATHER = { "맑음": "☀️", "구름 조금": "🌤️", "흐림": "☁️", "비": "🌧️", "폭풍": "⛈️" };
  const KIND = { "호재": "good", "악재": "bad", "소음": "" };
  // GPT가 없어도 보이는 기본 상식 (숫자 없음 · 투자 권유 아님)
  const SECTOR_BASICS = {
    "기술": { what: "반도체·소프트웨어·컴퓨터 회사예요 (엔비디아·마이크로소프트·애플).", ex: "학교가 컴퓨터실을 새로 지으면 컴퓨터 가게가 바빠져요. AI 붐이 그 컴퓨터실이에요.", sens: "금리·AI 투자 소식",
      good: ["새 기술이 나오면 매출이 빠르게 커져요", "돈을 잘 버는 큰 회사가 많아요"], care: ["기대가 커서 주가가 비싼 편이에요", "금리가 오르면 크게 흔들려요", "수출 규제(중국) 뉴스에 약해요"],
      check: ["매출이 최근 4개 분기 동안 계속 늘었나", "PER이 과거 평균보다 너무 높지 않나"], sell: ["매출 성장이 2분기 연속 꺾임", "큰 고객(빅테크)이 투자를 줄인다고 발표"] },
    "헬스케어": { what: "병원·약·의료기기·건강보험 회사예요.", ex: "감기에 걸리면 경기가 나빠도 약은 사요. 그래서 경기가 나쁠 때 덜 흔들려요.", sens: "약값 정책·신약 결과",
      good: ["사람은 늙고 아프면 꼭 돈을 써요 (수요가 꾸준)", "신약이 성공하면 몇 년 동안 크게 벌어요"], care: ["약값 규제·정부 정책 뉴스 하나에 업종 전체가 흔들려요", "특허가 끝나면 복제약이 나와 매출이 뚝 떨어져요", "작은 바이오 회사는 아직 돈을 못 버는 곳이 많아요"],
      check: ["주요 약의 특허가 언제 끝나나", "현금이 1년 이상 버틸 만큼 있나 (바이오)"], sell: ["핵심 신약 임상 실패", "보험사 의료비가 예상보다 계속 많이 나감"] },
    "금융": { what: "은행·보험·카드·증권 회사예요.", ex: "은행은 2%에 돈을 맡아 5%에 빌려줘요. 그 차이가 은행의 용돈이에요.", sens: "금리 모양·대출 연체",
      good: ["금리가 적당히 높으면 이자로 잘 벌어요", "배당과 자사주 매입을 많이 해요"], care: ["경기가 나빠지면 빌린 돈을 못 갚는 사람이 늘어요", "금리가 갑자기 움직이면 손해가 날 수 있어요"],
      check: ["대출 연체율이 오르고 있나", "PBR(주가 ÷ 회사가 가진 돈)이 1 근처인가"], sell: ["연체·부실 대출이 빠르게 증가", "배당 삭감"] },
    "에너지": { what: "석유·가스를 캐고, 나르고, 정제하는 회사예요.", ex: "기름값이 오르면 주유소 사장님이 웃어요. 에너지 회사가 그 사장님이에요.", sens: "유가",
      good: ["유가가 오르면 이익이 크게 늘어요", "배당을 많이 주는 회사가 많아요"], care: ["유가가 떨어지면 이익도 같이 떨어져요", "친환경 정책이 길게 보면 부담이에요"],
      check: ["국제 유가(WTI)가 한 달 사이 어디로 움직였나", "빚이 줄고 있나"], sell: ["유가가 회사 손익분기점 아래로 오래 머묾", "배당 삭감"] },
    "전기·가스(유틸리티)": { what: "전기·가스·수도를 공급하는 회사예요.", ex: "경기가 나빠도 불은 켜고 살아요. 그래서 불안할 때 사람들이 찾는 업종이에요.", sens: "금리·전기 수요(데이터센터)",
      good: ["수요가 꾸준하고 배당이 안정적이에요", "AI 데이터센터로 전기 수요가 늘고 있어요"], care: ["빚이 많아서 금리가 오르면 불리해요", "요금은 정부 허락을 받아야 올릴 수 있어요"],
      check: ["10년 국채 금리가 오르고 있나", "배당을 몇 년째 늘려 왔나"], sell: ["금리 급등이 계속됨", "요금 인상 거절·큰 재해 비용"] },
    "쓰고 싶은 소비(자동차·쇼핑)": { what: "자동차·쇼핑·여행·외식처럼 '안 써도 되는' 데 쓰는 회사예요 (아마존·테슬라).", ex: "용돈이 넉넉하면 장난감을 사고, 모자라면 안 사요. 경기에 따라 크게 움직여요.", sens: "경기·소비 심리·금리",
      good: ["경기가 좋으면 매출이 빠르게 늘어요"], care: ["경기가 나빠지면 가장 먼저 지갑을 닫는 곳이에요", "관세·물가에 약해요"],
      check: ["같은 매장 매출이 늘고 있나", "재고가 너무 쌓이지 않았나"], sell: ["매출이 2분기 연속 감소", "재고 급증·할인 판매 확대"] },
    "꼭 쓰는 소비(식품·생필품)": { what: "음식·음료·치약·휴지처럼 꼭 사는 물건 회사예요 (코카콜라·P&G).", ex: "용돈이 줄어도 밥은 먹어요. 그래서 불안할 때 피난처가 돼요.", sens: "원가(재료값)·경기 불안",
      good: ["경기가 나빠도 덜 흔들려요", "배당을 오래 늘려 온 회사가 많아요"], care: ["성장이 느려요", "재료값이 오르면 이익이 줄어요"],
      check: ["가격을 올려도 판매량이 유지되나", "영업이익률이 지켜지고 있나"], sell: ["판매량이 계속 줄어듦", "배당 성장 중단"] },
    "산업재": { what: "비행기·기계·철도·건설·방산 회사예요.", ex: "동네에 새 학교를 지으면 굴착기 회사가 바빠져요. 나라가 투자하면 좋아지는 업종이에요.", sens: "경기·정부 투자",
      good: ["정부 인프라·방산 투자가 늘면 주문이 쌓여요"], care: ["경기가 꺾이면 주문이 줄어요", "원자재·인건비가 오르면 이익이 줄어요"],
      check: ["수주 잔고(쌓인 주문)가 늘고 있나", "영업이익률 추이"], sell: ["수주 잔고 감소", "큰 사고·리콜"] },
    "부동산 리츠": { what: "빌딩·창고·데이터센터·아파트를 갖고 임대료를 받는 회사예요.", ex: "건물을 사서 월세를 받는 집주인이에요. 월세 대부분을 배당으로 나눠 줘요.", sens: "금리",
      good: ["임대료가 꾸준해 배당이 커요"], care: ["금리가 오르면 빌린 돈 이자가 늘고 건물 값이 떨어져요", "빈 사무실이 늘면 임대료가 줄어요"],
      check: ["입주율(공실률)", "FFO(리츠의 실제 현금 이익)가 늘고 있나"], sell: ["입주율 급락", "배당 삭감"] },
    "통신·미디어": { what: "통신사·인터넷·게임·영상 회사예요 (구글·메타·넷플릭스).", ex: "모두가 보는 게시판에 광고를 붙이면 돈이 돼요. 광고 회사가 많은 업종이에요.", sens: "광고 경기·규제",
      good: ["사용자가 많아 광고로 크게 벌어요"], care: ["경기가 나쁘면 광고비를 먼저 줄여요", "독점·개인정보 규제 뉴스에 약해요"],
      check: ["광고 매출 성장률", "사용자 수가 늘고 있나"], sell: ["사용자 감소", "큰 규제 판결"] },
    "소재": { what: "화학·철강·금속·광산·포장재 회사예요.", ex: "집을 많이 지으면 시멘트와 철이 많이 팔려요. 원재료 가격에 따라 웃고 울어요.", sens: "원자재 가격·중국 경기",
      good: ["원자재 값이 오르면 이익이 커져요"], care: ["경기에 따라 크게 출렁여요", "중국 수요 뉴스에 약해요"],
      check: ["주요 원자재(구리·철 등) 가격 흐름", "빚 수준"], sell: ["원자재 가격 급락이 이어짐", "배당 삭감"] },
    "모기지 리츠": { what: "집 담보대출(모기지) 채권을 빌린 돈으로 사서, 이자 차이로 버는 회사예요. NLY 같은 곳이에요.", ex: "은행에서 3% 이자로 빌려 5% 이자를 주는 채권을 사면 2%가 남아요. 빌린 이자가 5%로 오르면 남는 게 없어요.", sens: "금리·이자 차이",
      good: ["배당이 큰 편이에요 (번 돈 대부분을 나눠 줘야 하는 구조)", "금리가 내려가고 안정되면 채권 값이 올라 좋아져요"],
      care: ["금리가 갑자기 오르면 빌린 이자는 오르고 채권 값은 떨어져 이중으로 손해예요", "빚(레버리지)을 많이 써서 작은 변화도 크게 커져요", "배당이 커도 이익이 줄면 깎아요. 그날 주가도 크게 떨어져요", "금리가 많이 내려가면 대출을 갈아타서(조기상환) 높은 이자 채권이 사라져요"],
      check: ["주당 장부가치(BV)가 최근 4개 분기 동안 늘었나 줄었나", "주가 ÷ 장부가치(PBR)가 1보다 높나 낮나"], sell: ["배당 삭감 발표", "주당 장부가치가 2분기 연속 감소"] },
    "배당 BDC": { what: "중소기업에 돈을 빌려주고 이자를 받는 회사예요 (ARCC·FSK).", ex: "동네 가게들에 돈을 빌려주고 이자를 받는 저금통이에요. 이자 대부분을 배당으로 줘요.", sens: "금리·중소기업 부도",
      good: ["대출 이자가 변동금리라 금리가 높으면 이자를 많이 받아요", "배당이 커요"], care: ["경기가 나빠져 빌린 회사가 못 갚으면 손실이 나요", "금리가 내려가면 이자 수입이 줄어요"],
      check: ["못 받는 대출 비율(비발생 대출)", "주당 순자산(NAV) 대비 주가"], sell: ["비발생 대출 급증", "배당 삭감·NAV 계속 감소"] },
  };
  // GPT가 숫자 뒤에 붙인 "(자료: …, 날짜: …)" 같은 꼬리표는 화면에서 빼요 (검사는 이미 거쳤어요)
  function cleanSrc(o) {
    if (typeof o === "string") return o.replace(/\s*[(（](자료|출처|근거)\s*[:：][^)）]*[)）]/g, "").trim();
    if (Array.isArray(o)) return o.map(cleanSrc);
    if (o && typeof o === "object") { const r = {}; for (const k in o) r[k] = (k === "출처" || k === "링크") ? o[k] : cleanSrc(o[k]); return r; }
    return o;
  }
  function newsData() {
    const n = S.ai && S.ai.news;
    if (!n) return null;
    if (n._clean) return n;
    const c = Object.assign({}, n, { report: n.report ? cleanSrc(n.report) : null, all: n.all ? cleanSrc(n.all) : null, _clean: true });
    S.ai.news = c; return c;
  }
  function homeNewsCard() {
    const n = newsData(), r = n && n.report, L = (n && n.all && n.all["업종"]) || [];
    if (!n) return '<a class="card newscard" href="#/news"><b>📰 오늘의 경제뉴스</b><div class="small">아침 리포트 때부터 매일 와요 · 업종 13개 신호등 · 미리 보기 →</div></a>';
    const w = (r && r["시장 날씨"]) || {};
    const c = k => L.filter(x => x["신호등"] === k).map(x => x["업종"]);
    return '<a class="card newscard" href="#/news"><div class="row between"><b>📰 오늘의 경제뉴스</b><span class="small">' + esc(whenText(n.at)) + "</span></div>" +
      (r ? '<div class="newsw">' + (WEATHER[w["날씨"]] || "🌤️") + " <b>시장 날씨: " + esc(w["날씨"] || "") + "</b> " + esc(w["한 줄"] || "") + "</div>" +
        '<ul class="plain five">' + (r["5초 요약"] || []).slice(0, 3).map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : '<div class="small">' + esc(n.why || "") + "</div>") +
      (L.length ? '<div class="small" style="margin-top:4px"><b>업종 ' + L.length + "개</b> 🟢" + c("초록").length + " 🟡" + c("노랑").length + " 🔴" + c("빨강").length +
        (c("초록").length ? "<br>🟢 좋은 쪽: " + esc(c("초록").slice(0, 3).join(", ")) : "") + (c("빨강").length ? "<br>🔴 조심: " + esc(c("빨강").slice(0, 3).join(", ")) : "") + "</div>" : "") +
      '<div class="small">업종별·내 종목별 의견 보기 →</div></a>';
  }
  function srcLinks(arr) {
    arr = (arr || []).filter(x => x && x["링크"]);
    return arr.length ? '<div class="small">' + arr.slice(0, 3).map(x => '<a class="link" href="' + esc(x["링크"]) + '" target="_blank" rel="noopener">' + esc((x["제목"] || "출처").slice(0, 40)) + "</a>").join(" · ") + "</div>" : "";
  }
  function sectorCard(t, b, holds) {
    b = b || {};
    const list = (title, arr) => (arr && arr.length ? '<div class="sub" style="margin-top:8px">' + title + '</div><ul class="plain">' + arr.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "");
    const arr = v => (Array.isArray(v) ? v : v ? [v] : null);
    const sc = t["시나리오"] || {}, d = t["토론"] || {};
    return '<div class="card topic">' + (t["5초 답"] ? '<div class="five-a">' + esc(t["5초 답"]) + "</div>" : "") +
      (b.what ? '<div class="small">' + esc(b.what) + (b.sens ? " · 민감한 것: <b>" + esc(b.sens) + "</b>" : "") + "</div>" : "") +
      ((t["예시"] || b.ex) ? '<div class="ex">💡 예시: ' + esc(t["예시"] || b.ex) + "</div>" : "") +
      list("👍 좋은 점", arr(t["좋은 점"]) || b.good) + list("⚠️ 조심할 점", arr(t["조심할 점"]) || b.care) +
      (sc["낙관"] ? '<div class="sub" style="margin-top:8px">🔮 시나리오 3가지</div><dl class="kv"><dt>😀 낙관</dt><dd>' + esc(sc["낙관"]) + "</dd><dt>😐 기준</dt><dd>" + esc(sc["기준"] || "") + "</dd><dt>😟 비관</dt><dd>" + esc(sc["비관"] || "") + "</dd></dl>" : "") +
      (d["강세"] ? '<div class="sub" style="margin-top:8px">🗣️ AI 토론 (강세 vs 약세 → 위험관리 3명)</div><dl class="kv"><dt>🐂 강세</dt><dd>' + esc(d["강세"]) + "</dd><dt>🐻 약세</dt><dd>" + esc(d["약세"] || "") +
        "</dd><dt>🔥 공격형</dt><dd>" + esc(d["공격형"] || "") + "</dd><dt>⚖️ 중립형</dt><dd>" + esc(d["중립형"] || "") + "</dd><dt>🛡️ 보수형</dt><dd>" + esc(d["보수형"] || "") + "</dd><dt>📌 정리</dt><dd>" + esc(d["정리"] || "") + "</dd></dl>" : "") +
      list("✅ 사기 전에 확인할 것", arr(t["확인할 것"]) || b.check) + list("🚪 팔아야 하는 신호", arr(t["팔아야 하는 신호"]) || b.sell) +
      ((holds || []).length ? '<div class="msg note">💼 이 업종의 내 보유: ' + holds.map(h => '<a href="#/hold/' + encodeURIComponent(h) + '">' + esc(h) + "</a>").join(", ") + "</div>" : "") +
      srcLinks(t["출처"]) + "</div>";
  }
  function viewNews() {
    const n = newsData(), r = (n && n.report) || null, al = (n && n.all) || {};
    const seg = S.newsSeg || "sum";
    const segBtn = (k, l) => '<button data-ns="' + k + '"' + (seg === k ? ' class="on"' : "") + ">" + l + "</button>";
    let h = '<div class="head"><div><h1>경제뉴스</h1><div class="small">' + (n ? esc(whenText(n.at)) + " 기준 · " : "") + "쉬운 말 참고 자료 · 투자 권유 아님</div></div></div>" + statusLine() +
      '<div class="segs">' + segBtn("sum", "5초 요약") + segBtn("sec", "업종 13개") + segBtn("mine", "내 종목") + segBtn("more", "매크로·숫자") + "</div>";
    if (!n || (!r && seg === "sum")) {
      h += '<div class="msg note">' + esc(n ? (n.why || "오늘 GPT 요약이 없어요") : "첫 리포트는 다음 아침 리포트 때 만들어져요.") + " '업종 13개'의 기본 상식은 지금도 볼 수 있어요.</div>";
    }
    if (seg === "sum") {
    if (r) {
      const w = r["시장 날씨"] || {};
      h += '<div class="card"><div class="big">' + (WEATHER[w["날씨"]] || "🌤️") + " 시장 날씨: " + esc(w["날씨"] || "") + "</div><div>" + esc(w["한 줄"] || "") + "</div>" +
        (w["예시"] ? '<div class="ex">💡 ' + esc(w["예시"]) + "</div>" : "") + "</div>" +
        '<h2>⏱️ 5초 요약</h2><div class="card"><ul class="plain five">' + (r["5초 요약"] || []).map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" + checkNote(r["_검사"]) + "</div>";
      if ((r["숫자 3개"] || []).length) h += '<h2>🔢 오늘 꼭 볼 숫자 3개</h2><div class="nums3">' + r["숫자 3개"].map(x => '<div class="card"><div class="small">' + esc(x["이름"]) +
        '</div><div class="big num">' + esc(x["값"]) + '</div><div class="small">' + esc(x["쉬운 뜻"]) + "</div></div>").join("") + "</div>";
      if ((r["트렌드"] || []).length) h += "<h2>📈 지금 미국 주식 트렌드</h2>" + r["트렌드"].map((x, i) => '<div class="card"><div class="row between"><b>' + (i + 1) + ". " + esc(x["제목"]) +
        '</b><span class="badge ' + (KIND[x["구분"]] ?? "") + '">' + esc(x["구분"] || "") + "</span></div><div>" + esc(x["한 줄"]) + "</div>" +
        (x["예시"] ? '<div class="ex">💡 예시: ' + esc(x["예시"]) + "</div>" : "") +
        '<div class="small">왜 중요? ' + esc(x["왜 중요"] || "") + (x["관련 업종"] ? " · 관련: " + esc(x["관련 업종"]) : "") + "</div>" + srcLinks(x["출처"]) + "</div>").join("");
      if ((r["내 보유와 닿는 소식"] || []).length) h += "<h2>💼 내 보유와 닿는 소식</h2><div class=\"list\">" + r["내 보유와 닿는 소식"].map(x => '<div class="item" onclick="location.hash=\'#/hold/' +
        encodeURIComponent(x["종목"]) + '\'"><span class="tk">' + esc(x["종목"]) + '</span><span class="grow small">' + esc(x["한 줄"]) + '</span><span class="badge ' + (KIND[x["구분"]] ?? "") + '">' + esc(x["구분"] || "") + "</span></div>").join("") + "</div>";
    }
    } else if (seg === "sec") {
      const L = al["업종"] || [], by = {}; L.forEach(x => { by[x["업종"]] = x; });
      const pin = (n && n.pinned) || [], holdsBy = (n && n.sector_holds) || {}, wk = {};
      ((n && n.sectors) || []).forEach(x => { wk[x["이름"]] = x["1주"]; });
      const order = { "초록": 0, "노랑": 1, "빨강": 2 };
      const names = Object.keys(SECTOR_BASICS).sort((x, y) => {
        const px = pin.indexOf(x), py = pin.indexOf(y);
        if (px !== py) return (px < 0 ? 99 : px) - (py < 0 ? 99 : py);
        return ((order[(by[x] || {})["신호등"]] ?? 3) - (order[(by[y] || {})["신호등"]] ?? 3)) || ((wk[y] ?? -99) - (wk[x] ?? -99));
      });
      const c = k => L.filter(x => x["신호등"] === k).length;
      h += '<div class="card"><div class="row between"><b>미국 업종 ' + names.length + "개</b>" + (L.length ? "<span>🟢" + c("초록") + " 🟡" + c("노랑") + " 🔴" + c("빨강") + "</span>" : '<span class="small">기본 상식</span>') + "</div>" +
        '<div class="small">🟢 뉴스·흐름이 대체로 좋음 · 🟡 섞임 · 🔴 조심할 신호가 더 많음 · 📌 맨 위 고정(내 보유·설정) · 누르면 자세히</div></div>' +
        names.map(nm => { const x = by[nm] || {}, hs = holdsBy[nm] || x["내 보유"] || [];
          return '<details class="sig sector"><summary><span style="font-size:1.25em">' + (DOT[x["신호등"]] || "⚪") + '</span><span class="grow"><b>' + (pin.includes(nm) ? "📌 " : "") + esc(nm) +
            '</b> <span class="small num ' + ((wk[nm] || 0) >= 0 ? "good-t" : "bad-t") + '">' + (wk[nm] != null ? pct(wk[nm]) + " (1주)" : "") + '</span><br><span class="small">' +
            esc(x["5초 답"] || (SECTOR_BASICS[nm] || {}).what || "") + "</span></span>" + (hs.length ? '<span class="badge info">보유 ' + hs.length + "</span>" : "") + "</summary>" +
            sectorCard(x, SECTOR_BASICS[nm], hs) + "</details>"; }).join("");
      const sec = (n && n.sectors) || [];
      if (sec.length) h += '<h2>🗺️ 업종 날씨 (1주)</h2><div class="card"><div class="secs">' + sec.map(x => '<div class="sec ' + ((x["1주"] || 0) >= 0 ? "up" : "dn") + '"><b>' + esc(x["이름"]) +
        '</b><span class="num">' + pct(x["1주"]) + "</span></div>").join("") + "</div></div>";
    } else if (seg === "mine") {
      const M = al["종목"] || [];
      if (M.length) h += '<div class="small" style="margin:6px 0">내 보유 종목 ' + M.length + "개 하나하나 · 누르면 종목 화면</div>" + M.map(x => '<div class="card" onclick="location.hash=\'#/hold/' + encodeURIComponent(x["종목"]) +
        '\'" style="cursor:pointer"><div class="row between"><b>' + (DOT[x["신호등"]] || "⚪") + " " + esc(x["종목"]) + '</b><span class="badge ' + (KIND[x["구분"]] ?? "") + '">' + esc(x["구분"] || "") + "</span></div>" +
        "<div>" + esc(x["한 줄"] || "") + "</div>" + (x["확인할 것"] ? '<div class="small">✅ ' + esc(x["확인할 것"]) + "</div>" : "") +
        ((x["뉴스"] || []).length ? '<div class="newslist" onclick="event.stopPropagation()">' + x["뉴스"].slice(0, 3).map(nw =>
          '<div class="newsitem"><div class="row between"><b class="small">📰 ' + (nw["링크"] ? '<a class="link" href="' + esc(nw["링크"]) + '" target="_blank" rel="noopener">' + esc(nw["제목"] || "") + "</a>" : esc(nw["제목"] || "")) + "</b>" +
          (nw["구분"] ? '<span class="badge ' + (KIND[nw["구분"]] ?? "") + '">' + esc(nw["구분"]) + "</span>" : "") + "</div>" +
          (nw["요약"] ? '<div class="small">' + esc(nw["요약"]) + "</div>" : "") + "</div>").join("") + "</div>"
          : (x["출처"] && x["출처"]["링크"] ? '<a class="small link" href="' + esc(x["출처"]["링크"]) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">' + esc((x["출처"]["제목"] || "출처").slice(0, 50)) + "</a>" : "")) + "</div>").join("");
      else h += emp("📰", "내 종목 의견을 준비하고 있어요", "다음 아침 경제뉴스 리포트부터 종목마다 한 줄 의견이 붙어요.", "#/holdings", "보유 보기");
      if (r && (r["내 보유와 닿는 소식"] || []).length) h += "<h2>💼 오늘 특히 닿는 소식</h2><div class=\"list\">" + r["내 보유와 닿는 소식"].map(x => '<div class="item" onclick="location.hash=\'#/hold/' +
        encodeURIComponent(x["종목"]) + '\'"><span class="tk">' + esc(x["종목"]) + '</span><span class="grow small">' + esc(x["한 줄"]) + '</span><span class="badge ' + (KIND[x["구분"]] ?? "") + '">' + esc(x["구분"] || "") + "</span></div>").join("") + "</div>";
    } else {
      const mc = (r && r["매크로"]) || {}, mt = (n && n.macro) || {};
      if (mc["한 줄"] || Object.keys(mt).length) {
        h += '<h2>🌍 매크로 (금리·물가·고용·환율)</h2><div class="card">' + (mc["한 줄"] ? "<b>" + esc(mc["한 줄"]) + "</b>" : "") +
          (Object.keys(mt).length ? '<dl class="kv num" style="margin-top:6px">' + Object.values(mt).map(x => "<dt>" + esc(x["이름"]) + "</dt><dd>" + fmt(x["값"]) + esc(x["단위"] === "원" ? "원" : x["단위"] === "천 명" ? "천 명" : "%") +
            ' <span class="small">직전 ' + (x["직전"] == null ? "—" : fmt(x["직전"])) + " · " + esc(x["기준일"]) + "</span></dd>").join("") + "</dl>" : "") +
          ((mc["지표 풀이"] || []).length ? '<ul class="plain small">' + mc["지표 풀이"].map(x => "<li><b>" + esc(x["이름"]) + "</b> " + esc(x["값"] || "") + " — " + esc(x["쉬운 뜻"] || "") + "</li>").join("") + "</ul>" : "") +
          (mc["지정학"] ? '<div class="small">🌐 지정학: ' + esc(mc["지정학"]) + "</div>" : "") + "</div>";
        const sc = mc["6개월 시나리오"] || {};
        if (sc["기준"]) h += '<h2>🔮 앞으로 6개월 시나리오</h2>' + [["😀 낙관", "낙관"], ["😐 기준", "기준"], ["😟 비관", "비관"]].map(([l, k]) => { const x = sc[k] || {};
          return '<div class="card"><b>' + l + "</b><div>" + esc(x["조건"] || "") + '</div><div class="small">유리한 업종: ' + esc(x["유리한 업종"] || "—") + "</div></div>"; }).join("");
        h += '<div class="small">지표: 미국 연준 경제자료(FRED) 또는 노동통계국(BLS) · 풀이와 시나리오: GPT (참고용, 권유 아님)' + (Object.keys(mt).length ? "" : " · 오늘은 물가·고용 지표를 못 받아서 시세 표(금리·환율·유가)로만 풀었어요") + "</div>";
      }
      const mk = (n && n.market) || {};
      if (Object.keys(mk).length) h += '<h2>📊 시장 숫자</h2><div class="card"><dl class="kv num">' + Object.values(mk).map(x => "<dt>" + esc(x["이름"]) + "</dt><dd>" + fmt(x["값"]) + (x["단위"] || "") +
        ' <span class="small">1일 ' + (x["변화 단위"] ? fmt(x["1일"]) + "%p" : pct(x["1일"])) + " · 1주 " + (x["변화 단위"] ? fmt(x["1주"]) + "%p" : pct(x["1주"])) + "</span></dd>").join("") + "</dl></div>";
    if (r && (r["오늘의 단어"] || []).length) h += "<h2>📚 오늘의 단어</h2>" + r["오늘의 단어"].map(x => '<div class="card"><b>' + esc(x["말"]) + "</b> = " + esc(x["쉬운 뜻"]) + (x["예시"] ? '<div class="ex">💡 ' + esc(x["예시"]) + "</div>" : "") + "</div>").join("");
      if (r && (r["더 물어보기"] || []).length) h += '<h2>💬 더 물어보기 <span class="small">(누르면 AI에게 바로)</span></h2><div class="chips wrap">' +
        r["더 물어보기"].map(q => '<button class="chip" data-q="' + esc(q) + '">' + esc(q) + "</button>").join("") + "</div>";
      if (n && (n.headlines || []).length) h += '<details class="sig"><summary><b>원문 헤드라인 ' + n.headlines.length + "개</b></summary>" + '<ul class="plain small">' +
        n.headlines.map(x => "<li>" + (x["링크"] ? '<a class="link" href="' + esc(x["링크"]) + '" target="_blank" rel="noopener">' + esc(x["제목"]) + "</a>" : esc(x["제목"])) + ' <span class="small">' + esc(x["출처"] || "") + "</span></li>").join("") + "</ul></details>";
    const hist = (S.ai && S.ai.news_hist) || [];
      if (hist.length > 1) h += '<details class="sig"><summary><b>지난 경제뉴스 ' + (hist.length - 1) + "일</b></summary>" + hist.slice(1).map(x => '<div class="card"><b>' + esc(x.date) + "</b>" +
        '<ul class="plain small">' + (x.summary || []).map(y => "<li>" + esc(y) + "</li>").join("") + "</ul>" + '<div class="small">' + (x.topics || []).map(t => (DOT[t["신호등"]] || "⚪") + " " + esc(t["이름"])).join(" · ") + "</div></div>").join("") + "</details>";
    }
    h += '<p class="foot">맨 위 고정 업종은 구글 시트 \'설정\' 탭 \'뉴스 관심 주제\'에 쉼표로 적으면 바뀌어요 (비우면 내 보유가 많은 업종부터). ' + esc(DISCLAIMER) + "</p>";
    appShell("news", h);
    $app.querySelectorAll("[data-ns]").forEach(b => b.addEventListener("click", () => { S.newsSeg = b.dataset.ns; viewNews(); }));
    $app.querySelectorAll("[data-q]").forEach(b => b.addEventListener("click", () => { S.ask = { mode: "quick", hist: [], draft: b.dataset.q }; go("#/ask"); }));
  }

  // 질문 템플릿 (공유해 준 카드: 경제정리노트 15가지 + 클로드 금융 6가지 · 핵심은 기업명 + 지표 + 기간)
  const ASK_TPL = [
    ["사업 이해", "{T}가 어떤 사업으로 돈을 버는지 사업별 매출 비중과 핵심 수익원을 설명해줘."],
    ["최근 실적", "{T}의 최근 4개 분기 매출·영업이익·순이익과 전년 대비 좋아진 점, 아쉬운 점을 정리해줘."],
    ["재무 위험", "{T}의 재무제표에서 부채·현금흐름·이익의 위험 신호를 체크리스트로 정리해줘."],
    ["경쟁사 비교", "{T}와 같은 업종 경쟁사를 성장률·수익성·밸류에이션 기준으로 비교해줘."],
    ["주가 수준", "{T}의 PER·PBR을 과거 평균·경쟁사와 비교해서 지금 주가 수준을 분석해줘."],
    ["성장 이유", "{T}의 향후 3~5년 성장동력과 그게 실제 실적으로 이어질 조건을 알려줘."],
    ["투자 리스크", "{T}에 투자하지 말아야 할 이유를 실적·경쟁·규제·밸류에이션 관점에서 최대한 강하게 말해줘."],
    ["시나리오", "{T}의 향후 실적을 낙관·기준·비관 3가지 시나리오와 각 조건으로 나눠줘."],
    ["투자 비중", "내 투자금이 [ ]만원이고 {T}에 [ ]만원 넣으려 해. 한 종목 집중 시 위험과 손실 영향을 계산해줘."],
    ["분할매수", "{T}에 총 [ ]만원을 넣는다면 가격·기간 기준 분할매수 계획을 몇 가지로 보여줘."],
    ["실적 발표", "{T}의 최신 실적 발표에서 매출·이익·가이던스가 시장 기대와 달랐던 점을 정리해줘."],
    ["뉴스 영향", "최근 {T} 뉴스가 매출·이익·기업가치에 주는 실제 영향과 단순 소음을 구분해줘."],
    ["투자 논리", "내가 {T}를 산 이유는 [ ]야. 최근 실적과 사업 변화로 그 논리가 유지·강화·훼손됐는지 점검해줘."],
    ["매도 기준", "{T}를 보유 중이야. 투자 논리가 깨졌다고 볼 매도 조건을 실적·사업·재무 기준으로 정리해줘."],
    ["투자 복기", "{T}를 [ ]달러에 사서 [ ]달러에 팔았어. 잘한 점·아쉬운 점·다음 원칙 3가지를 정리해줘."],
    ["분기 흐름", "{T}의 분기별 매출·영업이익률·현금흐름 변화를 최근 8개 분기로 분석해줘."],
    ["업종 비교", "{T}와 같은 업종 회사 5곳의 최근 8개 분기 매출과 EBITDA 마진을 비교해줘."],
    ["적정 가치", "{T}의 DCF 가치평가에 필요한 자료와 가정을 정리해줘."],
    ["성장률 비교", "{T}와 가장 큰 경쟁사의 최근 8개 분기 성장률을 비교해줘."],
    ["종목 찾기", "후보 중에서 PER 15배 미만·잉여현금흐름 플러스·매출 성장률 5% 넘는 종목을 찾아줘."],
    ["모기지 리츠", "{T}의 최근 4개 분기 주당 장부가치·배당·PBR 변화와 금리 영향을 정리해줘."],
    ["차트 분석", "{T}의 최근 주가 추세, 주요 지지선과 저항선, 이동평균선(20·60·120일), 거래량, RSI, MACD를 바탕으로 상승·하락 시나리오와 주요 가격대를 정리해줘."],
    ["재무 건전성", "{T}의 최근 3~5년 매출·영업이익·순이익 성장률, ROE, ROIC, 부채비율, 유동비율, 영업현금흐름, 잉여현금흐름(FCF)으로 재무 건전성을 평가해줘."],
    ["분기 공시 비교", "{T}의 최신 분기 공시(10-Q/10-K)를 직전 분기와 비교해서 매출 구성·부채·재고·매출채권 등 달라진 주요 사항 5가지를 정리해줘."],
    ["포트폴리오", "내 보유 종목의 비중·업종 쏠림·같이 움직이는 정도·변동성을 분석하고 분산 관점에서 검토할 점을 알려줘."],
    ["매크로", "지금 미국 기준금리·물가·고용·GDP·달러와 원달러 환율·국채금리·유가를 바탕으로 앞으로 6개월 낙관·기준·비관 시나리오와 유리한 업종을 정리해줘."],
    ["아침 3분 브리핑", "내 보유 종목의 지난 24시간 주요 뉴스·공시를 매출·이익에 미칠 영향, 중요도(상·중·하), 출처 링크와 함께 정리해줘. 특이사항이 없으면 없다고 해줘."],
  ];

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
      if (a.answer && !a.answer["질문"]) h += '<button class="chip" type="button" data-recheck="1" style="margin-top:6px">🔍 검사관 모드로 다시 보기</button>';
      return h + "</div>";
    };
    appShell("home", '<button class="back" onclick="history.back()">← 뒤로</button><h1>AI에게 묻기</h1>' +
      '<div class="small">내 보유·후보·재무·쌓인 자료(RAG)에서 찾아 출처와 함께 답해요 · 이번 달 GPT $' + fmt(u.total) + " / $" + fmt(u.cap, 0) + "</div>" +
      (u.appKey === false ? '<div class="msg note">이 기능은 로그인 서버(Apps Script)의 스크립트 속성에 OPENAI_API_KEY가 있어야 해요. 설정 탭 안내를 봐 주세요.</div>' : "") +
      '<div class="chips">' + modes.map(m => '<button class="chip' + (A.mode === m[0] ? " on" : "") + '" data-m="' + m[0] + '">' + m[1] + "</button>").join("") + "</div>" +
      '<div class="small" style="margin:6px 0">' + (A.mode === "quick" ? "사소한 질문 없이 바로 답하고, 가정은 맨 위에 적어요." : A.mode === "big" ? "답을 바꾸는 질문만 하나씩, 최대 5개 묻고 답해요." : "리포트·커뮤니티 글을 붙이면 주장마다 맞음·틀림·기준이 다름·확인 못 함으로 가려요.") + "</div>" +
      (A.hist || []).map(h => h.role === "me" ? '<div class="bubble me">' + esc(h.text) + "</div>" : ansHtml(h.a)).join("") +
      (A.mode !== "fact" ? '<details class="sig" id="tpl"><summary><b>📋 질문 템플릿 ' + ASK_TPL.length + '개</b> <span class="small">기업명 + 지표 + 기간을 구체적으로</span></summary>' +
        '<label>종목</label><select id="tplt">' + [...new Set((S.data && S.data.holdings || []).map(h => h.t).concat(allPicks().slice(0, 15).map(p => p.t)))].map(t => "<option>" + esc(t) + "</option>").join("") + "</select>" +
        '<div class="chips wrap" style="margin-top:6px">' + ASK_TPL.map((t, i) => '<button type="button" class="chip" data-tpl="' + i + '">' + esc(t[0]) + "</button>").join("") + "</div></details>" : "") +
      '<form id="af">' + (A.mode === "fact" ? '<label>붙인 글</label><textarea id="ap" rows="6" maxlength="12000" placeholder="여기에 글을 붙여 넣어요">' + esc(A.pasted || "") + "</textarea>" : "") +
      '<label>' + (A.mode === "fact" ? "더 물을 것 (선택)" : "질문") + '</label><textarea id="aq" rows="3" maxlength="4000" placeholder="예: MO 지금 배당은 안전한가?">' + esc(A.draft || "") + '</textarea>' +
      '<button class="btn" type="submit">묻기</button><div class="out"></div></form>' +
      ((A.hist || []).length ? '<button class="btn ghost" id="aclear">새로 묻기</button>' : "") +
      '<p class="foot">AI 답은 참고용이에요. 숫자는 검사관이 한 번 더 확인해요. ' + esc(DISCLAIMER) + "</p>");
    $app.querySelectorAll("[data-m]").forEach(b => b.addEventListener("click", () => { A.mode = b.dataset.m; A.hist = []; viewAsk(); }));
    const cl = document.getElementById("aclear"); if (cl) cl.onclick = () => { A.hist = []; viewAsk(); };
    A.draft = ""; A.pasted = "";
    $app.querySelectorAll("[data-recheck]").forEach(b => b.addEventListener("click", () => {
      const last = [...(A.hist || [])].reverse().find(h => h.role === "ai" && h.a && h.a.answer);
      S.ask = { mode: "fact", hist: [], draft: "방금 분석을 비판적인 검토자 입장에서 재검토해줘. 숫자·인용·증감률 계산·단위·날짜·출처를 확인하고, 오류가 있으면 원래 답변·수정 내용·근거를 제시하고, 수정할 것이 없으면 '확인된 수정 사항 없음'이라고 답해줘.",
        pasted: last ? JSON.stringify(last.a.answer, null, 1).slice(0, 11000) : "" };
      viewAsk();
    }));
    $app.querySelectorAll("[data-tpl]").forEach(b => b.addEventListener("click", () => {
      const t = (document.getElementById("tplt") || {}).value || "[기업명]", q = document.getElementById("aq");
      q.value = ASK_TPL[+b.dataset.tpl][1].replace(/\{T\}/g, t); q.focus(); document.getElementById("tpl").open = false;
    }));
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

  function systemStatusHtml() {
    const d = S.data || {}, k = S.kis, a = S.ai || {}, sim = S.perf && S.perf.sim;
    const row = (name, ok, text) => '<div class="srow"><span class="sname">' + name + '</span><span class="badge wrap ' + (ok === true ? "good" : ok === false ? "bad" : "warn") + '">' + esc(text) + "</span></div>";
    const perm = typeof Notification !== "undefined" ? Notification.permission : "";
    return '<h2>시스템 상태</h2><div class="card">' +
      row("아침 리포트", !!d.run_at, d.run_at ? whenText(d.run_at) : "아직 없음") +
      row("모의투자 (가상 장부)", !!sim, sim ? "진행 중 · " + sim.day + "/" + sim.days + "일째" : "다음 리포트부터") +
      row("GPT", a.off ? false : (a.at ? true : null), a.off ? "꺼짐 · " + a.off : a.at ? "켜짐" : "다음 리포트부터") +
      row("증권사 모의계좌 (선택)", k && k.on && !k.err ? true : null, !k || !k.on ? "안 씀" : k.disabled ? "꺼짐 · 실전 키 감지 (모의투자 영향 없음)" : k.err ? "미연결 · 모의투자엔 영향 없음" : "연결됨") +
      row("이 기기 푸시", perm === "granted" ? true : perm === "denied" ? false : null, perm === "granted" ? "켜짐" : perm === "denied" ? "차단됨" : "꺼짐") +
      "</div>";
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
    appShell("settings", '<button class="back" onclick="history.back()">← 뒤로</button><h1>설정</h1>' +
      themeHtml() + '<a class="btn ghost" href="#/glossary">🏷️ 화면 이름표 (앱 UI 용어 지도)</a>' +
      '<div class="card"><div class="row between"><span>앱 버전</span><span class="sub">' + esc(CFG.VERSION || "") + '</span></div>' +
      '<div class="row between"><span>이 기기</span><span class="sub">' + esc(deviceLabel()) + "</span></div></div>" +
      '<h2>알림</h2><div id="pushBox"><div class="small">확인 중…</div></div>' +
      systemStatusHtml() + aiSettingsHtml() + changesHtml() +
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
    } else if (S.scope === "full" && open.indexOf(route) >= 0) {
      return go("#/home");   // 이미 로그인돼 있으면 로그인 화면 대신 홈으로
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
      case "watch": return viewWatch();
      case "cal": return viewCal();
      case "search": return viewSearch();
      case "stock": return viewStock(decodeURIComponent(arg || ""));
      case "hold": return viewHold(decodeURIComponent(arg || ""));
      case "alerts": if (arg) S.actSeg = arg; return viewAlerts();
      case "score": return viewScore();
      case "gap": return viewGap();
      case "ask": return viewAsk();
      case "news": return viewNews();
      case "glossary": return viewGlossary();
      case "profile": return viewProfile();
      case "settings": return viewSettings();
      case "password": return viewPassword();
      default: return viewHome();
    }
  }

  /* ---------- 업데이트 알림: 새 버전 감지 · 바뀐 것 보여주기 ---------- */
  S.changes = [];
  async function loadChanges() {
    try {
      const r = await fetch("changelog.json?x=" + Date.now(), { cache: "no-store" });
      S.changes = await r.json();
      const latest = (S.changes[0] || {}).v;
      let tried = ""; try { tried = sessionStorage.getItem("reloadTried") || ""; } catch (e) {}
      if (latest && latest !== CFG.VERSION && tried !== latest) {   // 서버에 새 버전 → 화면 틀을 새로 받아요 (한 번만 시도, 무한 새로고침 방지)
        try { sessionStorage.setItem("reloadTried", latest); } catch (e) {}
        try { const ks = await caches.keys(); await Promise.all(ks.map(k => caches.delete(k))); } catch (e) {}
        try { const reg = await navigator.serviceWorker.getRegistration(); if (reg) await reg.update(); } catch (e) {}
        location.reload();
        return;
      }
      render();
    } catch (e) {}
  }
  function seenVersion() { try { return localStorage.getItem("seenVersion") || ""; } catch (e) { return ""; } }
  function whatsNewCard() {
    const c = (S.changes || [])[0];
    if (!c || c.v !== CFG.VERSION || seenVersion() === c.v) return "";
    return '<div class="card newcard"><div class="row between"><b>🆕 업데이트 ' + esc(c.v) + " · " + esc(c.title) + '</b><span class="small">' + esc(c.date) + "</span></div>" +
      '<ul class="plain">' + c.items.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" +
      '<button class="btn ghost" id="seenNew" type="button">확인했어요</button> <a class="small link" href="#/settings">지난 업데이트 보기</a></div>';
  }
  function changesHtml() {
    if (!(S.changes || []).length) return "";
    return '<h2>업데이트 내역</h2>' + S.changes.map(c => '<details class="sig"><summary><b>' + esc(c.v) + " · " + esc(c.title) + '</b><span class="small">' + esc(c.date) + "</span></summary>" +
      '<ul class="plain small">' + c.items.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul></details>").join("");
  }
  document.addEventListener("click", e => {
    if (e.target && e.target.id === "seenNew") { try { localStorage.setItem("seenVersion", CFG.VERSION); } catch (x) {} render(); }
  });

  /* ---------- UI 용어 정리본 반영: 테마·배지·당겨서 새로고침·뒤로 제스처·오프라인 배너·화면 이름표 ---------- */
  function applyTheme() {
    const t = store.get("theme") || "auto";
    if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
  }
  applyTheme();
  function themeHtml() {
    const t = store.get("theme") || "auto";
    return '<h2>화면 모드 (테마 컨트롤러)</h2><div class="chips" id="themeSel">' + [["auto", "자동(폰 설정)"], ["light", "☀️ 밝게"], ["dark", "🌙 어둡게"]].map(([k, l]) =>
      '<button class="chip' + (t === k ? " on" : "") + '" data-theme-set="' + k + '">' + l + "</button>").join("") + "</div>";
  }
  document.addEventListener("click", e => {
    const b = e.target.closest && e.target.closest("[data-theme-set]");
    if (b) { store.set("theme", b.dataset.themeSet); applyTheme(); render(); }
  });
  // 탭 배지(인디케이터): 안 본 새 소식이 있으면 점
  function tabBadges(tab) {
    const newsAt = (S.ai && S.ai.news && S.ai.news.at) || "", sim = S.perf && S.perf.sim;
    const simAt = String((sim && (sim.intra_at || sim.updated)) || "");
    if (tab === "news" && newsAt) store.set("seenNews", newsAt);
    if (tab === "score" && simAt) store.set("seenSim", simAt);
    const mark = (k, on) => { const a = $tabs.querySelector('[data-tab="' + k + '"]'); if (a) a.classList.toggle("has-new", !!on); };
    mark("news", newsAt && store.get("seenNews") !== newsAt);
    mark("score", simAt && store.get("seenSim") !== simAt);
  }
  // 오프라인 배너
  function netBanner() {
    let b = document.getElementById("offline");
    if (!b) { b = document.createElement("div"); b.id = "offline"; b.setAttribute("role", "status"); document.body.appendChild(b); }
    b.textContent = "📡 인터넷이 끊겼어요 · 마지막으로 받은 내용을 보여드려요";
    b.hidden = navigator.onLine;
  }
  window.addEventListener("offline", netBanner);
  window.addEventListener("online", netBanner);
  netBanner();
  // 풀 투 리프레시 + 백 제스처 (홈 화면 앱에는 기본으로 없어서 직접)
  (function gestures() {
    let sx = 0, sy = 0, mode = "", ptr = null;
    const ind = () => { if (!ptr) { ptr = document.createElement("div"); ptr.id = "ptr"; document.body.appendChild(ptr); } return ptr; };
    window.addEventListener("touchstart", e => {
      const t = e.touches[0]; sx = t.clientX; sy = t.clientY; mode = "";
      if (sx < 22 && location.hash && !/^#\/(home)?$/.test(location.hash)) mode = "back";
      else if (window.scrollY <= 0 && S.token) mode = "pull";
    }, { passive: true });
    window.addEventListener("touchmove", e => {
      if (!mode) return;
      const t = e.touches[0], dx = t.clientX - sx, dy = t.clientY - sy;
      if (mode === "pull") {
        if (dy < 0 || Math.abs(dx) > dy) { mode = ""; ind().className = ""; return; }
        const p = ind(); p.className = "show" + (dy > 80 ? " ready" : ""); p.textContent = dy > 80 ? "↻ 놓으면 새로고침" : "↓ 당겨서 새로고침";
        p.style.transform = "translate(-50%," + Math.min(dy, 110) * 0.5 + "px)";
      } else if (mode === "back") {
        if (Math.abs(dy) > 50) mode = "";
        document.body.style.transform = dx > 0 ? "translateX(" + Math.min(dx, 120) * 0.35 + "px)" : "";
      }
    }, { passive: true });
    window.addEventListener("touchend", e => {
      const t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
      document.body.style.transform = "";
      if (mode === "pull" && ptr) {
        ptr.style.transform = "";
        if (dy > 80) { ptr.className = "show ready"; ptr.textContent = "새로 불러오는 중…"; refresh(true).then(() => { ptr.className = ""; toast("새로 불러왔어요"); }); loadChanges(); }
        else ptr.className = "";
      }
      if (mode === "back" && dx > 80 && Math.abs(dy) < 50) history.back();
      mode = "";
    }, { passive: true });
  })();
  // 화면 이름표: 우리 앱 화면을 UI 용어로 (수정 요청할 때 정확한 이름 쓰기)
  const GLOSSARY = [
    ["앱 전체", [["하단 탭바 (Tab Bar)", "홈 · 후보 · 보유 · 뉴스 · 모의투자 (5개)"], ["배지 · 인디케이터 (Badge)", "뉴스·모의투자 탭 위 빨간 점 = 안 본 새 소식"], ["세이프 에어리어 (Safe Area)", "탭바 아래 홈바 여백"], ["토스트 (Toast)", "잠깐 떴다 사라지는 검은 알림"], ["오프라인 배너", "인터넷 끊기면 맨 위 노란 줄"], ["풀 투 리프레시 (Refresher)", "맨 위에서 아래로 당기면 새로고침"], ["백 제스처 (Back Gesture)", "왼쪽 끝에서 오른쪽으로 밀면 뒤로"], ["테마 컨트롤러", "설정 → 화면 모드 (자동·밝게·어둡게)"]]],
    ["홈", [["앱바 (App Bar)", "맨 위 '오늘 · 날짜' 줄과 🔔·⚙️ 아이콘 버튼"], ["업데이트 카드", "새 버전 바뀐 점 (확인했어요 버튼)"], ["카드 · 래디얼 프로그레스", "모의투자 진행 중 카드의 동그란 진행률(○/90일)"], ["스테이터스 (Status)", "초록 깜빡이는 점 = 진행 중"], ["카드", "오늘의 경제뉴스 · 내 자산 · 밤사이 브리핑"], ["칩 (Chip)", "AI에게 묻기 · 장 전 갭 · 성향 인터뷰"], ["리스트 · 아이템 (List · Item)", "내 보유 한 줄 결론, 매수 후보 상위"]]],
    ["후보", [["세그먼트 (Segment)", "가격대 고르기 줄"], ["검색바 (Searchbar)", "종목 찾기 칸"], ["리스트 · 배지", "종목 줄과 점수·태그"], ["종목 상세 → 세그먼트", "재무 5초 · 찬반 근거 · 차트 · 4관점 · 쉬운 리포트"]]],
    ["보유", [["카드 (Stat)", "🧺 내 포트폴리오 진단 숫자 3칸"], ["프로그레스 바", "업종 비중 막대"], ["컬랩스 (Collapse)", "AI 풀이 · 주요 리스크 접기/펴기"], ["종목 상세 → 컬랩스", "차트 분석 · 분기 공시 비교 · 버핏 4관점 · 쉬운 리포트"]]],
    ["뉴스", [["세그먼트", "5초 요약 · 업종 13개 · 내 종목 · 매크로·숫자"], ["컬랩스 (아코디언)", "업종 13개 각 줄 (누르면 펼침)"], ["배지 (신호등)", "🟢🟡🔴 · 호재/악재/소음"], ["칩", "더 물어보기 질문"]]],
    ["모의투자", [["세그먼트", "자동 모의 · 내 계좌 · 실력·운 · 신호 · 주간"], ["프로그레스 바", "3개월 진행 막대, 체결률 막대"], ["버튼 (Secondary)", "주문표 복사"], ["리스트 · 배지", "주문표 채점 (체결·미체결·안 냄)"]]],
    ["입력·띄우는 것", [["텍스트에어리어 (Textarea)", "AI에게 묻기 질문 칸"], ["셀렉트 (Select)", "질문 템플릿 종목 고르기"], ["로딩 (loading)", "제출 버튼이 '처리 중…'으로 잠김"], ["인라인 에러 (Field Error)", "칸 아래 빨간 글씨"], ["엠프티 스테이트 (Empty State)", "내용 없을 때 아이콘 + 제목 + 다음 행동 칩"]]],
  ];
  function viewGlossary() {
    appShell("settings", '<button class="back" onclick="history.back()">← 뒤로</button><h1>🏷️ 화면 이름표</h1>' +
      '<div class="small">고칠 곳을 말할 때 이 이름을 쓰면 빨라요. 예: "뉴스 탭 <b>세그먼트</b>에서 내 종목을 맨 앞으로", "홈 <b>업데이트 카드</b> 글자를 줄여 줘"</div>' +
      GLOSSARY.map(([sec, rows]) => "<h2>" + esc(sec) + '</h2><div class="card"><dl class="kv">' + rows.map(r => "<dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd>").join("") + "</dl></div>").join("") +
      '<p class="foot">용어 출처: 바이브코딩 앱 UI 용어 정리본 · Apple HIG · Material · Ionic · daisyUI</p>');
  }
  window.addEventListener("hashchange", render);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refresh(true); loadChanges(); } });
  window.addEventListener("online", () => refresh(true));
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  loadChanges();
  render();
  refresh(true);
})();
