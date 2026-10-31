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
    data/roads/    cross_arms.json(임의 도로, 손으로 정함) · cross_arms_osm.json·gosaek_roads.geojson·overpass 캐시(참고)
    models/<stn>/  학습 산출물(지점별)
  server/          gosaek_server.py · board.json(보드 치수) · static/index.html · static/monitor.html · static/fonts/(Pretendard, OFL)
  pico/car/        config.py · car_core.py · main.py · hwtest.py
  pico/sensors/    기지 Pico: config.py · sensor_core.py · main.py · hwtest.py · ssd1306.py · lcd1602.py
  docs/            SYSTEM_DESIGN.md · BASE_AND_CAR.md · MODEL.md · BUILD.md · img/ · make_diagrams.py · build_design_pdf.py · *.pdf
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
- 글꼴은 Pretendard다(사용자 지정). 웹은 `server/static/fonts/PretendardVariable.woff2`를 @font-face로 쓰고 CDN은 쓰지 않는다. SVG·PDF도 "Pretendard Variable"을 쓴다.

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

## 4. 도로(임의 도로, 사용자 결정)
- 모형 보드의 도로는 **임의 도로**다. 실제 도로명이나 노드를 모형 갈래에 쓰지 않는다.
- 갈래 정의는 `data/roads/cross_arms.json` 하나다. 손으로 고치며, 엔진·서버·화면은 이름·속성을 여기서만 읽는다.
  - 형식: `{"source":{...},"arms":{"N":{"name","label","structure","shadow_index","risk","risk_pct",...}}}`
  - 기본값
    - N "북쪽 도로" 그늘 0.3
    - E "동쪽 도로" 0.0
    - S "남쪽 도로(기지 진입로)" 0.8
    - W "서쪽 도로(그늘)" 1.0
  - 그늘은 모형 건물 배치에서 정한다. SW 아파트와 남쪽 기지 건물이 W·S에 그늘을 만든다.
  - `risk = 0.25 + 0.6×shadow_index`, `risk_pct` = 네 갈래 순위
- 예보 모델은 그대로 고색고 주변 관측(수원 ASOS 119)으로 학습한다.
- [참고 분석] `python3 -m model.icezero.roads`
  - 고색고 반경 1.5km의 실제 OSM 도로 위험도와 교차로 후보를 계산한다.
  - 출력: `cross_arms_osm.json`, `gosaek_roads.geojson`, `docs/img/gosaek_map.svg`
  - 모형 갈래 파일은 덮어쓰지 않는다.

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
  - 젖음 센서는 `WET_ARM` 갈래(기본 W, 그늘이 가장 깊은 갈래)의 `wet`으로 넣는다.
  - 센서가 10초 넘게 조용하면 local을 비운다.
- 자동 출동
  - 조건: auto가 켜져 있고, 차가 idle이고, 실행 중인 계획이 없다. 기지 링크가 살아 있으면 `dock`도 참이어야 한다(도킹 스위치가 없으면 기지 Pico GP14를 GND에 점퍼로 잇는다).
  - 사거리 왕복(2026-10-31 변경): 기지 텔레메트리 `wet`(조도센서가 눈 조각에 덮임)이 참이면 바로, 아니면 step의 recommend가 참이고 N이 처리 효과 중이 아닐 때 출동한다. 순서는 항상 `SWEEP_ORDER = ["N"]`, 쿨다운 10초.
  - 출동 중에는 `@@SHOW beacon=true`로 기지 지붕 경광등을 돌린다.
  - 기지 TEL의 `dock`·`refills`·`refilling`을 상태와 화면(기지 상자)에 보여 준다.
  - `server/board.json`에 중심·기지 거리·갈래 거리를 차 config와 같은 값으로 둔다. 화면이 차 위치(x,y)를 그릴 때 이 값을 쓴다.
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

## 6. 기지 Pico #1(pico/sensors, 제설기지 관제실 안, Pico 2 W, USB 시리얼)
| 장치 | 핀 |
|---|---|
| DHT11 ×4 (갈래 N/E/S/W 길가 기둥) | GP2 / GP3 / GP4 / GP5 (모듈 풀업 사용, 3V3) |
| 수위감지(젖음) AO — 그늘이 가장 깊은 W 갈래 | GP26 (ADC0) |
| 조도 모듈 AO(W 그늘, 선택) | GP27 (ADC1) |
| OLED 0.91" SSD1306 128×32 I2C0 | SDA GP0, SCL GP1, 주소 0x3C |
| I2C 1602 LCD(기지 전광판, 선택) | 같은 I2C0, 주소 0x27 |
| 3색 LED 모듈(로컬 경고) | R GP10, G GP11, B GP12 |
| 능동 부저 | GP13 |
| **도킹 스위치**(차고 뒤벽 택트 스위치, 풀업) | GP14. 눌리면 0 = 차가 도킹함 |
| **보충 게이트 SG90**(사일로 출구) | GP15 (닫힘 0°, 열림 60°) |
| 네오픽셀 WS2812 링(기지 지붕 경광등 + 갈래 상태) | DIN GP16 |
- `@@TEL`(2초마다): `{"t":{"N":f|null,...},"rh":{"N":i|null,...},"ok":{"N":b,...},"wet_raw":i,"wet":b,"light_raw":i|null,"warn":b,"dock":b,"refills":i,"refilling":b,"up":i}`
  - DHT11은 0~50°C만 잰다. 측정 실패는 null이다.
