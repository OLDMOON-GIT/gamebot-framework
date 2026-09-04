"""리니지 클래식 PURPLE On 웹플레이 자동사냥 봇 (SPEC-1032722)

사용법:
  python bot.py            자동사냥 시작
  python bot.py --probe    프레임/HUD/몹 탐지만 확인 (입력 없음)
  python bot.py --shot     스크린샷 1장 저장 후 종료 (캘리브레이션용)
"""
import json
import logging
import os
import random
import sys
import time

import cv2

from cdp import CDPClient, Input, find_page_ws, press, screenshot_b64
from vision import HUD, decode_jpeg, find_mobs

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(os.path.join(BASE, "bot.log"), encoding="utf-8")])
log = logging.getLogger("linc-bot")


def jitter(a, b):
    return a + random.random() * (b - a)


class Bot:
    def __init__(self, probe=False, url=None):
        self.probe = probe
        ws = find_page_ws(CFG["debug_port"], url or CFG["page_url"])
        self.cdp = CDPClient(ws)
        self.cdp.call("Page.enable")
        self.inp = Input(self.cdp)
        self.hud = HUD(CFG)
        r = self.cdp.call("Runtime.evaluate", {
            "expression": "JSON.stringify([innerWidth, innerHeight])",
            "returnByValue": True})
        self.vw, self.vh = json.loads(r["result"]["value"])
        log.info(f"CSS 뷰포트: {self.vw}x{self.vh}")
        self.last_potion = 0.0
        self.last_mob_seen = time.time()
        self.last_combat = 0.0
        self.last_debug = 0.0
        os.makedirs(os.path.join(BASE, CFG["debug_dir"]), exist_ok=True)

    def to_css(self, ix, iy, img_w, img_h):
        """스크린샷(물리 픽셀) 좌표 → CSS 좌표."""
        return int(ix * self.vw / img_w), int(iy * self.vh / img_h)

    def act_potion(self, hp):
        now = time.time()
        if now - self.last_potion < CFG["potion_cooldown"]:
            return False
        if 0 <= hp < CFG["hp_emergency_threshold"]:
            if not self.probe:
                press(self.inp, CFG["hp_emergency_key"])
            self.last_potion = now
            log.warning(f"HP 위험({hp:.0%}) → {CFG['hp_emergency_key']}")
            return True
        if 0 <= hp < CFG["hp_potion_threshold"]:
            if not self.probe:
                press(self.inp, CFG["hp_potion_key"])
            self.last_potion = now
            log.info(f"HP {hp:.0%} → 포션 {CFG['hp_potion_key']}")
            return True
        return False

    def act_combat(self, mobs, w, h):
        if not mobs:
            return False
        cx, cy = w // 2, h // 2
        mx, my, area = min(mobs, key=lambda m: (m[0] - cx) ** 2 + (m[1] - cy) ** 2)
        tx, ty = self.to_css(mx + random.randint(-4, 4),
                             my + CFG["mob_click_offset_y"] + random.randint(-3, 3),
                             w, h)
        log.info(f"몹 클릭 ({tx},{ty}) area={area}")
        if not self.probe:
            self.inp.click(tx, ty)
        self.last_mob_seen = time.time()
        self.last_combat = time.time()
        return True

    def act_loot(self):
        if not CFG["loot_after_kill"]:
            return
        log.info(f"전투 종료 → 루팅 {CFG['loot_key']}")
        if not self.probe:
            press(self.inp, CFG["loot_key"])

    def act_wander(self, w, h):
        import math
        ang = random.uniform(0, 2 * math.pi)
        rad = random.uniform(0.15, 0.3) * min(w, h)
        tx = int(w / 2 + rad * math.cos(ang))
        ty = int(h / 2 + rad * math.sin(ang))
        tx = max(int(w * 0.05), min(int(w * 0.95), tx))
        ty = max(int(h * 0.15), min(int(h * 0.92), ty))
        tx, ty = self.to_css(tx, ty, w, h)
        log.info(f"배회 클릭 ({tx},{ty})")
        if not self.probe:
            self.inp.click(tx, ty)

    def debug_shot(self, img, mobs, ratios):
        dbg = img.copy()
        if self.hud.hp_rect:
            x, y, w, h = self.hud.hp_rect
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 0, 255), 1)
        if self.hud.mp_rect:
            x, y, w, h = self.hud.mp_rect
            cv2.rectangle(dbg, (x, y), (x + w, y + h), (255, 0, 0), 1)
        for mx, my, a in mobs:
            cv2.circle(dbg, (mx, my), 8, (0, 255, 255), 2)
        cv2.putText(dbg, f"HP={ratios['hp']:.2f} MP={ratios['mp']:.2f} mobs={len(mobs)}",
                    (10, dbg.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0), 2)
        p = os.path.join(BASE, CFG["debug_dir"], f"dbg_{int(time.time())}.jpg")
        cv2.imwrite(p, dbg)

    def step(self):
        raw = screenshot_b64(self.cdp, CFG["screenshot_quality"])
        img = decode_jpeg(raw)
        h, w = img.shape[:2]
        ratios = self.hud.ratios(img)
        mobs = find_mobs(img)

        if time.time() - self.last_debug > 15:
            self.debug_shot(img, mobs, ratios)
            self.last_debug = time.time()

        self.act_potion(ratios["hp"])
        in_combat = self.act_combat(mobs, w, h)

        if not in_combat:
            if self.last_combat and time.time() - self.last_combat < 3:
                self.act_loot()
                self.last_combat = 0
            elif time.time() - self.last_mob_seen > CFG["wander_after_idle_sec"]:
                self.act_wander(w, h)
                self.last_mob_seen = time.time()

        log.info(f"HP={ratios['hp']:.0%} MP={ratios['mp']:.0%} 몹={len(mobs)}")

    def run(self, once=False):
        log.info(f"봇 시작 (probe={self.probe})")
        while True:
            try:
                self.step()
            except Exception as e:
                log.error(f"스텝 오류: {e}")
            if once:
                break
            time.sleep(jitter(*CFG["loop_interval"]))


def main():
    probe = "--probe" in sys.argv
    shot = "--shot" in sys.argv
    url = None
    for a in sys.argv[1:]:
        if a.startswith("--url="):
            url = a.split("=", 1)[1]
    bot = Bot(probe=probe or shot, url=url)
    if shot:
        raw = screenshot_b64(bot.cdp, 90)
        p = os.path.join(BASE, CFG["debug_dir"], f"shot_{int(time.time())}.jpg")
        open(p, "wb").write(raw)
        img = decode_jpeg(raw)
        ratios = bot.hud.ratios(img)
        mobs = find_mobs(img)
        bot.debug_shot(img, mobs, ratios)
        print(f"저장: {p}  HP={ratios['hp']:.2f} MP={ratios['mp']:.2f} 몹={len(mobs)}")
        return
    bot.run()


if __name__ == "__main__":
    main()
