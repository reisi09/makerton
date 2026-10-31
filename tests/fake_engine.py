"""계약 3절 step JSON 모양을 흉내 내는 가짜 엔진. 시험·모의 시연용.

Engine 클래스 이름·메서드 이름은 model/icezero/engine.py 와 같다.
GOSAEK_ENGINE=tests.fake_engine 로 서버에 끼울 수 있다.
"""

import datetime

ARMS = ("N", "E", "S", "W")
NIGHTS = ("2025-01-09", "2025-01-10")

# 갈래별 가짜 값. risk·우선순위는 계약 4절 cross_arms.json 과 같은 모양이다.
# 실제 도로명을 쓰지 않는다. 모형의 임의 도로 이름만 쓴다(참고: model/data/roads/cross_arms.json).
ARM_SPEC = {
    "N": {"name": "북쪽 도로", "label": "general", "structure": 0,
          "shadow_index": 0.22, "risk": 0.44, "risk_pct": 0.41, "p": 0.18},
    "E": {"name": "동쪽 도로(학교 앞)", "label": "general", "structure": 1,
          "shadow_index": 0.08, "risk": 0.91, "risk_pct": 0.97, "p": 0.90},
    "S": {"name": "남쪽 도로(기지 진입로)", "label": "general", "structure": 0,
          "shadow_index": 0.36, "risk": 0.38, "risk_pct": 0.33, "p": 0.12},
    "W": {"name": "서쪽 도로", "label": "general", "structure": 0,
          "shadow_index": 0.61, "risk": 0.72, "risk_pct": 0.78, "p": 0.55},
}

METHOD = {"h1": "blend", "h3": "reg", "h6": "clf"}
RMSE = {"h1": 0.84, "h3": 1.12, "h6": 1.47}
PERSISTENCE = {"h1": 1.31, "h3": 2.02, "h6": 2.44}
BRIER = {"h1": 0.082, "h3": 0.101, "h6": 0.124}


def _round(value, digits=3):
    return round(float(value), digits)


def timeline_of(night):
    """재생 시각: 18:00 부터 다음 날 09:00 까지 16개(계약 3절)."""
    start = datetime.datetime.strptime(str(night)[:10] + "T18:00:00", "%Y-%m-%dT%H:%M:%S")
    return [(start + datetime.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S")
            for i in range(16)]


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


class FakeEngine(object):
    """Engine 과 같은 메서드. 값은 계약 3절 JSON 모양을 따른다."""

    stations = ("119",)          # 지점 모델이 있다고 가정하는 목록
    nights_list = NIGHTS

    def __init__(self, stn="119", models_dir=None, arms_path=None):
        self.stn = str(stn)
        self.models_dir = models_dir
        self.arms_path = arms_path
        self.loaded = False
        self.calls = []

    # -- 수명 --------------------------------------------------------------
    def load(self):
        self.loaded = True
        return self

    def available(self):
        return self.stn in self.stations

    # -- 자료 --------------------------------------------------------------
    def nights(self):
        return [{"night": n} for n in self.nights_list]

    @property
    def default_night(self):
        return self.nights_list[0]

    def timeline(self, night):
        return timeline_of(night)

    # -- 계산 --------------------------------------------------------------
    def step(self, ts, local=None, treated=None, budget=2):
        ts = str(ts)
        local = local or {}
        treated = treated or {}
        self.calls.append({"ts": ts, "local": dict(local), "treated": dict(treated),
                           "budget": budget})
        hour = int(ts[11:13])
        step_no = (hour - 18) % 24
        ground = _round(5.6 - 0.55 * step_no)
        forecast = {"h0": _round(ground - 0.1), "h1": _round(ground - 0.4),
                    "h3": _round(ground - 0.9), "h6": _round(ground - 0.7)}

        arms = {}
        candidates = []
        for order_no, arm in enumerate(ARMS):
            spec = ARM_SPEC[arm]
            entry = local.get(arm) or {}
            dt = _round(_clip(float(entry.get("dt") or 0.0), -6.0, 3.0))
            wet = bool(entry.get("wet"))
            t_eff = {}
            p_freeze = {}
            for key, hours in (("h0", 0), ("h1", 1), ("h3", 3), ("h6", 6)):
                t_eff[key] = _round(forecast[key] - 2.5 * spec["structure"] + dt)
                p_freeze[key] = _round(_clip(spec["p"] + dt * 0.05 - 0.01 * hours, 0.0, 1.0))
            p_max = max(p_freeze["h1"], p_freeze["h3"], p_freeze["h6"])
            if p_max >= 0.6:
                level = "risk3"
            elif p_max >= 0.3:
                level = "risk2"
            else:
                level = "risk1"
            end = treated.get(arm)
            is_treated = bool(end) and ts < str(end)
            if is_treated:
                level = "done"
            candidate = (p_max >= 0.5) and not is_treated
            priority = 0.0 if is_treated else _round(spec["risk"] + (0.3 if wet else 0.0))
            reasons = []
            if spec["structure"]:
                reasons.append("교량(−2.5°C 가정)")
            if abs(dt) >= 0.05:
                reasons.append("현장 %+.1f°C" % dt)
            reasons.append("예측 동결확률 %.2f(+3h)" % p_max)
            if is_treated:
                reasons.append("처리됨(%s까지)" % str(end)[11:16])
            arms[arm] = {
                "name": spec["name"], "label": spec["label"],
                "structure": spec["structure"], "shadow_index": spec["shadow_index"],
                "risk": spec["risk"], "risk_pct": spec["risk_pct"],
                "local_dt": dt, "wet": wet,
                "t_eff": t_eff, "p_freeze": p_freeze, "p_max": _round(p_max),
                "source": "model+local" if (dt or wet) else "model",
                "level": level, "candidate": candidate, "treated": is_treated,
                "priority": priority, "reasons": reasons,
            }
            if candidate:
                candidates.append((arm, priority, order_no))

        candidates.sort(key=lambda item: (-item[1], item[2]))
        order = [arm for arm, _p, _i in candidates[:max(0, int(budget))]]
        return {
            "time": ts,
            "station": self.stn,
            "obs": {"temp": _round(ground + 0.6), "humidity": 82,
                    "wind": 1.2, "precip": 0.0, "snow": 0.0, "ground_temp": ground},
            "forecast": forecast,
            "arms": arms,
            "dispatch": {"recommend": bool(order), "selected": order, "order": order,
                         "budget": int(budget), "threshold": 0.5},
            "model": {"name": "ICE-ZERO 가짜 엔진(시험용)", "station": self.stn,
                      "method": dict(METHOD), "rmse": dict(RMSE),
                      "persistence_rmse": dict(PERSISTENCE), "brier": dict(BRIER)},
            "notes": ["가짜 엔진: 계약 3절 JSON 모양만 흉내 냅니다"],
        }


class Only108Engine(FakeEngine):
    """119 모델이 없는 상황. 108 만 쓸 수 있다."""

    stations = ("108",)


# GOSAEK_ENGINE=tests.fake_engine 로 서버에 끼울 때 쓰는 이름
Engine = FakeEngine
