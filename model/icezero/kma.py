# -*- coding: utf-8 -*-
"""기상자료 읽기 (계약 3절).

입력 두 형식을 **같은 표준 열**로 맞춘다.

형식 1 — 정리본 CSV
    일시,temp,precip,wind,humidity,snow,ground_temp,... (utf-8-sig, BOM 있음)

형식 2 — 기상자료개방포털 원본 OBS_ASOS_TIM_*.csv
    지점, 일시, 기온(°C), 강수량(mm), 풍속(m/s), 습도(%), 일조(hr), 일사(MJ/m2),
    적설(cm), 지면온도(°C), ...
    인코딩은 cp949와 utf-8-sig 둘 다 온다.

표준 열: time(인덱스), temp, precip, wind, humidity, snow, ground_temp, sunshine, solar
자료에 없는 열은 만들지 않는다(호출 쪽에서 NaN으로 채운다).

`load_station(stn)`은 data/raw/<stn>/ 아래 모든 CSV를 읽어 합치고, 겹치는 시각은
관측값이 더 많은 쪽을 남긴 뒤 전체 시간 범위로 reindex한다. 계절 사이 공백을
명시적 NaN 행으로 남기는 것이 목적이다(시차·목표 누수 방지).
"""

from pathlib import Path

import pandas as pd

# model/icezero/kma.py → model/
MODEL_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = MODEL_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw"

STATION_NAMES = {"108": "서울", "119": "수원"}

STANDARD_COLUMNS = (
    "temp", "precip", "wind", "humidity", "snow", "ground_temp", "sunshine", "solar",
)

# 열 이름 → 표준 열. 앞뒤 공백·BOM은 읽을 때 지운다.
COLUMN_MAP = {
    # 시각
    "일시": "time", "일시(KST)": "time", "시각": "time", "날짜": "time",
    "time": "time", "date": "time", "datetime": "time",
    # 기온
    "기온(°C)": "temp", "기온(C)": "temp", "기온": "temp", "temp": "temp",
    # 강수
    "강수량(mm)": "precip", "강수량": "precip", "precip": "precip",
    # 바람
    "풍속(m/s)": "wind", "풍속": "wind", "wind": "wind",
    # 습도
    "습도(%)": "humidity", "습도": "humidity", "humidity": "humidity",
    # 일조·일사
    "일조(hr)": "sunshine", "일조": "sunshine", "sunshine": "sunshine",
    "일사(MJ/m2)": "solar", "일사(MJ/m²)": "solar", "일사": "solar", "solar": "solar",
    # 적설
    "적설(cm)": "snow", "적설": "snow", "snow": "snow",
    # 지면온도
    "지면온도(°C)": "ground_temp", "지면온도(C)": "ground_temp",
    "지면온도": "ground_temp", "ground_temp": "ground_temp",
}

# 빈칸이 '없음(0)'을 뜻하는 열
ZERO_WHEN_BLANK = ("precip", "snow", "sunshine", "solar")

# 시도할 인코딩 순서. utf-8-sig는 BOM 있는 정리본, cp949는 포털 원본.
ENCODINGS = ("utf-8-sig", "cp949", "euc-kr")


class StationDataMissing(RuntimeError):
    """지점 원본 파일이 없다. train은 이 예외를 받아 종료 코드 2로 끝난다."""


def station_dir(stn, data_dir=None):
    """data/raw/<stn>/ 경로. data_dir는 data 루트(model/data)를 가리킨다."""
    root = Path(data_dir) if data_dir is not None else DATA_ROOT
    return root / "raw" / str(stn)


def station_files(stn, data_dir=None):
    """지점 폴더의 CSV 목록(이름순). 없으면 빈 목록."""
    folder = station_dir(stn, data_dir)
    if not folder.is_dir():
        return []
    names = [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() == ".csv"]
    return names


def _clean_name(name):
    """열 이름에서 BOM·앞뒤 공백을 지운다."""
    return str(name).replace("\ufeff", "").strip()


