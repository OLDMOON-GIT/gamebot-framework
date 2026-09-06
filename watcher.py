"""퍼플온 로그인 감지 → 게임 자동 진입 감시 데몬 (SPEC-1032722)

흐름:
1) 9333 크롬의 plaync 탭을 NC 로그인 페이지로 이동시켜 둠 (사용자는 ID/PW만 입력)
2) 15초마다 폴링: 로그인 완료(purpleon으로 복귀) 감지
3) webplay/linclassic으로 자동 진입, 스트리밍 시작 여부 스크린샷으로 기록
4) debug/game_*.jpg 저장 + watch.state에 상태 기록
"""
import os
import sys
import time

import requests

sys.path.insert(0, r"C:\Users\moony\linc-bot")
from cdp import find_page_session, screenshot_b64

PORT = 9333
BASE = r"C:\Users\moony\linc-bot"
SIGNIN = ("https://login.plaync.com/nclogin/signin"
          "?return_url=https%3A%2F%2Fpurpleon.plaync.com%2Fwebplay%2Flinclassic")
WEBPLAY = "https://purpleon.plaync.com/webplay/linclassic"
LOG = os.path.join(BASE, "watcher.log")


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def plaync_tab():
    tabs = requests.get(f"http://127.0.0.1:{PORT}/json", timeout=5).json()
    pages = [t for t in tabs if t.get("type") == "page"]
    return next((t for t in pages if "plaync" in t.get("url", "")), None)


def main():
    os.makedirs(os.path.join(BASE, "debug"), exist_ok=True)
    tab = plaync_tab()
    if tab and "login.plaync" not in tab["url"]:
        try:
            s = find_page_session(PORT, "plaync")
            s.call("Page.navigate", {"url": SIGNIN})
            s.close()
            log("로그인 페이지로 이동시킴")
        except Exception as e:
            log(f"초기 이동 실패: {e}")
    open(os.path.join(BASE, "watch.state"), "w", encoding="utf-8").write("waiting-login")

    while True:
        try:
            tab = plaync_tab()
            url = tab["url"] if tab else ""
            if tab and "login.plaync" not in url and "purpleon" in url:
                log(f"로그인 감지: {url[:70]} → 웹플레이 진입")
                s = find_page_session(PORT, "purpleon")
                s.call("Page.navigate", {"url": WEBPLAY})
                time.sleep(25)
                tab = plaync_tab()
                if tab and "webplay" in tab["url"]:
                    open(os.path.join(BASE, "watch.state"), "w",
                         encoding="utf-8").write("entered-webplay")
                    log("웹플레이 진입 성공, 프레임 기록 시작")
                    for i in range(6):
                        try:
                            data = screenshot_b64(s, 80)
                            open(os.path.join(BASE, "debug", f"game_{i}.jpg"),
                                 "wb").write(data)
                            log(f"game_{i}.jpg 저장 ({len(data)//1024}KB)")
                        except Exception as e:
                            log(f"프레임 캡처 실패: {e}")
                            try:
                                s = find_page_session(PORT, "webplay")
                            except Exception:
                                pass
                        time.sleep(15)
                    open(os.path.join(BASE, "watch.state"), "a",
                         encoding="utf-8").write("\nframes-done")
                    break
            time.sleep(15)
        except Exception as e:
            log(f"폴링 오류: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
