# -*- coding: utf-8 -*-
"""고색고 주변 OSM 도로·교량·건물·하천으로 구간 위험도와 4방위 교차로 갈래를 만든다.

`python3 -m model.icezero.roads [--refresh]` 한 번이면
  data/roads/overpass_*.json   Overpass 캐시(처음 받을 때만, --refresh면 다시 받음)
                              endpoint는 overpass-api.de → kumi.systems 순, User-Agent 지정.
                              맥 python3.9(LibreSSL)가 TLS 협상을 못 해 urllib 실패 시 curl로 보낸다.
  data/roads/gosaek_roads.geojson
  data/roads/cross_arms.json
  docs/img/gosaek_map.svg
를 만든다. 표준 라이브러리만 쓴다(matplotlib 없음).

## 1. 구간 위험도 (ICE-ZERO risk_v2 계열)
risk_v2 원식(`~/Downloads/ICE-ZERO_github_repo_v3/scripts/improve02_risk.py`):
    risk_v2 = 0.30·rank(−T_eff) + 0.30·rank(shadow) + 0.15·rank(refreeze)
              + 0.10·rank(−width) + 0.15·structure
여기서는 T_eff(구간 유효표면온도), refreeze_index, road_width 실측값이 없다.
이번 범위(도로·건물·하천 형상만 있음)에서 쓸 수 있는 대응물로 바꿔 옮긴다.

    risk_raw = 0.40·등급 + 0.30·그림자 + 0.15·하천 + 0.15·구조물 − 0.10·터널
    risk     = min-max 정규화(risk_raw)        # 지역 내 0~1
    risk_pct = 지역 내 백분위                    # 상대 순위

가중치를 옮긴 근거
  - 등급 0.40 = freeze 0.30 + narrow 0.10
    ASOS 119는 지점 단일 관측이라 구간별 T_eff 편차를 만들 수 없다. 위험을 가르는
    실질 신호는 '제설이 늦고 통행이 적은 이면도로'이며, 원식에서 그 역할을 하던 것이
    narrow(0.10)다. 등급이 낮을수록 좁고 제설 우선순위가 낮다는 같은 방향이므로
    freeze 자리(0.30)까지 등급에 합쳐 0.40으로 둔다.
  - 그림자 0.30 = shadow 0.30 (원식 그대로, 겨울철 복사냉각의 공간 신호)
  - 하천 0.15 = refreeze 0.15
    하천 인접 구간은 수증기 공급과 안개로 재결빙이 잦다는 가정. refreeze_index 대체.
  - 구조물 0.15 = structure 0.15 (원식 그대로, 교량은 상시 가산)
  - 터널 −0.10 = TUNNEL_BONUS_C(+1.5°C)의 대응물
    원식은 터널 내부를 강수·복사냉각 차단으로 +1.5°C 보정했다. 여기선 온도 대신
    점수에서 빼고, 1.5°C를 0~1 점수의 0.10으로 잡았다(교량 2.5°C ≈ 0.15와 같은 비례).

원식과 다른 점
  - rank(percentile) 정규화를 쓰지 않는다. 네 구성 요소를 모두 0~1로 직접 만들었기
    때문이다(원식은 scale이 제각각이라 rank가 필요했다). 순위 정보는 risk_pct가 준다.
  - risk는 상대 우선순위다. 절대 결빙확률이 아니며, 결빙을 확정하지 않는다.

### 그림자 지수
겨울 태양고도가 낮아 건물 그림자는 북쪽으로 길게 뻗는다. 따라서 도로 '남쪽' 건물이
도로를 가린다. 구간 중점 기준 남쪽 섹터(180°±60°) 안, 80m 안 건물만 센다.
    기여 = 높이(m) / 거리(m)        # 높이/거리 ≈ tan(고도) 무차원 근사
    그림자 = min(1, Σ기여 / 2.0)     # 2.0에서 포화
높이는 height 태그, 없으면 building:levels×3.2m, 둘 다 없으면 8m로 본다.

## 2. 교차로 선정
OSM 노드 중 차량 도로가 4갈래로 만나는 곳을 후보로 두고, 갈래를 방위(N·E·S·W)로
묶는다(각 방위에 가장 가까운 갈래 하나, 같은 방위에 여럿이면 긴 쪽).
    점수 = (0.25 + 거리가중) × (0.5 + 갈래 위험 편차) × (1 + 0.5·교량 갈래) × (1 + 0.4·최대 그늘)
    거리가중 = max(0, 1 − 학교거리/1500m)
교량 갈래가 있는 후보가 없으면 그 사실을 source.note에 적고 가장 나은 곳을 고른다.
"""
import argparse
import datetime
import json
import math
import os
import shutil
import subprocess
import urllib.parse
import urllib.request

# ── 위치 상수 ──────────────────────────────────────────────
SCHOOL = (37.25378, 126.98246)      # 고색고등학교
STATION119 = (37.25746, 126.983)    # 수원 ASOS 119
RADIUS_M = 1500

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "model", "data", "roads")
IMG_DIR = os.path.join(ROOT, "docs", "img")

# ── Overpass ──────────────────────────────────────────────
FETCH_TIMEOUT = 240      # 주 엔드포인트 overpass-api.de
MIRROR_TIMEOUT = 100     # 미러 kumi는 느릴 때가 있어 짧게
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "makerton/0.1 (gosaek highschool ice-risk model; python-urllib)"

VEHICLE_HIGHWAY = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "living_street|service|motorway_link|trunk_link|primary_link|secondary_link|"
    "tertiary_link|track|road"
)
# 보행 전용은 요청에서 빼고, 태그가 바뀐 옛 캐시에 대비해 계산에서도 한 번 더 거른다.
PEDESTRIAN_HIGHWAY = ("footway", "path", "pedestrian", "cycleway", "steps", "corridor", "bridleway")

