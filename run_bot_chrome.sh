#!/bin/bash
while true; do
  DISPLAY=:0 /home/oldmoon/.cache/ms-playwright/chromium-1234/chrome-linux/chrome \
    --remote-debugging-port=9333 --remote-allow-origins='*' \
    --user-data-dir=/home/oldmoon/.purpleon-profile \
    --disable-backgrounding-occluded-windows \
    --disable-features=CalculateNativeWinOcclusion \
    --use-gl=swiftshader --use-angle=swiftshader \
    --force-device-scale-factor=1 --no-sandbox \
    --no-first-run --no-default-browser-check --password-store=basic \
    --window-size=1933,1332 --window-position=0,0 \
    'https://purpleon.plaync.com/webplay/linclassic' >> /home/oldmoon/workspace/linc-bot/botchrome.log 2>&1
  sleep 4
done
