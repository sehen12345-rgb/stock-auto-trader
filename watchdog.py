"""
자동매매 봇 Watchdog.

main.py를 감시하다가 크래시 발생 시 자동 재시작한다.
최대 재시작 횟수 초과 시 텔레그램으로 알림 후 종료.

사용법:
  python watchdog.py
"""
import os
import sys
import time
import subprocess
import httpx
from datetime import datetime
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────────────────────
MAX_RESTARTS      = 10        # 연속 최대 재시작 횟수
RESTART_COOLDOWN  = 30        # 재시작 간격 (초)
CRASH_RESET_SECS  = 300       # 이 시간 이상 정상 실행 시 재시작 카운터 리셋 (5분)
HEALTH_CHECK_URL  = "http://localhost:8000/api/status"
HEALTH_INTERVAL   = 60        # 헬스체크 간격 (초)

BASE_DIR  = Path(__file__).parent
PYTHON    = str(BASE_DIR / "venv" / "Scripts" / "python.exe")
MAIN      = str(BASE_DIR / "main.py")

# ── 텔레그램 직접 전송 ────────────────────────────────────────────────────────

def _tg_send(text: str) -> None:
    """텔레그램 봇으로 메시지 직접 전송 (watchdog용 동기 버전)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / "Userscomstock-auto-trader.env")
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass


def _is_healthy() -> bool:
    """FastAPI 헬스체크."""
    try:
        r = httpx.get(HEALTH_CHECK_URL, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Watchdog {ts}] {msg}", flush=True)


# ── 메인 루프 ──────────────────────────────────────────────────────────────────

def run() -> None:
    restart_count = 0
    proc: subprocess.Popen | None = None

    _log("Watchdog 시작")
    _tg_send("🐕 <b>Watchdog 시작</b>\n자동매매 봇을 감시합니다.")

    while True:
        if restart_count >= MAX_RESTARTS:
            msg = f"❌ <b>Watchdog 중단</b>\n재시작 {MAX_RESTARTS}회 초과 — 수동 점검 필요"
            _log(msg)
            _tg_send(msg)
            sys.exit(1)

        # 봇 프로세스 시작
        start_time = time.monotonic()
        _log(f"봇 시작 (재시작 {restart_count}회)")
        try:
            proc = subprocess.Popen(
                [PYTHON, MAIN],
                cwd=str(BASE_DIR),
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except Exception as e:
            _log(f"프로세스 시작 실패: {e}")
            time.sleep(RESTART_COOLDOWN)
            restart_count += 1
            continue

        # 프로세스 감시
        while True:
            ret = proc.poll()
            if ret is not None:
                # 프로세스 종료됨
                elapsed = time.monotonic() - start_time
                if elapsed >= CRASH_RESET_SECS:
                    restart_count = 0  # 장시간 정상 실행 후 종료 → 카운터 리셋
                restart_count += 1
                msg = (
                    f"⚠️ <b>봇 크래시 감지</b> (종료코드: {ret})\n"
                    f"실행 시간: {int(elapsed)}초\n"
                    f"재시작 시도: {restart_count}/{MAX_RESTARTS}\n"
                    f"{RESTART_COOLDOWN}초 후 재시작..."
                )
                _log(msg.replace("<b>", "").replace("</b>", ""))
                _tg_send(msg)
                time.sleep(RESTART_COOLDOWN)
                break

            time.sleep(HEALTH_INTERVAL)

        if proc and proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    run()