- 맥 → Pico
  - `@@SHOW {"arms":{"N":"risk1|risk2|risk3|plan|done|off",...},"msg":"ASCII 16자","beacon":b}`: beacon이 참이면 링이 경광등처럼 돈다(출동 중).
  - `@@REFILL {"ms":800}`: 수동 보충. 도킹 상태에서만 연다.
- 로컬 규칙(맥과 무관)
  - 경고
    - 켜짐: 어느 갈래든 (`t ≤ WARN_T`이고 `rh ≥ WARN_RH`)이거나, `wet`이고 W 갈래 `t ≤ WARN_T`
    - 꺼짐: 3회 연속 거짓
    - 실내 시연 기본값은 WARN_T 3.0, WARN_RH 85. 실제 설치값은 1.0이다.
  - 자동 보충
    - 조건: 도킹 스위치가 `DOCK_SETTLE_MS=1000` 동안 계속 눌리고, `REFILL_AUTO=True`이고, 마지막 보충에서 `REFILL_COOLDOWN_MS=20000`이 지났다.
    - 동작: 게이트를 `REFILL_MS=800` 동안 열었다 닫는다. 한 번 도킹에 한 번만 연다.

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
- 기구 상수(config): `WHEEL_D_MM=30`(병뚜껑), `TRACK_MM=108`, `STEPS_PER_REV=4096`(하프스텝), `STEP_US=1200`
  - 양쪽 모터는 마주 보게 달리므로 오른쪽 방향을 반전한다.
- 좌표: x는 동쪽, y는 남쪽(mm). 원점은 보드 왼쪽 위 모서리다.
  - 교차로 중심은 `(CENTER_X, CENTER_Y)`다. 사진 추정값 (480, 340)이며 실측해서 고친다.
  - 방위: N=0, E=90, S=180, W=270(시계 방향)
  - **홈 = 기지 도킹 위치** `(CENTER_X, CENTER_Y + BASE_DIST_MM)`, 북향(0°). `BASE_DIST_MM`은 추정 250이다(대기 칸 = 광장 남쪽 끝).
- 갈래 거리(config, 모두 '중심에서 거리', 사진 추정값이며 실측해서 고친다)
  - `ARM_OUT_MM = {"N":170, "E":380, "W":400}`: 차 중심이 멈추는 거리. N은 광장 북쪽 끝 − 차 앞 60 − 날 25.
  - `SPRAY_WIN = {"N":(100,170), "E":(100,380), "S":(100,240), "W":(100,400)}`: 서보를 여는 구간(서보가 없으면 무시된다)
  - `DOCK_OVERDRIVE_MM = 0`: 대기 칸은 벽 없는 테이프 칸이라 더 밀지 않는다.
- 경로(plan)
  1. **출발**: 도킹 위치에서 북쪽으로 `BASE_DIST_MM` 전진해 중심으로 간다.
     - order에 S가 있으면 이 길에서 `SPRAY_WIN["S"]`(중심까지 남은 거리 기준) 구간을 살포한다. S 갈래가 기지로 가는 길이기 때문이다.
     - 이때 S의 arm_start·arm_done을 보낸다.
  2. **갈래**: S를 뺀 갈래를 order 순서대로 처리한다.
     - 방위로 회전 → `ARM_OUT_MM[arm]` 전진(나가는 길에만 SPRAY_WIN 살포) → 같은 거리를 **후진**해 중심 복귀(회전 없음) → arm_done
  3. **귀환**: 북향으로 회전한다. `BASE_DIST_MM + DOCK_OVERDRIVE_MM`만큼 **후진**해 차고에 들어간다(phase home).
     - 끝나면 추측 자세를 도킹 위치·북향으로 다시 맞추고 plan_done을 보낸다.
  - `home` 명령: 지금 추측 위치에서 중심으로 돌아온 뒤 3번 귀환을 한다.
