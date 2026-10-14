"""연결 점검: 물가·고용 지표(FRED→BLS)와 분기 공시 비교(SEC→야후)를 받을 수 있는지 확인 (값은 짧게만 출력)."""
import config
import news
import secq
from sheets import Store

m = news.macro_table()
print("물가·고용:", ("성공 " + ", ".join(f"{v['이름']} {v['값']}{v['단위']}({v['기준일']}, {v['출처']})" for v in list(m.values())[:4])) if m else "실패")
email = str(config.merge_settings(Store().settings())[0].get("SEC 연락 이메일") or "")
r = secq.run(["JNJ"], email).get("JNJ")
print("분기 공시 비교:", f"성공({r.get('via', 'sec')}) JNJ {r['quarter']} · " + " / ".join(r["changes"][:2]) if r else "실패")
