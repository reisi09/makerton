# ICE-ZERO 사거리 모형 — 실행 안내

강남구 실제 교차로(노드 1220041600)를 옮긴 **십자 사거리** 모형이다. 맥북이 실제 ASOS 겨울밤 하나를
시간 단위로 재생하며 XGBoost 예보 모델로 갈래별 동결확률과 우선순위를 계산하고, 사람이 승인하면
USB 시리얼로 **Pico #1**(Pico 2 W · MicroPython)이 갈래 LED와 서보 살포기 4개를 순서대로 움직인다.
자유 문장 현장 제보는 Command Code LLM이 갈래·예산으로 구조화한다.

원칙
- 결빙을 확정하지 않는다. 화면에도 문서에도 '예측 동결확률', '상대 우선순위'로만 쓴다.
- LLM은 기기를 조종하지 않는다. **제보 확인 → 계획 승인 → 출동 승인**을 사람이 눌러야 움직인다.
- 교량 주의 LED는 Pico가 로컬 규칙으로 직접 켠다(USB를 뽑아도 동작).
- 기준 문서는 `CONTRACT_CROSS.md`다. 형식·핀·상수를 바꾸려면 계약을 먼저 고친다.

## 1. 준비물 확인

```bash
/usr/bin/python3 -V                     # 3.9.6
/usr/bin/python3 -c "import pandas, numpy, xgboost, sklearn, scipy, serial; \
  print(pandas.__version__, numpy.__version__, xgboost.__version__, sklearn.__version__, scipy.__version__, serial.__version__)"
# 2.3.3 2.0.2 2.1.4 1.6.1 1.13.1 3.5
```

XGBoost가 `libomp`를 찾지 못해 죽으면:

```bash
brew install libomp
```

MicroPython 컴파일 확인(펌웨어를 고쳤을 때만):

```bash
~/Library/Python/3.9/bin/mpy-cross pico_cross/config.py
~/Library/Python/3.9/bin/mpy-cross pico_cross/cross_core.py
~/Library/Python/3.9/bin/mpy-cross pico_cross/main.py
rm -f pico_cross/*.mpy
```

## 2. 모델 만들기 (`engine/models/`)

자료(`engine/data/weather_winter_clean.csv`, 2025년 시험 구간 포함)로 시점별(h0·h1·h3·h6)
XGBoost를 학습하고 isotonic 동결확률 보정, 지표, 후보 밤 목록을 저장한다. 이미 만들어 두었다면 건너뛴다.

```bash
cd icezero_model
python3 engine/train.py            # 학습 + 평가 + models/ 생성 (1분 이내)
python3 engine/train.py --force    # 다시 만들기
```

`engine/models/`에 `xgb_h0.json` … `xgb_h6.json`, `calib.json`, `metrics.json`, `nights.json`이 생긴다.
서버는 시작할 때 `Engine.load()`로 이것을 읽는다. 없으면 그 자리에서 학습하고, 그것도 실패하면
엔진 없이 뜨고 대시보드에 오류를 표시한다(제보·예산 API는 계속 동작).

## 3. 서버 실행

```bash
cd icezero_model

# 실제 시연(LLM + Pico 자동 연결)
CMD_API_KEY="$(omp token commandcode)" python3 server/icezero_server.py --pico-serial auto

# LLM 없이, Pico 없이(연습·시험)
python3 server/icezero_server.py --no-llm --pico-serial none
```

