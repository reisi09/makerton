# ICE-ZERO 4차로 모형 — 서버 실행 요약

우드락 왕복 4차로 위를 도는 Pico 라인트레이서 제설차가 **사람이 승인한 칸에만** 모형 제설제를 뿌린다.
노트북 서버가 계획(8칸 점수 → 예산 안 선정 → 루프 순서), 자유 문장 제보 해석, 사람 승인 대시보드를 맡는다.
이 모형은 결빙을 **확정**하는 장치가 아니다. 화면의 점수는 '관측 주의'와 제보를 합친 **상대 우선순위**다.

자세한 규격(칸 ID, 표식, UDP 메시지, 핀)은 [CONTRACT.md](CONTRACT.md)가 기준이다.

## 1. 필요한 것

- Python 3.8 이상 (표준 라이브러리만으로 동작)
- `pyserial` 3.5 — **보드를 USB로 붙일 때만** 필요. 없으면 경고를 남기고 시리얼 링크만 꺼진 채로 서버가 뜬다.
- Command Code API 키 — 제보를 LLM으로 해석할 때만. 없으면 규칙 파서(`rule_parse`)만 쓴다.

```bash
python3 -m pip install pyserial      # 선택
```

## 2. 실행

```bash
cd suwon-makeathon-2026/icezero_model

# 키는 환경변수로만 넘긴다. 화면·파일·로그에 남기지 않는다.
CMD_API_KEY="$(omp token commandcode)" python3 server/icezero_server.py
```

Windows PowerShell:

```powershell
$env:CMD_API_KEY = (omp token commandcode)
python server\icezero_server.py
```

키 없이 대시보드·UDP·승인 절차만 확인하려면:

```bash
python3 server/icezero_server.py --no-llm --board-serial none
```

시작하면 접속 주소와 설정 요약을 출력한다.

```
  대시보드(이 노트북): http://127.0.0.1:8000
  같은 와이파이에서:   http://192.168.0.23:8000   ← 휴대폰·다른 노트북
  제설차 UDP: 0.0.0.0:9100 수신 / 차는 9101 에서 듣는다
  보드 링크: /dev/cu.usbmodem1101
  LLM: deepseek/deepseek-v4.1-flash (reasoning=low)
```

## 3. 노트북 IP 확인 (같은 와이파이 폰에서 열 때)

- macOS: `ipconfig getifaddr en0` (없으면 `en1`)
- Windows: `ipconfig` → 무선 LAN 어댑터의 IPv4 주소
- 리눅스: `hostname -I`
- 서버가 시작할 때 위 주소를 대신 찾아서 출력해 준다.

방화벽이 8000 포트를 막으면 같은 와이파이에서 접속이 안 된다. 그때는 유선/USB 테더링을 쓰거나 방화벽 예외를 추가한다.

## 4. 옵션

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--host` | `0.0.0.0` | HTTP 바인드 주소 |
| `--port` | `8000` | HTTP 포트(대시보드·API) |
| `--udp-port` | `9100` | 제설차 UDP 수신 포트 |
| `--board-serial auto\|포트\|none` | `auto` | `auto`는 usbmodem·ttyACM·COM을 찾고, **2개 이상이면 목록을 출력하고 시리얼을 끈다**. `none`은 시리얼 없이 Wi-Fi(`POST /api/board/telemetry`)만 |
| `--no-llm` | 꺼짐 | LLM 호출 없이 규칙 파서만 사용 |
| `--events` | `server/events.jsonl` | 이벤트 기록 파일 경로 |

환경변수

| 이름 | 기본 | 설명 |
|---|---|---|
| `CMD_API_KEY` | 없음 | Command Code 키(필수는 아님) |
| `CMD_API_BASE` | `https://api.commandcode.ai/provider/v1` | API 주소 |
| `CMD_TEXT_MODEL` | `deepseek/deepseek-v4.1-flash` | 제보 해석 모델 |
| `CMD_TEXT_REASONING` | `low` | `off\|low\|medium\|high\|xhigh\|max` (`none`·`minimal`은 400 오류) |
| `CMD_ZDR` | `1` | `0`이면 `x-cmd-zdr` 헤더를 빼다 |
| `BUDGET_DEFAULT` | `4` | 예산 기본값(0~8) |
| `ICEZERO_TOKEN` | 없음 | 비어 있지 않으면 쓰기 요청에 `X-Token`, UDP 메시지에 `tok` 필요 |
| `ICEZERO_EVENTS` | `server/events.jsonl` | `--events`가 없을 때 쓰는 기록 경로 |

공유 비밀을 켜면 대시보드 오른쪽 위 `X-Token` 칸에 같은 값을 넣거나 `http://<IP>:8000/?token=<값>`으로 연다.
`POST /api/board/telemetry`만 예외다(보드가 토큰을 다루기 어려워 서버가 검사하지 않는다).

## 5. 승인 3단계

1. **제보 확인** — 자유 문장을 넣으면 LLM 해석과 규칙 해석이 나란히 뜬다. 모호하면 질문이 강조된다.
   사람이 칸 체크박스와 예산을 고친 뒤 `확인`을 눌러야 반영된다. `버리기`는 폐기다.
2. **계획 승인** — 자동 제안(점수·예산·루프 순서)을 확인하고 `계획 승인`. `P<n>`이 붙고 차에 UDP `plan`을 보낸다.
3. **출동 승인** — 차가 **같은 plan을 ack**하고 상태가 IDLE·DONE이며 신호가 3초 안에 있을 때만 `출동 승인`이 먹는다.

