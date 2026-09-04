@echo off
rem 리니지 클래식 웹플레이용 크롬 (CDP 디버깅 포트 9333)
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9333 --remote-allow-origins=* --user-data-dir=C:\Users\moony\linc-bot\chrome-profile --no-first-run --start-maximized "https://purpleon.plaync.com/webplay/linclassic"
