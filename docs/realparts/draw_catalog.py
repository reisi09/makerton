#!/usr/bin/env python3
"""부품 도감: 모든 실물 부품을 같은 배율(실제 크기 비율)로 한 장에 그린다.

    python3 docs/realparts/draw_catalog.py   → docs/img/real_parts_catalog.svg
"""
import os
import sys
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from realparts import base, car, common  # noqa: E402
from realparts.core import place, size_px, svg_doc, text_px  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "img", "real_parts_catalog.svg")
W, H = 1800, 1010
SCALE = 3.2  # px/mm, 모든 부품 공통(크기 비교가 실제와 같다)

# (부품, 이름, 키트 번호, 실제 크기, 쓰는 곳)
ITEMS = [
    (common.pico2wh(), "라즈베리파이 피코 2 WH", "#1 ×2", "51×21 mm", "차·기지"),
    (car.uln2003_board(), "ULN2003 드라이버", "#11 ×2", "35×32 mm", "차 바퀴"),
    (car.motor_28byj48(), "28BYJ-48 스텝모터", "#11 ×2", "Ø28×19 mm", "차 바퀴"),
    (common.sg90(), "SG-90 서보", "#12 ×2", "23×12×29 mm", "살포통·보충 게이트"),
    (car.hcsr04(), "SR-04 초음파", "#2", "45×20 mm", "차 앞면"),
    (common.rgb_led_module(), "3색 LED 모듈", "#10 ×2", "약 19×15 mm", "상태·경고"),
    (common.buzzer_module(), "능동 부저 모듈", "#13 ×2", "약 19×15 mm", "알림"),
    (common.tact_switch(), "택트 스위치", "#16 ×2", "6×6 mm", "비상 정지·도킹"),
    (base.dht11_module(), "DHT11 온습도", "#5 ×4", "약 28×12 mm", "갈래 기둥"),
    (base.water_level_sensor(), "수위감지 센서", "#18", "62×20 mm", "W 젖음"),
    (base.light_sensor_ky018(), "조도센서 모듈", "#19", "약 21×15 mm", "W 그늘"),
    (base.oled_091(), "0.91\" OLED", "#22", "38×12 mm", "관제실"),
    (base.lcd1602_i2c(), "I2C 1602 LCD", "#3", "80×36 mm", "기지 전광판"),
    (base.neopixel_ring(), "네오픽셀 링", "#26", "LED 8개", "지붕 경광등"),
    (car.foam_wheel(), "우드락 바퀴", "제작", "Ø65×8 mm", "차"),
    (common.resistor(1000), "저항 1kΩ·2kΩ", "조달", "각 1개", "Echo 분압"),
    (common.phone_charger(), "휴대폰 충전기", "조달", "5V 1A 이상", "차 유선 전원"),
    (base.breadboard_830(), "대형 브레드보드", "#6", "165×55 mm", "기지 Pico"),
]


def main():
    body = [text_px(30, 48, "부품 도감 — 실물 모양·같은 배율(실제 크기 비교 가능)", 28, "#012a4a", "start"),
            text_px(30, 76, "그림 배율 3.2px = 1mm(모든 부품 같음). 핀 순서가 모듈마다 다를 수 있으니(DHT11·RGB·부저·링) 꽂기 전에 실크 글자를 확인한다.",
                    14, "#2a6f97", "start", 700)]
    cols, cell_w, cell_h, x0, y0 = 6, 290, 300, 30, 100
    for i, (part, name, kit, dims, use) in enumerate(ITEMS):
        c, r = i % cols, i // cols
        cx, cy = x0 + c * cell_w, y0 + r * cell_h
        scale = SCALE
        pw, ph = size_px(part, scale)
        if pw > cell_w - 30 or ph > cell_h - 100:   # 큰 부품(브레드보드·LCD)만 줄이고 배율을 적는다
            scale = min((cell_w - 30) / part.w, (cell_h - 100) / part.h)
            pw, ph = size_px(part, scale)
        body.append('<rect x="%d" y="%d" width="%d" height="%d" rx="12" fill="#f4f8fb" stroke="#a9d6e5" stroke-width="1.5"/>' % (
            cx + 6, cy + 6, cell_w - 12, cell_h - 12))
        svg, _ = place(part, cx + (cell_w - pw) / 2, cy + 20 + (cell_h - 100 - ph) / 2, scale)
        body.append(svg)
        body.append(text_px(cx + cell_w / 2, cy + cell_h - 62, name, 16, "#012a4a"))
        body.append(text_px(cx + cell_w / 2, cy + cell_h - 40, "%s · %s" % (kit, dims), 13, "#2c7da0", "middle", 700))
        note = use if abs(scale - SCALE) < 1e-6 else "%s · 배율 축소" % use
        body.append(text_px(cx + cell_w / 2, cy + cell_h - 20, note, 12, "#468faf", "middle", 700))
    svg = svg_doc(W, H, "".join(body), "부품 도감")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    xml.dom.minidom.parse(OUT)
    print("SVG:", OUT)


if __name__ == "__main__":
    main()
