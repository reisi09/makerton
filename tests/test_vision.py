# -*- coding: utf-8 -*-
"""server/vision.py 시험: 점박이 바닥 위 보드를 비스듬히 찍은 합성 '사진'에서 도로 위 눈을 갈래별로 센다."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import vision  # noqa: E402

PHOTO = (1200, 900)
CORNERS = [(170, 60), (1050, 80), (1110, 860), (110, 840)]       # 보드 북서·북동·남동·남서가 찍힌 자리
N_SNOW = [(560, 100), (610, 160), (545, 230), (625, 300), (548, 60), (560, 350)]
E_SNOW = [(720, 440), (800, 520), (860, 470)]


def board(snow=(), glare=False, lane=580, tape=False, court=True):
    """실측 모형(925×910mm, 1px=1mm): 십자 도로·노란 중앙선·왼쪽 아래 노란 코트·축구장.
    lane은 세로 도로 중앙선의 x(실물은 손으로 붙여 가운데에서 비켜 있다), tape는 점선마다 옆에 생기는 짧은 테이프 반사.
    court=False는 코트가 가려진 사진: 공원에 있는 작은 노란 점 두 개만 남는다."""
    img = Image.new("RGB", (925, 910), (226, 231, 237))
    d = ImageDraw.Draw(img)
    d.rectangle([515, 0, 650, 910], fill=(38, 40, 42))
    d.rectangle([0, 404, 925, 552], fill=(38, 40, 42))
    for v in range(0, 910, 40):
        d.rectangle([lane, v, lane + 5, v + 20], fill=(235, 200, 60))
        d.rectangle([v, 476, v + 20, 481], fill=(235, 200, 60))
        if tape and v < 380:
            d.rectangle([lane + 7, v + 4, lane + 10, v + 14], fill=(240, 238, 232))
    if court:
        d.rectangle([0, 560, 360, 711], fill=(250, 210, 60))
    else:
        for x, y in ((380, 200), (430, 260)):
            d.ellipse([x - 12, y - 12, x + 12, y + 12], fill=(250, 210, 60))
    d.rectangle([383, 560, 508, 752], fill=(60, 150, 70))
    if glare:
        d.rectangle([578, 20, 587, 380], fill=(245, 245, 245))      # 중앙선 투명 테이프 반사
    for x, y in snow:
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(246, 246, 244))
    return img


def coeffs(photo_pts, board_pts):
    a, b = [], []
    for (x, y), (u, v) in zip(photo_pts, board_pts):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def floor():
    """테라초 바닥: 회색 바탕에 흰·검은 돌 점."""
    rng = np.random.default_rng(3)
    f = rng.normal(172, 12, (PHOTO[1], PHOTO[0], 1)).repeat(3, axis=2)
    f[rng.random((PHOTO[1], PHOTO[0])) < 0.06] = 235
    f[rng.random((PHOTO[1], PHOTO[0])) < 0.05] = 60
    return np.clip(f, 0, 255).astype(np.uint8)


def photo(b):
    mask = Image.new("L", (925, 910), 255)
    c = coeffs(CORNERS, [(0, 0), (925, 0), (925, 910), (0, 910)])
    shot = b.transform(PHOTO, Image.PERSPECTIVE, c, Image.BILINEAR)
    inside = np.asarray(mask.transform(PHOTO, Image.PERSPECTIVE, c, Image.NEAREST)) > 0
    out = floor()
    out[inside] = np.asarray(shot)[inside]
    return out


class VisionTest(unittest.TestCase):
    def test_counts_snow_per_arm_on_the_black_roads_only(self):
        found = vision.analyze(photo(board(snow=N_SNOW + E_SNOW)), 135.0)
        arms = found["arms"]
        self.assertGreater(arms["N"]["area_mm2"], 250, arms)
        self.assertGreater(arms["E"]["area_mm2"], 120, arms)
        self.assertLess(arms["S"]["area_mm2"] + arms["W"]["area_mm2"], 40, arms)
        self.assertLess(abs(arms["N"]["far_mm"] - 420), 60, arms)       # 중심(480)에서 가장 먼 N 알갱이(y 60). 축척 하나라 원근 오차가 있다

    def test_clean_board_with_centerline_glare_is_not_snow(self):
        found = vision.analyze(photo(board(glare=True)), 135.0)
        total = sum(a["area_mm2"] for a in found["arms"].values())
        self.assertLess(total, 40, found["arms"])

    def test_tape_glare_beside_an_off_center_centerline_is_not_snow(self):
        # 2026-10-31 IMG_1887: 중앙선이 도로 가운데에서 20mm 비켜 있어 점선 옆 반사가 S 갈래 154mm²로 잡혔다
        found = vision.analyze(photo(board(lane=600, tape=True)), 135.0)
        self.assertLess(found["arms"]["N"]["area_mm2"], 30, found["arms"])

    def test_top_down_photo_is_sure_and_a_squashed_one_is_not(self):
        shot = photo(board())
        self.assertTrue(vision.analyze(shot, 135.0)["sure"])
        squashed = np.asarray(Image.fromarray(shot).resize((PHOTO[0], int(PHOTO[1] * 0.6))))
        self.assertFalse(vision.analyze(squashed, 135.0)["sure"], "낮은 각도로 찍으면 가로 도로만 얇아진다")

    def test_rotated_photo_still_names_the_arms_by_the_yellow_court(self):
        found = vision.analyze(np.ascontiguousarray(np.rot90(photo(board(snow=N_SNOW)), -1)), 135.0)
        self.assertEqual(found["turns"], 1)
        self.assertGreater(found["arms"]["N"]["area_mm2"], 250, found["arms"])

    def test_frame_puts_board_points_where_the_photo_shows_them(self):
        # 화면이 최적 경로를 사진 위에 그리는 아핀. 합성 사진의 실제 원근 변환과 비교한다. 이 합성 사진은 실제 위에서 찍은 사진보다
        # 원근이 세고 가로 도로가 148mm라 축척 하나로는 먼 갈래 끝에서 6%쯤 어긋난다(실제 사진 25장은 보드 가장자리에서 대각선의 중앙값 1.9%).
        # 90° 단위로 잘못 돌리거나 비뚠 각도를 반대로 세우면 갈래 끝이 다른 갈래로 가서 20% 넘게 어긋나므로, 먼 점의 느슨한 허용치로도 걸린다
        g = coeffs([(0, 0), (925, 0), (925, 910), (0, 910)], CORNERS)      # 보드 mm → 사진 px
        def on_shot(x, y):
            w = g[6] * x + g[7] * y + 1
            return (g[0] * x + g[1] * y + g[2]) / w, (g[3] * x + g[4] * y + g[5]) / w
        def quarter(k):                                                       # np.rot90(사진, k): 점 (x, y) → (y, 너비-1-x)
            def move(x, y, w, h):
                for _ in range(k):
                    x, y, w, h = y, w - 1 - x, h, w
                return x / w, y / h
            return lambda img: np.ascontiguousarray(np.rot90(img, k)), move
        def tilted(a):                                                        # PIL rotate: 가운데를 축으로 반시계 a°
            def move(x, y, w, h):
                t, cx, cy = np.radians(a), w / 2.0, h / 2.0
                return ((cx + (x - cx) * np.cos(t) + (y - cy) * np.sin(t)) / w, (cy - (x - cx) * np.sin(t) + (y - cy) * np.cos(t)) / h)
            return lambda img: np.asarray(Image.fromarray(img).rotate(a, fillcolor=(172, 172, 172))), move
        center = (582.5, 478.0)                                             # 합성 보드의 도로 십자 가운데
        near = [((0, 0), 0.02), ((0, -150), 0.03), ((150, 0), 0.03)]
        far = [((0, -375), 0.08), ((238, 0), 0.08), ((0, 325), 0.08), ((-477, 0), 0.08), ((182, -230), 0.08)]   # 갈래 끝 넷, 차고 앞
        shot = photo(board())
        cases = [("rot%d" % k, quarter(k)) for k in range(4)] + [("tilt%+d" % a, tilted(a)) for a in (12, -12, 30, -30)]
        for name, (turn, move) in cases:
            a, b, c, d, e, f = vision.analyze(turn(shot), 135.0)["frame"]
            for (dx, dy), tol in near + far:
                got = (a * dx + b * dy + c, d * dx + e * dy + f)
                want = move(*on_shot(center[0] + dx, center[1] + dy), PHOTO[0], PHOTO[1])
                self.assertLess(max(abs(got[0] - want[0]), abs(got[1] - want[1])), tol, (name, dx, dy, got, want))

    def test_frame_is_withheld_when_the_direction_is_unknown(self):
        squashed = np.asarray(Image.fromarray(photo(board())).resize((PHOTO[0], int(PHOTO[1] * 0.6))))
        self.assertIsNone(vision.analyze(squashed, 135.0)["frame"], "비스듬한 사진에 경로를 그리면 엉뚱한 곳에 그린다")
        hidden = vision.analyze(photo(board(court=False)), 135.0)
        self.assertIsNone(hidden["frame"], "코트가 가려지면 공원의 작은 노란 점으로 방향을 정하지 않는다")

    def test_photo_without_roads_is_rejected(self):
        self.assertIsNone(vision.analyze(floor(), 135.0))


class DecodeTest(unittest.TestCase):
    """맥 Chrome은 아이폰 HEIC를 못 열어 원본 그대로 올린다. 서버가 읽고, 사진 방향(EXIF)대로 세워야 상자가 맞는다."""

    def b64(self, data):
        import base64
        return base64.b64encode(data).decode("ascii")

    @unittest.skipUnless(shutil.which("sips"), "HEIC 변환은 맥의 sips가 있어야 한다")
    def test_iphone_heic_is_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            png, heic = os.path.join(tmp, "a.png"), os.path.join(tmp, "a.heic")
            Image.new("RGB", (1600, 1200), (20, 20, 20)).save(png)
            subprocess.run(["sips", "-s", "format", "heic", png, "--out", heic], check=True, capture_output=True)
            with open(heic, "rb") as f:
                img = vision.decode_image("data:image/heic;base64," + self.b64(f.read()))
        self.assertEqual(img.shape, (900, 1200, 3))

    def test_photo_is_turned_upright_by_its_exif_orientation(self):
        buf = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6                                     # 세로로 든 폰: 90도 돌려 보여 줘야 한다
        Image.new("RGB", (800, 600), (20, 20, 20)).save(buf, "JPEG", exif=exif)
        self.assertEqual(vision.decode_image(self.b64(buf.getvalue())).shape, (800, 600, 3))

    def test_broken_heic_is_a_readable_error(self):
        with self.assertRaises(ValueError):
            vision.decode_image(self.b64(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64))


if __name__ == "__main__":
    unittest.main()