_QUERIES = {
    "roads": (
        '[out:json][timeout:240];'
        'way(around:%d,%.5f,%.5f)["highway"~"^(%s)$"];'
        'out body;>;out skel qt;'
    ),
    "buildings": (
        '[out:json][timeout:240];'
        'way(around:%d,%.5f,%.5f)["building"];'
        'out body;>;out skel qt;'
    ),
    "water": (
        '[out:json][timeout:240];'
        '('
        'way(around:%d,%.5f,%.5f)["waterway"];'
        'way(around:%d,%.5f,%.5f)["natural"="water"];'
        'relation(around:%d,%.5f,%.5f)["natural"="water"];'
        ');'
        'out body;>;out skel qt;'
    ),
}


def query_text(theme):
    lat, lon = SCHOOL
    q = _QUERIES[theme]
    if theme == "water":
        return q % (RADIUS_M, lat, lon, RADIUS_M, lat, lon, RADIUS_M, lat, lon)
    if theme == "roads":
        return q % (RADIUS_M, lat, lon, VEHICLE_HIGHWAY)
    return q % (RADIUS_M, lat, lon)


# ── 위험도 가중치 ──────────────────────────────────────────
W = {"class": 0.40, "shadow": 0.30, "water": 0.15, "structure": 0.15}
TUNNEL_DEDUCT = 0.10
SHADOW_RANGE_M = 80.0
SHADOW_SECTOR_DEG = 60.0
SHADOW_SAT = 2.0
BUILDING_H_CAP = 45.0
BUILDING_DEFAULT_H = 8.0
LEVEL_H_M = 3.2
WATER_RANGE_M = 300.0
NEAR_WATER_M = 80.0
SEG_MAX_M = 120.0        # 한 구간(엣지) 최대 길이. 넘으면 나눈다.
ARM_LEN_M = 60.0         # 교차로 갈래를 재는 길이

CLASS_RISK = {
    "motorway": 0.05, "trunk": 0.10, "primary": 0.20, "secondary": 0.30,
    "tertiary": 0.45, "unclassified": 0.60, "residential": 0.75,
    "living_street": 0.85, "service": 0.90, "road": 0.80, "track": 1.00,
}
LINK_BASE = {"motorway": "motorway", "trunk": "trunk", "primary": "primary",
             "secondary": "secondary", "tertiary": "tertiary"}

DIRS = ("N", "E", "S", "W")
DIR_KO = {"N": "북", "E": "동", "S": "남", "W": "서"}
DIR_BEARING = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}


# ── 기하 순수 함수 ─────────────────────────────────────────
def haversine_m(lat1, lon1, lat2, lon2):
    """두 좌표 사이 거리(m)."""
    r = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def local_xy(lat, lon, lat0=None, lon0=None):
    """등거리 근사 로컬 좌표(m). x=동, y=북."""
    if lat0 is None:
        lat0, lon0 = SCHOOL
    x = (lon - lon0) * 111320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 111132.0
    return x, y


def bearing_deg(lat1, lon1, lat2, lon2):
    """1→2 방위(0=북, 90=동, 시계 방향)."""
    dx, dy = local_xy(lat2, lon2, lat1, lon1)
    ang = math.degrees(math.atan2(dx, dy))
    return (ang + 360.0) % 360.0


