# ICE-ZERO 사거리 모형 — 구현 계약 (모든 모듈 공통)

이 문서가 기준이다. 모듈 사이의 형식, 핀, 상수를 바꾸려면 먼저 이 문서를 고친다.
주석, UI, 로그는 한국어, 식별자는 영어로 쓴다. 이전 4차로 버전은 `archive_4lane/`에 보관했으며 수정하지 않는다. 패턴만 참고한다.

## 0. 무엇을 만드나
- 우드락 위에 **십자 모양 사거리** 하나를 만든다.
  - 실제 강남구 교차로(노드 1220041600)를 옮긴 것이다.
  - 네 갈래 도로(N·E·S·W)마다 실제 ICE-ZERO 도로 속성이 있다(`engine/data/cross_arms.json`).
- **맥북**이 ICE-ZERO 예보 모델을 돌린다.
  - 모델: XGBoost + 지면온도 시차 피처 + isotonic 동결확률 보정
  - 데이터: 실제 ASOS 겨울 자료. 2025년 시험 구간의 겨울밤 하나를 시간 단위로 재생한다.
- 맥북이 계산하는 것
  - 갈래별 유효 노면온도와 동결확률
  - ICE-ZERO risk_v2 우선순위
  - 예산 안에서 고른 갈래와 처리 순서
- 사람이 승인하면 맥북이 USB 시리얼로 **Pico #1**에 명령을 보낸다.
- Pico #1이 하는 일
  - 갈래 LED를 표시한다.
  - 갈래별 **서보 살포기**를 순서대로 작동한다.
  - 교량 갈래의 센서(DS18B20 + 젖음)를 맥북에 보낸다. 이 값은 모델의 현장 보정값으로 쓴다.
- Command Code LLM: 자유 문장 현장 제보를 갈래·예산으로 구조화하고, 모호하면 되묻는다. 사람이 확인하기 전에는 반영하지 않는다.
- 원칙
  - 결빙을 '확정'하지 않는다(화면 문구: '예측 동결확률', '상대 우선순위').
  - 안전 경고(교량 주의 LED)는 Pico가 로컬에서 처리한다.
  - LLM은 기기를 직접 조종하지 않는다.

## 1. 폴더
```
icezero_model/
  CONTRACT_CROSS.md
  README.md                  실행 요약(서버 담당)
  engine/
    icezero_cross.py         Engine 클래스(학습·평가·보정·밤 찾기·step)
    train.py                 CLI: python3 engine/train.py [--force] → models/ 생성·지표 출력
    data/weather_winter_clean.csv   ASOS 겨울 시간 자료(사용자 저장소에서 복사, 읽기 전용)
    data/cross_arms.json            교차로 4갈래 속성(ICE-ZERO roads_rescored.csv에서 추출)
    models/                  생성물: xgb_h0.json…, calib.json, metrics.json, nights.json
  server/
    icezero_server.py        HTTP 대시보드·API, 재생, 승인, Pico 시리얼, events.jsonl
    llm.py                   Command Code 호출(4갈래판), rule_parse
    static/index.html        대시보드
  pico_cross/
    config.py · cross_core.py(순수 로직) · main.py · hwtest.py
  tests/                     python3 -m unittest discover -s icezero_model/tests 전부 통과
  docs/                      가이드 PDF(문서 담당)
  archive_4lane/             이전 버전 보관(수정 금지)
```

## 2. 갈래(arm)
- ID: `N` `E` `S` `W`. 보드 위쪽이 북쪽이다. 표시 순서와 LED 체인 순서도 N, E, S, W.
- 속성은 `engine/data/cross_arms.json`. 이름·종류·구조물·그림자·폭·risk_v2·강남구 내 백분위다.

| 갈래 | 도로 | 특성 |
|---|---|---|
| N | 테헤란로115길 | 일반, risk_v2 0.58 |
| E | 올림픽로 | **교량**(structure=1), risk_v2 0.91, 강남구 상위 2.5% |
| S | 역삼로107길 | 일반, risk_v2 0.52 |
| W | 테헤란로 | **그늘**(shadow 0.38), risk_v2 0.79 |