def _to_standard(df):
    """한 파일의 표를 표준 열로 바꾼다. 'time' 열이 없으면 KeyError."""
    df = df.rename(columns={c: _clean_name(c) for c in df.columns})
    rename = {}
    for col in df.columns:
        target = COLUMN_MAP.get(col)
        if target and target not in rename.values():
            rename[col] = target
    if "time" not in rename.values():
        raise KeyError("time")
    out = df[list(rename)].rename(columns=rename)
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    out = out.dropna(subset=["time"])
    for col in out.columns:
        if col == "time":
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce")
    # 포털 원본은 비·눈이 없거나 밤이라 일조·일사가 없으면 빈칸이다. 관측된 시각의 빈칸은 0이다.
    # (관측 자체가 없는 시각은 reindex_hourly에서 NaN 행으로 남는다.)
    for col in ZERO_WHEN_BLANK:
        if col in out.columns:
            out[col] = out[col].fillna(0.0)
    return out


def read_table(path):
    """파일 하나를 표준 표로 읽는다. 빈 파일은 None.

    인코딩은 utf-8-sig → cp949 → euc-kr 순으로 시도하고, '일시' 열이 실제로
    읽혔을 때만 그 결과를 쓴다(잘못 디코딩된 열 이름을 걸러내기 위해서다).
    """
    path = Path(path)
    errors = []
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError as exc:
            errors.append("%s: %s" % (enc, exc))
            continue
        except pd.errors.EmptyDataError:
            return None
        try:
            return _to_standard(df)
        except KeyError:
            errors.append("%s: '일시' 열 없음" % enc)
            continue
    raise ValueError("자료를 읽지 못했다: %s (%s)" % (path, "; ".join(errors)))


def merge_tables(tables):
    """여러 표를 합친다. 같은 시각은 관측값이 더 많은 행을 남긴다."""
    parts = [t for t in tables if t is not None and len(t) > 0]
    if not parts:
        raise StationDataMissing("읽을 자료가 없다")
    df = pd.concat(parts, ignore_index=True)
    counts = df.drop(columns=["time"]).notna().sum(axis=1)
    df = df.assign(_filled=counts).sort_values(["time", "_filled"], kind="mergesort")
    df = df.drop_duplicates("time", keep="last").drop(columns=["_filled"])
    return df.sort_values("time").reset_index(drop=True)


def reindex_hourly(df):
    """전체 시간 범위로 매시 reindex한다. 계절 사이 공백은 NaN 행이 된다."""
    if df is None or len(df) == 0:
        raise StationDataMissing("자료가 비어 있다")
    df = df.set_index("time").sort_index()
    full = pd.date_range(df.index.min(), df.index.max(), freq="h")
    out = df.reindex(full).rename_axis("time")
    keep = [c for c in STANDARD_COLUMNS if c in out.columns]
    return out[keep]


def load_station(stn, data_dir=None):
    """지점 자료를 모두 읽어 표준 표로 돌려준다(인덱스 time, 매시).

    파일이 없으면 StationDataMissing을 올린다. 이유는 호출 쪽에서 출력한다.
    """
    files = station_files(stn, data_dir)
    if not files:
        folder = station_dir(stn, data_dir)
        raise StationDataMissing(
            "지점 %s 자료가 없다: %s 안에 CSV가 없다" % (stn, folder)
        )
    tables = []
    for path in files:
        table = read_table(path)
        if table is not None and len(table) > 0:
            tables.append(table)
    if not tables:
        raise StationDataMissing("지점 %s 폴더에 쓸 수 있는 행이 없다" % stn)
    return reindex_hourly(merge_tables(tables))


def has_solar(frame):
    """일사·일조 열이 실제 값과 함께 있는지."""
    cols = [c for c in ("solar", "sunshine") if c in frame.columns]
    return any(frame[c].notna().any() for c in cols)


def station_label(stn):
    """'108 서울' 같은 표시용 이름."""
    name = STATION_NAMES.get(str(stn))
    return ("%s %s" % (stn, name)).strip() if name else str(stn)
