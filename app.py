"""F-15 웹페이지 (스트림릿). 구글 시트를 읽기만 해요."""
from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

st.set_page_config(page_title="미국주식 알림", page_icon="📈", layout="centered")

# ---- 접속 제한 (비밀번호 1개) ----
pw = st.secrets.get("APP_PASSWORD", "") if hasattr(st, "secrets") else ""
if pw and not st.session_state.get("ok"):
    entered = st.text_input("비밀번호", type="password")
    if entered == pw:
        st.session_state["ok"] = True
        st.rerun()
    st.stop()

# 스트림릿 비밀 값 → 환경 변수 (sheets.Store가 읽어요)
for k in ("SHEET_ID",):
    if k in st.secrets:
        os.environ[k] = str(st.secrets[k])
if "gcp_service_account" in st.secrets:
    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps(dict(st.secrets["gcp_service_account"]))

from sheets import Store  # noqa: E402
import config  # noqa: E402


@st.cache_data(ttl=600)
def load():
    s = Store()
    return s.read("오늘 리스트"), s.read("신호 기록"), s.read("실행 기록"), s.read("보유 종목"), s.settings()


today, signals, runs, holds, settings = load()
cfg, _ = config.merge_settings(settings)
sheet_url = f"https://docs.google.com/spreadsheets/d/{os.environ.get('SHEET_ID', '')}"

GREEN, RED, GREY = "#1a7f37", "#cf222e", "#8c959f"


def card(color: str, html: str):
    st.markdown(f'<div style="border:1px solid #d0d7de;border-left:5px solid {color};border-radius:8px;padding:8px 12px;margin:6px 0">{html}</div>',
                unsafe_allow_html=True)


date = today["날짜"].iloc[0] if len(today) else "-"
regime = today["시장 국면"].iloc[0] if len(today) else "-"
last_run = runs.iloc[-1] if len(runs) else None
c1, c2 = st.columns([3, 1])
c1.markdown(f"### 오늘 · {date} 장 기준 · **{regime}**")
c2.link_button("설정 열기", sheet_url)
if last_run is not None and last_run.get("성공/실패") == "실패":
    st.error(f"오늘 분석이 실패했어요({last_run.get('막힌 단계')}). 아래는 마지막으로 성공한 결과예요.")

buy = today[today["판정"] == "매수 후보"].copy()
sell = today[today["판정"] == "매도 후보"].copy()
avoid = today[today["판정"] == "피해야 할 종목"].copy()
surge = today[today["판정"] == "급등 · 추격 주의"].copy()
mine = today[today["가격대"] == "내 보유"].copy()
ref = today[today["판정"] == "참고"].copy()

tabs = st.tabs(["오늘", "가격대별", "예산 계산기", "내 보유", "종목 상세", "성적표"])

# 1 오늘
with tabs[0]:
    a, b, c = st.columns(3)
    a.metric("매수 후보", len(buy))
    b.metric("신규 진입", int((buy["어제 대비"] == "신규").sum()) if len(buy) else 0)
    c.metric("내 보유 매도", len(sell))
    st.markdown("#### 내 보유 · 매도 후보")
    if len(sell):
        for _, r in sell.iterrows():
            card(RED, f"<b>{r['종목']}</b> · {r['주가']}달러 · {r['이유']} → <b>{r['표시']}</b>")
    else:
        st.caption("오늘은 없어요.")
    if len(ref):
        st.info("오늘은 매수 쉬는 날이에요. 아래는 85점 이상 참고용이에요.")
        st.dataframe(ref[["종목", "회사명", "주가", "총점", "매수 구간", "손절", "1차 목표"]], hide_index=True)
    st.markdown("#### 가격대별 조건 맞은 종목")
    if len(buy):
        st.bar_chart(buy.groupby("가격대").size(), horizontal=True)

# 2 가격대별
with tabs[1]:
    bands = [n for _, _, n in config.price_bands(cfg)]
    pick = st.radio("가격대", bands, horizontal=True, index=min(1, len(bands) - 1))
    only_new = st.toggle("새로 들어온 종목만")
    sub = buy[buy["가격대"] == pick]
    if only_new:
        sub = sub[sub["어제 대비"] == "신규"]
    st.markdown(f"#### 매수 상위 {len(sub)}")
    for _, r in sub.iterrows():
        extra = f"<br>→ {r['쉬운 설명']}" if r["쉬운 설명"] else ""
        extra += f"<br><span style='color:#9a6700'>주의: {r['주의 한 줄']}</span>" if r["주의 한 줄"] else ""
        extra += f"<br><span style='color:{RED}'>⚠ {r['위험 경고']}</span>" if r["위험 경고"] else ""
        card(GREEN, f"<b>{r['순위']} {r['종목']}</b> · {r['주가']}달러 · <b>{r['총점']}점</b> · {r['표시']}<br>"
                    f"<span style='color:#57606a'>{r['회사명']}</span><br>이유: {r['이유']}<br>"
                    f"매수 구간 <b>{r['매수 구간']}</b> · 손절 <b>{r['손절']}</b> · 1차 목표 <b>{r['1차 목표']}</b> · {r['유효 기한']}까지{extra}")
    with st.expander("피해야 할 종목 3"):
        st.dataframe(avoid[avoid["가격대"] == pick][["종목", "회사명", "주가", "총점", "이유"]], hide_index=True)
    with st.expander("급등 · 추격 주의 3"):
        st.dataframe(surge[surge["가격대"] == pick][["종목", "회사명", "주가", "이유"]], hide_index=True)

