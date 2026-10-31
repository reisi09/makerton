#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수원 ASOS(119) 시간자료를 기상청 API로 받아 기상자료개방포털 CSV 형식으로 저장한다.

makerton/model/icezero/kma.py '형식 2'(OBS_ASOS_TIM_*.csv)의 열 이름을 그대로 쓰므로
결과 파일을 model/data/raw/119/에 두면 바로 학습에 들어간다.

인증키는 환경변수 KMA_AUTH_KEY로 받는다. 없으면 화면에서 입력받는다(셸 기록에 남지 않게).
    python3 fetch_asos.py                       # API Hub(apihub.kma.go.kr) 키 → kma_sfctm3.php(텍스트)
    python3 fetch_asos.py --provider datagokr   # 공공데이터포털(data.go.kr) 키 → AsosHourlyInfoService(JSON)
    python3 tools/fetch_asos.py --qc-file model/data/source/119/OBS_ASOS_TIM_119_api.csv \
        --out model/data/raw/119/OBS_ASOS_TIM_119_api.csv     # 원본은 두고 QC 정리본만 만든다

typ01 텍스트는 결측을 -9.0으로 적는다. 실제 -9.0°C와 구별해 기온·지면온도의 결측 표시와
한 시간짜리 튐을 빈칸으로 바꾼다(qc_values). 2026-10-31 수원 119 파일에 적용했다.
"""
import argparse
import csv
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HUB_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
DATAGOKR_URL = "https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"
# 서울 108 학습 자료와 같은 달
WINTER_MONTHS = (1, 2, 11, 12)
# 포털 원본 열 이름 ← 행 필드(data.go.kr 필드 이름을 기준으로 쓴다)
COLUMNS = (
    ("지점", "stnId"), ("일시", "tm"),
    ("기온(°C)", "ta"), ("강수량(mm)", "rn"), ("풍속(m/s)", "ws"), ("습도(%)", "hm"),
    ("일조(hr)", "ss"), ("일사(MJ/m2)", "icsr"), ("적설(cm)", "dsnw"), ("지면온도(°C)", "ts"),
)
# API Hub 열 이름 → 행 필드
HUB_FIELDS = {"TM": "tm", "STN": "stnId", "TA": "ta", "RN": "rn", "WS": "ws", "HM": "hm",
              "SS": "ss", "SI": "icsr", "SD_TOT": "dsnw", "TS": "ts"}
# help=1 열 설명이 없을 때 쓰는 kma_sfctm2/3 열 순서(46열)
HUB_DEFAULT_ORDER = (
    "TM STN WD WS GST_WD GST_WS GST_TM PA PS PT PR TA TD HM PV RN RN_DAY RN_JUN RN_INT "
    "SD_HR3 SD_DAY SD_TOT WC WP WW CA_TOT CA_MID CH_MIN CT CT_TOP CT_MID CT_LOW VS SS SI "
    "ST_GD TS TE_005 TE_01 TE_02 TE_03 ST_SEA WH BF IR IX"
).split()
PAGE_ROWS = 999
SENTINEL = -9.0          # typ01 텍스트의 결측 표시(실제 -9.0°C와 구별해야 한다)
SPIKE_C = 8.0            # 앞뒤 값과 모두 이만큼 넘게 다르고
AGREE_C = 3.0            # 앞뒤 두 값은 서로 이만큼 안에서 비슷하면 한 시간짜리 튐이다
MAX_SENTINEL_RUN = 6     # -9.0이 이보다 길게 이어지면 앞뒤가 -9 근처여도 멈춘 센서로 본다


class ApiError(RuntimeError):
    pass


def month_ranges(first_year, last_year, today):
    """겨울 달마다 (첫날, 끝날). 31일 조회 제한 안이고, 자료는 전날까지만 있으므로 끝날을 자른다."""
    for year in range(first_year, last_year + 1):
        for month in WINTER_MONTHS:
            start = date(year, month, 1)
            end = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
            end = min(end, today - timedelta(days=1))
            if start <= end:
                yield start, end


def json_error(text):
    """게이트웨이·서비스가 JSON으로 돌려준 오류를 ApiError로 바꾼다. 오류가 아니면 dict를 돌려준다."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ApiError("JSON이 아닌 응답: %s" % text[:200].strip())
    if "OpenAPI_ServiceResponse" in data:  # 공공데이터포털 게이트웨이 오류(키 미등록 등)
        head = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
        raise ApiError("%s %s" % (head.get("errMsg"), head.get("returnAuthMsg")))
    if "response" not in data:  # API Hub 오류: {"result": {"status": 401, "message": ...}}
        result = data.get("result", {})
        raise ApiError("%s %s" % (result.get("status", "?"), result.get("message", text[:200])))
    return data


def parse_datagokr(text):
    """data.go.kr JSON 한 쪽 → (행 목록, 전체 행 수)."""
    data = json_error(text)
    header = data["response"]["header"]
    code = header.get("resultCode")
    if code == "03":  # NODATA_ERROR: 그 기간에 자료가 없다
        return [], 0
    if code != "00":
        raise ApiError("%s %s" % (code, header.get("resultMsg")))
    body = data["response"]["body"]
    items = body.get("items") or {}
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    return rows, int(body.get("totalCount") or 0)


