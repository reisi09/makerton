# makerton — 고색고 ICE-ZERO 자동 제설 모형

수원 고색고등학교 주변 도로를 대상으로 ICE-ZERO 지면온도 예보 모델을 다시 학습하고, **예측 동결확률**이 기준을 넘거나 **패드 사진에서 도로 위 눈**이 보이면 사거리 모형의 제설차가 **자동으로** 출동하는 메이커톤 작품이다. 판단은 학습한 예보 모델과 코드 규칙이 한다. LLM은 쓰지 않는다.

- 웹 데모(모델이 2025년 겨울밤을 판단하는 재생): https://reisi09.github.io/makerton/
- 패드 사진 출동 화면: 맥 서버를 켜고 같은 핫스팟에서 `http://<맥 IP>:8000/app/vision/`

![모니터 화면](docs/img/monitor.png)

## 지금 상태(2026-10-31)

| 항목 | 상태 |
|---|---|
| 자동 시험 | Python 226개(`python3 -m unittest discover -s tests`), 웹 5개(`cd web && npm test`) 통과 |
| 모델 | 수원 ASOS **119**(학교에서 0.4km) 2020~2025 시간자료로 학습. 2025년 시험 결과는 아래 |
| 웹 데모 | Next.js 정적 사이트. `main`에 푸시하면 GitHub Actions가 GitHub Pages에 배포한다 |
| 패드 사진 출동 | 사진 한 장 → 검은 도로 위 흰 알갱이를 갈래별로 센다 → 출동 판단. 실제 모형 사진 26장 중 25장을 맞혔다(낮은 각도로 비스듬히 찍은 1장이 반사로 오탐) |
| 제설차 Pico | 실물로 확인: 펌웨어 업로드(SHA-256 일치), 모터 방향(T3), 서버↔차 UDP 양방향(T5), 바퀴를 돌리지 않은 출동 드라이런 46초. 실제 주행과 바퀴 보정(T4·T6)은 차체 완성 뒤 |
| 기지(센서) Pico | 코드와 시험만 있다. 눈 감지는 패드 사진이 대신할 수 있어 시연에는 선택이다 |
| 보드 실측 | 925×910mm(노란 코트 방향이 가로), 도로 폭 135, 교차로 중심 (582, 480). 아래 구조도 |
| 차 경로 | 도로 폭 전체를 덮는 차(길이 150 가정). S 대기 칸(중심 남쪽 345) → 교차로 → N(중심 북쪽 385) → 같은 길 후진, 실물 약 87초 |
| 인쇄용 PDF | [`docs/사거리_제설차_설계도.pdf`](docs/사거리_제설차_설계도.pdf), [`docs/단순_제설차_설계도.pdf`](docs/단순_제설차_설계도.pdf), [`docs/실물부품_배선도_조립도.pdf`](docs/실물부품_배선도_조립도.pdf), [`docs/제설기지_제설차_제작가이드.pdf`](docs/제설기지_제설차_제작가이드.pdf), [`docs/라즈베리파이_시스템_설계도.pdf`](docs/라즈베리파이_시스템_설계도.pdf) |
| 글꼴 | Pretendard(`server/static/fonts/`, OFL). 웹·도면·PDF 공통 |

### 모형 구조(실측)

![사거리 모형 구조도](docs/img/board_measured.png)

눈 없는 사진(IMG_1892)의 보드 네 변을 직선으로 맞춰(오차 0.5px 이하) 92.5×91cm 평면으로 펴고 잰 값이다. 건물은 높이 때문에 지붕이 밀려 보여 위치가 ±30mm 정도다.