# 3 예산 계산기
with tabs[2]:
    budget = st.number_input("예산(달러)", min_value=1, value=30, step=10)
    if len(buy):
        b2 = buy.assign(p=buy["주가"].astype(float), s=buy["총점"].astype(float))
        b2 = b2[b2["p"] <= budget].sort_values("s", ascending=False).head(int(cfg["보여줄 개수"]))
        for _, r in b2.iterrows():
            n = int(budget // r["p"])
            card(GREEN, f"<b>{r['종목']}</b> · {r['p']:.2f}달러 · <b>{n}주</b> · 남는 돈 {budget - n * r['p']:.2f}달러 · {r['총점']}점")
        if b2.empty:
            st.caption("이 예산으로 살 수 있는 매수 후보가 없어요.")

# 4 내 보유
with tabs[3]:
    st.dataframe(mine[["종목", "판정", "주가", "총점", "추세", "가치", "성장", "안전", "이유", "표시"]], hide_index=True)
    st.caption("보유 수량·단가·손절선은 구글 시트 '보유 종목' 탭에서 입력해요.")

# 5 종목 상세
with tabs[4]:
    options = list(buy["종목"]) + [t for t in mine["종목"] if t not in set(buy["종목"])]
    if options:
        t = st.selectbox("종목", options)
        r = today[today["종목"] == t].iloc[0]
        cols = st.columns(4)
        for col, k in zip(cols, ["추세", "가치", "성장", "안전"]):
            col.metric(k, r[k] or "-", help="25점 만점")
        st.write(f"**이유**: {r['이유']}")
        if r["쉬운 설명"]:
            st.write(f"**쉬운 설명**: {r['쉬운 설명']}")
        if r["주의 한 줄"]:
            st.warning(f"주의: {r['주의 한 줄']}")
        if r["위험 경고"]:
            st.error(r["위험 경고"])
        try:
            import altair as alt
            import yfinance as yf

            h = yf.download(t, period="6mo", progress=False, auto_adjust=True)
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.get_level_values(0)
            d = h.reset_index()[["Date", "Close"]].rename(columns={"Date": "날짜", "Close": "종가"})
            line = alt.Chart(d).mark_line().encode(x="날짜:T", y=alt.Y("종가:Q", scale=alt.Scale(zero=False)))
            layers = [line]
            for label, val, color in (("손절", r["손절"], RED), ("1차 목표", r["1차 목표"], GREEN)):
                if val:
                    layers.append(alt.Chart(pd.DataFrame({"y": [float(val)], "l": [label]})).mark_rule(color=color, strokeDash=[4, 3]).encode(y="y:Q"))
            if r["매수 구간"]:
                lo, hi = [float(x) for x in r["매수 구간"].split("~")]
                layers.append(alt.Chart(pd.DataFrame({"a": [lo], "b": [hi]})).mark_rect(opacity=0.15, color="#0969da").encode(y="a:Q", y2="b:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=280), use_container_width=True)
            st.caption("파란 띠 = 매수 구간 · 초록 점선 = 1차 목표 · 빨간 점선 = 손절")
        except Exception as e:
            st.caption(f"차트를 불러오지 못했어요: {e}")

# 6 성적표
with tabs[5]:
    done = signals[signals["5일 뒤 수익률"].astype(str) != ""].copy()
    if done.empty:
        st.caption("신호가 한 달쯤 쌓이면 여기서 성적을 볼 수 있어요. 매주 일요일에 계산해요.")
    else:
        done["r5"] = done["5일 뒤 수익률"].astype(float)
        a, b = st.columns(2)
        a.metric("5일 뒤 수익인 비율", f"{(done['r5'] > 0).mean() * 100:.0f}%")
        b.metric("5일 뒤 평균 수익률", f"{done['r5'].mean():+.1f}%")
        for col in ("순위", "가격대", "시장 국면"):
            st.markdown(f"**{col}별**")
            st.dataframe(done.groupby(col)["r5"].agg(건수="count", 평균="mean").round(2))

st.caption("규칙에 따른 검토 후보이며 투자 판단과 책임은 본인에게 있습니다.")
