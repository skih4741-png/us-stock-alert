# 운영 점검과 독립 OOS 전략 검증

## 운영 점검 — 실제 예약 실행 이후 확인

- GitHub Actions `.github/workflows/daily.yml`에서 한국 화~토 오전 7시 예약 실행을 수행합니다. GitHub 실행 지연 가능성은 앱 '운영 점검'에서 별도 표시합니다.
- `main.run_daily`는 보고서 발송 결과, 모의매매 실행 상태, 앱 데이터 저장과 다시 읽은 기준일을 체크합니다.
- 단계별 점검은 Google Sheets '앱 데이터'에 저장되는 `perf.runs`와 `health`에 기록됩니다. 실패한 체크가 있으면 전체 프로세스가 정상 종료돼도 `warn/failed`로 표시합니다.
- PWA: 로그인 → **설정 → 관리자 운영 점검**, 또는 Streamlit 앱의 '운영 점검' 탭.
- 예약 실행 단계 자체가 실패하면(예: pip 설치 오류) workflow가 Slack에 해당 GitHub Actions 실행 URL을 발송하도록 설정했습니다.
- Slack/메일이 요청을 받아들였다는 사실만 점검합니다. 개인 기기에 최종 전달됐는지까지 보장하지 않습니다. 발송 관련 비밀값이 없으면 미전송/미확인으로 기록합니다.
- GitHub Actions `아침 리포트` 첫 예약 실행이 완료된 뒤 단계별 상태를 실제로 확인해야 하며, 코드 테스트 통과만으로 운영 성공을 선언하지 않습니다.

## 상장폐지 종목을 포함한 데이터 파일

실제 과거 상장폐지 데이터는 이 저장소에 포함되지 않습니다. 제공 업체의 정당한 데이터 권한과 시점별 상장 종목 목록 및 OHLCV가 필요합니다.

파일 구조:

```text
historical_data/
  membership.csv                  # ticker,start_date,end_date
  prices/
    SPY.csv                       # Date,Open,High,Low,Close,Volume
    AAPL.csv
    DELISTED_TICKER.csv
```

**입력 데이터 확인(코드는 실제 데이터가 아님):**

```bash
python -m validation.research_pipeline --offline-data-dir historical_data --years 2 --folds 3 --months 12
```

`read_historical_dataset`은 자료 누락·OHLCV 오류를 차단합니다. 하지만 CSV가 역사적으로 완전한지, 액면분할·배당·상장폐지 관련 조정이 적절한지는 자동 인증하지 못합니다.

## 독립 OOS 및 전략 자동 반영 게이트

1. 데이터 제공 업체의 시점별 유니버스와 상장폐지 종목을 검증합니다.
2. 기간을 고정한 독립 OOS 평가 및 SPY 대비 성과를 확인합니다.
3. 최소 **90일**의 실제 포워드 모의매매와 거래 기록을 검증합니다.
4. `validation.policy_publisher`에 독립 검증된 audit/oos/forward JSON을 입력합니다. 모든 조건 충족 전략만 14일 유효한 HMAC 서명 정책을 발행합니다.
5. 관리자가 `--publish`를 명시하면 Google Sheets의 `validated_strategy_policy`로 정책이 저장됩니다. 읽기 검증도 수행합니다.
6. 전략 필터는 기본 OFF입니다. 설정 '검증 전략만 표시=예'일 때만 주식 매수 알림 후보에 정책을 적용합니다. 모의매매는 별도의 `validated_strategy_mode=True`가 필요합니다.

`STRATEGY_POLICY_HMAC_KEY`는 최소 32자 비밀 값으로 GitHub Actions Secrets 등에서 관리해야 합니다. **실제 운영과 발행에서 같은 서명 키를 사용**해야 합니다. 이 키가 없거나 서명이 변조됐거나 기간이 지난 정책은 자동으로 거부합니다.

주의: `audit.json`의 필드와 '외부 검증자' 이름만으로 독립성이 실제 보장되는 것은 아닙니다. 독립된 검증자가 별도로 진위와 데이터 출처를 확인해야 합니다. 이 저장소의 연구용 Yahoo 백테스트는 승인 조건을 충족하지 못했고, **현재 승인된 수익 전략은 0개**입니다.

실계좌 주문 API를 활성화하거나 전략을 실제 계좌에 자동 매수시키는 기능은 추가하지 않았습니다. 유료구독 기능도 범위에서 제외했습니다.
