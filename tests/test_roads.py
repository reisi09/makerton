# -*- coding: utf-8 -*-
"""model/icezero/roads.py 순수 함수 시험. 네트워크·Overpass 캐시는 쓰지 않는다.

합성 자료만 쓴다: 좌표는 고색고 주변 위경도에 100m 격자로 찍는다.
"""
import json
import os
import shutil
import tempfile
import unittest

from model.icezero import roads


def _payload(nodes, ways, ts="2026-01-01T00:00:00Z"):
    els = [{"type": "node", "id": k, "lat": v[0], "lon": v[1]} for k, v in nodes.items()]
    els += [{"type": "way", "id": w[0], "tags": w[1], "nodes": w[2]} for w in ways]
    return {"elements": els, "osm3s": {"timestamp_osm_base": ts}}


# 고색고 기준 100m 오프셋(위도 1도≈111.1km, 이 위도에서 경도 1도≈88.7km)
LAT = roads.SCHOOL[0]
LON = roads.SCHOOL[1]
DN = 100.0 / 111132.0        # 북쪽 100m
DE = 100.0 / 88700.0         # 동쪽 100m


def plus_payload(bridge_ew=False, footway=False):
    """십자 교차로: 동서(way 1), 남북(way 2), 중심 node 100."""
    nodes = {
        100: (LAT, LON),
        1: (LAT, LON + DE), 2: (LAT, LON - DE),
        3: (LAT + DN, LON), 4: (LAT - DN, LON),
    }
    tags_ew = {"highway": "residential", "name": "동서로"}
    if bridge_ew:
        tags_ew["bridge"] = "yes"
    ways = [(1, tags_ew, [2, 100, 1]),
            (2, {"highway": "tertiary", "name": "남북로"}, [3, 100, 4])]
    if footway:
        nodes[5] = (LAT + DN, LON + DE)
        nodes[6] = (LAT - DN, LON - DE)
        ways.append((3, {"highway": "footway"}, [5, 100, 6]))
    return _payload(nodes, ways)


def empty_payload():
    return {"elements": [], "osm3s": {"timestamp_osm_base": "2026-01-01T00:00:00Z"}}


class TestGeometry(unittest.TestCase):
    def test_haversine(self):
        d = roads.haversine_m(37.25378, 126.98246, 37.25378 + 0.01, 126.98246)
        self.assertAlmostEqual(d, 1111.9, delta=5.0)
        self.assertAlmostEqual(roads.haversine_m(LAT, LON, LAT, LON), 0.0, places=6)

    def test_bearing_cardinal(self):
        self.assertAlmostEqual(roads.bearing_deg(LAT, LON, LAT + DN, LON), 0.0, delta=0.5)
        self.assertAlmostEqual(roads.bearing_deg(LAT, LON, LAT, LON + DE), 90.0, delta=0.5)
        self.assertAlmostEqual(roads.bearing_deg(LAT, LON, LAT - DN, LON), 180.0, delta=0.5)
        self.assertAlmostEqual(roads.bearing_deg(LAT, LON, LAT, LON - DE), 270.0, delta=0.5)

    def test_bearing_to_dir(self):
        cases = [(0, "N"), (10, "N"), (44, "N"), (46, "E"), (90, "E"),
                 (134, "E"), (136, "S"), (180, "S"), (225, "W"), (270, "W"),
                 (315, "N"), (359, "N"), (-90 % 360, "W")]
        for b, want in cases:
            self.assertEqual(roads.bearing_to_dir(b), want, b)

    def test_angle_diff(self):
        self.assertAlmostEqual(roads.angle_diff(10, 350), 20.0)
        self.assertAlmostEqual(roads.angle_diff(0, 180), 180.0)

    def test_point_segment(self):
        # (0,10)에서 (0,0)-(0,20) 선분까지 10
        self.assertAlmostEqual(roads.point_segment_m(10, 10, 0, 0, 0, 20), 10.0)
        # 수선의 발이 선분 밖이면 끝점 거리
        self.assertAlmostEqual(roads.point_segment_m(10, 30, 0, 0, 0, 20), (100 + 100) ** 0.5)
        self.assertAlmostEqual(roads.point_segment_m(3, 4, 0, 0, 0, 0), 5.0)


