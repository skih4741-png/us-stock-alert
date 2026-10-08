"""F-09 알림 발송 (네이버 메일 + 슬랙). 메일·슬랙 문구도 여기서 만들어요."""
from __future__ import annotations

import html
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from terms import DISCLAIMER, REGIME

log = logging.getLogger(__name__)


def md(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(m)}월 {int(d)}일"


# ---------------- 문구 ----------------

def subject(r: dict) -> str:
    d = r["date_label"]
    sell = len(r["sell"])
    if r["market"]["rest_day"]:
        return f"[미국주식] {d} · 오늘은 매수 쉬기 · 내 보유 매도 {sell}"
    return f"[미국주식] {d} · {REGIME[r['market']['regime']]} · 매수 후보 {r['buy_total']} · 내 보유 매도 {sell}"


def summary_line(r: dict) -> str:
    mk = r["market"]
    sell = len(r["sell"])
    if mk["rest_day"]:
        head = f"{mk['reason']} 오늘은 새로 사지 않는 걸 권해요." if mk["reason"] else "오늘은 매수를 쉬어요."
    else:
        head = f"시장은 {REGIME[mk['regime']]}이에요(매수 기준 {mk['threshold']:.0f}점)."
    s2 = f" 내 보유 종목 중 팔기를 검토할 종목이 {sell}개 있어요." if sell else " 내 보유 종목은 오늘 할 일이 없어요."
    s3 = "" if mk["rest_day"] else f" 오늘 새로 들어온 매수 후보는 {r['new_count']}개예요."
    return head + s2 + s3


def pick_lines(p: dict) -> list[str]:
    pl = p["plan"]
    tags = f"  [{' · '.join(p['tags'])}]" if p["tags"] else ""
    lines = [
        f"{p['rank']}  {p['ticker']}  {p['price']:.2f}달러  {p['total']:.0f}점{tags}",
        f"   {p['name'][:40]}",
        f"   이유: {' · '.join(p['reasons'])}",
        f"   매수 구간 {pl['zone_low']:.2f}~{pl['zone_high']:.2f} · 손절 {pl['stop']:.2f} · 1차 목표 {pl['target']:.2f} · {md(pl['valid_until'])}까지",
    ]
    if p.get("desc"):
        lines.append(f"   → {p['desc']}")
    if p.get("caution"):
        lines.append(f"   주의: {p['caution']}")
    if p.get("warn"):
        lines.append(f"   ⚠ {p['warn']}")
    return lines


def sell_line(s: dict) -> str:
    return (f"{s['ticker']} | {s['close']:.2f}달러 | 수익률 {s['gain_pct']:+.1f}% | 손절선까지 {s['to_stop_pct']:.1f}% | "
            f"{s['why']} → {s['action']}")


def text_body(r: dict) -> str:
    out = ["■ 한 줄 요약", summary_line(r), ""]
    if r["warnings"]:
        out += ["■ 알림"] + [f"- {w}" for w in r["warnings"]] + [""]
    if r["sell"]:
        out += ["■ 내 보유 · 매도 후보"] + [sell_line(s) for s in r["sell"]] + [""]
    if not r["market"]["rest_day"]:
        out.append("■ 가격대별 개수 (조건 맞은 종목 → 보내는 상위)")
        for b in r["bands"]:
            out.append(f"{b['name']:<12} {b['count']:>3} → 종목 {len(b['picks'])}" + (f" + ETF {len(b.get('etf_picks', []))}" if b.get("etf_picks") else ""))
        out.append("")
        for b in r["bands"]:
            if not b["picks"] and not b.get("etf_picks"):
                continue
            out.append(f"■ {b['name']} · 개별 종목 상위 {len(b['picks'])}")
            for p in b["picks"]:
                out += pick_lines(p)
            if b.get("etf_picks"):
                out.append(f"  ▷ ETF·펀드 상위 {len(b['etf_picks'])}")
                for p in b["etf_picks"]:
                    out += pick_lines(p)
            if b["dropped"]:
                out.append("어제에서 빠짐: " + ", ".join(b["dropped"]))
            out.append("")
    if r.get("web_url"):
        out.append(f"피해야 할 종목·전체 상세 → {r['web_url']}")
    out.append(DISCLAIMER)
    return "\n".join(out)


