"""패드 사진 한 장 → 검은 도로만 찾기 → 도로 위 흰 알갱이(우드락 눈)를 갈래별로 센다(객체 인식).
출동 여부와 도는 순서는 server/route.py가 정한다.

기준 사진도, 모서리 찍기도, 학습 데이터도 없다. 도로는 '꽉 찬 검정'이라 점박이 바닥 타일과 갈리고,
눈은 도로 안의 흰 점이다. 노란 페인트(중앙선 점선·교차로 테두리) 위 투명 테이프가 빛을 받으면 눈처럼
하얗게 찍히므로 도로 방향으로 길쭉한 반사, 도로 가운데 띠, 노란 페인트 바로 옆은 뺀다.
중앙선은 손으로 붙여 도로 가운데에서 비켜 있을 수 있어 가운데 띠만으로는 모자란다(IMG_1887).
축척은 도로 폭(board.json ROAD_MM)으로 잡는다.
사진 방향은 노란 코트가 교차로 왼쪽 아래에 오도록 돌려 맞춘다(그래서 N은 늘 공원·큰 건물 쪽 도로).
코트가 안 보이거나 가로·세로 도로 폭이 크게 다르면(비스듬히 찍음) sure=False로 알린다.
2026-10-31 모형 사진 42장(도로가 보이는 40장): 위에서 찍은 눈 없는 사진은 갈래당 14mm² 이하. 눈 사진 19장 중 18장은 어느 갈래든
100mm² 이상이고, 눈이 몇 알뿐인 1892는 S 갈래 44mm²였다(route.py가 애매하다고 보고 전체 청소).
"""

import base64
import io

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

MAX_SIDE = 1200        # 이보다 크면 줄여서 본다(알갱이가 2px 아래로 작아지지 않는 선)
DARK = 80              # 이보다 어두운 픽셀이 도로 후보
SOLID = 0.8            # 주변이 이 비율 넘게 검어야 도로(바닥 타일 점박이는 빠진다)
SNOW_MIN = 140         # 도로 안에서 RGB가 모두 이보다 밝으면 눈
CENTER_FRAC = 0.12     # 도로 폭의 이 비율만큼 중앙선 띠는 보지 않는다(점선·투명 테이프 반사)
STREAK = 3.0           # 이 비율 넘게 길쭉하고 10mm 넘게 긴 흰 덩어리는 반사로 본다
PAINT_MM = 8           # 노란 페인트에서 이 거리 안의 흰 점은 그 위 테이프 반사로 본다
SQUARE = 1.25          # 위에서 찍으면 가로·세로 도로 폭이 같다. 이 배 넘게 다르면 비스듬히 찍은 사진
ARMS = ("C", "N", "S", "E", "W")


def decode_image(data_url):
    """'data:image/jpeg;base64,...' 또는 base64 문자열 → RGB 배열(긴 변 MAX_SIDE 이하)."""
    if not isinstance(data_url, str) or not data_url:
        raise ValueError("image 는 base64 JPEG 문자열이어야 합니다")
    img = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[-1]))).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.asarray(img)