| 부분 | 위치(mm, 왼쪽 위가 원점) |
|---|---|
| 세로 도로(N–S) | x 515~650, 보드 위끝부터 아래끝까지 |
| 가로 도로(W–E) | y 404~552(테이프가 약 1° 기울어 오른쪽 끝은 419~552) |
| 교차로 | 노란 테두리 x 512~652, y 412~550, 중심 (582, 480) |
| 중심에서 보드 끝 | N 480, S 430, E 343, W 582 |
| 노란 코트 · 축구장 · 공원 | x 0~360 y 545~711 · x 383~508 y 554~752 · x 298~472 y 45~392 |

### 모형 갈래(임의 도로 4갈래)

| 갈래 | 이름 | 성격 | 그림자(모형) |
|---|---|---|---|
| N | 북쪽 도로 | 낮은 주택가 | 0.29 |
| E | 동쪽 도로(학교 앞) | 학교 앞, 그늘 없음 | 0.00 |
| S | 남쪽 도로(기지 진입로) | 아파트 그늘 | 0.84 |
| W | 서쪽 도로 | 아파트 그늘(가장 깊음) | 1.00 |

모형 갈래는 **임의 도로**다. 실제 교차로를 모형에 그대로 옮기지 않았다. 갈래 이름·그림자·위험도는 `model/data/roads/cross_arms.json`에서 읽고, 코드·화면·문서에 도로명을 박지 않는다.

참고 분석: `model/icezero/roads.py`는 고색고 반경 1.5km의 OSM 도로·건물로 상대 위험도를 계산해 [`docs/img/gosaek_map.svg`](docs/img/gosaek_map.svg)에 남긴다. 이 값은 모형 갈래의 이름·근거로 쓰지 않는다.

### 모델 결과(수원 119, 2025년 시험)

학습 ≤2024, 확률 보정 2024, 시험 2025다. 2025년은 학습에 쓰지 않았다.

| 시점 | 방법 | RMSE °C | 그대로 두기(persistence) RMSE °C |
|---|---|---|---|
| +0h | 회귀 | 0.80 | 1.89 |
| +1h | 회귀·분류 혼합 | 1.26 | 1.89 |
| +3h | 회귀·분류 혼합 | 1.86 | 4.67 |
| +6h | 회귀·분류 혼합 | 2.24 | 7.01 |

- 결빙 경보(2025년 밤 118개): 결빙 밤 85개를 모두 경보했다. 결빙이 없던 밤 33개 가운데 6개는 오경보였다(18%).
- 18시에는 아직 0°C 위였다가 밤사이 얼기 시작한 27밤에서 첫 경보가 결빙보다 2시간(중앙값) 앞섰다.
- 자료는 API Hub `kma_sfctm3`로 받았고, 결측 표시 −9.0과 한 시간짜리 튐을 걸러냈다(`tools/fetch_asos.py`). 원본은 `model/data/source/119/`, 걸러낸 파일은 `model/data/raw/119/`에 있다.
- 수치 원본은 `model/models/119/metrics.json`이다. [`docs/MODEL.md`](docs/MODEL.md)에는 서울 108로 파이프라인을 검증하던 때의 설명과 지표 정의가 있다.

## 무엇이 돌아가나

- **맥북**: 예보 모델, 서버(`0.0.0.0:8000`), 조작 대시보드(`/`)·모니터(`/monitor`), 패드용 화면(`/app`), 사진 눈 인식(`server/vision.py`).
- **제설차 Pico #2(Wi-Fi UDP)**: 28BYJ-48 두 개와 병뚜껑 바퀴, 앞에 붙인 날로 S 대기 칸에서 N 끝까지 도로 폭 전체를 밀고 같은 길로 후진한다. 서보·초음파는 쓰지 않는다. 서버의 정지 명령과 차 버튼이 항상 우선한다.
- **패드**: 보드를 위에서 찍어 맥으로 보낸다. 판정·출동 결과와 정지 버튼이 같은 화면에 있다.
- **기지(센서) Pico #1(USB, 선택)**: DHT11·조도·도킹 스위치. 연결하면 현장 온도로 예보를 보정하고, 도킹했을 때만 자동 출동한다.
- **웹 데모(GitHub Pages)**: 같은 모델이 2025년 밤을 시간 단위로 판단하는 재생과 실측 사거리 지도.