def bearing_to_dir(bearing):
    """방위를 4방위 중 가장 가까운 쪽으로. 45° 경계는 다음 방위로 넘긴다."""
    b = bearing % 360.0
    idx = int((b + 45.0) // 90.0) % 4
    return DIRS[idx]


def angle_diff(a, b):
    """방위 차이(0~180)."""
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return d


def point_segment_m(px, py, ax, ay, bx, by):
    """점 (px,py)에서 선분 (a,b)까지 거리(m). 로컬 좌표계."""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    vv = vx * vx + vy * vy
    if vv <= 1e-9:
        return math.hypot(wx, wy)
    t = (wx * vx + wy * vy) / vv
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(wx - t * vx, wy - t * vy)


def building_height(tags):
    """건물 높이(m). height → building:levels×3.2 → 기본 8m."""
    raw = (tags or {}).get("height")
    if raw:
        try:
            v = float(str(raw).replace("m", "").strip())
            if 0.0 < v < 500.0:
                return v
        except ValueError:
            pass
    lv = (tags or {}).get("building:levels")
    if lv:
        try:
            v = float(str(lv).strip())
            if 0.0 < v < 200.0:
                return v * LEVEL_H_M
        except ValueError:
            pass
    return BUILDING_DEFAULT_H


def shadow_index(lat, lon, buildings):
    """구간 중점 남쪽 건물이 만드는 그늘 지수(0~1).

    buildings: [{"lat","lon","height_m"}, ...]
    남쪽 섹터(180°±60°) 안, SHADOW_RANGE_M 안 건물의 높이/거리를 합해
    SHADOW_SAT에서 포화시킨다.
    """
    total = 0.0
    for b in buildings:
        dx, dy = local_xy(b["lat"], b["lon"], lat, lon)
        d = math.hypot(dx, dy)
        if d > SHADOW_RANGE_M or d < 1.0:
            continue
        brg = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
        if angle_diff(brg, 180.0) > SHADOW_SECTOR_DEG:
            continue
        total += min(b.get("height_m", BUILDING_DEFAULT_H), BUILDING_H_CAP) / d
    return min(1.0, total / SHADOW_SAT)


def percentile_rank(values):
    """평균 순위 백분위(0~1). 동점은 같은 값."""
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg / n
        i = j + 1
    return out


def minmax(values):
    """0~1 정규화. 전부 같으면 0.5."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def class_risk(highway):
    """도로 등급 위험 성분(0~1). 링크는 상위 등급 + 0.05."""
    h = (highway or "").strip()
    if h in CLASS_RISK:
        return CLASS_RISK[h]
    if h.endswith("_link"):
        base = LINK_BASE.get(h[: -len("_link")])
        if base:
            return min(1.0, CLASS_RISK[base] + 0.05)
    return 0.5


def water_component(dist_m):
    """하천 근접 성분(0~1). 가까울수록 크다."""
    if dist_m is None:
        return 0.0
    return max(0.0, 1.0 - dist_m / WATER_RANGE_M)


def risk_raw(class_c, shadow_c, water_c, structure_c, tunnel):
    """구간 원점수(0 언저리). 가중합 후 터널 감산."""
    v = (W["class"] * class_c + W["shadow"] * shadow_c
         + W["water"] * water_c + W["structure"] * structure_c)
    if tunnel:
        v -= TUNNEL_DEDUCT
    return v


def assign_arms(branches):
    """갈래들을 4방위에 맞춘다. 각 방위에 가장 가까운 갈래 하나,
    같은 방위가 겹치면 긴 갈래를 남긴다."""
    out = {}
    for b in sorted(branches, key=lambda x: -x.get("length_m", 0.0)):
        d = bearing_to_dir(b.get("bearing_deg", 0.0))
        if d not in out:
            out[d] = b
    return out


def arm_name(way_name, direction):
    if way_name:
        return way_name
    return "%s 방면 무명도로" % DIR_KO.get(direction, direction)


def junction_score(dist_m, arm_risks, structures, shadows, radius_m=RADIUS_M):
    """교차로 점수. 학교 거리·갈래 위험 편차·교량·그늘을 함께 본다."""
    if not arm_risks:
        return 0.0
    w_dist = max(0.0, 1.0 - float(dist_m) / float(radius_m))
    spread = max(arm_risks) - min(arm_risks)
    has_bridge = 1.0 if any(s > 0.5 for s in structures) else 0.0
    shadow_max = max(shadows) if shadows else 0.0
    return (0.25 + w_dist) * (0.5 + spread) * (1.0 + 0.5 * has_bridge) * (1.0 + 0.4 * shadow_max)


# ── Overpass 캐시 ─────────────────────────────────────────
def _post_urllib(endpoint, query, timeout):
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_curl(endpoint, query, timeout):
    """맥 기본 python3.9(LibreSSL 2.8)은 overpass-api.de와 TLS 협상을 못 한다.
    curl로 우회한다."""
    if not shutil.which("curl"):
        raise RuntimeError("curl이 없어 대체 경로를 쓸 수 없다")
    cmd = ["curl", "-sS", "--fail", "-m", str(int(timeout)),
           "-A", USER_AGENT, "--data-urlencode", "data=" + query, endpoint]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("curl 실패(%d): %s" % (p.returncode, p.stderr.decode("utf-8", "replace")[:200]))
    return json.loads(p.stdout.decode("utf-8"))


def fetch_overpass(query):
    """엔드포인트를 차례로 시도한다. urllib 실패 시 curl로 같은 요청을 다시 보낸다.

    맥 기본 python3.9는 LibreSSL 2.8이라 overpass-api.de와 TLS 협상을 못 한다.
    그래서 urllib이 즉시 실패하고 curl 경로로 넘어간다(정상 동작).
    미러는 응답이 늦을 때가 있어 제한 시간을 짧게 둔다.
    """
    errors = []
    for ep, timeout in zip(ENDPOINTS, (FETCH_TIMEOUT, MIRROR_TIMEOUT)):
        try:
            return _post_urllib(ep, query, timeout)
        except Exception as exc:  # noqa: BLE001 - 엔드포인트·전송 오류 모두 다음 후보로
            errors.append("%s urllib: %s" % (ep, exc.__class__.__name__))
        try:
            return _post_curl(ep, query, timeout)
        except Exception as exc:  # noqa: BLE001
            errors.append("%s curl: %s" % (ep, str(exc)[:110]))
    raise RuntimeError("Overpass 요청 실패\n  " + "\n  ".join(errors))


def cache_path(theme):
    return os.path.join(DATA_DIR, "overpass_%s.json" % theme)


def load_osm(refresh=False):
    """주제별 캐시를 읽고, 없거나 --refresh면 받아서 저장한다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    out = {}
    for theme in ("roads", "buildings", "water"):
        path = cache_path(theme)
        if refresh or not os.path.exists(path):
            print("[overpass] %s 받는 중…" % theme)
            payload = fetch_overpass(query_text(theme))
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
            print("[overpass] %s 저장: %s" % (theme, os.path.relpath(path, ROOT)))
        out[theme] = json.load(open(path, encoding="utf-8"))
    return out


def osm_timestamp(payload):
    try:
        return payload["osm3s"]["timestamp_osm_base"]
    except Exception:  # noqa: BLE001
        return None


def split_elements(payload):
    """(nodes{id:(lat,lon)}, ways[{id,tags,nodes}])"""
    nodes, ways = {}, []
    for e in payload.get("elements", []):
        if e.get("type") == "node":
            nodes[e["id"]] = (e["lat"], e["lon"])
        elif e.get("type") == "way":
            ways.append({"id": e["id"], "tags": e.get("tags") or {}, "nodes": e.get("nodes") or []})
    return nodes, ways


# ── 구간 만들기·위험도 ─────────────────────────────────────
def _edge_nodes(way, nodes):
    """웨이를 연속 노드 쌍으로 자른다. SEG_MAX_M을 넘는 쌍은 균등 분할."""
    pts = [n for n in way["nodes"] if n in nodes]
    out = []
    for a, b in zip(pts, pts[1:]):
        (lat1, lon1), (lat2, lon2) = nodes[a], nodes[b]
        d = haversine_m(lat1, lon1, lat2, lon2)
        if d <= 1e-6:
            continue
        if d > SEG_MAX_M:
            k = int(math.ceil(d / SEG_MAX_M))
            coords = [nodes[a]]
            for i in range(1, k):
                t = i / float(k)
                coords.append((lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t))
            coords.append(nodes[b])
            for i in range(k):
                out.append((a if i == 0 else None, coords[i], coords[i + 1]))
            continue
        out.append((a, nodes[a], nodes[b]))
    return out


def is_bridge(tags):
    v = (tags or {}).get("bridge")
    return bool(v) and v != "no"


def is_tunnel(tags):
    v = (tags or {}).get("tunnel")
    return bool(v) and v != "no"


def build_water(payload):
    """하천·물 형상을 로컬 좌표 선분 목록으로."""
    nodes, ways = split_elements(payload)
    segs = []
    for w in ways:
        pts = [nodes[n] for n in w["nodes"] if n in nodes]
        for (lat1, lon1), (lat2, lon2) in zip(pts, pts[1:]):
            ax, ay = local_xy(lat1, lon1)
            bx, by = local_xy(lat2, lon2)
            segs.append((ax, ay, bx, by, w["tags"].get("name")))
    return segs


def build_buildings(payload):
    nodes, ways = split_elements(payload)
    out = []
    for w in ways:
        pts = [nodes[n] for n in w["nodes"] if n in nodes]
        if not pts:
            continue
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        out.append({"id": w["id"], "lat": lat, "lon": lon,
                    "height_m": building_height(w["tags"])})
    return out


def nearest_water_m(lat, lon, water_segs):
    """가장 가까운 하천 형상까지 거리(m). WATER_RANGE_M 밖은 None."""
    px, py = local_xy(lat, lon)
    best = None
    for ax, ay, bx, by, _name in water_segs:
        if (min(ax, bx) - WATER_RANGE_M > px or max(ax, bx) + WATER_RANGE_M < px
                or min(ay, by) - WATER_RANGE_M > py or max(ay, by) + WATER_RANGE_M < py):
            continue
        d = point_segment_m(px, py, ax, ay, bx, by)
        if best is None or d < best:
            best = d
    return best


def build_segments(roads_payload, buildings, water_segs):
    """도로 엣지별 위험도. 보행 전용은 건너뛴다."""
    nodes, ways = split_elements(roads_payload)
    segs = []
    for w in ways:
        hw = w["tags"].get("highway")
        if not hw or hw in PEDESTRIAN_HIGHWAY:
            continue
        bridge = is_bridge(w["tags"])
        tunnel = is_tunnel(w["tags"])
        for node_a, pa, pb in _edge_nodes(w, nodes):
            lat = (pa[0] + pb[0]) / 2.0
            lon = (pa[1] + pb[1]) / 2.0
            segs.append({
                "osm_id": w["id"],
                "node_a": node_a,
                "name": w["tags"].get("name"),
                "highway": hw,
                "bridge": bool(bridge),
                "tunnel": bool(tunnel),
                "coords": [pa, pb],
                "mid": (lat, lon),
                "bearing_deg": bearing_deg(pa[0], pa[1], pb[0], pb[1]),
                "length_m": haversine_m(pa[0], pa[1], pb[0], pb[1]),
                "structure": 1.0 if bridge else 0.0,
                "shadow_index": shadow_index(lat, lon, buildings),
                "class_c": class_risk(hw),
                "water_dist_m": nearest_water_m(lat, lon, water_segs),
            })
    return segs


def score_segments(segs):
    """가중합 → 0~1 정규화 → 백분위."""
    raws = []
    for s in segs:
        s["water_c"] = water_component(s["water_dist_m"])
        raws.append(risk_raw(s["class_c"], s["shadow_index"], s["water_c"],
                             s["structure"], s["tunnel"]))
    for s, r in zip(segs, raws):
        s["risk_raw"] = r
    norm = minmax(raws)
    pct = percentile_rank(norm)
    for s, v, p in zip(segs, norm, pct):
        s["risk"] = max(0.0, min(1.0, v))
        s["risk_pct"] = p
    return segs


# ── 교차로 ────────────────────────────────────────────────
def _walk_branch(way, idx, step, nodes, limit_m=ARM_LEN_M):
    """노드 way[idx]에서 step 방향으로 limit_m까지 걸으며 (방위, 길이, 끝점)을 낸다.

    방위는 limit_m 밖 첫 노드까지 실제로 걸은 거리로 잰다(노드 간격이 성길 수 있어
    length_m이 limit_m을 조금 넘기도 한다).
    """
    lat0, lon0 = nodes[way["nodes"][idx]]
    dist = 0.0
    prev = (lat0, lon0)
    far = prev
    i = idx + step
    while 0 <= i < len(way["nodes"]):
        nid = way["nodes"][i]
        if nid not in nodes:
            break
        cur = nodes[nid]
        dist += haversine_m(prev[0], prev[1], cur[0], cur[1])
        prev = cur
        far = cur
        if dist >= limit_m:
            break
        i += step
    return bearing_deg(lat0, lon0, far[0], far[1]), dist, far


def junction_candidates(roads_payload, seg_by_key):
    """4갈래 교차로 후보. seg_by_key: (way_id, node_id) -> 엣지.

    갈래의 위험도·그늘·교량은 교차로에 붙은 첫 구간(엣지) 값이다. 그 갈래로 들어서는
    순간 만나는 노면이 판단 대상이라는 뜻이다.
    """
    nodes, ways = split_elements(roads_payload)
    vehicle = []
    for w in ways:
        hw = w["tags"].get("highway")
        if not hw or hw in PEDESTRIAN_HIGHWAY:
            continue
        vehicle.append(w)
    uses = {}
    for w in vehicle:
        for i, nid in enumerate(w["nodes"]):
            uses.setdefault(nid, []).append((w, i))
    cands = []
    for nid, refs in uses.items():
        if len(refs) < 2 or nid not in nodes:
            continue
        lat, lon = nodes[nid]
        branches = []
        for w, i in refs:
            for step in (-1, 1):
                j = i + step
                if not (0 <= j < len(w["nodes"])):
                    continue
                if w["nodes"][j] not in nodes:
                    continue
                brg, dist, _far = _walk_branch(w, i, step, nodes)
                if dist <= 0.0:
                    continue
                key = (w["id"], w["nodes"][min(i, j)])
                edge = seg_by_key.get(key)
                branches.append({
                    "way_id": w["id"],
                    "way_name": w["tags"].get("name"),
                    "highway": w["tags"].get("highway"),
                    "node": w["nodes"][j],
                    "bearing_deg": brg,
                    "length_m": dist,
                    "edge": edge,
                })
        arms = assign_arms(branches)
        if len(arms) != 4:
            continue
        bearings = [arms[d]["bearing_deg"] for d in DIRS]
        min_sep = min(angle_diff(a, b) for k, a in enumerate(bearings) for b in bearings[k + 1:])
        if min_sep < 40.0:
            continue
        missing = [d for d in DIRS if arms[d]["edge"] is None]
        if missing:
            continue
        dist_school = haversine_m(SCHOOL[0], SCHOOL[1], lat, lon)
        risks = [arms[d]["edge"]["risk"] for d in DIRS]
        structs = [arms[d]["edge"]["structure"] for d in DIRS]
        shadows = [arms[d]["edge"]["shadow_index"] for d in DIRS]
        cands.append({
            "osm_id": nid, "lat": lat, "lon": lon,
            "dist_school_m": dist_school,
            "arms": arms, "branches": branches,
            "min_sep_deg": min_sep,
            "score": junction_score(dist_school, risks, structs, shadows),
        })
    cands.sort(key=lambda c: -c["score"])
    return cands


def choose_junction(cands):
    """점수 순 후보에서 하나. 교량 갈래가 있는 후보가 있으면 그중 1위.
    반환: (후보, 교량갈래_존재여부)"""
    if not cands:
        raise ValueError("4갈래 교차로 후보가 없다")
    def _has_bridge(c):
        return any(c["arms"][d]["edge"]["structure"] > 0.5 for d in DIRS)
    with_bridge = [c for c in cands if _has_bridge(c)]
    if with_bridge:
        return with_bridge[0], True
    return cands[0], False


def arms_payload(junction):
    """CONTRACT 4절 cross_arms.json의 arms 부분.

    osm_ids는 그 갈래 도로의 OSM way id다(방위를 정한 도로와 노면 구간이 같은 웨이).
    """
    out = {}
    for d in DIRS:
        b = junction["arms"][d]
        e = b["edge"]
        out[d] = {
            "name": arm_name(b["way_name"], d),
            "label": "bridge" if e["structure"] > 0.5 else "general",
            "structure": int(e["structure"]),
            "shadow_index": round(float(e["shadow_index"]), 3),
            "risk": round(float(e["risk"]), 3),
            "risk_pct": round(float(e["risk_pct"]), 3),
            "bearing_deg": round(float(b["bearing_deg"]), 1),
            "length_m": round(float(b["length_m"]), 1),
            "osm_ids": sorted({b["way_id"], e["osm_id"]}),
            "near_water": bool(e["water_dist_m"] is not None and e["water_dist_m"] <= NEAR_WATER_M),
        }
    return out


# ── 산출물 ────────────────────────────────────────────────
def write_geojson(segs, path):
    feats = []
    for s in segs:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[round(p[1], 6), round(p[0], 6)] for p in s["coords"]]},
            "properties": {
                "osm_id": s["osm_id"],
                "name": s["name"],
                "highway": s["highway"],
                "bridge": s["bridge"],
                "tunnel": s["tunnel"],
                "structure": int(s["structure"]),
                "shadow_index": round(s["shadow_index"], 3),
                "water_dist_m": None if s["water_dist_m"] is None else round(s["water_dist_m"], 1),
                "risk": round(s["risk"], 3),
                "risk_pct": round(s["risk_pct"], 3),
                "length_m": round(s["length_m"], 1),
            },
        })
    doc = {"type": "FeatureCollection",
           "properties": {"school": {"lat": SCHOOL[0], "lon": SCHOOL[1]},
                          "radius_m": RADIUS_M, "weights": W,
                          "note": "risk는 상대 우선순위(0~1). 절대 결빙확률 아님."},
           "features": feats}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return len(feats)