## 3. 엔진(engine/icezero_cross.py)
- 입력: `weather_winter_clean.csv`. 열은 `일시,temp,precip,wind,humidity,snow,ground_temp,...`이고 BOM을 처리한다.
  - 전체 시간 범위로 reindex해서 시즌 경계를 넘는 시차 누수를 막는다.
- 피처(ICE-ZERO v10, 일사·일조는 자료에 없어 제외 → '경량 재현판'이라고 표기)
  - base: temp, temp_6h_mean, humidity, dewpoint_depression(Magnus 식으로 이슬점 계산 후 temp−dewpoint), wind, precip_6h, snow, new_snow_6h(=max(snow−snow.shift(6),0)), hour_sin, hour_cos, day_sin, day_cos
  - lag: gt_lag1, gt_lag2, gt_lag3, gt_lag6, gt_roll6(=shift(1).rolling(6).mean), gt_trend3(=shift(1)−shift(4)), air_gt_gap_lag1(=temp−gt.shift(1))
  - 목표: ground_temp.shift(−h), h ∈ {0,1,3,6}. h=0은 시차·현재 기상으로 현재 지면온도를 추정하는 nowcast다.
- 모델: `xgboost.XGBRegressor(n_estimators=600, learning_rate=0.05, max_depth=6, subsample=0.9, colsample_bytree=0.9, random_state=42, n_jobs=4)`를 시점별로 만든다.
  - 최종 모델은 2020~2024로 학습하고 2025를 시험 구간으로 둔다.
  - 지표: RMSE·MAE를 persistence(h>0: 발행 시각 지면온도, h0: gt_lag1)·공기온도 기준선과 비교한다.
- 동결확률 보정: 2020~2023으로 학습한 모델의 2024 예측값 → 실제 `ground_temp ≤ 0` 여부에 isotonic 회귀(increasing=False, out_of_bounds='clip')를 시점별로 맞춘다. 2025 Brier를 보고한다.
- 갈래 유효온도: `t_eff(arm,h) = pred_h − 2.5×structure` (ICE-ZERO 교량 공학 가정)
- 현장 보정(override): 교량 갈래(structure=1)에 신선한 센서값 `t_bridge`가 있으면 `offset = t_bridge − t_eff(E,h0)`을 구해 모든 h에 더한다. 이때 source='sensor'.
- 동결확률: `p_freeze(arm,h) = iso_h(t_eff(arm,h))` (관측소 보정곡선을 유효온도에 적용하는 가정이므로 note에 명시)
- `p_max` = h ∈ {1,3,6} 중 최댓값
- 단계(level): `p_max ≥ 0.6 → risk3`, `≥ 0.3 → risk2`, 그 밖 `risk1`
- 후보: `p_max ≥ DISPATCH_P(0.5)` 또는 확인된 제보가 있는 갈래
- 우선순위: `priority = risk_v2 + 0.5×(확인된 제보)`
- 선정: 후보를 (−priority, N·E·S·W 순)으로 정렬해 예산(기본 2)만큼 고른다. 처리 순서는 우선순위 순서다(한 교차로라 경로 = 우선순위).
- `recommend` = 선정된 갈래가 있을 때 true
- 밤 찾기 `nights(year=2025)`
  - 조건: 18시 지면온도 > 0이고 다음 날 09시까지 최저 ≤ 0인 밤
  - 점수: 직전 12시간 강수·적설(젖음)과 하강 폭
  - 출력: 상위 목록과 기본 시연 밤을 `models/nights.json`에 저장한다.