## 폴더

```
makerton/
  CONTRACT.md          구현 계약(핀·상수·형식의 기준)
  README.md
  docs/                MODEL.md · BUILD.md · BASE_AND_CAR.md · SYSTEM_DESIGN.md · 설계도 PDF · img/
  model/icezero/       kma.py · features.py · train.py · engine.py · roads.py
  model/data/          source/119(원본) · raw/119(QC) · roads/cross_arms.json
  model/models/119/    학습 산출물(metrics.json 등)
  server/              gosaek_server.py · vision.py(사진 눈 인식) · board.json(보드 실측) · static/
  pico/car/            config.py · car_core.py · main.py · hwtest.py · sweep_test.py
  pico/sensors/        config.py · sensor_core.py · main.py · hwtest.py · ssd1306.py · lcd1602.py
  tools/               pico.py(Pico 업로드) · fetch_asos.py(기상청 자료) · export_demo.py(웹 재생 자료)
  web/                 Next.js: 재생 데모(/) · 사진 출동(/vision)
  tests/               python3 -m unittest discover -s tests
```

## 빠른 시작

### 0. 준비

맥북 Python 3.9에 pandas·numpy·scipy·Pillow·xgboost·scikit-learn·pyserial, 웹에는 Node 24가 필요하다.

```
python3 -m unittest discover -s tests
cd web && npm ci && npm test
```

### 1. 모델 학습(한 번)

```
python3 -m model.icezero.train --stn 119 --force
```

`model/models/119/`에 `reg_h*.json`, `clf_h*.json`, `calib.json`, `metrics.json`, `nights.json`이 생긴다. 기상청 자료를 다시 받을 때는 `KMA_AUTH_KEY=… python3 tools/fetch_asos.py`(키는 환경변수로만 준다).

### 2. 서버

```
python3 server/gosaek_server.py --car udp --sensors-serial none --auto
```

- `--sensors-serial auto|PORT|none|fake`(기지 Pico와 차 Pico가 둘 다 USB에 꽂혀 있으면 기지 포트를 직접 준다), `--car udp|fake|none`, `--no-auto`, `--mode live`, `--night YYYY-MM-DD`.
- 브라우저에서 `http://localhost:8000/`(조작) 또는 `/monitor`(모니터 전용)를 연다. 서버는 시작할 때 접속 주소를 출력한다.

### 3. 제설차 Pico

```
python3 tools/pico.py put car --wifi     # Wi-Fi 이름·비밀번호는 이때 입력받아 Pico에만 쓴다
python3 tools/pico.py reset              # main.py가 돌고 서버를 찾는다
```

- 저장소의 `config.py`는 Wi-Fi 칸을 빈 문자열로 둔다. Thonny가 포트를 잡고 있으면 `실행 > 연결해제` 뒤에 쓴다.
- 배선 확인은 `hwtest.py`(모터만), 왕복 실험·바퀴 보정은 `sweep_test.py`(`MODE = "calib"` 또는 `"run"`).
- 아이폰 핫스팟은 '호환성 최대화'(2.4GHz)를 켠다. 맥이 IPv6 전용(CLAT)으로 붙으면 서버에서 차로 명령이 가지 않으니, 맥 Wi-Fi 세부사항 > TCP/IP > IPv6 구성을 '링크-로컬 전용'으로 둔다(서버가 이벤트로 경고한다).
- 보조배터리로 돌릴 때는 맥에 꽂던 마이크로 USB를 보조배터리에 꽂는다. 배선은 그대로다.
- 기지 Pico는 `pico/sensors/`를 USB로 복사한다(Thonny 또는 같은 방식).

### 4. 패드 사진으로 출동

```
cd web && npm run build:app      # 서버가 /app 에서 내는 패드용 화면
```

