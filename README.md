# makerton — 고색고 ICE-ZERO 자동 제설 모형

수원 고색고등학교 주변 도로를 대상으로 ICE-ZERO 지면온도 예보 모델을 다시 학습하고, 갈래별 **예측 동결확률**과 **상대 우선순위**를 내서 제설차가 **자동으로** 출동하는 메이커톤 작품이다. 판단은 학습 모델과 코드 규칙이 한다. LLM은 쓰지 않는다.

![모니터 화면](docs/img/monitor.png)

![시스템 구성](docs/img/system.svg)

## 지금 상태(2026-10-31)

| 항목 | 상태 |
|---|---|
| 자동 시험 | `python3 -m unittest discover -s tests` → 158개 통과 |
| Pico 펌웨어 | `pico/car` 4개, `pico/sensors` 5개 파일 `mpy-cross` 통과. 실물 배선·주행은 미검증 |
| 모델 | 서울 108로 파이프라인 검증 완료. 수원 119 원본 CSV를 받으면 `--stn 119`로 다시 학습한다 |
| 교차로 | 고색고에서 171m 떨어진 OSM 노드 4641502519(아래 표) |
| 서버·모니터 | 실제 엔진 + 가짜 차·센서로 자동 출동 → 살포 완료 → 처리됨(3시간) 흐름 확인 |

### 교차로(OSM, 고색고 반경 1.5km 후보 108곳 중 선정)

| 갈래 | 도로 | 등급 | 그림자 | risk | 지역 백분위 |
|---|---|---|---|---|---|
| N | 매송고색로711번길 | residential | 0.29 | 0.573 | 0.685 |
| E | 서둔로17번길(학교 앞) | tertiary | 0.00 | 0.250 | 0.109 |
| S | 매송고색로711번길 | residential | 0.84 | 0.829 | 0.967 |
| W | 서부로1596번길 | tertiary | 1.00 | 0.719 | 0.844 |

반경 1.5km 안에 교량 갈래가 있는 4갈래 교차로는 없었다. 그래서 갈래 차이는 그늘·도로 등급(risk)과 현장 센서로 만든다. 지도는 [`docs/img/gosaek_map.svg`](docs/img/gosaek_map.svg)에 있다.

### 모델 개선 결과(서울 108, 2025년 시험)

| 시점 | 방법 | RMSE °C | persistence | Brier(개선 전 회귀+보정 → 개선) |
|---|---|---|---|---|
| +0h | 회귀 | 0.69 | 1.45 | 0.0346 |
| +1h | 회귀·분류 평균 | 1.11 | 1.45 | 0.0499 → **0.0438** |
| +3h | 회귀·분류 평균 | 1.53 | 3.63 | 0.0731 → **0.0654** |
| +6h | 회귀·분류 평균 | 1.85 | 5.54 | 0.0940 → **0.0853** |

- 개선 피처: 이슬점, 3시간 습도 추세. 검증에서 이긴 피처만 남겼다.
- 결빙 경보(2025년 밤 117개): 결빙 밤 84개 중 84개를 경보했다. 결빙 없던 밤 33개 중 8개는 오경보였다(24%).
- 18시에 아직 0°C 위였다가 밤사이 얼기 시작한 25밤에서는 첫 경보가 결빙보다 3시간(중앙값) 앞섰다.
- 자세한 수치와 정의는 [`docs/MODEL.md`](docs/MODEL.md)에 있다.

## 무엇이 돌아가나

- **맥북**: 수원 ASOS(지점 119)로 다시 학습한 XGBoost 예보 모델, 갈래 위험도, 서버(`0.0.0.0:8000`), 대시보드.
- **센서 Pico #1(USB)**: 갈래별 DHT11 4개, 젖음(E)·조도(W), OLED·3색 LED·부저·링. 맥이 없어도 로컬 경고를 켠다.
- **제설차 Pico #2(Wi-Fi UDP)**: 28BYJ-48 두 개로 사거리를 주행하고, 중심 110~340mm 구간에서만 서보를 열어 살포한다. 초음파 8cm, 버튼, `stop` 명령이 항상 우선한다.
- **모니터**: `http://<맥 IP>:8000/monitor`를 전체 화면으로 띄워 3m 거리에서도 읽히게 보여 준다.

## 폴더