- `Engine.step(ts, sensor=None, reports=None, budget=2)`: 아래 JSON을 반환한다(값은 소수 3자리).
```json
{"time":"2025-01-09T03:00:00",
 "obs":{"temp":-3.1,"humidity":82,"wind":1.2,"precip":0.0,"snow":0.0,"ground_temp":-0.4},
 "forecast":{"h0":-0.2,"h1":-0.6,"h3":-1.1,"h6":-0.8},
 "arms":{"E":{"name":"올림픽로","label":"bridge","structure":1,"shadow_index":0.0,"risk_v2":0.914,"risk_v2_pct":0.975,
              "t_eff":{"h0":0,"h1":0,"h3":0,"h6":0},"p_freeze":{"h0":0,"h1":0,"h3":0,"h6":0},"p_max":0.93,
              "source":"model","level":"risk3","candidate":true,"priority":0.914,
              "reasons":["교량(−2.5°C 가정)","예측 동결확률 0.93(+3h)"]}},
 "dispatch":{"recommend":true,"selected":["E","W"],"order":["E","W"],"budget":2,"threshold":0.5},
 "model":{"name":"ICE-ZERO 예보 경량 재현(XGBoost+시차, 일사·일조 제외)","rmse":{},"persistence_rmse":{},"brier":{}},
 "notes":["동결확률은 관측소 지면온도 보정곡선을 갈래 유효온도에 적용한 값(가정)","risk_v2는 ICE-ZERO 상대 순위"]}
```
- `Engine.load()`: models/가 있으면 불러오고 없으면 학습한다. 학습은 1분 이내를 목표로 한다.
- `Engine.timeline(night)`: 그날 18:00부터 다음 날 09:00까지 시각 목록
- 성능: step 1회 0.2초 이내(피처 행렬 캐시)

## 4. 서버(server/icezero_server.py, 0.0.0.0:8000)
| 메서드·경로 | 내용 |
|---|---|
| GET / · GET /api/state | 대시보드 · 전체 상태: 현재 step 결과, 재생(밤·시각·자동 여부), 예산, 확인된 제보, pending 제보, 승인 계획, 실행 진행, 센서·Pico 링크, 이벤트 |
| POST /api/replay `{"night":"YYYY-MM-DD"}` | 재생할 밤 선택(18:00부터) |
| POST /api/replay/step `{"hours":1}` | 시각 이동(음수 허용, 범위 제한) |
| POST /api/replay/auto `{"on":true,"sec_per_hour":6}` | 자동 재생 |
| POST /api/report `{"text"}` | LLM 해석(실패 시 rule_parse) + 규칙 해석을 pending에 저장 |
| POST /api/report/confirm `{"arms":[],"budget":null\|int}` · /api/report/reject | 사람이 확인한 값만 반영 |
| POST /api/budget `{"budget":int 0~4}` | 예산 |
| POST /api/sensor `{"use_sensor":bool,"t_bridge":float\|null}` | 센서 현장 보정 사용 여부. Pico가 없을 때 수동 값 입력 |
| POST /api/plan/approve | 현재 제안(선정·순서)을 승인 계획(plan_id)으로 고정 → Pico LED 'plan' |
| POST /api/dispatch | 승인 계획 순서대로 `@@SPRAY`를 하나씩 보내고 `spray_done`을 기다린다(갈래당 4초 제한, 실패하면 중단하고 표시). Pico가 없으면 '모의 실행'으로 표시 |
| POST /api/estop · /api/reset | 남은 실행 취소와 `@@STOP` · 시연 초기화 |
- Pico 링크: `--pico-serial auto|<포트>|none` (pyserial)
- 그 밖의 옵션: `--port`, `--no-llm`, `--events`, `--night`. 시작할 때 Engine.load()를 부른다.
- LLM: 스타터 방식을 따른다(User-Agent `icezero-model/1.0`, `x-cmd-zdr`, `reasoning_effort` low, max_tokens 2000, 20초).
  - 출력: `{"arms":["E"],"condition":"slippery|ice_suspected|snow|accident|clear|other","budget":null|int,"ambiguous":bool,"question":"","summary":""}`
  - 갈래 동의어: '올림픽로·다리·교량·동쪽', '테헤란로·그늘·서쪽', '테헤란로115길·북쪽', '역삼로107길·남쪽'
  - '테헤란로'만 있으면 W와 N(115길) 사이에서 모호하다. 이때 되묻는다.