- 패드를 맥과 같은 핫스팟에 붙이고 `http://<맥 IP>:8000/app/vision/`을 연다(맥에서 열면 QR이 나온다).
- 보드 전체가 보이게 **위에서 내려다보며** 사진 한 장을 찍는다. 기준 사진·모서리 찍기는 없고, 방향은 노란 코트로 맞춘다.
- 서버는 검은 도로만 찾아 그 위 흰 알갱이를 교차로·N·S·E·W 갈래별로 센다. 중앙선 투명 테이프 반사와 길쭉한 반사는 뺀다.
- 차 경로(S·교차로·N)의 눈이 300mm²를 넘거나 N 결빙확률이 출동 기준(50%)을 넘으면 사거리 왕복을 보낸다. E·W 갈래 눈은 '닿지 않음'으로 표시만 한다.
- '바로 출동'을 끄면 판정만 보고 보내지 않는다. 출동 중에는 화면 위쪽 '정지' 버튼으로 멈춘다.
- 차 길이가 정해지면 `pico/car/config.py`와 `server/board.json`의 `BASE_DIST_MM`·`ARM_OUT_MM["N"]`만 고친다(중심→끝 거리 − 차 반길이 − 여유 10).

### 5. 웹 데모

```
cd web && npm run dev             # 로컬 미리보기
python3 tools/export_demo.py      # 재생 자료(web/public/demo/replay.json)를 실제 엔진으로 다시 만든다
```

`main`에 `web/`나 `docs/` 변경을 푸시하면 `.github/workflows/pages.yml`이 빌드·시험·배포한다. GitHub Pages의 `/vision`은 브라우저 보안 때문에 맥으로 사진을 보낼 수 없어 안내만 띄운다.

### 6. 모니터에 띄우기

```
ipconfig getifaddr en0
open -a "Google Chrome" --args --kiosk http://localhost:8000/monitor
```

같은 Wi-Fi의 다른 기기에서는 `http://<맥 IP>:8000/monitor`를 연다. 자세한 절차는 `docs/BUILD.md` 4절.

## 문서

| 문서 | 내용 |
|---|---|
| `CONTRACT.md` | 핀·상수·JSON 형식. 다른 문서와 코드가 어긋나면 이 문서를 먼저 고친다 |
| `docs/SYSTEM_DESIGN.md` | 구성, 데이터 흐름, 핀표, 전원, 프로토콜, 상태기계, 안전, 보정 |
| `docs/BASE_AND_CAR.md` | 제설기지, 제설차 제작, 도킹 보정 |
| `docs/REAL_PARTS.md` | 실물 모양 부품 도감, 배선도(선 색·핀 번호)와 조립도. 그림 생성: `docs/realparts/draw_*.py` |
| `docs/MODEL.md` | 학습 자료, 피처, 지표 정의, 방법 선택(서울 108 검증 기록) |
| `docs/BUILD.md` | 부품표, 제작 순서, 시험 T1~T12, 90초 시연 대본, 문제 해결 |

## 원칙

1. **결빙을 확정하지 않는다.** 화면·로그·발표 모두 '예측 동결확률', '상대 우선순위'라고 쓴다.
2. **자동이어도 멈출 수 있어야 한다.** 대시보드와 패드의 정지 버튼, 차 버튼이 항상 동작한다. 서버 신호가 5초 끊기면 차가 선다.
3. **LLM을 쓰지 않는다.** 예보는 학습 모델, 눈 인식은 규칙 기반 영상 처리, 출동은 코드 규칙이 정한다.
4. **비밀값은 저장소에 넣지 않는다.** Wi-Fi 비밀번호는 업로드할 때 입력하고, 기상청 키는 환경변수로만 준다.
5. **센서는 보정해서 쓴다.** 시작 30초 평균 또는 `/api/sensors/baseline`으로 기준값을 잡는다.
6. **주석·UI·로그는 한국어, 식별자는 영어.**
