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
  - **제설차 Pico**(#2, Wi-Fi UDP 명령, 전원은 맥 USB): 스텝모터 이동만 한다. 서보·초음파·버튼·LED·부저는 config에 핀만 있고 달지 않았다(선택).
- **LLM(Claude)은 사진을 보는 데만 쓴다.** 서버는 `ANTHROPIC_API_KEY`가 있으면 Claude를 쓴다(접근 키·헤더는 없다). 패드 화면의 '눈 위치 표시'는 서버 없이 브라우저가 Claude API를 직접 부를 수도 있다.
  - 패드 화면의 '눈 위치 표시'는 Claude가 찾은 눈 자리를 상자로 보여 주기만 한다. 차는 움직이지 않는다.
    - 그 기기의 브라우저에 입력해 둔 Claude API 키가 있으면 브라우저가 Claude API를 직접 부른다(`web/lib/claudeBoxes.ts`, 서버·같은 Wi-Fi 불필요). 키는 그 브라우저의 localStorage에만 두고 코드·저장소·서버에는 두지 않는다. 브라우저를 쓰는 누구나 그 키를 쓸 수 있으니 여럿이 쓰는 기기에서는 '키 지우기'를 누른다. 지시문·스키마는 `server/claude_vision.py`와 같아야 하고 `web/lib/claudeBoxes.test.ts`가 확인한다.
    - 키가 없으면 `/api/vision/boxes`로 서버를 거친다(서버에 `ANTHROPIC_API_KEY` 필요).
  - Claude는 눈 상자와 함께 갈래별 눈 여부(`arms`)와 사진이 쓸 만한지(`usable`)도 돌려준다. 화면은 눈 있는 갈래를 도는 가장 빠른 순서와 경로를 지도에 그리기만 한다(출동하지 않음). 경로는 `tools/make_route_table.py`가 `server/route.py`의 `plan`으로 미리 만든 `web/lib/routeTable.json`(눈 갈래 조합 15가지 + 교차로만)에서 고른다. `usable`이 false면 네 갈래 모두(전체 청소 순서), 교차로에만 눈이 있으면 가장 빨리 다녀오는 갈래 하나다. 펌웨어 경로·시간 모형이 바뀌면 이 표를 다시 만들어야 하고 `tests/test_route_table.py`가 확인한다.
  - 패드 화면에서 빠진 `/api/vision/detect`는 Claude를 규칙의 두 번째 의견으로 쓰고, 규칙과 다르면 전체 청소한다.
  - 출동 여부는 코드 규칙이 정한다. 패드 화면에서 출동시키는 버튼은 '전체 청소' 하나다.
- 원칙
  - 결빙을 '확정'하지 않는다. 화면 문구는 '예측 동결확률', '상대 우선순위'다.
  - 자동 출동에도 비상 정지(대시보드·패드의 정지 버튼)는 항상 동작하고, 서버 신호가 5초 끊기면 차가 선다. 차 버튼·초음파 정지는 달았을 때만 동작한다(지금은 달지 않음).

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
  server/          gosaek_server.py · vision.py(사진 눈 인식) · route.py(최적 경로) · claude_vision.py(Claude) · board.json(보드 치수) · static/index.html · static/monitor.html · static/fonts/(Pretendard, OFL)
  web/             Next.js 조작 화면. npm run build:app → web/out-app, 서버가 /app 에서 낸다
  tools/           pico.py(Pico 업로드) · sim_car.py(Pico 없이 펌웨어 돌리기)
  pico/car/        config.py · car_core.py · main.py · hwtest.py · sweep_test.py
  pico/sensors/    기지 Pico: config.py · sensor_core.py · main.py · hwtest.py · ssd1306.py · lcd1602.py
  docs/            SYSTEM_DESIGN.md · BASE_AND_CAR.md · MODEL.md · BUILD.md · img/ · make_diagrams.py · build_design_pdf.py · *.pdf
  tests/           python3 -m unittest discover -s tests (저장소 루트에서) 전부 통과
```

## 2. 공통 규칙
- 맥북 Python 3.9
  - pandas 2.3, numpy 2.0, xgboost 2.1.4, scikit-learn 1.6.1, pyserial 3.5가 설치되어 있다. matplotlib은 없다.
  - `match` 문과 `X | Y` 타입 표기는 쓰지 않는다.
- MicroPython(제설차 Pico 2 W는 1.29)
  - f-string, dataclass, typing, walrus를 쓰지 않는다.
  - 입력은 풀업만 쓴다(RP2350-E9).
  - `~/Library/Python/3.9/bin/mpy-cross`로 컴파일 오류가 없어야 한다.
  - 하드웨어 import가 없는 `*_core.py`에 로직을 모으고, CPython 시험에서 직접 import한다.
- 비밀값(Wi-Fi 비밀번호 등)은 저장소에 넣지 않는다. config에는 빈 문자열만 두고, 업로드할 때 채운다.
  - 서버의 Claude API 키(`ANTHROPIC_API_KEY`)는 서버를 켜는 셸의 환경변수로만 준다. 파일·로그·스냅숏에 남기지 않는다. 화면에서 입력하는 Claude API 키는 그 브라우저의 localStorage에만 두고 코드·저장소·서버에는 두지 않는다.
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
    - S "남쪽 도로" 0.8
    - W "서쪽 도로(그늘)" 1.0
  - 그늘은 모형 건물 배치에서 정한다. SW 아파트가 W·S에 그늘을 만든다. 제설 기지는 북동쪽 건물이다(9절).
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
- 환경변수
  - `ANTHROPIC_API_KEY`가 있으면 Claude를 쓴다. 없으면 규칙만 쓰고, 시작할 때 '사진 판정:' 줄에 `규칙 + Claude(claude-opus-5-5)` 또는 `규칙 만(ANTHROPIC_API_KEY 없음)`을 출력한다.
  - `/api/vision/boxes`·`/api/vision/detect`에는 접근 키나 별도 헤더가 필요 없다(401은 없다).
- API
  - `GET / · /monitor · /app/ · /api/state`(`/app/`은 `web/out-app`의 패드용 화면)
  - `POST /api/replay {"night"}`
  - `/api/replay/step {"hours"}`
  - `/api/replay/auto {"on","sec_per_hour"}`
  - `/api/auto {"on"}`
  - `/api/dispatch`(수동 1회)
  - `/api/vision/boxes {"image"}`(사진 → Claude가 찾은 눈 상자, 표시 전용. 아래)
  - `/api/vision/detect {"image","go"}`(사진 → 규칙(+Claude) 판정·출동. 패드 화면에서는 빠졌고 API로만 남았다)
  - `/api/sweep`(전체 청소: 네 갈래를 최적 순서로 1회, 출동 중이면 409)
  - `/api/car/stop`(비상 정지 → 자동 끔)
  - `/api/car/home`
  - `/api/budget {"budget":0~4}`
  - `/api/sensors/baseline`(센서 기준값 다시 잡기)
  - `/api/reset`
- `POST /api/vision/boxes`(패드 '눈 위치 표시')
  - 요청: 헤더 요구 없음, 본문 `{"image":"data:image/jpeg;base64,…"}`(JPEG·PNG·HEIC). 화면은 긴 변 1600px로 줄여 보낸다. 브라우저가 사진을 열지 못하면(맥 Chrome의 HEIC) 원본 파일을 그대로 보내고, 서버가 macOS `sips`로 JPEG로 바꾼다. 읽을 때 EXIF 방향을 적용한다.
  - 200: `{"boxes":[{"x0":0.12,"y0":0.40,"x1":0.31,"y1":0.52}],"usable":true,"arms":{"C":false,"N":false,"E":true,"S":false,"W":false},"note":"…","secs":6.5,"width":1200,"height":900,"time":"HH:MM:SS","photo":"data:image/jpeg;base64,…"}`
    - 좌표는 사진 너비·높이에 대한 0~1 비율이고 x0≤x1, y0≤y1이다. 눈이 없으면 빈 목록, 최대 30개.
    - `arms`는 갈래별 눈 여부(노란 코트가 교차로 왼쪽 아래에 오게 놓고 본 방위), `usable`은 사진으로 판단할 수 있는지다. 화면이 최적 경로를 고르는 데만 쓴다. `arms`가 없는 응답이면 경로를 그리지 않는다.
    - 규칙 판정·출동·`vision_last`와 무관하다. 차는 움직이지 않는다.
    - `photo`는 분석한 사진이다(EXIF 방향 적용, 긴 변 1200px 이하 JPEG data URL). `width`·`height`는 이 사진의 크기이고, 화면은 이 사진 위에 상자를 그린다.
  - 503: 서버에 `ANTHROPIC_API_KEY`가 없음
  - 400: 사진을 읽지 못함(JPEG·PNG·HEIC가 아니거나 HEIC를 `sips`로 바꾸지 못함)
  - 502: Claude 호출 실패
  - 오류 본문은 `{"error":"…"}`다.
- 센서 융합
  - 갈래 k의 `dt = T_k − baseline_k`. baseline은 시작 후 30초 평균이거나 `/baseline` 시점의 값이다.
  - 젖음 센서는 `WET_ARM` 갈래(기본 W, 그늘이 가장 깊은 갈래)의 `wet`으로 넣는다.
  - 센서가 10초 넘게 조용하면 local을 비운다.
- 자동 출동
  - 조건: auto가 켜져 있고, 차가 idle이고, 실행 중인 계획이 없다. 기지 링크가 살아 있으면 `dock`도 참이어야 한다(도킹 스위치가 없으면 기지 Pico GP14를 GND에 점퍼로 잇는다).
  - 출동은 눈을 봤을 때만 한다(2026-10-31 변경). 날씨 예보 모델(step의 recommend)은 화면 참고용이고 출동을 정하지 않는다.
    - 사진(API만, 패드 화면에서는 빠짐): `POST /api/vision/detect` → `server/vision.py`가 검은 도로 위 흰 알갱이를 갈래별로 센다 → `server/route.py`가 눈이 `ARM_MIN_MM2`(100) 넘는 갈래를 기지에서 도는 모든 순서를 펌웨어 `plan_for_order`로 만들어 가감속을 넣은 시간 모형(`car_core.estimate_seconds`)으로 가장 빠른 순서를 고른다(1ms 안으로 같으면 눈 많은 갈래 먼저. 구간마다 가감속하므로 스텝이 가장 적은 순서와 다를 수 있다. 전체 청소는 S→E→W→N 약 140초, 계산값) → 그 순서로 plan. 판단이 애매하면(어느 갈래든 `ARM_VAGUE_MM2`(30) 이상 100 미만, 또는 vision `sure`=False: 노란 코트가 안 보이거나 비스듬한 사진) 네 갈래 모두의 최적 순서로 plan. Claude가 켜져 있으면(`ANTHROPIC_API_KEY`가 있을 때) `server/claude_vision.py`가 규칙이 돌린 사진을 Claude(`claude-opus-5-5`)에게 보여 갈래별 눈 여부를 받는다. 규칙(100mm² 이상)과 한 갈래라도 다르거나 `usable`=False면 네 갈래 모두. 호출이 실패하면 규칙만. 판정 중 사고 요약은 `/api/state`의 `vision_live.thinking`, 끝난 판정은 `vision.eye`(`usable`·`arms`·`note`·`thinking`·`secs` 또는 `error`).
    - 전체 청소: `POST /api/sweep` → 사진 없이 네 갈래를 `route.plan`의 최적 순서로 돈다.
    - 기지 조도센서 `wet`: 어느 갈래인지 모르니 네 갈래를 최적 순서로 돈다. 쿨다운 10초.
    - `order`는 받은 순서 그대로 쓴다(서버가 다시 정렬하지 않는다).
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
| 왼쪽 28BYJ-48 + ULN2003 IN1~IN4 | GP6, GP7, GP8, GP9 |
| 오른쪽 28BYJ-48 + ULN2003 IN1~IN4 | GP2, GP3, GP4, GP5 |
| SG90 살포 서보(선택, 달지 않음) | GP15 (닫힘 0°, 열림 70°) |
| SR-04 초음파 TRIG / ECHO(선택, 달지 않음) | GP16 / GP17. ECHO는 1kΩ·2kΩ 분압 권장 |
| 택트 스위치(비상 정지·재개, 풀업, 선택, 달지 않음) | GP14 |
| 3색 LED 모듈(상태, 선택, 달지 않음) | R GP18, G GP19, B GP20 |
| 능동 부저(선택, 달지 않음) | GP21 |
- 2026-11-01 수리로 범퍼가 반대쪽 끝으로 가서 좌우 핀을 바꿨다(GP2~5가 오른쪽 바퀴). 모터마다 도는 방향은 그대로라 `LEFT_INVERT=False`, `RIGHT_INVERT=True`는 안 바꾼다.
- 지금 차에는 모터 두 개만 단다. `hwtest.py`는 `MOTORS_ONLY=True`로 모터만 시험한다.
- 전원: 맥 USB → Pico 마이크로 USB(보조배터리 없음). ULN2003 VCC는 VBUS(5V), GND는 공통이다. 명령은 Wi-Fi UDP로 오간다.
- 기구 상수(config): `WHEEL_D_MM=30`(병뚜껑), `TRACK_MM=108`, `STEPS_PER_REV=4096`(하프스텝)
  - 스텝 간격: 구간마다 `START_US=1200`에서 출발해 `RAMP_STEPS=2500`스텝(약 58mm) 동안 `STEP_US=600`(초당 약 38mm)까지 가속하고, 구간 끝 같은 거리에서 감속한다. 2026-11-01 보드 위에서 600으로 바로 출발하면 모터가 떨기만 했다.
  - 스텝이 `LATE_RAMP_US=6000` 넘게 밀리면(소켓 처리 등) 모터가 선 것으로 보고 `START_US`부터 다시 가속한다. 초음파 한 번 재기(최대 4ms)와 루프 여유보다 길어야 초음파를 켰을 때 가속이 처음부터 다시 시작되지 않는다.
  - 예상 시간(`server/route.py`)은 펌웨어 `estimate_seconds`(가감속 포함)에 `REAL_FACTOR=1.05`를 곱한다(2026-11-01 N 드라이런 실측 104.2초 / 계산 101.8초).
  - 양쪽 모터는 마주 보게 달리므로 오른쪽 방향을 반전한다.
- 좌표: x는 동쪽, y는 남쪽(mm). 원점은 보드 왼쪽 위 모서리다.
  - 교차로 중심은 `(CENTER_X, CENTER_Y)` = (582, 480)이다(2026-10-31 사진 실측, 보드 925×910, 도로 폭 135).
  - 방위: N=0, E=90, S=180, W=270(시계 방향)
  - **홈 = 제설 기지(북동쪽 건물) 차고 안** `(BASE_X, BASE_Y)` = (764, 250), 출입구(서쪽)를 본다(`BASE_H` 270°). 출입구는 N 도로 쪽이다.
- 갈래 거리(config, 모두 '중심에서 거리', 사진 추정값이며 실측해서 고친다)
  - `ARM_OUT_MM = {"N":375, "E":238, "S":325, "W":477}`: 차 자세(모터 바퀴 축 가운데, 제자리 회전 중심)가 멈추는 거리 = 중심→보드 끝 − 범퍼 앞면까지 95 − 여유 10. 2026-11-01 실측 차 길이 230, 범퍼 폭 152, 바퀴 축 → 뒤 끝 135. 차고에서는 범퍼가 출입구 밖 21mm에 선다.
  - `SPRAY_WIN`: 서보를 여는 구간(서보가 없으면 무시된다). 갈래마다 (100, ARM_OUT).
- 경로(plan)
  1. **출발**: 차고에서 서쪽으로 182 전진해 N 도로 가운데로 나오고, 남쪽으로 돌아 230 전진해 중심으로 간다.
  2. **갈래**: order 순서대로(S 포함) 처리한다.
     - 방위로 회전 → `ARM_OUT_MM[arm]` 전진(날이 눈을 보드 끝으로 민다) → 같은 거리를 **후진**해 중심 복귀(회전 없음) → arm_done
  3. **귀환**: 북향으로 돌아 230 전진해 출입구 높이로 가고, 서쪽을 보고 182 **후진**해 차고에 들어간다(phase home).
     - 끝나면 추측 자세를 도킹 위치·서향으로 다시 맞추고 plan_done을 보낸다.
  - `home` 명령: 출입구 길이면 바로 차고로 후진하고, 도로 위면 도로를 따라 중심으로 간 뒤 3번 귀환을 한다(건물을 가로지르지 않는다).
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
  - stop 명령이 오면 코일 전원을 끄고 서보를 닫은 뒤 stopped로 바꾼다. 버튼(선택, 지금은 달지 않음)을 달면 누를 때 같은 정지를 하고, 다시 누르면 남은 구간을 재개한다.
  - 실행 중 서버 패킷이 `LINK_TIMEOUT_MS=5000` 넘게 없으면 pause하고, 다시 받으면 재개한다.

## 8. 물리 배치(사용자 보드 사진 기준, mm)
- 보드: 흰 우드락 위에 검은 종이 도로를 붙였다. 925×910(노란 코트 방향이 가로), 2026-10-31 사진 실측.
  - 도로 폭 135(처음에는 150으로 추정했다)
  - 중앙 광장은 검은 A3 한 장 297(동서)×420(남북)
  - 실측값은 차 config와 `server/board.json`에 같이 넣는다(7절).
- 중심 기준 길이
  - 판 끝까지(실측): N 480, E 343, S 430, W 582. 네 도로 모두 판 끝까지 간다.
  - 광장 가장자리(추정): N 243, S 176, W 157, E 140
- 건물: 네 모퉁이(NW·NE·SW·SE) 흰 공간에 세운다.
  - 도로 가장자리에서 30mm, 광장 모서리에서 40mm 이상 띄운다. 차·초음파 간섭을 막기 위해서다.
  - SW(높은 아파트)는 W·S 갈래에 그늘을 만든다. 실제 그림자 지수 W 1.00, S 0.84에 맞춘다.
  - E 갈래 옆에는 고색고 교사동을 둔다. NW는 낮은 주택이다(N 0.29).
- DHT11 기둥: 도로 가장자리에서 30mm 밖, 중심에서 약 200mm
  - 중심 기준 (동+, 남+): N (+105,−220), E (+220,+105), S (−105,+260), W (−220,−105)
- 젖음·조도 센서: W 갈래(−300, −95) 길가
- 기지: 북동쪽 큰 건물(9절). 맥북은 보드 옆 책상에 둔다.

## 9. 제설기지(base)
- 위치: 북동쪽 큰 건물(서쪽 면 x 690, 동쪽 벽 x 909, 출입구 폭 약 290). 출입구는 서쪽 면이라 N 도로로 나온다.
  - 차고 안 바퀴 축 `(BASE_X, BASE_Y)` = (764, 250) = 동쪽 벽 909 − 바퀴 축→뒤 135 − 여유 10. 서향(270°).
  - 건물 안 깊이(약 219)가 차 길이 230보다 짧아 범퍼는 출입구 밖 21mm에 선다.
  - 출발은 서쪽 182 → 남쪽으로 돌아 230 → 교차로 중심(7절 경로).
- 아래 외곽·차고·사일로·도킹 스위치는 S 도로 끝 남쪽 기지로 그렸던 첫 설계값이다. 북동쪽 건물에는 그대로 만들지 않았다.
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
- 차(2026-11-01 실측): 길이 230(범퍼 앞면 → 뒤 끝), 범퍼 폭 152, 범퍼 앞면 → 모터 바퀴 축 95, 바퀴 축 → 뒤 끝 135. 차 자세는 모터 바퀴 축 가운데이고 제자리 회전도 이 점을 중심으로 돈다.
