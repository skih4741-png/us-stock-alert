/**
 * 미국주식 알림 앱 — 로그인 서버 (Google Apps Script 웹 앱)
 *
 * - 계정은 하나뿐이에요(회원가입 없음). 처음 한 번 메일로 받은 설정 코드로 만들어요.
 * - 비밀번호 원문은 어디에도 저장하지 않아요. 소금(salt)을 친 해시만 스크립트 속성에 둬요.
 * - 로그인해야만 구글 시트 '앱 데이터' 탭의 내용을 내줘요.
 *
 * 배포: 구글 시트 → 확장 프로그램 → Apps Script 에 이 파일을 붙여넣고
 *       배포 → 새 배포 → 웹 앱 (실행: 나, 액세스: 모든 사용자).
 */
const OWNER_EMAIL = 'skih4741@naver.com';   // 설정 코드·임시 비밀번호를 받는 메일 (여기만 바꾸면 돼요)
const APP_NAME = '미국주식 알림';
const ITER = 1000;                           // 해시 반복 횟수
const FULL_TTL_KEEP = 30 * 24 * 3600e3;      // 로그인 유지 30일
const FULL_TTL = 12 * 3600e3;                // 유지 안 함 12시간 (앱은 닫으면 지워요)
const RESET_TTL = 15 * 60e3;                 // 임시 비밀번호로 들어온 뒤 새 비밀번호를 정할 시간
const TEMP_TTL = 30 * 60e3;                  // 임시 비밀번호 유효 시간
const SETUP_TTL = 10 * 60e3;                 // 설정 코드 유효 시간
const MAX_FAILS = 5, LOCK_MS = 15 * 60e3;
const MAIL_PER_DAY = 3;

const PROPS = PropertiesService.getScriptProperties();

function doGet() { return out_({ ok: true, app: APP_NAME }); }

function doPost(e) {
  let req;
  try { req = JSON.parse((e && e.postData && e.postData.contents) || '{}'); }
  catch (err) { return out_({ ok: false, error: '요청 형식이 잘못됐어요' }); }
  const fn = ACTIONS[req.action];
  if (!fn) return out_({ ok: false, error: '알 수 없는 요청이에요' });
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(15000);
    return out_(fn(req));
  } catch (err) {
    return out_({ ok: false, error: String(err && err.message || err) });
  } finally {
    try { lock.releaseLock(); } catch (x) {}
  }
}