def write_cross_arms(payload, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def risk_color(risk):
    """0(파랑) → 0.5(노랑) → 1(빨강)."""
    r = max(0.0, min(1.0, risk))
    if r < 0.5:
        t = r / 0.5
        c0, c1 = (147, 197, 253), (250, 204, 21)
    else:
        t = (r - 0.5) / 0.5
        c0, c1 = (250, 204, 21), (220, 38, 38)
    rgb = [int(round(a + (b - a) * t)) for a, b in zip(c0, c1)]
    return "#%02x%02x%02x" % tuple(rgb)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def write_svg(segs, junction, path, water_segs=(), width=1100, pad=64):
    """도로 위험도 색 + 교량 굵게 + 학교·관측소·교차로 표시. 등거리 투영."""
    pts = [p for s in segs for p in s["coords"]]
    pts.append(SCHOOL)
    pts.append(STATION119)
    pts.append((junction["lat"], junction["lon"]))
    xs = [local_xy(la, lo)[0] for la, lo in pts]
    ys = [local_xy(la, lo)[1] for la, lo in pts]
    span_x = max(xs) - min(xs) or 1.0
    span_y = max(ys) - min(ys) or 1.0
    scale = min((width - 2.0 * pad) / span_x, (width - 2.0 * pad) / span_y)
    map_h = span_y * scale + 2.0 * pad
    cx_m = (max(xs) + min(xs)) / 2.0
    cy_m = (max(ys) + min(ys)) / 2.0
    total_h = map_h + 174.0      # 지도 + 아래 정보판
    y_top = pad + span_y / 2.0 + cy_m   # 화면 위쪽 y=pad에 오는 로컬 y

    def m2px(x, y):
        return (width / 2.0 + (x - cx_m) * scale, pad + (y_top - y) * scale)

    def proj(lat, lon):
        x, y = local_xy(lat, lon)
        return m2px(x, y)

    def txt(x, y, label, size=12, anchor="start", weight=400, fill="#0f172a"):
        """지도 위 글자는 흰 테두리를 둘러 도로 색 위에서도 읽히게 한다."""
        return ('<text x="%.1f" y="%.1f" font-size="%s" font-weight="%s" fill="%s" '
                'text-anchor="%s" paint-order="stroke" stroke="#f8fafc" stroke-width="3.5" '
                'stroke-linejoin="round">%s</text>'
                % (x, y, size, weight, fill, anchor, _esc(label)))

    o = []
    o.append('<?xml version="1.0" encoding="UTF-8"?>')
    o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%.0f" '
             'viewBox="0 0 %.0f %.0f" font-family="Helvetica, AppleGothic, sans-serif">'
             % (width, total_h, width, total_h))
    o.append('<rect width="100%" height="100%" fill="#f8fafc"/>')
    o.append('<text x="%.0f" y="30" font-size="20" font-weight="700" fill="#0f172a">'
             '고색고 주변 도로 예측 결빙 위험도(상대 순위) · 반경 %d m</text>'
             % (pad * 0.5, RADIUS_M))
    o.append('<text x="%.0f" y="50" font-size="11" fill="#475569">'
             '자료: OpenStreetMap(ODbL) · ICE-ZERO risk_v2 계열 가중합 · 결빙을 확정하지 않음</text>'
             % (pad * 0.5))

    # 학교 기준 1.5km 범위
    sx, sy = proj(*SCHOOL)
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#cbd5e1" '
             'stroke-width="1" stroke-dasharray="4 6"/>' % (sx, sy, RADIUS_M * scale))

    # 하천
    if water_segs:
        for ax, ay, bx, by, _name in water_segs:
            x1, y1 = m2px(ax, ay)
            x2, y2 = m2px(bx, by)
            o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#7dd3fc" '
                     'stroke-width="1.4" opacity="0.75"/>' % (x1, y1, x2, y2))

    # 도로
    for s in segs:
        (la1, lo1), (la2, lo2) = s["coords"]
        x1, y1 = proj(la1, lo1)
        x2, y2 = proj(la2, lo2)
        w = 5.0 if s["structure"] > 0.5 else 1.5
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                 'stroke-width="%.1f" stroke-linecap="round"/>'
                 % (x1, y1, x2, y2, risk_color(s["risk"]), w))

    # 교량 테두리(굵게)
    for s in segs:
        if s["structure"] <= 0.5:
            continue
        (la1, lo1), (la2, lo2) = s["coords"]
        x1, y1 = proj(la1, lo1)
        x2, y2 = proj(la2, lo2)
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#0f172a" '
                 'stroke-width="7" stroke-opacity="0.16"/>' % (x1, y1, x2, y2))

    # 교차로 갈래(고정 길이 화살선 + 방위 글자만)
    jx, jy = proj(junction["lat"], junction["lon"])
    views = arms_payload(junction)
    for d in DIRS:
        a = views[d]
        rad = math.radians(a["bearing_deg"])
        ex = jx + math.sin(rad) * 78.0
        ey = jy - math.cos(rad) * 78.0
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                 'stroke-width="4" stroke-linecap="round"/>'
                 % (jx, jy, ex, ey, risk_color(a["risk"])))
        lx = jx + math.sin(rad) * 96.0
        ly = jy - math.cos(rad) * 96.0 + 5.0
        o.append(txt(lx, ly, d, size=14, anchor="middle", weight=700))

    # 학교 · 관측소 · 교차로
    o.append('<circle cx="%.1f" cy="%.1f" r="8" fill="#fff" stroke="#0f172a" stroke-width="2.5"/>'
             % (sx, sy))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#64748b" stroke-width="1"/>'
             % (sx, sy, sx - 16, sy - 26))
    o.append(txt(sx - 14, sy - 14, "고색고", size=13, anchor="end", weight=700))
    ax, ay = proj(*STATION119)
    o.append('<rect x="%.1f" y="%.1f" width="12" height="12" fill="#0e7490" stroke="#0f172a"/>'
             % (ax - 6, ay - 6))
    o.append(txt(ax + 11, ay + 4, "수원 ASOS 119 (약 0.4 km)", fill="#0e7490"))
    o.append('<circle cx="%.1f" cy="%.1f" r="7" fill="#7c2d12" stroke="#fff" stroke-width="2"/>'
             % (jx, jy))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#94a3b8" stroke-width="1"/>'
             % (jx, jy + 6, jx + 26, jy + 108))
    o.append(txt(jx + 30, jy + 112, "선정 교차로 (학교 %.0f m)" % junction["dist_school_m"],
                 size=12, weight=700, fill="#7c2d12"))

    # 지도 안 축척·방위
    bar = 500.0 * scale
    o.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#0f172a" stroke-width="2"/>'
             % (pad, map_h - 24, pad + bar, map_h - 24))
    o.append('<text x="%.0f" y="%.0f" font-size="11" fill="#0f172a">500 m</text>'
             % (pad, map_h - 32))
    o.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#0f172a" stroke-width="2"/>'
             % (width - pad, map_h - 30, width - pad, map_h - 62))
    o.append('<path d="M%.0f %.0f L%.0f %.0f L%.0f %.0f z" fill="#0f172a"/>'
             % (width - pad, map_h - 72, width - pad - 6, map_h - 56, width - pad + 6, map_h - 56))
    o.append('<text x="%.0f" y="%.0f" font-size="12" font-weight="700" fill="#0f172a" '
             'text-anchor="middle">N</text>' % (width - pad, map_h - 78))

    # 아래 정보판: 색 범례 · 교량 · 갈래 표
    py = map_h + 30.0
    lx = pad * 0.5
    o.append('<text x="%.0f" y="%.0f" font-size="12" font-weight="700" fill="#0f172a">'
             '위험도 색</text>' % (lx, py))
    for i in range(24):
        o.append('<rect x="%.1f" y="%.1f" width="13" height="12" fill="%s"/>'
                 % (lx + 76 + i * 13, py - 11, risk_color(i / 23.0)))
    o.append('<text x="%.1f" y="%.1f" font-size="11" fill="#475569">0 낮음</text>'
             % (lx + 76, py + 15))
    o.append('<text x="%.1f" y="%.1f" font-size="11" fill="#475569" text-anchor="end">높음 1</text>'
             % (lx + 76 + 24 * 13, py + 15))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#0f172a" '
             'stroke-width="7" stroke-opacity="0.2"/>'
             % (lx + 76, py + 38, lx + 112, py + 38))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#dc2626" stroke-width="5"/>'
             % (lx + 76, py + 38, lx + 112, py + 38))
    o.append('<text x="%.1f" y="%.1f" font-size="11" fill="#475569">교량 구간</text>'
             % (lx + 120, py + 42))
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#7dd3fc" stroke-width="2"/>'
             % (lx + 76, py + 60, lx + 112, py + 60))
    o.append('<text x="%.1f" y="%.1f" font-size="11" fill="#475569">하천·물</text>'
             % (lx + 120, py + 64))
    o.append('<text x="%.1f" y="%.1f" font-size="11" fill="#475569">'
             'risk는 상대 우선순위이며 절대 결빙확률이 아니다. 결빙을 확정하지 않는다.</text>'
             % (lx, py + 88))

    tx = width * 0.52
    o.append('<text x="%.0f" y="%.0f" font-size="12" font-weight="700" fill="#0f172a">'
             '선정 교차로 갈래 · OSM node %s · %.5f, %.5f · 학교 %.0f m</text>'
             % (tx, py, junction["osm_id"], junction["lat"], junction["lon"],
                junction["dist_school_m"]))
    cols = (("방위", 4), ("이름", 36), ("등급", 184), ("교량", 252),
            ("그늘", 292), ("risk", 344))
    for head, dx in cols:
        o.append('<text x="%.0f" y="%.0f" font-size="11" font-weight="700" fill="#475569">'
                 '%s</text>' % (tx + dx, py + 24, head))
    for i, d in enumerate(DIRS):
        a = views[d]
        yy = py + 44 + i * 17
        o.append('<text x="%.0f" y="%.0f" font-size="11" font-weight="700" fill="#0f172a">'
                 '%s</text>' % (tx + 4, yy, d))
        o.append('<text x="%.0f" y="%.0f" font-size="11" fill="#0f172a">%s</text>'
                 % (tx + 36, yy, _esc(a["name"])))
        o.append('<text x="%.0f" y="%.0f" font-size="11" fill="#475569">%s</text>'
                 % (tx + 184, yy, a["label"]))
        o.append('<text x="%.0f" y="%.0f" font-size="11" fill="#475569">%s</text>'
                 % (tx + 252, yy, "O" if a["structure"] else "-"))
        o.append('<text x="%.0f" y="%.0f" font-size="11" fill="#475569">%.2f</text>'
                 % (tx + 292, yy, a["shadow_index"]))
        o.append('<text x="%.0f" y="%.0f" font-size="11" font-weight="700" fill="%s">%.2f</text>'
                 % (tx + 344, yy, risk_color(a["risk"]), a["risk"]))
        o.append('<rect x="%.1f" y="%.1f" width="16" height="10" fill="%s"/>'
                 % (tx + 378, yy - 9, risk_color(a["risk"])))
    o.append('</svg>')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(o) + "\n")
    return width, total_h