비상 정지·재개·중단은 언제나 즉시 UDP로 나간다. 안전 정지(초음파·버튼·길 잃음)는 차 안의 피코가 스스로 한다.

## 6. HTTP API (요약)

| 메서드·경로 | 내용 |
|---|---|
| `GET /` | 대시보드(`server/static/index.html`, CDN 없음) |
| `GET /api/state` | 전체 상태(cells·budget·sensors·proposal·approved·car·pending_report·links·events) |
| `POST /api/report` `{"text"}` | LLM 해석(실패 시 규칙) + 규칙 해석을 함께 `pending`에 저장 |
| `POST /api/report/confirm` `{"cells":[],"budget":null\|int,"lane1_closed":[]}` | 사람이 확인한 값만 반영 → 제안 재계산 |
| `POST /api/report/reject` | pending 폐기 |
| `POST /api/observe` `{"caution":true\|false\|null}` | 수동 관측(null=자동 해제) |
| `POST /api/budget` `{"budget":int}` | 예산 수정(0~8) |
| `POST /api/plan/approve` | 현재 제안 승인 → `P<n>` 발급, UDP `plan`, 보드 LED 갱신 |
| `POST /api/dispatch` | 승인 계획 + 차의 같은 plan ack 일 때만 UDP `go` |
| `POST /api/estop` `/api/resume` `/api/abort` | UDP `stop` / `resume` / `abort` |
| `POST /api/reset` | 시연 초기화(제보·살포·수동 관측·승인 계획, 예산 기본값) |
| `POST /api/board/telemetry` | (보드 Wi-Fi 모드) 텔레메트리 본문 → 응답 `{"cells":{...LED 모드}}` |

## 7. 파일 구조

```
icezero_model/
  CONTRACT.md                 공통 계약(기준)
  README.md                   이 문서
  server/
    icezero_server.py         HTTP 대시보드·API + UDP 제설차 + 보드 링크
    plan.py                   순수 함수: 점수·선정·순서·위험 단계
    llm.py                    Command Code 호출 + 응답 검증 + rule_parse 기준선
    static/index.html         대시보드(바닐라 JS)
    events.jsonl              이벤트 기록(실행 중 생김)
  pico_car/                   제설차 펌웨어(config·car_core·main)
  pico_board/                 보드 펌웨어(config·board_core·main)
  tools/car_usb_plan.py       (예비) USB로 계획을 넣는 CLI
  tests/
    test_plan.py              점수·예산·순서·살포·위험 단계
    test_llm.py               JSON 추출·검증·모호 처리·rule_parse(네트워크 없이)
    smoke_e2e.py              서버를 실제로 띄우는 끝단 시험(가짜 차 UDP·가짜 보드 HTTP)
    test_smoke_e2e.py         위 파일을 unittest discover 에 노출하는 래퍼
    reports_eval.json         평가용 제보 12건 + 정답
    eval_reports.py           규칙 vs LLM 정확도·지연 평가
    eval_result.json          평가 결과(실행하면 갱신)
```

## 8. 시험·평가

```bash
cd suwon-makeathon-2026/icezero_model

python3 -m unittest discover -s tests -p 'test_plan*.py' -v
python3 -m unittest discover -s tests -p 'test_llm*.py' -v
python3 -m unittest discover -s tests -p 'test_smoke*.py' -v     # 서버를 임의 포트에 띄운다
python3 -m unittest discover -s tests -v                         # 전부(펌웨어 시험 포함)
```

제보 해석 정확도(규칙 vs LLM 실호출, 12건 · LLM 12회 호출):

```bash
CMD_API_KEY="$(omp token commandcode)" python3 tests/eval_reports.py
python3 tests/eval_reports.py --no-llm      # 규칙 기준선만
```

결과는 `tests/eval_result.json`에 저장한다. 칸 완전 일치는 모호하지 않은 제보만 집계하고, 모호 판정과 예산은 12건 전체로 센다.

## 9. 계약과 다르게 정한 것(빈 곳을 단순하게 채운 부분)

- `POST /api/board/telemetry`는 `X-Token`을 요구하지 않는다. 보드 펌웨어가 토큰을 들고 다니기 어렵기 때문이다.
- '확인된 제보' 점수는 **칸당 1회**로 센다. 같은 칸에 제보가 여러 번 와도 3.0이 중복으로 더해지지 않는다(살포 뒤 새 제보는 다시 3.0).
- `rule_parse`는 문장에 칸 ID(`U2`, `D3` 등)가 직접 있으면 그것을 우선한다. '일반' 구간만 말하면 S1·S4를 가릴 수 없어 모호로 둔다.
- `/api/budget`은 숫자가 아닌 문자열을 400으로 거절한다(조용히 기본값으로 바꾸지 않는다).
- `출동 승인`은 계약의 세 조건(IDLE·DONE, 같은 plan ack)에 더해 **차 링크가 3초 안에 살아 있을 것**도 본다.
- 시험용으로 `--host/--port/--udp-port/--events` 옵션과 `ICEZERO_EVENTS` 환경변수를 두었다. 기본값은 계약과 같다(0.0.0.0:8000, UDP 9100, `server/events.jsonl`).
- 초기화(`/api/reset`)는 계획 번호를 되돌리지 않는다. 같은 시연에서 `P1`이 다시 나오지 않게 하려는 것이다.
