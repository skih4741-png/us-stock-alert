"""기본 설정값. 구글 시트 "설정" 탭에 같은 항목 이름으로 값을 적으면 그 값이 우선해요."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

DEFAULTS: dict[str, float | str] = {
    # 리스트
    "가격대 단위(달러)": 10,
    "가격대 개수": 11,            # 0~10 … 90~100, 100 이상
    "보여줄 개수": 3,             # 가격대마다 매수 후보 수 (최대 15)
    "보고 싶은 가격대 최대(달러)": 0,  # 0이면 전체, 50이면 50달러 이하 가격대만
    "예산 목록(달러)": "10,20,30,50,100",
    # 기본 거름망
    "최소 거래대금(달러)": 1_000_000,
    "최소 주가(달러)": 1,
    "최소 상장 기간(일)": 250,
    # 시장 국면
    "상승장 매수 기준": 70,
    "횡보장 매수 기준": 75,
    "하락장 참고 기준": 85,
    "상승장 손익비": 2.0,
    "횡보장 손익비": 2.5,
    "흔들린 날 하락률(%)": -3,
    "공포 지수 기준": 30,
    # 판정
    "점수별 최소 통과 점수": 10,
    "급등 기준(5일 상승률 %)": 25,
    "피해야 할 종목 최대 점수": 35,
    # 타이밍
    "최대 손실(%)": 8,
    "최소 위험폭(%)": 1.5,
    "추격 금지 기준(%)": 2,
    "신호 유효 거래일": 3,
    "실적 발표 보류 거래일": 3,
    # 매도
    "추적 매도 하락률(%)": 8,
    "제자리 판단 거래일": 20,
    "점수 급락 기준": 40,
    # 장중 감시
    "손절선 근접(%)": 5,
    "장중 급락 기준(%)": -7,
    # AI
    "AI 설명 사용": "예",
    "AI 모델": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5"),
}


def now_kst() -> datetime:
    return datetime.now(KST)


def merge_settings(sheet_values: dict[str, str] | None) -> tuple[dict, list[str]]:
    """시트 값으로 기본값을 덮어써요. 잘못된 값은 기본값을 쓰고 경고 목록에 남겨요."""
    cfg = dict(DEFAULTS)
    warnings: list[str] = []
    for key, raw in (sheet_values or {}).items():
        key = str(key).strip()
        if key not in DEFAULTS or raw is None or str(raw).strip() == "":
            continue
        default = DEFAULTS[key]
        if isinstance(default, (int, float)):
            try:
                cfg[key] = float(str(raw).replace(",", "").replace("%", ""))
            except ValueError:
                warnings.append(f"설정 '{key}' 값 '{raw}'을(를) 숫자로 못 읽어 기본값 {default}을(를) 썼어요")
        else:
            cfg[key] = str(raw).strip()
    cfg["보여줄 개수"] = int(max(1, min(15, cfg["보여줄 개수"])))
    return cfg, warnings


def budgets(cfg: dict) -> list[int]:
    out = []
    for part in str(cfg["예산 목록(달러)"]).split(","):
        try:
            out.append(int(float(part)))
        except ValueError:
            pass
    return out or [10, 20, 30, 50, 100]


def price_bands(cfg: dict) -> list[tuple[float, float, str]]:
    step = float(cfg["가격대 단위(달러)"])
    n = int(cfg["가격대 개수"])
    limit = float(cfg["보고 싶은 가격대 최대(달러)"])
    bands = []
    for i in range(n):
        lo = i * step
        if i == n - 1:
            hi, name = float("inf"), f"{lo:g}달러 이상"
        else:
            hi, name = lo + step, f"{lo:g}~{lo + step:g}달러"
        if limit and lo >= limit:
            break
        bands.append((lo, hi, name))
    return bands