# ── 실행 ─────────────────────────────────────────────────
def build_source(roads_payload, segs, buildings, cands, junction, chosen_note):
    arms = arms_payload(junction)
    src = {
        "generated_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "generator": "model/icezero/roads.py",
        "school": {"lat": SCHOOL[0], "lon": SCHOOL[1]},
        "station": {"id": 119, "lat": STATION119[0], "lon": STATION119[1]},
        "radius_m": RADIUS_M,
        "osm_timestamp": osm_timestamp(roads_payload),
        "endpoints": ENDPOINTS,
        "cache_files": ["model/data/roads/overpass_%s.json" % t for t in ("roads", "buildings", "water")],
        "counts": {
            "road_segments": len(segs),
            "buildings": len(buildings),
            "bridge_segments": sum(1 for s in segs if s["structure"] > 0.5),
            "tunnel_segments": sum(1 for s in segs if s["tunnel"]),
            "four_way_candidates": len(cands),
        },
        "weights": W,
        "tunnel_deduct": TUNNEL_DEDUCT,
        "risk_formula": ("risk_raw = 0.40·등급 + 0.30·그림자 + 0.15·하천 + 0.15·구조물 − 0.10·터널, "
                         "risk = 지역 min-max(risk_raw), risk_pct = 지역 백분위"),
        "shadow_formula": ("남쪽 섹터 180°±60°, 80m 안 건물의 높이/거리 합을 2.0에서 포화 "
                           "(높이: height 태그 → building:levels×3.2 → 8m)"),
        "assumptions": [
            "ASOS 119는 단일 지점 관측이라 구간별 유효표면온도 차를 만들 수 없다. risk_v2의 freeze(0.30)+narrow(0.10)를 도로 등급 0.40으로 합쳐 옮겼다.",
            "하천 근접(0.15)은 refreeze_index(0.15)의 대체물이다. 수증기·안개로 재결빙이 잦다는 가정.",
            "교량은 structure=1(상시 가산 0.15). 터널은 원식의 +1.5°C 보정을 −0.10 점수로 바꿨다.",
            "risk는 상대 우선순위이며 절대 결빙확률이 아니다.",
        ],
        "junction": {
            "osm_id": junction["osm_id"],
            "lat": round(junction["lat"], 6),
            "lon": round(junction["lon"], 6),
            "dist_school_m": round(junction["dist_school_m"], 1),
            "score": round(junction["score"], 3),
            "min_sep_deg": round(junction["min_sep_deg"], 1),
            "bridges": [d for d in DIRS if arms[d]["structure"] > 0.5],
            "names": dict((d, arms[d]["name"]) for d in DIRS),
        },
        "note": chosen_note.strip(),
    }
    return src


