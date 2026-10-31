# makerton — 고색고 ICE-ZERO 자동 제설 모형: 구현 계약

이 문서가 기준이다. 모듈 사이 형식·핀·상수를 바꾸려면 이 문서를 먼저 고친다. 주석·UI·로그는 한국어, 식별자는 영어.

## 0. 무엇을 만드나
- ICE-ZERO 지면온도 예보 모델을 **고색고등학교 주변**으로 다시 학습하고 개선한다.
  - 학습 기준 관측소: **수원 ASOS 119**(37.25746, 126.983). 고색고(37.25378, 126.98246)에서 약 0.4km 떨어져 있다.
  - 교차로와 도로 위험도는 고색고 주변 OSM 도로·교량·건물에서 다시 계산한다.
- 맥북이 모델을 돌린다. 겨울밤 재생 또는 실시간으로 갈래별 동결확률과 우선순위를 낸다.
  - 주변 센서(DHT11 등) 값을 갈래별 현장 보정으로 섞는다.
  - 위험하면 **자동으로** 제설차를 출동시킨다.
- Pico는 두 대다.
  - **센서 Pico**(#1, USB): 온습도·젖음·조도 관리
  - **제설차 Pico**(#2, Wi-Fi): 스텝모터 이동과 서보 살포
- **LLM은 쓰지 않는다.** 판단은 모델과 코드 규칙이 한다.
- 원칙
  - 결빙을 '확정'하지 않는다. 화면 문구는 '예측 동결확률', '상대 우선순위'다.
  - 자동 출동에도 비상 정지(대시보드·차 버튼)와 장애물 정지는 항상 동작한다.

## 1. 폴더
```
makerton/
  CONTRACT.md  README.md  .gitignore
  docs/            SYSTEM_DESIGN.md · MODEL.md · BUILD.md · img/*.svg · make_diagrams.py · svgkit.py
  model/
    icezero/       __init__.py · kma.py · features.py · train.py · engine.py · roads.py
    data/raw/108/  서울 ASOS(정리본, 기준선 비교용)
    data/raw/119/  수원 ASOS 원본 CSV(기상자료개방포털 OBS_ASOS_TIM_*.csv)
    data/roads/    gosaek_roads.geojson · cross_arms.json · overpass 캐시
    models/<stn>/  학습 산출물(지점별)
  server/          gosaek_server.py · static/index.html
  pico/car/        config.py · car_core.py · main.py · hwtest.py
  pico/sensors/    config.py · sensor_core.py · main.py · hwtest.py · ssd1306.py
  tests/           python3 -m unittest discover -s tests (저장소 루트에서) 전부 통과
```

## 2. 공통 규칙
- 맥북 Python 3.9
  - pandas 2.3, numpy 2.0, xgboost 2.1.4, scikit-learn 1.6.1, pyserial 3.5가 설치되어 있다. matplotlib은 없다.
  - `match` 문과 `X | Y` 타입 표기는 쓰지 않는다.
- MicroPython
  - f-string, dataclass, typing, walrus를 쓰지 않는다.
  - 입력은 풀업만 쓴다(RP2350-E9).
  - `~/Library/Python/3.9/bin/mpy-cross`로 컴파일 오류가 없어야 한다.
  - 하드웨어 import가 없는 `*_core.py`에 로직을 모으고, CPython 시험에서 직접 import한다.
- 비밀값(Wi-Fi 비밀번호 등)은 저장소에 넣지 않는다. config에는 빈 문자열만 두고, 업로드할 때 채운다.

## 3. 모델(model/icezero)
- `kma.py`: 입력 두 형식을 같은 표준 열로 읽는다.
  - 형식 1: 정리본 CSV. 열은 `일시,temp,precip,wind,humidity,snow,ground_temp,...`
  - 형식 2: 기상자료개방포털 원본 `OBS_ASOS_TIM_*.csv`. cp949와 utf-8-sig를 모두 받는다.
    - 열 이름: `지점, 일시, 기온(°C), 강수량(mm), 풍속(m/s), 습도(%), 일조(hr), 일사(MJ/m2), 적설(cm), 지면온도(°C)` 등
  - 표준 열: `time, temp, precip, wind, humidity, snow, ground_temp, sunshine, solar` (없는 열은 NaN)
  - `load_station(stn)` → `data/raw/<stn>/` 아래 파일을 모두 읽어 합친다. 중복 시각은 제거하고 시간 단위로 reindex한다.
- `features.py`: ICE-ZERO v10 피처 + 개선 피처
  - 일사·일조가 있으면 `solar, solar_3h_sum, sunshine`을 복원한다. 없으면 빼고 metrics에 적는다.
  - 목표: `ground_temp.shift(−h)`, h ∈ {0,1,3,6}
  - 시즌 경계를 넘는 누수를 막는다(reindex 후 shift).
- `train.py`: `python3 -m model.icezero.train --stn 119 [--force]`
  - 지점 자료가 없으면 이유를 출력하고 종료 코드 2로 끝낸다.
  - 개선 실험
    1. 회귀(XGBRegressor) + isotonic 보정
    2. 직접 동결 분류(XGBClassifier)
    3. 둘의 평균
    - 2024 검증 Brier로 시점별 방법을 고른다(학습 ≤2023). 최종 학습은 ≤2024, 시험은 2025.
  - 연도별 rolling 검증(시험 연도 2022~2025)으로 RMSE를 persistence·공기온도 기준선과 비교한다.
  - 사건 지표(시험 연도 밤): 결빙 발생 밤의 경보 적중률, 첫 경보 선행 시간 중앙값, 결빙 없는 밤 오경보율
  - XGB 파라미터 기본값: n_estimators=600, learning_rate=0.05, max_depth=6, subsample=0.9, colsample_bytree=0.9, random_state=42, n_jobs=4
- 산출물 `model/models/<stn>/`: `reg_h{0,1,3,6}.json`, `clf_h{1,3,6}.json`, `calib.json`, `metrics.json`(방법 선택 포함), `nights.json`, `features.json`
- `engine.py`
  - `Engine(stn="119", models_dir=None, arms_path=None)`
  - 메서드: `.load()`, `.available()`(지점 모델 존재 여부), `.nights()`, `.default_night`, `.timeline(night)`(18:00~다음 날 09:00), `.step(ts, local=None, treated=None, budget=2)`
  - step 1회는 0.2초 이내
- 갈래 계산(step)
  - `t_eff(arm,h) = pred_h − 2.5×structure + local_dt(arm)`
    - `local_dt`는 센서 변화량이다. [−6, +3]으로 자른다.
  - `p_freeze(arm,h)` = 선택된 방법의 동결확률. 회귀 경로는 t_eff에 보정곡선을 적용하고, 분류 경로는 피처의 기온·지면 시차를 t_eff 차이만큼 옮겨 다시 예측한다. 구현자가 고르고 metrics에 적는다.
  - `p_max` = h1·h3·h6 최댓값
  - level: `p_max ≥ 0.6` → risk3, `≥ 0.3` → risk2, 그 밖 risk1
  - 처리됨(treated) 갈래는 level "done"이고 후보에서 뺀다.
  - 후보: p_max ≥ 0.5이고 처리됨이 아님
  - `priority = risk + 0.3×wet(arm)`
  - 후보를 (−priority, N·E·S·W)로 정렬해 예산만큼 고른다. 처리 순서 = 우선순위 순서
- step JSON(값은 소수 3자리)
```json
{"time":"2025-01-09T03:00:00","station":"119",
 "obs":{"temp":-3.1,"humidity":82,"wind":1.2,"precip":0.0,"snow":0.0,"ground_temp":-0.4},
 "forecast":{"h0":-0.2,"h1":-0.6,"h3":-1.1,"h6":-0.8},
 "arms":{"E":{"name":"…","label":"bridge|general","structure":1,"shadow_index":0.0,"risk":0.91,"risk_pct":0.97,
   "local_dt":-2.1,"wet":false,"t_eff":{"h0":0,"h1":0,"h3":0,"h6":0},"p_freeze":{"h0":0,"h1":0,"h3":0,"h6":0},
   "p_max":0.93,"source":"model|model+local","level":"risk3","candidate":true,"treated":false,"priority":0.91,
   "reasons":["교량(−2.5°C 가정)","현장 −2.1°C","예측 동결확률 0.93(+3h)"]}},
 "dispatch":{"recommend":true,"selected":["E","W"],"order":["E","W"],"budget":2,"threshold":0.5},
 "model":{"name":"…","station":"119","method":{"h1":"reg|clf|blend"},"rmse":{},"persistence_rmse":{},"brier":{}},
 "notes":["…"]}
```
- `local` 형식: `{"N":{"dt":-2.1,"wet":false},...}`. 빠진 갈래는 0과 false로 본다.
- `treated` 형식: `{"E":"2025-12-08T06:00:00"}`. 값은 효과가 끝나는 시각이다. ts가 그보다 앞이면 처리됨으로 본다.

## 4. 도로·교차로(model/icezero/roads.py)
- `python3 -m model.icezero.roads [--refresh]`
  - Overpass API로 고색고 반경 1.5km의 도로(highway), 교량(bridge), 터널, 건물(높이·층수), 하천을 받는다.
  - 받은 결과는 `data/roads/overpass_*.json`에 캐시한다.
- 도로 구간 위험도는 ICE-ZERO risk_v2 방식을 따른다(`~/Downloads/ICE-ZERO_github_repo_v3/scripts/improve02_risk.py` 참고).
  - 구성 요소: 교량, 그림자 지수(남쪽 건물 높이·거리), 도로 등급, 하천 근접
  - 0~1 상대 점수 `risk`와 지역 내 백분위 `risk_pct`를 낸다.
- 교차로 선정: 고색고 근처 4방향 교차로 가운데 교량·그늘 갈래가 있고 갈래 위험도 차이가 큰 곳 하나를 고른다. 갈래는 방위로 N·E·S·W에 맞춘다.
- 출력
  - `data/roads/gosaek_roads.geojson`
  - `data/roads/cross_arms.json`: `{"source":{...},"arms":{"N":{"name","label","structure","shadow_index","risk","risk_pct","bearing_deg","length_m","osm_ids":[],"near_water":bool}}}`
  - `docs/img/gosaek_map.svg`: 학교·관측소·교차로·위험도 색

## 5. 서버(server/gosaek_server.py, 0.0.0.0:8000)
- 옵션
  - `--stn 119|108`: 119 모델이 없으면 108로 대체하고 화면에 경고를 띄운다.
  - `--mode replay|live`
  - `--night YYYY-MM-DD`
  - `--sensors-serial auto|PORT|none|fake`
  - `--car udp|fake|none`, `--udp-port 9200`, `--car-port 9201`
  - `--auto/--no-auto`(기본 auto), `--events`
- API
  - `GET / · /api/state`
  - `POST /api/replay {"night"}`
  - `/api/replay/step {"hours"}`
  - `/api/replay/auto {"on","sec_per_hour"}`
  - `/api/auto {"on"}`
  - `/api/dispatch`(수동 1회)
  - `/api/car/stop`(비상 정지 → 자동 끔)
  - `/api/car/home`
  - `/api/budget {"budget":0~4}`
  - `/api/sensors/baseline`(센서 기준값 다시 잡기)
  - `/api/reset`
- 센서 융합
  - 갈래 k의 `dt = T_k − baseline_k`. baseline은 시작 후 30초 평균이거나 `/baseline` 시점의 값이다.
  - 젖음 센서는 E 갈래 `wet`으로 넣는다.
  - 센서가 10초 넘게 조용하면 local을 비운다.
- 자동 출동
  - 조건: auto가 켜져 있고, step의 recommend가 참이고, 차가 idle이고, 실행 중인 계획이 없다.
  - 이때 `plan`을 보낸다. 대상 갈래는 order다.
  - 갈래 완료(`arm_done`) 시 `treated[arm] = 그 시각 + 3h`. replay는 재생 시각, live는 실제 시각으로 센다.
  - 차가 없으면(`--car none` 또는 링크 끊김) '모의 실행'으로 갈래당 3초 뒤 완료 처리한다.
- 이벤트는 `server/events.jsonl`에 남긴다. 이 파일은 저장소에 올리지 않는다.
- 웹 서비스 화면(사용자 요청: 모니터에 띄운다)
  - `GET /monitor`: 모니터 전용 보기
    - 1920×1080 전체 화면 기준, 스크롤 없음, 조작 버튼 없음, 1초마다 갱신
    - 3m 거리에서 읽히는 큰 글씨
    - 사거리 그림, 제설차 위치·진행, 갈래별 예측 동결확률·현장 센서, 자동 출동 상태, 예보 그래프, 최근 이벤트
  - `GET /`: 조작 대시보드. 같은 팔레트를 쓴다.
  - 두 화면 모두 같은 네트워크의 다른 기기에서 `http://<맥북 IP>:8000/monitor`로 연다.
    - 서버는 시작할 때 이 주소를 출력한다.
    - 화면 구석에도 이 주소를 작게 표시한다.
  - 색은 아래 팔레트만 쓴다(글자는 흰색·밝은색 허용).
    - 위험 단계는 색상(빨강·초록·노랑)이 아니라 밝기 단계·글자 라벨·아이콘으로 구분한다.
    - risk1 `--rich-cerulean`, risk2 `--steel-blue`, risk3 `--light-blue`(가장 밝음, 깜박임·'높음' 라벨), 처리됨 `--yale-blue-3` + ✓, 자료 없음 `--yale-blue`
    - 실물 LED 색은 이 규칙과 무관하다.
```css
--deep-space-blue:#012a4aff; --yale-blue:#013a63ff; --yale-blue-2:#01497cff; --yale-blue-3:#014f86ff;
--rich-cerulean:#2a6f97ff; --cerulean:#2c7da0ff; --air-force-blue:#468fafff; --steel-blue:#61a5c2ff;
--sky-blue-light:#89c2d9ff; --light-blue:#a9d6e5ff;
```
  - 배경은 `--deep-space-blue`, 패널은 `--yale-blue`·`--yale-blue-2`, 강조는 `--cerulean`·`--sky-blue-light`다.

## 6. 센서 Pico #1(pico/sensors, Pico 2 W, USB 시리얼)
| 장치 | 핀 |
|---|---|
| DHT11 ×4 (갈래 N/E/S/W) | GP2 / GP3 / GP4 / GP5 (모듈 풀업 사용, 3V3) |
| 수위감지(젖음, E 교량) AO | GP26 (ADC0) |
| 조도 모듈 AO(W 그늘, 선택) | GP27 (ADC1) |
| OLED 0.91" SSD1306 128×32 I2C0 | SDA GP0, SCL GP1, 주소 0x3C |
| 3색 LED 모듈(로컬 경고) | R GP10, G GP11, B GP12 |
| 능동 부저 | GP13 |
| 네오픽셀 WS2812 링(선택, 갈래 상태) | DIN GP16 |
- `@@TEL`(2초마다): `{"t":{"N":f|null,...},"rh":{"N":i|null,...},"ok":{"N":b,...},"wet_raw":i,"wet":b,"light_raw":i|null,"warn":b,"up":i}`
  - DHT11은 0~50°C만 잰다. 측정 실패는 null이다.
- 맥 → Pico: `@@SHOW {"arms":{"N":"risk1|risk2|risk3|plan|done|off",...},"msg":"16자 이내"}`
- 로컬 경고(맥과 무관)
  - 켜짐: 어느 갈래든 (`t ≤ WARN_T`이고 `rh ≥ WARN_RH`)이거나, `wet`이고 `t ≤ WARN_T`
  - 꺼짐: 3회 연속 거짓
  - 실내 시연 기본값은 WARN_T 3.0, WARN_RH 85. 실제 설치값은 1.0으로 config에 적는다.

## 7. 제설차 Pico #2(pico/car, Pico 2 W, Wi-Fi UDP)
| 장치 | 핀 |
|---|---|
| 왼쪽 28BYJ-48 + ULN2003 IN1~IN4 | GP2, GP3, GP4, GP5 |
| 오른쪽 28BYJ-48 + ULN2003 IN1~IN4 | GP6, GP7, GP8, GP9 |
| SG90 살포 서보 | GP15 (닫힘 0°, 열림 70°) |
| SR-04 초음파 TRIG / ECHO | GP16 / GP17. ECHO는 1kΩ·2kΩ 분압 권장, 선택 |
| 택트 스위치(비상 정지·재개, 풀업) | GP14 |
| 3색 LED 모듈(상태) | R GP18, G GP19, B GP20 |
| 능동 부저 | GP21 |
- 전원: 보조배터리 USB → Pico. ULN2003 VCC는 VBUS(5V), GND는 공통이다.
- 기구 상수(config): `WHEEL_D_MM=65`, `TRACK_MM=105`, `STEPS_PER_REV=4096`(하프스텝), `STEP_US=1200`
  - 양쪽 모터는 마주 보게 달리므로 오른쪽 방향을 반전한다.
- 좌표: 보드 900×900, 중심 (450,450), 위쪽이 북이다.
  - 홈 = 중심, 북향(0°)
  - 방위: N=0, E=90, S=180, W=270(시계 방향)
- 경로(갈래 하나)
  1. 갈래 방위로 제자리 회전
  2. `OUT_MM=360` 전진. 중심에서 `SPRAY_FROM_MM=110`~`SPRAY_TO_MM=340` 구간에서만 서보를 연다.
  3. 180° 회전
  4. 360 전진해 중심으로 복귀
  - 계획이 끝나면 북향으로 회전한다.
- UDP JSON(한 줄 = 한 데이터그램)
  - 차 → 서버(서버 9200)
    - `{"t":"hello","id":"car1"}`: 부팅 시 브로드캐스트. config `SERVER_IP`가 비면 브로드캐스트한다.
    - `{"t":"tel","id":"car1","state":"idle|run|pause|stopped|error","seq":n,"arm":"E","phase":"turn|out|back|home|idle","x":mm,"y":mm,"h":deg,"spray":b,"obst_cm":f|null,"up":ms}`: 500ms마다
    - `{"t":"ack","seq":n,"ok":b,"reason":""}`
    - `{"t":"evt","e":"plan_start|arm_start|spray_on|spray_off|arm_done|plan_done|stopped|obstacle|resumed|aborted","seq":n,"arm":"E"}`
  - 서버 → 차(차 9201)
    - `{"t":"plan","seq":n,"order":["E","W"]}`: 실행 중이면 거절(ack ok=false)
    - `{"t":"stop"}`
    - `{"t":"home"}`
    - `{"t":"ping"}`
  - 같은 seq는 한 번만 실행한다.
- 안전
  - 초음파 `< OBST_CM=8`이면 정지한다. 1초 동안 비면 재개하고, 10초 넘게 막히면 aborted를 보낸다.
  - 버튼이나 stop 명령이 오면 코일 전원을 끄고 서보를 닫은 뒤 stopped로 바꾼다. home 명령이 오면 추측 위치로 중심에 돌아간다.
  - 실행 중 서버 패킷이 `LINK_TIMEOUT_MS=5000` 넘게 없으면 pause하고, 다시 받으면 재개한다.

## 8. 물리 배치(mm, 원점 왼쪽 위, 위쪽 북)
- 보드 900×900. 도로는 세로 x 375~525, 가로 y 375~525. 갈래 이름·속성은 `cross_arms.json`을 따른다.
- 센서 기둥(DHT11): N (535,220), E (680,535), S (365,680), W (220,365)
- 젖음 센서: E 갈래 남쪽 가장자리 (700,540)
- 조도 센서: W 갈래 (200,530)
- 센서 Pico와 맥북은 보드 동쪽 책상에 둔다. 제설차는 중심(450,450)에서 북향으로 대기한다.