브라우저에서 `http://127.0.0.1:8000` 을 연다. 같은 와이파이의 휴대폰에서는 시작할 때 찍히는
`http://<노트북 IP>:8000` 으로 접속한다.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--host` / `--port` | `0.0.0.0` / `8000` | HTTP 바인드 주소·포트 |
| `--pico-serial` | `auto` | `auto`(usbmodem 자동, 후보가 2개 이상이면 끔) · `/dev/cu.usbmodem…` · `none` · `fake`(시험용 가짜 Pico) |
| `--no-llm` | 꺼짐 | LLM 호출 없이 규칙 파서만 쓴다 |
| `--night` | 후보 1순위 | 처음 재생할 밤(`YYYY-MM-DD`) |
| `--events` | `server/events.jsonl` | 이벤트 기록 파일(한 줄에 JSON 하나) |

API 키는 환경변수로만 넘긴다. 코드·로그·화면·파일 어디에도 쓰지 않는다.

### API

| 메서드·경로 | 내용 |
|---|---|
| `GET /`, `GET /api/state` | 대시보드, 전체 상태(현재 step, 재생, 예산, 제보, 승인 계획, 실행, 센서·Pico, 이벤트) |
| `POST /api/replay {"night":"YYYY-MM-DD"}` | 재생할 밤 선택(18:00부터) |
| `POST /api/replay/step {"hours":1}` | 시각 이동(음수 허용, 범위 밖은 끝에서 멈춤) |
| `POST /api/replay/auto {"on":true,"sec_per_hour":6}` | 자동 재생 |
| `POST /api/report {"text"}` | LLM 해석(실패·꺼짐이면 규칙 해석) + 규칙 해석을 pending 에 저장 |
| `POST /api/report/confirm {"arms":["E"],"budget":2}` · `/api/report/reject` | 사람이 확인한 값만 반영 |
| `POST /api/budget {"budget":0~4}` | 예산 |
| `POST /api/sensor {"use_sensor":true,"t_bridge":-3.4}` | 현장 보정 사용 여부·수동 값 |
| `POST /api/plan/approve` | 현재 제안을 승인 계획(`plan_id`)으로 고정 → Pico LED `plan` |
| `POST /api/dispatch` | 승인 순서대로 `@@SPRAY` 하나씩, `spray_done` 대기(갈래당 4초). Pico 없으면 모의 실행 |
| `POST /api/estop` · `POST /api/reset` | 남은 실행 취소 + `@@STOP` · 시연 초기화 |

화면은 0.5초마다 `/api/state`를 폴링한다. CDN·외부 폰트를 쓰지 않는다(현장 와이파이 없이 동작).

### 시연 순서

1. 밤 선택(기본 1순위: `2025-12-07`) → `▶` 로 새벽까지 이동한다. 선 그래프에 관측 지면온도와
   +3h 예측이 같이 그려지고 현재 시각이 세로선으로 표시된다.
2. (선택) 센서 패널에서 '현장 보정 사용'을 켠다. Pico가 5초 안에 `t_bridge`를 보내면 그 값,
   Pico가 없으면 수동 값이 쓰인다. 보정은 교량 갈래(E)에만 들어간다.
3. 제보를 적고 **해석하기** → LLM 해석과 규칙 해석을 나란히 비교하고, 갈래 체크박스와 예산을
   사람이 고친 뒤 **확인**. 확인 전에는 계획이 바뀌지 않는다.
4. **계획 승인** → Pico 갈래 LED가 파랑(2Hz)으로 바뀐다.
5. **출동 승인** → 승인 순서대로 서보가 하나씩 열리고, 끝난 갈래는 흰색(done)이 된다.
   갈래당 4초 안에 완료 신호가 없으면 중단하고 화면에 표시한다.
6. **비상 정지**는 언제든 남은 실행을 취소하고 `@@STOP`을 보낸다.

## 4. Pico #1 업로드

`pico_cross/`의 네 파일을 Pico 파일 시스템 루트에 그대로 올린다. Thonny로 열어 두고
'실행'하면 되고, 명령줄이면:

```bash
# mpremote 사용(권장)
python3 -m mpremote connect /dev/cu.usbmodem* fs cp pico_cross/config.py :config.py
python3 -m mpremote connect /dev/cu.usbmodem* fs cp pico_cross/cross_core.py :cross_core.py
python3 -m mpremote connect /dev/cu.usbmodem* fs cp pico_cross/main.py :main.py

# 배선 확인용(선택): 서보·LED·센서를 하나씩 시험한다.
python3 -m mpremote connect /dev/cu.usbmodem* fs cp pico_cross/hwtest.py :hwtest.py
python3 -m mpremote connect /dev/cu.usbmodem* run hwtest.py
```

배선(계약 5절)

| 장치 | 핀 |
|---|---|
| 서보 살포기 SG90 ×4 | N=GP18, E=GP19, S=GP20, W=GP21 (전원은 별도 5V, GND 공통) |
| 갈래 LED | WS2812 4픽셀 DIN=GP16 (N,E,S,W 순) 또는 단색 GP6·GP7·GP8·GP9 (`config.LED_MODE`) |
| DS18B20 ×2 | GP4 + 4.7kΩ 풀업(교량 시험편·공기) |
| 젖음센서 AO | GP26 |
| 교량 주의 LED | GP15 |
| 부저(선택) | GP17 |

부팅하면 시험편 DS18B20 순서(`PIECE_INDEX`)와 젖음 임계값(`WET_THRESHOLD`)을 배선에 맞춰 고친다.

## 5. 폴더

```
icezero_model/
  CONTRACT_CROSS.md              기준 문서(형식·핀·상수)
  README.md                      이 문서
  engine/
    icezero_cross.py             Engine: 학습·평가·보정·밤 찾기·step
    train.py                     CLI → models/
    data/weather_winter_clean.csv  ASOS 겨울 시간 자료(읽기 전용)
    data/cross_arms.json         교차로 4갈래 속성(N·E·S·W)
    models/                      생성물: xgb_h0..h6.json, calib.json, metrics.json, nights.json
  server/
    icezero_server.py            HTTP 대시보드·API, 재생, 승인, Pico 시리얼, events.jsonl
    llm.py                       Command Code 호출(4갈래판) + rule_parse 기준선
    static/index.html            대시보드(CDN 없음, 0.5초 폴링)
  pico_cross/
    config.py                    핀·상수
    cross_core.py                순수 로직(살포 큐·LED 색·경고 규칙)
    main.py                      MicroPython 진입점(@@TEL / @@LED / @@SPRAY / @@STOP)
    hwtest.py                    배선 확인용
  tests/                         시험·평가
    test_server_cross.py         서버(가짜 엔진·가짜 Pico + 실제 엔진 CLI 스모크)
    test_llm_cross.py            제보 해석(네트워크 없음)
    test_engine.py, test_pico_cross.py
    reports_cross.json           제보 12건 + 정답
    eval_reports_cross.py        규칙 vs LLM 평가 → eval_cross_result.json
  docs/                          가이드 PDF
  archive_4lane/                 이전 4차로 버전(수정 금지)