/* ---------------- 요청 ---------------- */
const ACTIONS = {
  status: function () {
    return { ok: true, hasAccount: !!acct_().hash };
  },

  sendSetupCode: function () {
    const a = acct_();
    if (a.hash) return { ok: false, error: '이미 계정이 있어요. 로그인해 주세요.' };
    if (!mailQuota_(a, 'setup')) return { ok: false, error: '오늘은 코드를 더 보낼 수 없어요. 내일 다시 해 주세요.' };
    const code = digits_(6);
    a.setupHash = sha_(code); a.setupExp = Date.now() + SETUP_TTL; a.setupTries = 0;
    save_(a);
    mail_('계정 설정 코드', '앱에서 계정을 만들려면 아래 코드를 넣어 주세요.\n\n설정 코드: ' + code +
      '\n\n10분 동안만 쓸 수 있어요. 직접 요청하지 않았다면 이 메일은 무시하세요.');
    return { ok: true, message: '설정 코드를 메일로 보냈어요.' };
  },

  createAccount: function (r) {
    const a = acct_();
    if (a.hash) return { ok: false, error: '이미 계정이 있어요.' };
    if (!a.setupHash || Date.now() > a.setupExp) return { ok: false, error: '설정 코드가 없거나 만료됐어요. 다시 받아 주세요.' };
    if ((a.setupTries || 0) >= 5) return { ok: false, error: '코드를 너무 많이 틀렸어요. 새 코드를 받아 주세요.' };
    if (sha_(String(r.code || '').trim()) !== a.setupHash) {
      a.setupTries = (a.setupTries || 0) + 1; save_(a);
      return { ok: false, error: '설정 코드가 맞지 않아요.' };
    }
    const id = String(r.id || '').trim();
    if (!/^[A-Za-z0-9_.-]{4,20}$/.test(id)) return { ok: false, error: '아이디는 영문·숫자 4~20자로 정해 주세요.' };
    const bad = pwProblem_(r.pw, id);
    if (bad) return { ok: false, error: bad };
    a.id = id; a.salt = salt_(); a.hash = hash_(r.pw, a.salt);
    delete a.setupHash; delete a.setupExp; delete a.setupTries;
    a.devices = [String(r.device || '')]; a.logins = [];
    record_(a, r, '계정 만들기');
    save_(a);
    sessionsSet_({});
    mail_('계정이 만들어졌어요', '아이디 ' + id + ' 계정이 만들어졌어요. 직접 만든 것이 아니라면 바로 알려 주세요.');
    return Object.assign({ ok: true }, issue_('full', r));
  },

  login: function (r) {
    const a = acct_();
    if (!a.hash) return { ok: false, error: '아직 계정이 없어요.', setup: true };
    const now = Date.now();
    if (a.lockUntil && now < a.lockUntil) {
      return { ok: false, error: '비밀번호를 여러 번 틀려서 잠겼어요. ' + Math.ceil((a.lockUntil - now) / 60000) + '분 뒤에 다시 해 주세요.' };
    }
    const idOk = String(r.id || '').trim() === a.id;
    const pw = String(r.pw || '');
    const normal = idOk && hash_(pw, a.salt) === a.hash;
    const temp = idOk && !normal && a.tempHash && !a.tempUsed && now < a.tempExp && hash_(pw, a.tempSalt) === a.tempHash;
    if (!normal && !temp) {
      a.fails = (a.fails || 0) + 1;
      let msg = '아이디 또는 비밀번호가 맞지 않아요.';
      if (a.fails >= MAX_FAILS) {
        a.fails = 0; a.lockUntil = now + LOCK_MS;
        msg = '5번 틀려서 15분 동안 잠겼어요.';
        mail_('로그인이 잠겼어요', '비밀번호가 5번 틀려 15분 동안 로그인을 잠갔어요. 본인이 아니라면 비밀번호를 바꿔 주세요.');
      } else {
        msg += ' (남은 기회 ' + (MAX_FAILS - a.fails) + '번)';
      }
      save_(a);
      return { ok: false, error: msg };
    }
    a.fails = 0; a.lockUntil = 0;
    if (temp) {
      a.tempUsed = true;
      record_(a, r, '임시 비밀번호 로그인');
      save_(a);
      return Object.assign({ ok: true, mustChange: true }, issue_('reset', r));
    }
    const dev = String(r.device || '');
    if (dev && (a.devices || []).indexOf(dev) < 0) {
      a.devices = (a.devices || []).concat([dev]).slice(-10);
      mail_('새 기기에서 로그인했어요', '처음 보는 기기에서 로그인했어요.\n기기: ' + String(r.label || '알 수 없음').slice(0, 80) +
        '\n본인이 아니라면 앱 설정에서 비밀번호를 바꾸고 "모든 기기 로그아웃"을 눌러 주세요.');
    }
    record_(a, r, '로그인');
    save_(a);
    return Object.assign({ ok: true }, issue_('full', r));
  },

  forgot: function (r) {
    const same = { ok: true, message: '아이디와 메일이 맞으면 임시 비밀번호를 보냈어요. 메일함(스팸함 포함)을 확인해 주세요.' };
    const a = acct_();
    if (!a.hash) return same;
    const idOk = String(r.id || '').trim() === a.id;
    const mailOk = String(r.email || '').trim().toLowerCase() === OWNER_EMAIL.toLowerCase();
    if (!idOk || !mailOk) return same;
    if (!mailQuota_(a, 'temp')) return { ok: false, error: '오늘은 임시 비밀번호를 더 보낼 수 없어요(하루 3번). 내일 다시 해 주세요.' };
    const tmp = tempPw_();
    a.tempSalt = salt_(); a.tempHash = hash_(tmp, a.tempSalt); a.tempExp = Date.now() + TEMP_TTL; a.tempUsed = false;
    save_(a);
    mail_('임시 비밀번호', '임시 비밀번호: ' + tmp + '\n\n30분 동안 한 번만 쓸 수 있어요. 이걸로 로그인하면 새 비밀번호를 정하는 화면이 나와요.' +
      '\n기존 비밀번호는 새 비밀번호를 정하기 전까지 그대로 쓸 수 있어요.\n직접 요청하지 않았다면 이 메일은 무시하세요.');
    return same;
  },

  setPassword: function (r) {
    const s = session_(r.token);
    if (!s) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    const a = acct_();
    if (s.scope === 'full' && hash_(String(r.currentPw || ''), a.salt) !== a.hash) {
      return { ok: false, error: '지금 비밀번호가 맞지 않아요.' };
    }
    const bad = pwProblem_(r.newPw, a.id);
    if (bad) return { ok: false, error: bad };
    if (hash_(r.newPw, a.salt) === a.hash) return { ok: false, error: '이전 비밀번호와 다르게 정해 주세요.' };
    a.salt = salt_(); a.hash = hash_(r.newPw, a.salt);
    delete a.tempHash; delete a.tempSalt; delete a.tempExp; a.tempUsed = true;
    record_(a, r, '비밀번호 변경');
    save_(a);
    sessionsSet_({});   // 다른 기기는 모두 로그아웃
    mail_('비밀번호가 바뀌었어요', '비밀번호가 바뀌었고 다른 기기는 모두 로그아웃됐어요. 본인이 아니라면 바로 "비밀번호 찾기"로 다시 바꿔 주세요.');
    return Object.assign({ ok: true }, issue_('full', r));
  },

  data: function (r) {
    if (!full_(r.token)) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    const blobs = readBlobs_();
    return { ok: true, daily: parse_(blobs.daily), alerts: parse_(blobs.alerts) || [] };
  },

  history: function (r) {
    if (!full_(r.token)) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    return { ok: true, logins: (acct_().logins || []).slice(0, 10) };
  },

  savePush: function (r) {
    if (!full_(r.token)) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    const sub = r.sub || {};
    if (!sub.endpoint || !/^https:\/\//.test(sub.endpoint) || !sub.keys) return { ok: false, error: '알림 구독 정보가 올바르지 않아요.' };
    const kinds = (r.kinds || ['daily', 'watch', 'weekly']).filter(function (k) { return ['daily', 'watch', 'weekly'].indexOf(k) >= 0; }).join(',');
    const sh = pushSheet_();
    const rows = sh.getDataRange().getValues();
    for (let i = rows.length - 1; i >= 1; i--) {
      if (String(rows[i][3]).indexOf(sub.endpoint) >= 0) sh.deleteRow(i + 1);
    }
    sh.appendRow([new Date().toISOString(), String(r.label || '').slice(0, 60), kinds, JSON.stringify({ endpoint: sub.endpoint, keys: sub.keys })]);
    return { ok: true, kinds: kinds };
  },

  removePush: function (r) {
    if (!full_(r.token)) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    const sh = pushSheet_();
    const rows = sh.getDataRange().getValues();
    let n = 0;
    for (let i = rows.length - 1; i >= 1; i--) {
      if (r.endpoint && String(rows[i][3]).indexOf(String(r.endpoint)) >= 0) { sh.deleteRow(i + 1); n++; }
    }
    return { ok: true, removed: n };
  },

  pushStatus: function (r) {
    if (!full_(r.token)) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    const rows = pushSheet_().getDataRange().getValues().slice(1);
    const mine = rows.filter(function (x) { return r.endpoint && String(x[3]).indexOf(String(r.endpoint)) >= 0; })[0];
    return { ok: true, registered: !!mine, kinds: mine ? String(mine[2]).split(',') : [], devices: rows.length };
  },

  logout: function (r) {
    const all = sessions_();
    delete all[sha_(String(r.token || ''))];
    sessionsSet_(all);
    return { ok: true };
  },

  logoutAll: function (r) {
    if (!full_(r.token)) return { ok: false, auth: true, error: '다시 로그인해 주세요.' };
    sessionsSet_({});
    return { ok: true };
  }
};

/* ---------------- 시트 ---------------- */
function readBlobs_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(PROPS.getProperty('SHEET_ID'));
  const sh = ss.getSheetByName('앱 데이터');
  if (!sh) return {};
  const rows = sh.getDataRange().getValues().slice(1);
  const parts = {};
  rows.forEach(function (row) {
    const k = String(row[0] || ''); if (!k) return;
    (parts[k] = parts[k] || []).push([Number(row[1]) || 0, String(row[2] || '')]);
  });
  const outp = {};
  Object.keys(parts).forEach(function (k) {
    outp[k] = parts[k].sort(function (x, y) { return x[0] - y[0]; }).map(function (x) { return x[1]; }).join('');
  });
  return outp;
}

function pushSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(PROPS.getProperty('SHEET_ID'));
  let sh = ss.getSheetByName('푸시 구독');
  if (!sh) { sh = ss.insertSheet('푸시 구독'); sh.appendRow(['등록 시각', '기기', '종류', '구독']); }
  return sh;
}

/* ---------------- 계정·로그인 표 ---------------- */
function acct_() { return JSON.parse(PROPS.getProperty('ACCOUNT') || '{}'); }
function save_(a) { PROPS.setProperty('ACCOUNT', JSON.stringify(a)); }
function sessions_() { return JSON.parse(PROPS.getProperty('SESSIONS') || '{}'); }
function sessionsSet_(s) {
  const now = Date.now(); const keep = {};
  Object.keys(s).forEach(function (k) { if (s[k].exp > now) keep[k] = s[k]; });
  PROPS.setProperty('SESSIONS', JSON.stringify(keep));
}
function issue_(scope, r) {
  const token = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
  const ttl = scope === 'reset' ? RESET_TTL : (r.keep ? FULL_TTL_KEEP : FULL_TTL);
  const all = sessions_();
  all[sha_(token)] = { scope: scope, exp: Date.now() + ttl, dev: String(r.device || '').slice(0, 64) };
  sessionsSet_(all);
  return { token: token, scope: scope, exp: Date.now() + ttl };
}
function session_(token) {
  if (!token) return null;
  const s = sessions_()[sha_(String(token))];
  return s && s.exp > Date.now() ? s : null;
}
function full_(token) { const s = session_(token); return s && s.scope === 'full'; }
function record_(a, r, what) {
  a.logins = [{ at: new Date().toISOString(), what: what, label: String(r.label || '').slice(0, 80) }].concat(a.logins || []).slice(0, 20);
}