def hub_value(name, raw):
    """API Hub 결측 표기(-9, -99 등)를 빈칸으로 바꾼다. 영하 기온·지면온도는 살린다."""
    try:
        v = float(raw)
    except ValueError:
        return ""
    if name in ("TA", "TS"):
        return "" if v <= -50 else raw
    return "" if v < 0 else raw  # 강수·적설 음수 = 없음(포털 원본도 빈칸), 나머지는 결측


def parse_hub(text):
    """kma_sfctm3.php 텍스트 → (행 목록, 열 수가 안 맞아 버린 행 수)."""
    if text.lstrip().startswith("{"):
        json_error(text)
        raise ApiError("예상하지 못한 JSON 응답: %s" % text[:200].strip())
    # help=1이면 '#  1. TM  : 관측시각' 꼴의 열 설명이 온다. 있으면 그 순서를 쓴다.
    described = {}
    for m in re.finditer(r"^#\s*(\d+)\.\s*([A-Z][A-Z0-9_]*)\s*:", text, re.M):
        described[m.group(2)] = int(m.group(1)) - 1
    if all(k in described for k in HUB_FIELDS):
        index, width = described, len(described)
    else:
        index, width = {n: i for i, n in enumerate(HUB_DEFAULT_ORDER)}, len(HUB_DEFAULT_ORDER)
    rows, bad = [], 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if len(parts) != width:
            bad += 1
            continue
        row = {field: hub_value(name, parts[index[name]]) for name, field in HUB_FIELDS.items()}
        tm = parts[index["TM"]]
        row["tm"] = "%s-%s-%s %s:%s" % (tm[:4], tm[4:6], tm[6:8], tm[8:10], tm[10:12])
        row["stnId"] = parts[index["STN"]]
        rows.append(row)
    return rows, bad


def get(url):
    """GET 본문. 네트워크 오류만 세 번까지 다시 시도한다. HTTP 오류 본문은 그대로 돌려준다."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                raw = resp.read()
            break
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise ApiError("네트워크 오류(세 번 실패)")
            time.sleep(2 * (attempt + 1))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", "replace")  # typ01 텍스트는 EUC-KR로 올 수 있다


def fetch_hub(base_url, key, stn, start, end):
    params = {"tm1": start.strftime("%Y%m%d0000"), "tm2": end.strftime("%Y%m%d2300"),
              "stn": stn, "help": 1, "authKey": key}
    rows, bad = parse_hub(get(base_url + "?" + urllib.parse.urlencode(params)))
    if bad > max(5, len(rows) // 20):
        raise ApiError("%s: 열 수가 안 맞는 행 %d개(정상 %d개) — 응답 형식이 예상과 다르다" % (
            start.strftime("%Y-%m"), bad, len(rows)))
    return rows


def fetch_datagokr(base_url, key, stn, start, end):
    rows, page = [], 1
    while True:
        params = {
            "serviceKey": key, "pageNo": page, "numOfRows": PAGE_ROWS, "dataType": "JSON",
            "dataCd": "ASOS", "dateCd": "HR", "stnIds": stn,
            "startDt": start.strftime("%Y%m%d"), "startHh": "00",
            "endDt": end.strftime("%Y%m%d"), "endHh": "23",
        }
        items, total = parse_datagokr(get(base_url + "?" + urllib.parse.urlencode(params)))
        rows.extend(items)
        if not items or len(rows) >= total:
            return rows
        page += 1


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def qc_values(values):
    """시간순 기온·지면온도 목록에서 결측 표시(-9.0)와 한 시간짜리 튐을 None으로 바꾼다.

    앞뒤 값이 -9°C 근처(±2)가 아니거나, -9.0이 MAX_SENTINEL_RUN시간보다 길게 이어지면 결측 표시로 본다.
    앞뒤가 -8.9 · -9.1 같은 실제 -9.0°C는 몇 시간 이어져도 남긴다(추운 밤에 흔하다).
    """
    v = [_num(x) for x in values]
    n = len(v)
    i = 0
    while i < n:
        if v[i] != SENTINEL:
            i += 1
            continue
        j = i
        while j + 1 < n and v[j + 1] == SENTINEL:
            j += 1
        sides = (v[i - 1] if i > 0 else None, v[j + 1] if j + 1 < n else None)
        near = [x for x in sides if x is not None and abs(x - SENTINEL) <= 2.0]
        if not near or j - i + 1 > MAX_SENTINEL_RUN:
            for k in range(i, j + 1):
                v[k] = None
        i = j + 1
    out = list(v)
    for k in range(1, n - 1):
        p, x, q = v[k - 1], v[k], v[k + 1]
        if None not in (p, x, q) and abs(x - p) > SPIKE_C and abs(x - q) > SPIKE_C and abs(p - q) < AGREE_C:
            out[k] = None
    return out


def qc_rows(rows):
    """시간순 행 목록의 기온(ta)·지면온도(ts)에 qc_values를 적용한다. 빈칸으로 바꾼 개수를 돌려준다."""
    changed = 0
    for field in ("ta", "ts"):
        cleaned = qc_values([r.get(field) for r in rows])
        for r, c in zip(rows, cleaned):
            if c is None and _num(r.get(field)) is not None:
                r[field] = ""
                changed += 1
    return changed


def write_csv(out, rows):
    """포털 원본 열 이름으로 쓴다. 쓰는 도중 파일은 *ASOS* 패턴과 겹치지 않는 이름으로 둔다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / ".kma_fetch.part"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([name for name, _ in COLUMNS])
        for row in rows:
            writer.writerow(["" if row.get(field) is None else row.get(field) for _, field in COLUMNS])
    os.replace(tmp, out)