- UDP JSON(한 줄 = 한 데이터그램)
  - 차 → 서버(서버 9200)
    - `{"t":"hello","id":"car1"}`: 부팅 시 브로드캐스트. config `SERVER_IP`가 비면 브로드캐스트한다.
    - `{"t":"tel","id":"car1","state":"idle|run|pause|stopped|error","seq":n,"arm":"E","phase":"depart|turn|out|back|home|idle","x":mm,"y":mm,"h":deg,"spray":b,"obst_cm":f|null,"up":ms}`: 500ms마다
    - `{"t":"ack","seq":n,"ok":b,"reason":""}`
    - `{"t":"evt","e":"plan_start|arm_start|spray_on|spray_off|arm_done|plan_done|stopped|obstacle|resumed|aborted","seq":n,"arm":"E"}`
  - 서버 → 차(차 9201)
    - `{"t":"plan","seq":n,"order":["E","W"]}`: 실행 중이면 거절(ack ok=false)
    - `{"t":"stop"}`, `{"t":"home"}`, `{"t":"ping"}`
  - 같은 seq는 한 번만 실행한다.
- 안전
  - 초음파(`SONAR_ENABLED`, 기본 False)를 달면 `< OBST_CM=8`이면 정지한다. 1초 동안 비면 재개하고, 10초 넘게 막히면 aborted를 보낸다.
    - **후진(귀환) 중에는 앞쪽 초음파를 무시한다.** 차고 벽을 장애물로 보지 않게 하려는 것이다.
  - 버튼이나 stop 명령이 오면 코일 전원을 끄고 서보를 닫은 뒤 stopped로 바꾼다. 버튼을 다시 누르면 남은 구간을 재개한다.
  - 실행 중 서버 패킷이 `LINK_TIMEOUT_MS=5000` 넘게 없으면 pause하고, 다시 받으면 재개한다.

## 8. 물리 배치(사용자 보드 사진 기준, mm)
- 보드: 흰 우드락 위에 검은 종이 도로를 붙였다.
  - 도로 폭 약 150(A4를 세로로 반 자른 폭으로 추정)
  - 중앙 광장은 검은 A3 한 장 297(동서)×420(남북)
  - 아래 값은 모두 사진 추정이다. 줄자로 재서 차 config와 `server/board.json`에 같이 넣는다.
- 중심 기준 길이(추정)
  - 판 끝까지: N 340, E 470, W 500. S 도로는 남쪽 395에서 끝나고, 그 아래 흰 공간이 기지 자리다.
  - 광장 가장자리: N 243, S 176, W 157, E 140
- 건물: 네 모퉁이(NW·NE·SW·SE) 흰 공간에 세운다.
  - 도로 가장자리에서 30mm, 광장 모서리에서 40mm 이상 띄운다. 차·초음파 간섭을 막기 위해서다.
  - SW(높은 아파트)는 W·S 갈래에 그늘을 만든다. 실제 그림자 지수 W 1.00, S 0.84에 맞춘다.
  - E 갈래(서둔로17번길) 옆에는 고색고 교사동을 둔다. NW는 낮은 주택이다(N 0.29).
- DHT11 기둥: 도로 가장자리에서 30mm 밖, 중심에서 약 200mm
  - 중심 기준 (동+, 남+): N (+105,−220), E (+220,+105), S (−105,+260), W (−220,−105)
- 젖음·조도 센서: W 갈래(−300, −95) 길가
- 기지: S 도로 끝 남쪽(9절). 맥북은 기지 옆 책상에 둔다.

## 9. 제설기지(base)
- 위치: S 도로 끝 남쪽. 차고 입구 중심선 = S 도로 중심선
- 외곽은 약 320(동서)×230(남북)
  - 서쪽에 차고(bay)를 둔다. 동쪽은 관제실(Pico #1·브레드보드·LCD·부저)이다.
  - 지붕에 네오픽셀 링 경광등을 단다.
- 차고
  - 안쪽 크기: 폭 140, 깊이 190, 높이 120
  - 입구 양쪽 벽 끝을 45°로 20mm 벌린다(깔때기).
  - 바닥 양쪽 벽을 따라 높이 8mm 안내 레일을 붙여 차를 가운데로 모은다.
  - 뒤벽에 범퍼판(우드락 60×30)을 대고 그 뒤에 도킹 스위치를 단다. 차가 후진으로 밀면 눌린다.
- 보충 사일로
  - 차고 위 깔때기(종이·PET 원뿔), 출구 지름 12mm
  - 출구 아래 SG90 패들이 게이트다(닫힘 0°, 열림 60°).
  - 출구 위치 = 도킹했을 때 차 호퍼 입구 위. 차 뒤 범퍼에서 `HOPPER_FROM_REAR_MM`(차 설계값 75)이다.
- 차(참고): 전체 길이 150, 폭 113(바퀴 포함), 높이 약 95(호퍼 입구). 자세한 치수는 docs의 제설차 도면이다.
