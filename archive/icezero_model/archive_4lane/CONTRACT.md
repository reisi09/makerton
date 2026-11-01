# ICE-ZERO 4차로 모형 — 구현 계약 (모든 모듈 공통)

이 문서가 기준이다. 모듈끼리 주고받는 형식, 핀, 상수를 바꾸지 않는다. 바꿔야 하면 이 문서를 먼저 고친다.
모든 주석, 대시보드, 로그 메시지는 한국어로 쓴다. 코드 식별자는 영어로 쓴다.

## 0. 무엇을 만드나
- 우드락 1800×600mm(900×600 2장)에 왕복 4차로 직선 도로를 만든다. 양 끝에는 회차로를 둔다.
- **제설차(Pico #2)**: 검정 유도선을 따라 타원 루프를 도는 라인트레이서다.
  - 바닥의 막대 표식을 세어 지금 어느 칸에 있는지 안다.
  - 승인된 칸에서만 서보 살포통을 연다.
- **보드(Pico #1)**: 교량의 금속 시험편 온도·젖음을 관측하고, 주의 LED(로컬 규칙)를 켠다. 칸별 LED 8개를 표시한다.
- **노트북 서버**(Python 3.8+ 표준 라이브러리, 보드 USB 연결에만 pyserial 사용)
  - ICE-ZERO-lite 계획 계산: 8칸 점수 → 예산 안 선정 → 루프 순서
  - Command Code LLM으로 자유 문장 제보를 구조화한다.
  - 대시보드를 제공하고 사람 승인 3단계(제보 확인 → 계획 승인 → 출동 승인)를 거친다.
  - 제설차와는 UDP, 보드와는 USB 시리얼(기본) 또는 Wi-Fi HTTP로 통신한다.
- **원칙**
  - LLM은 차를 조종하지 않는다. LLM 결과는 사람이 확인하기 전에는 계획에 반영하지 않는다.
  - 안전 정지(초음파, 버튼, 길 잃음)는 차 안의 피코가 로컬로 한다.
  - 결빙을 '확정'하는 표현을 쓰지 않는다. 화면에는 '관측 주의', '상대 우선순위'라고 쓴다.

## 1. 폴더
```
icezero_model/
  CONTRACT.md            (이 문서)
  README.md              (실행 요약: 서버 담당이 작성)
  server/
    icezero_server.py    HTTP(대시보드·API) + UDP(제설차) + 보드 링크(시리얼 또는 HTTP)
    plan.py              순수 함수: 점수·선정·순서
    llm.py               Command Code 호출 + 응답 검증 + 규칙 기반 비교 파서(rule_parse)
    static/index.html    대시보드(바닐라 JS, 외부 CDN 없음)
  pico_car/
    config.py            팀이 고치는 설정
    car_core.py          순수 로직(하드웨어 import 금지): 조향, 막대 감지, 묶음 분류, 위치, 살포 판단
    main.py              하드웨어·Wi-Fi·UDP·상태기계
  pico_board/
    config.py
    board_core.py        순수 로직: 로컬 경고 규칙(히스테리시스), LED 색, 메시지 파싱
    main.py
  tools/
    car_usb_plan.py      (예비) USB 시리얼로 제설차에 계획을 넣는 CLI
  tests/                 python3 -m unittest discover -s tests 로 전부 통과해야 함
```

## 2. 칸·순서·고정 특성
- 칸 ID: 상행(→ 동쪽, 아래 차로) `U1 U2 U3 U4`, 하행(← 서쪽, 위 차로) `D1 D2 D3 D4`
- 구간
  - S1 일반(서쪽): x 330~615
  - S2 교량: x 615~900, 은박으로 표시하고 평평하게 둔다.
  - S3 그늘: x 900~1185, 양옆에 방음벽
  - S4 일반(동쪽): x 1185~1470
- 루프(주행) 순서: `["U1","U2","U3","U4","D4","D3","D2","D1"]`. 계획의 실행 순서와 보드 LED 체인 순서는 모두 이 순서를 따른다.
- 구조물(교량): `{"U2","D2"}`, 그늘: `{"U3","D3"}`. 보드 관측(교량 시험편)은 교량 칸 U2, D2에 적용한다.

## 3. 바닥 표식(검정 절연테이프 19mm 폭, 길이 70mm, 진행 방향에 수직)
| 종류 | 막대 수(간격: 막대 중심 간 49mm) | 위치 |
|---|---|---|
| END(직선 시작·끝) | 2개 | 아래 차로(y=490): x≈345·394(서), x≈1406·1455(동). 위 차로(y=110): x≈1455·1406(동), x≈394·345(서) |
| SEG(구간 경계) | 1개 | 두 직선 모두 x=615, 900, 1185 |
| HOME(차고지) | 3개 | 서쪽 회차 원호 위, 중심 (330,300), 반지름 190, 각도 155°·140°·125° |

- 유도선
  - 아래 직선: y=490, x 330→1470
  - 동쪽 원호: 중심 (1470,300), r=190
  - 위 직선: y=110, x 1470→330
  - 서쪽 원호: 중심 (330,300), r=190
  - 차는 반시계(화면 기준)로 돈다. 아래 차로는 동쪽으로, 위 차로는 서쪽으로 간다.
- 한 바퀴의 묶음 순서: (HOME에서 출발) → END → SEG → SEG → SEG → END → (동쪽 회차) → END → SEG → SEG → SEG → END → (서쪽 회차) → HOME(정지)
- 위치 규칙(car_core.Position)
  - END 묶음 번호 n(1~4)으로 다리(leg)를 정한다.
    - n=1: 상행 직선 시작 → 현재 칸 U1
    - n=2: 상행 끝 → 회차 중(칸 없음)
    - n=3: 하행 직선 시작 → D4
    - n=4: 하행 끝 → 회차 중
  - 직선 안의 SEG는 구간 번호를 하나씩 올린다. 상행은 U1→U2→U3→U4, 하행은 D4→D3→D2→D1 순서다. 4를 넘으면 마지막 칸에 고정하고 경고 이벤트를 보낸다.
  - END가 오면 SEG 계수를 초기화한다. 막대 하나를 놓쳐도 다음 END에서 다시 맞춘다.
  - HOME(막대 3개 이상) 묶음이 오면 무조건 정지하고 DONE이 된다.
  - 출발 때 이미 막대 위에 서 있으면 첫 검정은 무시한다. 세 센서 중 하나라도 흰색을 본 뒤부터 센다(arming).

## 4. 계획(server/plan.py)
- 점수 = 3.0×확인된 제보 + 2.0×관측 주의(교량 칸, 보드 warn 또는 수동 관측) + 1.5×구조물 + 1.0×그늘
- 이번 밤에 이미 살포한 칸(salted)은 점수를 0으로 둔다. 단, 살포 뒤에 새로 확인된 제보가 있는 칸은 다시 점수를 받는다.
- 후보: 점수 > 0인 칸. 정렬 기준은 (−점수, 루프 순서)이다. 앞에서부터 `budget`개를 고르고, 실행 순서는 루프 순서로 다시 정렬한다.
- 예산 기본값은 4회분(환경변수 `BUDGET_DEFAULT`)이다. 1칸에 1회분을 쓴다. 범위는 0~8이다.
- 위험 단계(LED·화면 색): 점수 0 → `risk1`(초록), 0 초과 2.5 미만 → `risk2`(노랑), 2.5 이상 → `risk3`(빨강)
- 반환 예: `{"plan_id":"P3","cells":["U2","D3","D2"],"order":["U2","D3","D2"],"budget":3,"scores":{...8칸},"reasons":{"U2":["구조물(교량)","관측 주의"],...}}`
  - `cells`와 `order`는 같은 목록(루프 순서)이다.
  - plan_id는 승인될 때 `P<번호>`로 붙인다.

## 5. LLM 제보 해석(server/llm.py)
- 호출 방식은 기존 스타터(`starter/relay/server.py`의 call_api/chat_text)와 같다.
  - `POST {CMD_API_BASE}/chat/completions`, 기본 주소 `https://api.commandcode.ai/provider/v1`
  - 헤더: `Authorization: Bearer $CMD_API_KEY`, `Content-Type: application/json`, **`User-Agent: icezero-model/1.0`**(기본 urllib UA는 Cloudflare 1010으로 차단된다). `CMD_ZDR=1`(기본)이면 `x-cmd-zdr: 1`도 보낸다.
  - 본문: `{"model": CMD_TEXT_MODEL(기본 "deepseek/deepseek-v4.1-flash"), "max_tokens": 2000, "messages":[...], "reasoning_effort": CMD_TEXT_REASONING(기본 "low")}`
  - 허용값은 off|low|medium|high|xhigh|max다. "none"과 "minimal"은 400 오류다.
  - 추론 모델이라 max_tokens가 작으면 본문이 빈다.
  - 시간 제한은 20초다.
- 출력 스키마(코드가 검증한다. 어긋나면 고치거나 버린다)
  ```json
  {"cells":["D3"], "condition":"slippery|ice_suspected|snow|accident|clear|other",
   "budget":3, "lane1_closed":["U3"], "ambiguous":false, "question":"", "summary":"한 줄 요약"}
  ```
  - `cells`는 2절의 8개 ID 중에서만 고른다. 위치가 모호하면 `ambiguous=true`로 두고 `question`에 되물을 문장 하나를 쓴다. 방향이 없으면 "상행(동쪽 방향)인가요, 하행(서쪽 방향)인가요?"처럼 묻는다.
  - `budget`은 "남은 제설제 n회분" 같은 말이 있을 때만 0~8 정수로 채우고, 없으면 null이다.
  - `lane1_closed`는 화면 표시용이다. 1차로는 제설차가 쓰지 않는다.
- `rule_parse(text)`: 같은 스키마를 내는 키워드 규칙 파서다. LLM이 실패할 때 대체로 쓰고, 정확도 비교의 기준선이 된다.
  - 다리/교량 → S2, 그늘/방음벽 → S3
  - 상행/동쪽 방향 → U, 하행/서쪽 방향 → D, 양방향 → 둘 다
  - "숫자+회분"이 있으면 예산
  - 구간은 있는데 방향이 없으면 ambiguous
- 해석 결과는 `pending`에 저장만 한다. 사람이 `/api/report/confirm`으로 수정·확인해야 반영된다.

## 6. 서버 HTTP API (기본 0.0.0.0:8000)
| 메서드·경로 | 내용 |
|---|---|
| GET / | 대시보드(static/index.html) |
| GET /api/state | 전체 상태: cells(점수·이유·위험 단계·제안 포함 여부·승인 포함 여부·살포 여부), budget, sensors(보드 텔레메트리 + 마지막 수신 시각 + 수동 관측), proposal, approved, car(상태·위치·살포 목록·마지막 수신), pending_report, links(board/car/llm), events(최근 50개) |
| POST /api/report `{"text"}` | LLM 해석(실패 시 rule_parse) + rule_parse 결과를 함께 pending에 저장하고 반환 |
| POST /api/report/confirm `{"cells":[],"budget":null\|int,"lane1_closed":[]}` | 사람이 확인한 값만 반영 → 제안 재계산 |
| POST /api/report/reject | pending 폐기 |
| POST /api/observe `{"caution":true\|false\|null}` | 수동 관측. 보드가 없을 때 쓰고, null이면 해제한다 |
| POST /api/budget `{"budget":int}` | 예산 직접 수정 |
| POST /api/plan/approve | 현재 제안을 승인하고 plan_id를 붙인다 → 보드 LED 갱신, 제설차에 UDP plan 전송(ack 받을 때까지 재전송) |
| POST /api/dispatch | 승인 계획이 있고 차가 IDLE·DONE이며 같은 plan을 ack했을 때만 UDP go 전송 |
| POST /api/estop, /api/resume, /api/abort | UDP stop / resume / abort |
| POST /api/reset | 시연 초기화(제보·살포·관측 수동값 초기화, 예산 기본값) |
| POST /api/board/telemetry | (보드 Wi-Fi 모드) 본문은 7절 텔레메트리, 응답은 `{"cells":{...LED 모드}}` |
- 선택 공유 비밀: 환경변수 `ICEZERO_TOKEN`이 비어 있지 않으면 쓰기 요청 헤더 `X-Token`과 UDP 메시지 `tok` 필드를 확인한다.
- 이벤트는 `server/events.jsonl`에 한 줄 JSON으로 덧붙인다.

## 7. 보드(Pico #1) 링크
- 텔레메트리(1초마다): `{"t_piece":float|null,"t_air":float|null,"wet":bool,"wet_raw":int,"warn":bool,"up":int}`
- LED 명령: `{"cells":{"U1":"risk1|risk2|risk3|plan|salted|off", ...8칸}}`
  - 서버 규칙: 승인 계획에 있고 아직 안 뿌린 칸 → plan, 살포한 칸 → salted, 나머지 → 위험 단계
- USB 모드(기본)
  - 보드는 `print("@@TEL " + json)`으로 보낸다.
  - 서버는 시리얼 115200으로 `@@LED {json}\n`을 쓴다. 바뀔 때마다 쓰고, 2초마다 다시 쓴다.
  - 서버 옵션은 `--board-serial auto|<포트>|none`이다. auto는 usbmodem·ttyACM·COM 포트를 찾고, 2개 이상이면 목록을 출력하고 시리얼 링크를 끈다.
- Wi-Fi 모드: 보드가 `POST /api/board/telemetry`를 보내고 응답으로 LED 명령을 받는다.
- 로컬 경고(board_core.local_warn)는 서버와 무관하게 동작한다.
  - 켜짐: `t_piece ≤ WARN_ON_C(기본 1.0) and wet` 또는 `t_piece ≤ FREEZE_C(기본 0.0)`
  - 꺼짐: 켜짐 조건이 3회 연속 거짓일 때
  - t_piece가 None이면 젖음만으로는 켜지 않고 이전 상태를 유지한다.

## 8. 제설차(Pico #2) UDP
- 서버는 UDP 9100에서 듣는다. 차는 9101에서 듣는다. 메시지는 UTF-8 JSON 한 개이고 512바이트 이하다.
- 차 → 서버
  - `hello`(1초마다): `{"t":"hello","id":"car-1","st":"IDLE|RUN|HOLD_OBS|HOLD_CMD|LOST|DONE","plan":"P3"|null,"cells":[...],"salted":[...],"pos":{"leg":0-4,"seg":0-4,"cell":"U2"|null},"dist":cm|null}`
  - 이벤트: `{"t":"evt","id":"car-1","e":"start|marker|salt|obstacle|clear|estop|resume|lost|done|warn","cell":..,"grp":1|2|3,"pos":{...}}`
  - 응답: `{"t":"ack","seq":n}`
- 서버 → 차
  - `{"t":"plan","seq":n,"plan_id":"P3","cells":[...]}`: IDLE·DONE에서만 받는다. 그 밖의 상태에서는 ack만 하고 거절 이벤트(warn)를 보낸다.
  - `{"t":"go","seq":n,"plan_id":"P3"}`: plan_id가 같을 때만 출발한다.
  - `{"t":"stop","seq":n}`(언제나 즉시 정지 → HOLD_CMD), `{"t":"resume","seq":n}`(HOLD_CMD에서만), `{"t":"abort","seq":n}`(정지 → IDLE, 사람이 차를 차고지로 옮긴다)
  - 같은 seq는 한 번만 실행하고 ack는 매번 보낸다.
  - 서버는 ack가 올 때까지 300ms마다 최대 10회 다시 보낸다.
- 차는 첫 hello를 보낼 서버 주소를 config.SERVER_IP로 안다. 서버는 받은 패킷의 주소로 답한다.

## 9. 핀 배치
### Pico #2 제설차
| 장치 | 핀 |
|---|---|
| 모터 드라이버 TB6612FNG(기본, DRIVER="tb6612") | AIN1=GP10, AIN2=GP11, PWMA=GP12(왼쪽), BIN1=GP13, BIN2=GP14, PWMB=GP15(오른쪽), STBY=GP9 |
| L9110S·DRV8833(DRIVER="pwm2") | 왼쪽 IN1=GP10, IN2=GP11 / 오른쪽 IN1=GP13, IN2=GP14(모두 PWM) |
| 라인센서 디지털 출력 | 왼쪽=GP18, 가운데=GP19, 오른쪽=GP20 (`BLACK_LEVEL` 기본 1: 검정에서 1을 내는 모듈. 반대면 0) |
| HC-SR04 | TRIG=GP2, ECHO=GP3(1kΩ/2kΩ 분압 필수), VCC=VBUS(5V) |
| 살포 서보 SG90 | GP16(50Hz), 전원 VBUS 5V + 470µF 권장 |
| 경광 LED | GP17(220Ω). 보드 내장 LED도 함께 깜박임 |
| 버튼 | GP21 ↔ GND(내부 풀업) |
- 모터 PWM은 1000Hz다. 서보 duty는 스타터와 같은 식을 쓴다: `1638 + (8192-1638)*angle//180`

### Pico #1 보드
| 장치 | 핀 |
|---|---|
| DS18B20 2개(시험편·공기) | 데이터=GP4, 4.7kΩ 풀업 → 3V3 |
| 젖음센서 AO | GP26(ADC0), 모듈 전원 3V3 |
| 교량 주의 LED | GP15(220Ω) |
| 칸 LED | LED_MODE="neopixel"(기본): WS2812 8개, DIN=GP16(330Ω), 5V. 체인 순서 = 루프 순서 / "gpio": 단색 LED 8개 GP6~GP13 |

## 10. 제설차 주행 로직(car_core, 기본값은 config.py)
- 조향(steer): 센서 (L,C,R), 1=검정
  - (0,1,0): 직진(BASE, BASE)
  - (1,1,0): 약하게 좌회전(BASE−SOFT, BASE+SOFT). (0,1,1)은 대칭
  - (1,0,0): 강하게 좌회전(BASE−HARD, BASE+HARD). (0,0,1)은 대칭
  - (1,1,1) 또는 (1,0,1): 직진(막대 통과)
  - (0,0,0): 마지막으로 본 쪽으로 강하게 회전한다. LOST_MS(700)를 넘기면 정지하고 LOST가 된다.
  - 반환값은 −1.0~1.0 비율이다. main.py가 duty로 바꾼다.
- 막대 감지(BarDetector): 세 센서 모두 검정이 BAR_CONFIRM(2)회 연속이면 막대 1개다. 셋 중 하나가 흰색이 될 때까지는 같은 막대로 본다.
- 묶음 분류(GroupClassifier): 막대 사이 간격이 GROUP_GAP_MS(700) 미만이면 같은 묶음이다. 마지막 막대 뒤 GROUP_GAP_MS 동안 새 막대가 없으면 묶음을 확정한다(1=SEG, 2=END, 3 이상=HOME).
- 살포(Salter): 현재 칸이 계획에 있고 아직 살포하지 않았으면 칸에 들어온 직후 SALT_MS(600) 동안 열었다 닫는다. 칸당 1회다.
- 초음파: US_PERIOD_MS(60)마다 1회 잰다(time_pulse_us 시간 제한 6000µs, 시간 초과는 '멀리 있음').
  - STOP_CM(12) 이하: HOLD_OBS(정지)
  - RESUME_CM(18) 이상이 500ms 이어지면 이전 상태로 돌아간다.
- 버튼(짧게 누름)
  - IDLE·DONE에 계획이 있음: 출발(USB 대체 모드)
  - RUN: 비상 정지(HOLD_CMD)
  - HOLD_CMD: 재개
- 계획 저장: 받은 계획은 `plan.json`에 저장해 재부팅 뒤에도 남긴다.
- USB 대체: IDLE일 때 stdin에서 `@@PLAN {"plan_id":..,"cells":[..]}` 줄을 받으면 저장한다.
- Wi-Fi 연결 실패: 오프라인으로 계속 동작한다(버튼 출발 가능). 10초마다 재연결을 시도만 한다(기다리지 않음).

## 11. 시험 기준
- `python3 -m unittest discover -s icezero_model/tests -v`가 하드웨어 없이 전부 통과해야 한다.
- MicroPython 파일은 `~/Library/Python/3.9/bin/mpy-cross <파일>`로 컴파일 오류가 없어야 한다. 생성된 .mpy는 지운다.
- MicroPython 호환
  - f-string 대신 `%`나 `.format`을 쓴다.
  - dataclass, typing, walrus 연산자를 쓰지 않는다.
  - `time.ticks_ms`/`ticks_diff`를 쓴다(CPython 시험용 대체는 테스트 쪽에서 주입).
- 비밀값: API 키는 환경변수로만 읽는다. 출력이나 파일에 쓰지 않는다. 키는 `omp token commandcode`로 얻는다.