def _masks(img):
    """(도로, 눈, 노란 코트, 도로 위 노란 페인트) 마스크. 도로를 못 찾으면 None."""
    a = img.astype(int)
    mx, mn = a.max(2), a.min(2)
    k = max(9, a.shape[1] // 60)
    solid = ndi.uniform_filter((mx < DARK).astype(float), size=k) > SOLID
    closed = ndi.binary_closing(solid, structure=np.ones((k, k)))
    lab, n = ndi.label(closed)
    if n == 0:
        return None
    sizes = ndi.sum(closed, lab, range(1, n + 1))
    road = ndi.binary_fill_holes(lab == 1 + int(np.argmax(sizes)))
    if road.mean() < 0.02:
        return None
    yellow = (a[:, :, 0] > 160) & (a[:, :, 1] > 130) & (a[:, :, 2] < 120)
    snow = ndi.binary_erosion(road, structure=np.ones((5, 5))) & (mn > SNOW_MIN) & ~yellow
    snow = ndi.binary_opening(snow, structure=np.ones((2, 2)))      # 한 픽셀 반짝임은 뺀다
    court = ndi.binary_opening(yellow & ~road, structure=np.ones((9, 9)))   # 얇은 중앙선은 빠진다
    paint = yellow & ndi.binary_dilation(road, iterations=3)
    return road, snow, court, paint


def _cross(road):
    """십자 도로의 세로 띠 x 범위와 가로 띠 y 범위."""
    rf, cf = road.mean(1), road.mean(0)
    hb = np.nonzero(rf > 0.5 * rf.max())[0]
    vb = np.nonzero(cf > 0.5 * cf.max())[0]
    return vb.min(), vb.max(), hb.min(), hb.max()


def _turns(road, court):
    """노란 코트가 교차로 왼쪽 아래에 오게 하는 np.rot90 횟수. 코트를 못 찾으면 0."""
    if court.sum() == 0:
        return 0
    x0, x1, y0, y1 = _cross(road)
    ys, xs = np.nonzero(court)
    v = (xs.mean() - (x0 + x1) / 2.0, ys.mean() - (y0 + y1) / 2.0)
    for k in range(4):
        if v[0] < 0 and v[1] > 0:
            return k
        v = (v[1], -v[0])                  # 반시계 90° 돌리면 (dx, dy) → (dy, -dx)
    return 0


def _center_band(road, cross):
    """갈래마다 실제 도로 중앙선(행·열마다 도로의 가운데)을 따라 가는 좁은 띠."""
    x0, x1, y0, y1 = cross
    w = ((x1 - x0) + (y1 - y0)) / 2.0
    half = CENTER_FRAC * w / 2.0
    band = np.zeros_like(road)
    rows, cols = road.shape
    lo, hi = max(0, x0 - int(w)), min(cols, x1 + int(w))
    for y in range(rows):
        xs = np.nonzero(road[y, lo:hi])[0]
        if len(xs) and not y0 <= y <= y1:
            c = xs.mean() + lo
            band[y, int(c - half):int(c + half) + 1] = True
    lo, hi = max(0, y0 - int(w)), min(rows, y1 + int(w))
    for x in range(cols):
        ys = np.nonzero(road[lo:hi, x])[0]
        if len(ys) and not x0 <= x <= x1:
            c = ys.mean() + lo
            band[int(c - half):int(c + half) + 1, x] = True
    return band


def _drop_streaks(snow, px_mm):
    """길쭉한 흰 덩어리(테이프·점선 반사)를 뺀다. 눈 알갱이는 둥글게 뭉친다."""
    lab, n = ndi.label(ndi.binary_dilation(snow), structure=np.ones((3, 3)))
    keep = np.zeros(n + 1, bool)
    for i, sl in enumerate(ndi.find_objects(lab)):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        long, short = max(h, w), max(1, min(h, w))
        keep[i + 1] = not (long >= STREAK * short and long / px_mm >= 10)
    return snow & keep[lab]


def analyze(img, road_mm):
    """사진 → {"arms": {갈래: {area_mm2, far_mm}}, "turns", "sure", "view"} 또는 도로가 없으면 None.
    sure가 False면 갈래 이름이나 면적을 믿을 수 없다(코트가 안 보여 방향을 모르거나 비스듬히 찍음)."""
    m = _masks(img)
    if m is None:
        return None
    road, snow, court, paint = m
    k = _turns(road, court)
    img, road, snow, paint = (np.rot90(a, k) for a in (img, road, snow, paint))
    cross = _cross(road)
    x0, x1, y0, y1 = cross
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    wide, tall = x1 - x0 + 1, y1 - y0 + 1
    px_mm = (wide + tall) / 2.0 / road_mm
    sure = bool(court.any()) and 1 / SQUARE <= wide / tall <= SQUARE
    near_paint = ndi.binary_dilation(paint, iterations=max(1, int(round(PAINT_MM * px_mm))))
    # 길쭉한 반사는 띠·페인트 둘레로 잘리기 전에 통째로 봐야 짧은 조각으로 남지 않는다
    snow = _drop_streaks(snow, px_mm) & ~_center_band(road, cross) & ~near_paint
    ys, xs = np.nonzero(snow)
    in_h = (ys >= y0) & (ys <= y1)
    in_v = (xs >= x0) & (xs <= x1)
    vertical = in_v | (~in_h & (np.abs(xs - cx) < np.abs(ys - cy)))
    arm = np.where(in_h & in_v, "C", np.where(vertical, np.where(ys < cy, "N", "S"), np.where(xs < cx, "W", "E")))
    dist = np.where(vertical, np.abs(ys - cy), np.abs(xs - cx)) / px_mm
    arms = {}
    for name in ARMS:
        sel = arm == name
        arms[name] = {"area_mm2": int(round(sel.sum() / px_mm ** 2)),
                      "far_mm": int(round(dist[sel].max())) if sel.any() else 0}
    return {"arms": arms, "turns": k, "sure": sure, "view": _overlay(img, road, snow, (cx, cy), (x0, x1, y0, y1))}


def _overlay(img, road, snow, center, cross):
    """도로(파랑 칠)·눈(빨강)·교차로 중심·갈래 이름을 그린 JPEG data URL."""
    out = img.astype(float).copy()
    out[road] = out[road] * 0.6 + np.array([40, 90, 200]) * 0.4
    out[ndi.binary_dilation(snow, iterations=2)] = (230, 30, 30)
    im = Image.fromarray(out.astype(np.uint8))
    d = ImageDraw.Draw(im)
    cx, cy = center
    x0, x1, y0, y1 = cross
    d.rectangle([x0, y0, x1, y1], outline=(255, 210, 0), width=3)
    for name, (x, y) in {"N": (cx, y0 / 2), "S": (cx, (y1 + im.height) / 2),
                         "W": (x0 / 2, cy), "E": ((x1 + im.width) / 2, cy)}.items():
        d.text((x - 6, y - 8), name, fill=(255, 255, 255))
    return to_data_url(im)


def to_data_url(img):
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