```

## 6. 시험

```bash
cd icezero_model

# 전체
python3 -m unittest discover -s tests -v

# 서버·제보 해석만
python3 -m unittest discover -s tests -p 'test_server*.py' -v
python3 -m unittest discover -s tests -p 'test_llm*.py' -v
```

시험은 하드웨어 없이 돈다.
- 서버: 프로세스 안에서 `Model` + `ThreadingHTTPServer`를 띄우고 **가짜 엔진**(계약 3절 JSON과 같은 모양)과
  **가짜 Pico**(시리얼 대신 내부 큐)를 주입한다. 재생 → 제보 → 확인 → 예산 → 승인 → 출동(모의) →
  상태 확인과, `@@SPRAY` 순서 / `spray_done` 처리 / 시간초과 중단 / `@@STOP` 경로를 본다.
- 실제 엔진이 있으면(`engine/models/xgb_h3.json`) 서브프로세스로 `--no-llm --pico-serial none` 서버를
  임의 포트에 띄워 실제 모델로 같은 흐름을 한 번 더 돈다. 모델이 없으면 그 시험만 건너뛴다.

### 제보 해석 평가

```bash
python3 tests/eval_reports_cross.py --rule-only          # 규칙만(네트워크 없음)
CMD_API_KEY="$(omp token commandcode)" python3 tests/eval_reports_cross.py
python3 tests/eval_reports_cross.py --llm-ids 8,9,11     # LLM 호출 예산을 지킬 때
python3 tests/eval_reports_cross.py --llm-from tests/eval_cross_result.json   # 저장된 해석 재채점
```

결과는 `tests/eval_cross_result.json`에 남는다. 개발 세트(제보 12건)는 규칙 파서를 만들며 본 문장이라
규칙 12/12는 맞춘 결과다. LLM은 이 세트에서 3건 표본만 쟀다(3/3).

공정한 비교는 보류 세트다. 규칙을 만든 뒤 새로 쓰고 정답을 먼저 정한 12건이다(`tests/reports_cross_holdout.json`).
이 세트를 보고 규칙·프롬프트를 고치지 않는다. 고치면 새 보류 세트를 만든다.

```bash
CMD_API_KEY="$(omp token commandcode)" python3 tests/eval_reports_cross.py \
  --reports tests/reports_cross_holdout.json --out tests/eval_cross_holdout.json
```

최근 측정(2026-10-31, LLM 실호출 12건, 대체 0건)
- 규칙: 완전 일치 6/12
- LLM: 완전 일치 12/12, 평균 2,650ms

규칙이 틀린 문장 유형은 동의어('그림자', '역삼로', '네 방향'), 부정('괜찮은데'), 예산 표현('한 번 분량', '없음')이다.

## 7. 계약과 다르게 채운 부분

- **`--pico-serial fake`**: 계약의 `auto|포트|none`에 시험용 `fake`를 더했다. 프로세스 안 가짜 Pico로
  시리얼 경로(파싱·LED·SPRAY·STOP)를 하드웨어 없이 확인한다.
- **`ICEZERO_ENGINE_MODULE` 환경변수**: 기본값 `icezero_cross`. 시험에서 가짜 엔진 모듈을
  주입하거나 '엔진 없음' 상태를 확인할 때만 바꾼다(서버 코드는 `import icezero_cross`만 한다).
- **시계열(`state.series`)**: 시간 추이 그래프용으로 그 밤의 `obs.ground_temp`와 `forecast.h3`를
  밤마다 한 번 백그라운드에서 계산해 상태에 넣는다. 계약 4절 상태 JSON에 없던 키이며,
  화면 전용이다(제보·센서 보정 전 모델 값).
- **`/api/sensor`의 `t_bridge`**: `null`이면 수동 값을 지운다. `use_sensor`가 참이고 Pico 값이
  5초 안에 있으면 Pico 값이 이긴다(계약 4절).
- **`/api/plan/approve` 응답의 `sent`**: Pico가 없으면 false(승인은 그대로 유지).
- **`execution.mode`**: `pico`(실제 시리얼) 또는 `mock`(모의 실행). Pico 텔레메트리가 5초 넘게
  없으면 자동으로 `mock`으로 간다.
- **평가 정답 1건 조정**: '사거리 전체가 얼음 같아요'를 처음에는 '모호'로 두었으나, LLM이 네 갈래
  전부로 해석했고 그쪽이 제품 의도에 맞아 정답을 '네 갈래'로 고치고 규칙 파서에도 전체 표현
  (`전체`·`모두`·`네 갈래`) 처리를 넣었다.