/* ---------------- 비밀번호 ---------------- */
function pwProblem_(pw, id) {
  pw = String(pw || '');
  if (pw.length < 10) return '비밀번호는 10자 이상으로 정해 주세요.';
  if (!/[A-Za-z]/.test(pw) || !/[0-9]/.test(pw)) return '비밀번호에 영문과 숫자를 섞어 주세요.';
  if (id && pw.toLowerCase().indexOf(String(id).toLowerCase()) >= 0) return '비밀번호에 아이디를 넣지 말아 주세요.';
  return '';
}
function hash_(pw, salt) {
  let h = String(pw);
  for (let i = 0; i < ITER; i++) {
    h = Utilities.base64Encode(Utilities.computeHmacSha256Signature(h, salt + ':' + i));
  }
  return h;
}
function sha_(s) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(s), Utilities.Charset.UTF_8)
    .map(function (b) { return ('0' + (b & 255).toString(16)).slice(-2); }).join('');
}
function salt_() { return Utilities.getUuid().replace(/-/g, ''); }
function digits_(n) {
  let s = ''; while (s.length < n) s += sha_(Utilities.getUuid()).replace(/[^0-9]/g, '');
  return s.slice(0, n);
}
function tempPw_() {
  const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, Utilities.getUuid() + Utilities.getUuid());
  let s = '';
  for (let i = 0; i < 12; i++) s += abc.charAt((bytes[i] & 255) % abc.length);
  if (!/[0-9]/.test(s)) s = s.slice(0, 11) + '7';
  if (!/[A-Za-z]/.test(s)) s = 'k' + s.slice(1);
  return s;
}

/* ---------------- 메일 ---------------- */
function mailQuota_(a, kind) {
  const day = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd');
  a.mail = a.mail && a.mail.day === day ? a.mail : { day: day };
  a.mail[kind] = (a.mail[kind] || 0) + 1;
  return a.mail[kind] <= MAIL_PER_DAY;
}
function mail_(subject, body) {
  MailApp.sendEmail({ to: OWNER_EMAIL, subject: '[' + APP_NAME + '] ' + subject, body: body + '\n\n— ' + APP_NAME + ' 앱' });
}

function parse_(s) { try { return s ? JSON.parse(s) : null; } catch (e) { return null; } }
function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

/** 편집기에서 한 번 실행하면 메일·시트 권한을 승인하는 창이 떠요. */
function authorize() {
  readBlobs_();
  MailApp.getRemainingDailyQuota();
}