class TestShadow(unittest.TestCase):
    def test_south_building_shadows(self):
        # 도로 남쪽 25m, 높이 25m → 기여 1.0 → 1.0/2.0 포화 = 0.5
        b = {"lat": LAT - 25.0 / 111132.0, "lon": LON, "height_m": 25.0}
        self.assertAlmostEqual(roads.shadow_index(LAT, LON, [b]), 0.5, places=3)

    def test_north_building_ignored(self):
        b = {"lat": LAT + 25.0 / 111132.0, "lon": LON, "height_m": 40.0}
        self.assertEqual(roads.shadow_index(LAT, LON, [b]), 0.0)

    def test_east_west_outside_sector(self):
        b = {"lat": LAT, "lon": LON + 25.0 / 88700.0, "height_m": 40.0}
        self.assertEqual(roads.shadow_index(LAT, LON, [b]), 0.0)

    def test_distance_limit(self):
        far = {"lat": LAT - 200.0 / 111132.0, "lon": LON, "height_m": 40.0}
        self.assertEqual(roads.shadow_index(LAT, LON, [far]), 0.0)

    def test_monotone_and_saturates(self):
        near = {"lat": LAT - 20.0 / 111132.0, "lon": LON, "height_m": 30.0}
        far = {"lat": LAT - 60.0 / 111132.0, "lon": LON, "height_m": 30.0}
        s_near = roads.shadow_index(LAT, LON, [near])
        s_far = roads.shadow_index(LAT, LON, [far])
        self.assertGreater(s_near, s_far)
        many = [{"lat": LAT - (20 + 5 * i) / 111132.0, "lon": LON, "height_m": 30.0} for i in range(8)]
        self.assertLessEqual(roads.shadow_index(LAT, LON, many), 1.0)
        self.assertAlmostEqual(roads.shadow_index(LAT, LON, many), 1.0, places=3)

    def test_building_height_parse(self):
        self.assertAlmostEqual(roads.building_height({"height": "42"}), 42.0)
        self.assertAlmostEqual(roads.building_height({"height": "42 m"}), 42.0)
        self.assertAlmostEqual(roads.building_height({"building:levels": "5"}), 16.0)
        self.assertAlmostEqual(roads.building_height({}), roads.BUILDING_DEFAULT_H)


class TestNormalize(unittest.TestCase):
    def test_percentile_rank(self):
        self.assertEqual(roads.percentile_rank([1, 2, 3, 4]), [0.25, 0.5, 0.75, 1.0])
        # 동점은 평균 순위(pandas rank(pct=True, method='average')와 같은 값)
        self.assertEqual(roads.percentile_rank([5, 5, 5, 5]), [0.625] * 4)
        got = roads.percentile_rank([1, 2, 2, 3])
        self.assertAlmostEqual(got[0], 0.25)
        self.assertAlmostEqual(got[1], 0.625)
        self.assertAlmostEqual(got[3], 1.0)
        self.assertEqual(roads.percentile_rank([]), [])

    def test_minmax(self):
        self.assertEqual(roads.minmax([0, 5, 10]), [0.0, 0.5, 1.0])
        self.assertEqual(roads.minmax([3, 3]), [0.5, 0.5])
        self.assertEqual(roads.minmax([]), [])