## 5. Pico #1 (pico_cross, Pico 2 W, MicroPython)
| 장치 | 핀 |
|---|---|
| 서보 살포기 SG90 ×4 | N=GP18, E=GP19, S=GP20, W=GP21 (50Hz, 닫힘 0°·열림 60°, 한 번에 하나만 움직임) |
| 갈래 LED | LED_MODE="neopixel": WS2812 4픽셀 DIN=GP16(N,E,S,W 순) / "gpio": 단색 LED N=GP6, E=GP7, S=GP8, W=GP9 |
| DS18B20 ×2(교량 시험편·공기) | GP4, 4.7kΩ 풀업 |
| 젖음센서 AO | GP26 |
| 교량 주의 LED | GP15 |
| 부저(선택) | GP17 |
- 로컬 경고: 켜짐 = `t_bridge ≤ 1.0 and wet` 또는 `t_bridge ≤ 0.0`. 꺼짐 = 3회 연속 거짓. 맥북과 무관하게 동작한다.
- 시리얼(USB stdio)
  - Pico → 맥: `@@TEL {"t_bridge":f|null,"t_air":f|null,"wet":b,"wet_raw":i,"warn":b,"busy":b,"up":i}`(1초마다), `@@EVT {"e":"spray_start|spray_done|spray_reject|stopped","seq":n,"arm":"E"}`
  - 맥 → Pico: `@@LED {"arms":{"N":"risk1|risk2|risk3|plan|done|off",...}}`, `@@SPRAY {"seq":n,"arm":"E","ms":600}`, `@@STOP {}`
  - 같은 seq는 한 번만 실행한다. 이미 끝난 seq는 spray_done을 다시 보낸다. 실행 중에는 큐에 넣는다(최대 4).
  - `@@STOP`은 모든 서보를 닫고 큐를 비운다.
- LED 색: risk1 초록, risk2 노랑, risk3 빨강, plan 파랑 2Hz 깜박임, done 흰색, off. 맥 명령이 10초 넘게 없으면 끈다.
- MicroPython 호환: f-string, dataclass, typing, walrus를 쓰지 않는다. 입력은 풀업만 쓴다(RP2350-E9). mpy-cross로 컴파일 오류가 없어야 한다.

## 6. 물리 배치(도면 기준, mm, 원점 = 왼쪽 위, 위쪽 = 북)
- 바닥 900×900: 우드락 900×600 한 장과 900×300 조각을 y=600에서 잇는다.
- 세로 도로 x 375~525 전체, 가로 도로 y 375~525 전체. 도로 폭 150(중앙선 하나, 양방향 1차로씩).
- 갈래 길이: 중앙 사각형(375~525)에서 판 끝까지 375.
- E 갈래 = 교량
  - 상판 x 610~790, y 355~545(보도 20mm 포함)를 은박과 난간으로 표시한다. 그 아래로 '하천'(파란 띠)이 남북으로 흐른다(x 660~740, 전체 높이).
  - 교량 관측부(물받이 + 시험편 + DS18B20 + 젖음센서)는 상판 남쪽 (650~760, 575~637)에 둔다. 교량 주의 LED는 그 왼쪽(636, 595)에 둔다.
- W 갈래 = 그늘: 북서 (40,240)·(250,240), 남서 (40,535)·(250,535)에 바닥 100×125, 높이 120인 L자 건물 상자를 둔다. 남쪽 램프로 남서 건물 그림자를 W 갈래에 드리운다.
- 서보 살포기(바닥 56×56, 높이 105 상자. 바닥판은 35mm 높이에 두고 그 아래에 서보, 앞벽 윗부분에 갈래 LED): 짧은 미끄럼판으로 도로 위에 알갱이를 떨어뜨린다.
  - N (535~591, 150~206) → 서쪽 · E (600~656, 292~348) → 남쪽(교량 시작부) · S (309~365, 692~748) → 동쪽 · W (162~218, 537~593) → 북쪽
- 갈래 LED: 각 살포기 상자 윗면(WS2812 1픽셀 또는 단색 LED).
- 받침: 밑면에 900×80 가로대를 두 겹(10mm)으로 y 20~100 · 560~640(이음 보강) · 800~880에 붙인다. 배선은 가로대 사이 통로로 보낸다.
- 전자부: 보드 동쪽 책상 위(하천이 북동 모서리를 지나므로 보드 밖). Pico #1, 브레드보드, 서보 전용 5V를 두고 맥북 USB에 연결한다.
- 도면 좌표의 단일 기준은 `docs/cross_drawings.py` 상수다.