def html_body(r: dict) -> str:
    e = html.escape
    green, red, grey = "#1a7f37", "#cf222e", "#8c959f"

    def bar(color, inner):
        return (f'<div style="border-left:4px solid {color};padding:8px 12px;margin:6px 0;'
                f'border:1px solid #d0d7de;border-left-width:4px;border-left-color:{color};border-radius:6px">{inner}</div>')

    h = [f'<div style="font-family:-apple-system,Segoe UI,Malgun Gothic,sans-serif;max-width:640px;font-size:14px;line-height:1.5;color:#1f2328">']
    h.append(f'<p style="font-size:16px;font-weight:600">{e(summary_line(r))}</p>')
    for w in r["warnings"]:
        h.append(bar("#bf8700", e(w)))
    h.append('<h3 style="margin:18px 0 6px">내 보유 · 매도 후보</h3>')
    if r["sell"]:
        for s in r["sell"]:
            h.append(bar(red, f"<b>{e(s['ticker'])}</b> · {s['close']:.2f}달러 · 수익률 {s['gain_pct']:+.1f}% · 손절선까지 {s['to_stop_pct']:.1f}%<br>"
                              f"{e(s['why'])} → <b>{e(s['action'])}</b>"))
    else:
        h.append(f'<p style="color:{grey}">오늘은 없어요.</p>')
    if not r["market"]["rest_day"]:
        h.append('<h3 style="margin:18px 0 6px">가격대별 개수</h3><table style="border-collapse:collapse">')
        for b in r["bands"]:
            h.append(f'<tr><td style="padding:2px 12px 2px 0">{e(b["name"])}</td><td style="text-align:right">조건 맞음 {b["count"]}</td>'
                     f'<td style="padding-left:12px">→ 종목 {len(b["picks"])} · ETF {len(b.get("etf_picks", []))}</td></tr>')
        h.append("</table>")
        for b in r["bands"]:
            if not b["picks"] and not b.get("etf_picks"):
                continue
            h.append(f'<h3 style="margin:18px 0 6px">{e(b["name"])} · 개별 종목 {len(b["picks"])} · ETF {len(b.get("etf_picks", []))}</h3>')
            for p in b["picks"] + b.get("etf_picks", []):
                pl = p["plan"]
                tags = " ".join(f'<span style="background:#ddf4ff;border-radius:10px;padding:0 6px;font-size:12px">{e(t)}</span>' for t in p["tags"])
                inner = (f"<b>{p['rank']} {e(p['ticker'])}</b> {pl and ''}{p['price']:.2f}달러 · <b>{p['total']:.0f}점</b> {tags}<br>"
                         f"<span style='color:#57606a'>{e(p['name'][:50])}</span><br>"
                         f"이유: {e(' · '.join(p['reasons']))}<br>"
                         f"매수 구간 <b>{pl['zone_low']:.2f}~{pl['zone_high']:.2f}</b> · 손절 <b>{pl['stop']:.2f}</b> · 1차 목표 <b>{pl['target']:.2f}</b> · {md(pl['valid_until'])}까지")
                if p.get("desc"):
                    inner += f"<br>→ {e(p['desc'])}"
                if p.get("caution"):
                    inner += f"<br><span style='color:#9a6700'>주의: {e(p['caution'])}</span>"
                if p.get("warn"):
                    inner += f"<br><span style='color:{red}'>⚠ {e(p['warn'])}</span>"
                h.append(bar(green, inner))
            if b["dropped"]:
                h.append(f'<p style="color:{grey};font-size:13px">어제에서 빠짐: {e(", ".join(b["dropped"]))}</p>')
    if r.get("web_url"):
        h.append(f'<p><a href="{e(r["web_url"])}">피해야 할 종목·전체 상세 보기</a></p>')
    h.append(f'<p style="color:{grey};font-size:12px">{e(DISCLAIMER)}</p></div>')
    return "".join(h)