class TestRisk(unittest.TestCase):
    def test_class_risk_order(self):
        self.assertLess(roads.class_risk("primary"), roads.class_risk("tertiary"))
        self.assertLess(roads.class_risk("tertiary"), roads.class_risk("residential"))
        self.assertLess(roads.class_risk("residential"), roads.class_risk("service"))
        self.assertAlmostEqual(roads.class_risk("primary_link"), roads.class_risk("primary") + 0.05)

    def test_water_component(self):
        self.assertAlmostEqual(roads.water_component(0.0), 1.0)
        self.assertAlmostEqual(roads.water_component(150.0), 0.5)
        self.assertAlmostEqual(roads.water_component(300.0), 0.0)
        self.assertAlmostEqual(roads.water_component(900.0), 0.0)
        self.assertAlmostEqual(roads.water_component(None), 0.0)

    def test_weights_sum(self):
        self.assertAlmostEqual(sum(roads.W.values()), 1.0, places=9)

    def test_bridge_and_tunnel(self):
        base = roads.risk_raw(0.5, 0.4, 0.2, 0.0, False)
        bridge = roads.risk_raw(0.5, 0.4, 0.2, 1.0, False)
        tunnel = roads.risk_raw(0.5, 0.4, 0.2, 0.0, True)
        self.assertAlmostEqual(bridge - base, 0.15, places=9)
        self.assertAlmostEqual(base - tunnel, 0.10, places=9)


class TestArms(unittest.TestCase):
    def _branch(self, bearing, length, name="로", way=1):
        return {"bearing_deg": bearing, "length_m": length, "way_name": name,
                "way_id": way, "edge": None}

    def test_assign_four(self):
        arms = roads.assign_arms([self._branch(2, 50), self._branch(92, 50),
                                  self._branch(185, 50), self._branch(268, 50)])
        self.assertEqual(sorted(arms), ["E", "N", "S", "W"])
        self.assertAlmostEqual(arms["N"]["bearing_deg"], 2)

    def test_assign_longest_wins(self):
        arms = roads.assign_arms([self._branch(350, 20, "짧은로"), self._branch(10, 60, "긴로")])
        self.assertEqual(sorted(arms), ["N"])
        self.assertEqual(arms["N"]["way_name"], "긴로")

    def test_assign_three(self):
        arms = roads.assign_arms([self._branch(0, 50), self._branch(90, 50), self._branch(180, 50)])
        self.assertEqual(sorted(arms), ["E", "N", "S"])

    def test_arm_name(self):
        self.assertEqual(roads.arm_name("매송고색로", "N"), "매송고색로")
        self.assertEqual(roads.arm_name(None, "E"), "동 방면 무명도로")


class TestJunctionScore(unittest.TestCase):
    def test_closer_is_better(self):
        near = roads.junction_score(100, [0.2, 0.8, 0.3, 0.6], [0, 0, 0, 0], [0.1, 0.2, 0.0, 0.1])
        far = roads.junction_score(1400, [0.2, 0.8, 0.3, 0.6], [0, 0, 0, 0], [0.1, 0.2, 0.0, 0.1])
        self.assertGreater(near, far)

    def test_spread_matters(self):
        flat = roads.junction_score(400, [0.5, 0.5, 0.5, 0.5], [0, 0, 0, 0], [0, 0, 0, 0])
        wide = roads.junction_score(400, [0.1, 0.9, 0.2, 0.8], [0, 0, 0, 0], [0, 0, 0, 0])
        self.assertGreater(wide, flat)

    def test_bridge_and_shadow_help(self):
        plain = roads.junction_score(300, [0.1, 0.9, 0.2, 0.7], [0, 0, 0, 0], [0, 0, 0, 0])
        bridged = roads.junction_score(300, [0.1, 0.9, 0.2, 0.7], [0, 1, 0, 0], [0, 0, 0, 0])
        shaded = roads.junction_score(300, [0.1, 0.9, 0.2, 0.7], [0, 0, 0, 0], [0.6, 0.3, 0, 0])
        self.assertGreater(bridged, plain)
        self.assertGreater(shaded, plain)

    def test_empty(self):
        self.assertEqual(roads.junction_score(100, [], [], []), 0.0)