```
makerton/
  CONTRACT.md          구현 계약(핀·상수·형식의 기준)
  README.md
  docs/                SYSTEM_DESIGN.md · MODEL.md · BUILD.md · img/*.svg · make_diagrams.py · svgkit.py
  model/icezero/       kma.py · features.py · train.py · engine.py · roads.py
  model/data/raw/119/  수원 ASOS 원본 CSV
  model/data/roads/    gosaek_roads.geojson · cross_arms.json
  model/models/119/    학습 산출물
  server/              gosaek_server.py · static/index.html
  pico/car/            config.py · car_core.py · main.py · hwtest.py
  pico/sensors/        config.py · sensor_core.py · main.py · hwtest.py · ssd1306.py
  tests/               python3 -m unittest discover -s tests
```

## 빠른 시작

### 0. 준비

맥북 Python 3.9에 pandas·numpy·xgboost·scikit-learn·pyserial이 설치되어 있어야 한다.

```
python3 -V
python3 -m unittest discover -s tests
```

### 1. 도로·교차로 (한 번)

```
python3 -m model.icezero.roads --refresh
```

`model/data/roads/cross_arms.json`이 생기고 `docs/img/gosaek_map.svg`가 갱신된다. 캐시가 있으면 `--refresh` 없이 다시 돌려도 된다.

### 2. 모델 학습 (한 번)

```
python3 -m model.icezero.train --stn 119
```

`model/models/119/`에 `reg_h*.json`, `clf_h*.json`, `calib.json`, `metrics.json`, `nights.json`이 생긴다. 지점 119 자료가 없으면 이유를 출력하고 종료 코드 2로 끝난다(이때는 `--stn 108`로 기준선만 확인할 수 있다).

학습·검증 수치(연도별 RMSE, Brier, 사건 지표)는 **(MODEL.md 참조)**.

### 3. 서버

```
python3 server/gosaek_server.py --stn 119 --mode replay --auto
```

- `--sensors-serial auto|PORT|none|fake`, `--car udp|fake|none`, `--mode live`, `--night YYYY-MM-DD`.
- 브라우저에서 `http://localhost:8000/`(조작) 또는 `/monitor`(모니터 전용)를 연다.
- 서버는 시작할 때 접속 주소(`http://<맥 IP>:8000/monitor`)를 출력한다.

### 4. Pico 업로드

```
~/Library/Python/3.9/bin/mpy-cross pico/sensors/*.py pico/car/*.py
```

- 센서 Pico #1: `pico/sensors/`의 `config.py`·`sensor_core.py`·`main.py`·`ssd1306.py`를 USB로 복사한다.
- 제설차 Pico #2: `pico/car/`의 `config.py`·`car_core.py`·`main.py`를 복사한다.
- `config.py`의 Wi-Fi SSID·비밀번호와 `SERVER_IP`는 **업로드할 때만** 채운다. 저장소에는 빈 문자열로 둔다.
- 부팅 뒤 `hwtest.py`로 핀을 하나씩 확인한다.

### 5. 모니터에 띄우기

```
ipconfig getifaddr en0                                   # 맥 IP 확인
open -a "Google Chrome" --args --kiosk http://localhost:8000/monitor
```

같은 Wi-Fi의 다른 기기에서는 `http://<맥 IP>:8000/monitor`를 연다. 외부 모니터로 옮길 때는 창을 그 모니터로 끌고 간 뒤 `⌃⌘F`로 전체 화면으로 만든다. 자세한 절차는 `docs/BUILD.md` 4절.

## 문서

| 문서 | 내용 |
|---|---|
| `CONTRACT.md` | 핀·상수·JSON 형식. 다른 문서와 코드가 어긋나면 이 문서를 먼저 고친다 |
| `docs/SYSTEM_DESIGN.md` | 구성, 데이터 흐름, 핀표, 전원, 프로토콜, 상태기계, 안전, 보정 |
| `docs/MODEL.md` | 학습 자료, 피처, 검증 수치, 방법 선택 |
| `docs/BUILD.md` | 부품표, 제작 순서, 시험 T1~T10, 90초 시연 대본, 문제 해결 |

## 원칙

1. **결빙을 확정하지 않는다.** 화면·로그·발표 모두 '예측 동결확률', '상대 우선순위'라고 쓴다.
2. **자동이어도 멈출 수 있어야 한다.** 대시보드 `stop`, 차 버튼, 초음파 장애물 정지가 항상 동작한다.
3. **LLM을 쓰지 않는다.** 판단은 모델과 코드 규칙이 한다.
4. **비밀값은 저장소에 넣지 않는다.** `config.py`는 빈 문자열로 두고 업로드할 때 채운다.
5. **센서는 보정해서 쓴다.** 시작 30초 평균 또는 `/api/sensors/baseline`으로 기준값을 잡는다.
6. **주석·UI·로그는 한국어, 식별자는 영어.**