def slack_blocks(r: dict) -> list[dict]:
    def sec(text):
        return {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}

    blocks = [{"type": "header", "text": {"type": "plain_text", "text": subject(r).replace("[미국주식] ", "")[:150]}},
              sec(summary_line(r))]
    for w in r["warnings"]:
        blocks.append(sec(f":warning: {w}"))
    if r["sell"]:
        blocks.append(sec("*:red_circle: 내 보유 · 매도 후보*\n" + "\n".join(f"• {sell_line(s)}" for s in r["sell"])))
    if not r["market"]["rest_day"]:
        blocks.append(sec("*가격대별 개수*\n" + "\n".join(f"{b['name']}: {b['count']} → 종목 {len(b['picks'])} · ETF {len(b.get('etf_picks', []))}" for b in r["bands"])))
        for b in r["bands"]:
            if not b["picks"] and not b.get("etf_picks"):
                continue
            lines = [f"*:large_green_circle: {b['name']} · 개별 종목 {len(b['picks'])} · ETF {len(b.get('etf_picks', []))}*"]
            for p in b["picks"] + b.get("etf_picks", []):
                if p is (b.get("etf_picks") or [None])[0]:
                    lines.append("_ETF·펀드_")
                pl = p["plan"]
                tags = f" `{' · '.join(p['tags'])}`" if p["tags"] else ""
                lines.append(f"{p['rank']}. *{p['ticker']}* {p['price']:.2f} · {p['total']:.0f}점{tags}\n"
                             f"   구간 {pl['zone_low']:.2f}~{pl['zone_high']:.2f} · 손절 {pl['stop']:.2f} · 목표 {pl['target']:.2f}"
                             + (f"\n   주의: {p['caution']}" if p.get("caution") else ""))
            blocks.append(sec("\n".join(lines)))
    if len(blocks) > 48:
        blocks = blocks[:47] + [sec("…나머지는 메일과 웹에서 확인하세요")]
    foot = DISCLAIMER + (f" · <{r['web_url']}|웹에서 전체 보기>" if r.get("web_url") else "")
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": foot}]})
    return blocks


# ---------------- 발송 ----------------

def send_mail(subj: str, text: str, html_text: str | None = None) -> bool:
    if os.environ.get("MAIL_ENABLED", "0") != "1":
        return False  # 지금은 슬랙으로만 받아요 (메일을 켜려면 MAIL_ENABLED=1)
    user = os.environ.get("NAVER_ID")
    pw = os.environ.get("NAVER_APP_PASSWORD")
    to = os.environ.get("MAIL_TO") or user
    if not (user and pw):
        log.info("메일 설정 없음 → 메일은 건너뜀")
        return False
    if "@" not in user:
        user = f"{user}@naver.com"
    domain = user.split("@")[1].lower()
    host = os.environ.get("SMTP_HOST") or {"gmail.com": "smtp.gmail.com", "daum.net": "smtp.daum.net"}.get(domain, "smtp.naver.com")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subj, user, to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    if html_text:
        msg.attach(MIMEText(html_text, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(host, 465, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
        return True
    except Exception as e:
        log.error("메일 실패: %s", e)
        return False


def send_slack(text: str, blocks: list[dict] | None = None) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        log.info("슬랙 설정 없음 → 슬랙은 건너뜀")
        return False
    try:
        r = requests.post(url, json={"text": text[:3000], **({"blocks": blocks} if blocks else {})}, timeout=30)
        if r.status_code != 200:
            log.error("슬랙 실패 %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        log.error("슬랙 실패: %s", e)
        return False


def send_report(r: dict) -> dict:
    subj = subject(r)
    text = text_body(r)
    ok_mail = send_mail(subj, text, html_body(r))
    ok_slack = send_slack(subj, slack_blocks(r))
    # 한쪽만 실패하면 다른 쪽에 알려요
    if ok_mail and not ok_slack and os.environ.get("SLACK_WEBHOOK_URL") and os.environ.get("MAIL_ENABLED", "0") == "1":
        send_mail("[미국주식] 슬랙 발송 실패", "오늘 리포트를 슬랙으로 보내지 못했어요. 메일 내용을 확인하세요.")
    if ok_slack and not ok_mail and os.environ.get("MAIL_ENABLED", "0") == "1":
        send_slack(":warning: 오늘 리포트를 메일로 보내지 못했어요. 네이버 앱 비밀번호를 확인하세요.")
    return {"mail": ok_mail, "slack": ok_slack, "subject": subj, "text": text}


def send_text(title: str, text: str) -> None:
    """주간 요약·과거 검증처럼 긴 글: 슬랙(코드 블록) + 메일(켜져 있을 때)."""
    send_slack(title, [{"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
                       {"type": "section", "text": {"type": "mrkdwn", "text": "```" + text[:2800] + "```"}}])
    send_mail(f"[미국주식] {title}", text)