class TestPipelineSynthetic(unittest.TestCase):
    def _segments(self, bridge_ew=False):
        roads_payload = plus_payload(bridge_ew=bridge_ew)
        buildings = roads.build_buildings(empty_payload())
        return roads_payload, roads.score_segments(
            roads.build_segments(roads_payload, buildings, []))

    def test_segments_and_risk_bounds(self):
        roads_payload, segs = self._segments()
        self.assertEqual(len(segs), 4)          # 동서 2 + 남북 2
        for s in segs:
            self.assertGreaterEqual(s["risk"], 0.0)
            self.assertLessEqual(s["risk"], 1.0)
            self.assertGreaterEqual(s["risk_pct"], 0.0)
            self.assertLessEqual(s["risk_pct"], 1.0)
            self.assertAlmostEqual(s["length_m"], 100.0, delta=2.0)

    def test_pedestrian_way_excluded(self):
        roads_payload = plus_payload(footway=True)
        segs = roads.build_segments(roads_payload, [], [])
        self.assertFalse(any(s["highway"] == "footway" for s in segs))
        self.assertEqual(len(segs), 4)

    def test_bridge_has_higher_risk(self):
        _p, segs = self._segments(bridge_ew=True)
        ew = [s for s in segs if s["highway"] == "residential"]
        ns = [s for s in segs if s["highway"] == "tertiary"]
        self.assertTrue(all(s["structure"] == 1.0 for s in ew))
        self.assertTrue(all(s["structure"] == 0.0 for s in ns))
        # 같은 자료 안에서 교량 갈래가 그렇지 않은 갈래보다 위험하다
        self.assertGreater(min(s["risk"] for s in ew), max(s["risk"] for s in ns))

    def test_junction_candidates(self):
        roads_payload, segs = self._segments(bridge_ew=True)
        key = {}
        for s in segs:
            if s["node_a"] is not None:
                key[(s["osm_id"], s["node_a"])] = s
        cands = roads.junction_candidates(roads_payload, key)
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(sorted(c["arms"]), ["E", "N", "S", "W"])
        for d in roads.DIRS:
            self.assertIsNotNone(c["arms"][d]["edge"])
        self.assertGreaterEqual(c["min_sep_deg"], 40.0)
        self.assertGreater(c["score"], 0.0)
        arms = roads.arms_payload(c)
        self.assertEqual(sorted(arms), ["E", "N", "S", "W"])
        for d in roads.DIRS:
            a = arms[d]
            for k in ("name", "label", "structure", "shadow_index", "risk", "risk_pct",
                      "bearing_deg", "length_m", "osm_ids", "near_water"):
                self.assertIn(k, a)
            self.assertIn(a["label"], ("bridge", "general"))
        self.assertEqual(arms["E"]["label"], "bridge")
        self.assertEqual(arms["E"]["name"], "동서로")
        self.assertEqual(arms["N"]["label"], "general")

    def test_choose_junction_prefers_bridge(self):
        _p, segs = self._segments(bridge_ew=True)
        key = {}
        for s in segs:
            if s["node_a"] is not None:
                key[(s["osm_id"], s["node_a"])] = s
        cands = roads.junction_candidates(plus_payload(bridge_ew=True), key)
        plain = dict(cands[0])
        plain["arms"] = dict((d, dict(a)) for d, a in cands[0]["arms"].items())
        for d in roads.DIRS:
            edge = dict(plain["arms"][d]["edge"])
            edge["structure"] = 0.0
            plain["arms"][d] = dict(plain["arms"][d], edge=edge)
        plain["score"] = 99.0        # 점수는 더 높지만 교량 갈래가 없다
        picked, has_bridge = roads.choose_junction([plain, cands[0]])
        self.assertTrue(has_bridge)
        self.assertEqual(picked["osm_id"], cands[0]["osm_id"])
        picked2, has_bridge2 = roads.choose_junction([plain])
        self.assertFalse(has_bridge2)
        self.assertEqual(picked2["osm_id"], plain["osm_id"])
        with self.assertRaises(ValueError):
            roads.choose_junction([])

    def test_water_distance(self):
        # 하천을 동서 도로 남쪽 30m에 둔다: 동서 갈래 30m, 남북 갈래 남쪽 20m/북쪽 80m
        water_nodes = {200: (LAT - 30.0 / 111132.0, LON - DE),
                       201: (LAT - 30.0 / 111132.0, LON + DE)}
        water = _payload(water_nodes, [(9, {"waterway": "stream", "name": "고색천"}, [200, 201])])
        segs = roads.build_segments(plus_payload(), [], roads.build_water(water))
        ew = [s for s in segs if s["highway"] == "residential"]
        ns = [s for s in segs if s["highway"] == "tertiary"]
        self.assertEqual(len(ew), 2)
        for s in ew:
            self.assertAlmostEqual(s["water_dist_m"], 30.0, delta=3.0)
        north = max(ns, key=lambda s: s["mid"][0])
        south = min(ns, key=lambda s: s["mid"][0])
        self.assertAlmostEqual(north["water_dist_m"], 80.0, delta=3.0)
        self.assertAlmostEqual(south["water_dist_m"], 20.0, delta=3.0)
        self.assertGreater(roads.water_component(south["water_dist_m"]),
                           roads.water_component(north["water_dist_m"]))
        self.assertAlmostEqual(roads.water_component(30.0), 0.9, places=6)
        # 300m 밖은 None
        far = roads.build_segments(plus_payload(), [], roads.build_water(_payload(
            {300: (LAT - 900.0 / 111132.0, LON), 301: (LAT - 900.0 / 111132.0, LON + DE)},
            [(8, {"waterway": "stream"}, [300, 301])])))
        self.assertTrue(all(s["water_dist_m"] is None for s in far))


