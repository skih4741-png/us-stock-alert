"""연결 점검: FRED(물가·고용 지표)와 SEC(분기 공시) 자료를 받을 수 있는지 확인 (값은 짧게만 출력)."""
import news
import secq
import config
from sheets import Store

m = news.macro_table()
print("FRED:", "성공 " + ", ".join(f"{v['이름']} {v['값']}{v['단위']}({v['기준일']})" for v in list(m.values())[:3]) if m else "실패")
email = str(config.merge_settings(Store().settings())[0].get("SEC 연락 이메일") or "")
if not email:
    print("SEC: 설정에 이메일 없음")
else:
    r = secq.compare("JNJ", email)
    print("SEC:", f"성공 JNJ {r['quarter']} {r['form']} 신고 {r['filed']} · " + " / ".join(r["changes"][:2]) if r else "실패")
