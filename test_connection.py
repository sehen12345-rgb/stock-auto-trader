import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from config.settings import KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO, KIS_MOCK
from core.broker.kis import KISBroker

print("=" * 50)
print("KIS API 연결 테스트")
print("=" * 50)
print(f"모드: {'모의투자' if KIS_MOCK else '실전투자'}")
print(f"App Key: {KIS_APP_KEY[:8]}..." if KIS_APP_KEY else "App Key: 미입력")
print(f"계좌번호: {KIS_ACCOUNT_NO[:4]}****" if KIS_ACCOUNT_NO else "계좌번호: 미입력")
print()

if not KIS_APP_KEY or not KIS_APP_SECRET or not KIS_ACCOUNT_NO:
    print("❌ .env 파일에 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO를 입력하세요.")
    sys.exit(1)

broker = KISBroker()

print("1. 토큰 발급 테스트...")
ok = broker.connect()
if not ok:
    print("[FAIL] 연결 실패 - App Key/Secret 확인하세요.")
    sys.exit(1)
print("[OK] 토큰 발급 성공")

print("2. 삼성전자 현재가 조회...")
try:
    price = broker.get_current_price("005930")
    print(f"[OK] 삼성전자(005930) 현재가: {price:,.0f}원")
except Exception as e:
    print(f"[FAIL] 현재가 조회 실패: {e}")

print("3. 계좌 잔고 조회...")
try:
    balance = broker.get_balance()
    print(f"[OK] 현금: {balance.cash:,.0f}원 | 총평가: {balance.total_equity:,.0f}원")
except Exception as e:
    print(f"[FAIL] 잔고 조회 실패: {e}")

print("4. 잔고 원본 응답 확인...")
import requests as req
broker._ensure_token()
acc_no, acc_suffix = broker._split_account()
print(f"    계좌번호: {acc_no}, 상품코드: {acc_suffix}")
resp = req.get(
    f"{broker.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
    params={
        "CANO": acc_no, "ACNT_PRDT_CD": acc_suffix,
        "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
        "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
    },
    headers={
        "authorization": f"Bearer {broker._access_token}",
        "appkey": broker.app_key,
        "appsecret": broker.app_secret,
        "tr_id": "TTTC8434R",
        "Content-Type": "application/json",
    },
    timeout=10
)
print(f"    HTTP 상태: {resp.status_code}")
print(f"    응답 내용: {resp.text[:500]}")

print()
print("=" * 50)
print("테스트 완료")
print("=" * 50)