class TestWriters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="roads_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self):
        roads_payload = plus_payload(bridge_ew=True)
        segs = roads.score_segments(roads.build_segments(roads_payload, [], []))
        key = {}
        for s in segs:
            if s["node_a"] is not None:
                key[(s["osm_id"], s["node_a"])] = s
        cands = roads.junction_candidates(roads_payload, key)
        junction, _ = roads.choose_junction(cands)
        return roads_payload, segs, cands, junction

    def test_geojson_and_cross_arms(self):
        roads_payload, segs, cands, junction = self._build()
        geo = os.path.join(self.tmp, "roads.geojson")
        arms_path = os.path.join(self.tmp, "cross_arms.json")
        n = roads.write_geojson(segs, geo)
        self.assertEqual(n, len(segs))
        with open(geo, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["type"], "FeatureCollection")
        self.assertEqual(len(doc["features"]), len(segs))
        feat = doc["features"][0]
        self.assertEqual(feat["geometry"]["type"], "LineString")
        self.assertEqual(len(feat["geometry"]["coordinates"][0]), 2)

        arms = roads.arms_payload(junction)
        src = roads.build_source(roads_payload, segs, [], cands, junction, "시험")
        roads.write_cross_arms({"source": src, "arms": arms}, arms_path)
        with open(arms_path, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(sorted(doc), ["arms", "source"])
        self.assertEqual(sorted(doc["arms"]), ["E", "N", "S", "W"])
        self.assertEqual(doc["source"]["junction"]["osm_id"], junction["osm_id"])
        self.assertIn("weights", doc["source"])
        self.assertEqual(doc["source"]["osm_timestamp"], "2026-01-01T00:00:00Z")
        self.assertAlmostEqual(sum(doc["source"]["weights"].values()), 1.0, places=9)

    def test_svg(self):
        _p, segs, _c, junction = self._build()
        path = os.path.join(self.tmp, "map.svg")
        w, h = roads.write_svg(segs, junction, path)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("<svg", text)
        self.assertIn("</svg>", text)
        self.assertIn("고색고", text)
        self.assertIn("수원 ASOS 119", text)
        self.assertIn("선정 교차로", text)
        self.assertGreater(text.count("<line"), len(segs))
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_risk_color(self):
        self.assertEqual(roads.risk_color(0.0), "#93c5fd")
        self.assertEqual(roads.risk_color(1.0), "#dc2626")
        mid = roads.risk_color(0.5)
        self.assertTrue(mid.startswith("#"))
        self.assertEqual(len(mid), 7)


if __name__ == "__main__":
    unittest.main()