def run(refresh=False, do_fetch=True):
    payloads = load_osm(refresh=refresh) if do_fetch else load_osm(refresh=False)
    buildings = build_buildings(payloads["buildings"])
    water_segs = build_water(payloads["water"])
    segs = score_segments(build_segments(payloads["roads"], buildings, water_segs))

    seg_by_key = {}
    for s in segs:
        if s["node_a"] is not None:
            seg_by_key[(s["osm_id"], s["node_a"])] = s
    cands = junction_candidates(payloads["roads"], seg_by_key)
    if not cands:
        raise SystemExit("4갈래 교차로 후보를 찾지 못했다(반경 %d m)." % RADIUS_M)

    junction, has_bridge = choose_junction(cands)
    bridge_cands = [c for c in cands if any(c["arms"][d]["edge"]["structure"] > 0.5 for d in DIRS)]
    if has_bridge:
        note = ("반경 %d m 안 4갈래 교차로 후보 %d곳 중 교량 갈래가 있는 %d곳에서 골랐다."
                % (RADIUS_M, len(cands), len(bridge_cands)))
    else:
        note = ("반경 %d m 안 4갈래 교차로 후보 %d곳 중 교량 갈래가 있는 곳이 없어, "
                "교량 없이 가장 나은 곳을 골랐다." % (RADIUS_M, len(cands)))

    arms = arms_payload(junction)
    payload = {"source": build_source(payloads["roads"], segs, buildings, cands,
                                     junction, note),
               "arms": arms}

    os.makedirs(DATA_DIR, exist_ok=True)
    out_geo = os.path.join(DATA_DIR, "gosaek_roads.geojson")
    out_arms = os.path.join(DATA_DIR, "cross_arms.json")
    out_svg = os.path.join(IMG_DIR, "gosaek_map.svg")
    nfeat = write_geojson(segs, out_geo)
    write_cross_arms(payload, out_arms)
    write_svg(segs, junction, out_svg, water_segs)

    print("")
    print("4갈래 후보 %d곳, 교량 갈래 후보 %d곳" % (len(cands), len(bridge_cands)))
    for c in cands[:3]:
        print("  후보 node %d  %.5f,%.5f  학교 %.0f m  점수 %.3f" % (
            c["osm_id"], c["lat"], c["lon"], c["dist_school_m"], c["score"]))
    print("")
    print("선정 교차로 OSM node %d  (%.6f, %.6f)" % (
        junction["osm_id"], junction["lat"], junction["lon"]))
    print("학교에서 %.0f m, 갈래 최소 분리각 %.0f°, 점수 %.3f" % (
        junction["dist_school_m"], junction["min_sep_deg"], junction["score"]))
    print("")
    print("| 방위 | 이름 | 등급 | 교량 | 그늘 | risk | pct | 방위각 | 길이(m) | 하천근접 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for d in DIRS:
        a = arms[d]
        e = junction["arms"][d]["edge"]
        print("| %s | %s | %s | %s | %.2f | %.3f | %.3f | %.1f | %.0f | %s |" % (
            d, a["name"], e["highway"], "O" if a["structure"] else "-", a["shadow_index"],
            a["risk"], a["risk_pct"], a["bearing_deg"], a["length_m"],
            "O" if a["near_water"] else "-"))
    print("")
    print("구간 %d개(교량 %d, 터널 %d), 건물 %d개" % (
        len(segs), sum(1 for s in segs if s["structure"] > 0.5),
        sum(1 for s in segs if s["tunnel"]), len(buildings)))
    print("저장: %s (%d features)" % (os.path.relpath(out_geo, ROOT), nfeat))
    print("저장: %s" % os.path.relpath(out_arms, ROOT))
    print("저장: %s" % os.path.relpath(out_svg, ROOT))
    print("")
    print("주의: risk는 상대 우선순위다. 절대 결빙확률이 아니다.")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="고색고 주변 도로 위험도·교차로 갈래 생성")
    ap.add_argument("--refresh", action="store_true", help="Overpass 캐시를 버리고 다시 받는다")
    args = ap.parse_args(argv)
    run(refresh=args.refresh)


if __name__ == "__main__":
    main()