def qc_file(path, out=None):
    """받은 CSV(이 스크립트가 쓴 형식)에 QC를 적용해 out(기본: 같은 파일)에 쓴다. 원본은 out을 따로 두어 남긴다."""
    path = Path(path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        table = list(csv.DictReader(f))
    rows = sorted(({field: rec.get(name, "") for name, field in COLUMNS} for rec in table), key=lambda r: r["tm"])
    changed = qc_rows(rows)
    write_csv(Path(out) if out else path, rows)
    return changed, len(rows)


def plausible(rows):
    """열을 잘못 짚었는지 확인한다: 겨울 지면온도는 기온 근처에 있어야 한다."""
    pairs = []
    for r in rows:
        try:
            pairs.append((float(r["ta"]), float(r["ts"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not pairs:
        return False, "기온·지면온도가 함께 있는 행이 없다"
    gap = sum(abs(a - b) for a, b in pairs) / len(pairs)
    out = sum(1 for _, b in pairs if not -35 <= b <= 65)
    if gap > 8 or out > len(pairs) // 100:
        return False, "기온-지면온도 평균 차 %.1f°C, 범위 밖 지면온도 %d개" % (gap, out)
    return True, "기온-지면온도 평균 차 %.1f°C" % gap


def main(argv=None):
    ap = argparse.ArgumentParser(description="기상청 ASOS 시간자료 → OBS_ASOS_TIM 형식 CSV")
    ap.add_argument("--stn", default="119")
    ap.add_argument("--from", dest="first", type=int, default=2020)
    ap.add_argument("--to", dest="last", type=int, default=2025)
    ap.add_argument("--provider", choices=("hub", "datagokr"), default="hub")
    ap.add_argument("--base-url", help="시험용 주소 덮어쓰기")
    ap.add_argument("--out", type=Path, help="쓸 파일(받기: ~/Downloads/OBS_ASOS_TIM_119_api.csv, QC: --qc-file 자신)")
    ap.add_argument("--qc-file", type=Path, help="받기 없이 이 파일에 QC만 적용해 다시 쓴다")
    args = ap.parse_args(argv)

    if args.qc_file:
        out = args.out or args.qc_file
        changed, total = qc_file(args.qc_file, out)
        print("QC: %d행 중 %d개 값을 결측으로 바꿨다 → %s" % (total, changed, out))
        return 0

    if args.provider == "hub":
        fetch, base_url = fetch_hub, args.base_url or HUB_URL
    else:
        fetch, base_url = fetch_datagokr, args.base_url or DATAGOKR_URL
    key = os.environ.get("KMA_AUTH_KEY") or getpass.getpass("기상청 인증키(화면에 안 보임): ")
    # 공공데이터포털 'Encoding' 키를 넣어도 이중 인코딩되지 않게 한 번 푼다
    key = urllib.parse.unquote(key.strip())
    if not key:
        print("인증키가 비어 있다")
        return 1

    by_time = {}
    try:
        for start, end in month_ranges(args.first, args.last, date.today()):
            rows = fetch(base_url, key, args.stn, start, end)
            for row in rows:
                by_time[row.get("tm")] = row
            print("%s  %d행" % (start.strftime("%Y-%m"), len(rows)))
    except ApiError as exc:
        print("실패: %s" % str(exc).replace(key, "***"))
        return 1

    rows = [by_time[t] for t in sorted(t for t in by_time if t)]
    print("QC: %d개 값을 결측으로 바꿨다(결측 표시 -9.0 · 한 시간짜리 튐)" % qc_rows(rows))
    ground = [r for r in rows if str(r.get("ts", "")).strip() not in ("", "None")]
    if not rows or not ground:
        print("실패: 행 %d개, 지면온도 있는 행 %d개 — 학습에 쓸 수 없어 파일을 쓰지 않는다" % (len(rows), len(ground)))
        return 1
    ok, note = plausible(rows)
    if not ok:
        print("실패: 열을 잘못 읽은 것 같다(%s) — 파일을 쓰지 않는다" % note)
        return 1

    out = args.out or Path("~/Downloads/OBS_ASOS_TIM_119_api.csv").expanduser()
    write_csv(out, rows)
    print("저장: %s" % out)
    print("행 %d개(%s ~ %s), 지면온도 있는 행 %d개(%.1f%%), %s" % (
        len(rows), rows[0]["tm"], rows[-1]["tm"], len(ground), 100.0 * len(ground) / len(rows), note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
