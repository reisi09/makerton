# 피코 WH × Command Code 공통 스타터

```
[피코 WH + 센서] ──USB 직렬(기본) 또는 Wi-Fi HTTP(선택)──> [노트북 relay/server.py] ──HTTPS──> [Command Code API]
      ↑                                                           │  /systemone (typesafe/jev): 상태 → 확률 → 조치 단계
      └──────────────────── 조치 단계 0~3 ───────────────────────┘  /chat/completions: 수동 요청서 또는 AGENT=1 제안
```

- API 키는 노트북 환경변수에만 둔다. 피코, 코드 파일, 화면 캡처에는 넣지 않는다.
- USB 모드는 AI 응답을 기다리는 동안에도 센서를 읽고 LED를 바꾼다. Wi-Fi 모드는 `requests.post(..., timeout=5)`를 동기로 기다리므로 같은 실시간 반응을 보장하지 않는다. 응답이 없으면 로컬 규칙으로 돌아가 **파랑을 같이 켠다**(AI 아님 표시). 파랑만 켜지면 센서 오류다.
- jev 선택지 확률이 0.80 미만이면 `review`(노랑, 사람 확인)로 내린다. 2026-10-31 실호출 10건을 돌려 봤다.
  - jev가 가장 높게 준 선택지는 10건 모두 예상과 같았다.
  - 그중 5건은 확률이 0.47~0.76이라 `review`로 내려갔다.
  - 시연 전에 프로필별 `min_p`를 반복 측정으로 정한다.
  - 단차처럼 반드시 지켜야 하는 조건은 jev에 맡기지 말고 규칙으로 강제한다. 단차가 있는 A에도 0.26을 줬다.
- chat 모델 `deepseek/deepseek-v4.1-flash`는 추론 모델이다. 추론에 `max_tokens`를 다 쓰면 본문이 빈다. 실호출에서 300과 1,200 모두 빈 응답이었다.
  - 그래서 서버가 `reasoning_effort`(`CMD_TEXT_REASONING`, 기본 `low`)와 `max_tokens` 2,000을 보낸다.
  - 실측: `low`는 4.7~6.5초에 3번 중 3번 상태를 맞게 읽었다. `off`는 2.1~3.0초지만 6번 중 1번 상태를 잘못 읽었다.
  - 이 옵션을 받지 않는 모델로 바꾸면 `CMD_TEXT_REASONING=`(빈 값)으로 끈다.
- jev 질문은 `relay/profiles.json`에 있다. 기본 예제는 `access_space`(통로 1곳)이고, v2 아이디어 5개는 `route_guide`, `collect_station`, `boarding_handoff`, `drain_lab`, `noise_lab`이다. `pico/main.py`는 `access_space` 예제다. `action`은 `actuate()`까지 전달하지만 경로 화살표 등 아이디어별 분기는 직접 구현해야 한다.

## 0. 준비물
- Command Code API 키: GOAT·Pro·Max·Team·Provider 플랜만 API를 쓸 수 있다(Go 플랜은 안 됨). https://commandcode.ai/settings/keys 에서 만든다.
- 노트북: Python 3.8 이상, `pip install pyserial`(USB 모드용). 중계 서버는 표준 라이브러리만 쓴다.
- 피코: MicroPython 펌웨어(Pico W용 UF2). Thonny로 `pico/main.py`와 `pico/config.py`를 보드에 저장한다.

## 1. 실행: USB 모드(기본)
```bash
cd relay
export CMD_API_KEY='여기에-키'          # 터미널에만 입력한다. 파일에 저장하지 않는다
export RELAY_TOKEN='team-secret'
HOST=127.0.0.1 python3 server.py        # 터미널 1: relay on 127.0.0.1:8000
python3 serial_bridge.py /dev/tty.usbmodem1101   # 터미널 2: Windows는 COM3 같은 이름. Thonny는 먼저 닫는다
```
- 대시보드는 `http://127.0.0.1:8000/?token=team-secret`이다. AI 확률과 '요청서 초안 만들기' 버튼이 보인다.
- 포트 이름 찾기: macOS `ls /dev/tty.usbmodem*`, Windows 장치 관리자 → 포트(COM & LPT)

## 2. Wi-Fi 모드(선택, 첫날 5분 점검을 통과한 경우)
1. 휴대폰 핫스팟을 2.4GHz로 켠다(아이폰은 '호환성 최대화'). 노트북과 피코를 둘 다 연결한다.
2. `python3 server.py`로 띄운다(0.0.0.0:8000). 피코 `config.py`를 `TRANSPORT="wifi"`, `WIFI_SSID`, `WIFI_PASSWORD`, `RELAY_URL="http://<노트북 IP>:8000/decide"`, `RELAY_TOKEN`으로 고친다.
3. Thonny 셸에 `AI {...}`가 찍히면 통과다. `relay 연결 실패`가 나오면 원인은 보통 노트북 방화벽(Windows는 python의 '공용 네트워크' 허용 필요)이나 핫스팟의 단말 간 차단이다. 5분 안에 안 풀리면 USB로 돌아간다.

## 3. 다른 아이디어로 바꾸기
- 피코: `read_state()`(센서 → dict), `local_level()`(로컬 규칙), `actuate()`(단계·선택지 → LED·서보), `config.PROFILE`을 바꾼다. `state_key()`는 현재 로컬 단계와 참/거짓 값만 포함하므로, 새 판단에 필요한 수치 구간·열거 상태·이동 단계가 있으면 키에도 반영해야 한다. 그렇지 않으면 낡은 제안을 무효화하지 못할 수 있다.
- 중계: `profiles.json`의 해당 프로필 `labels`가 피코가 보내는 키 이름과 같아야 한다. 선택지를 바꾸면 `levels`도 같이 바꾼다(서버가 시작할 때 검사한다).
- 시연용으로 시간을 줄였다면 `profiles.json`의 `context` 문장도 같은 숫자로 고친다(jev는 그 문장을 기준으로 판단한다).

## 3-1. LLM 에이전트 제안 + 사람 승인(고도화 아이디어용)
기본 예제는 피코 1대다. 초보팀 전제를 철회한 최신 추천은 `../최종_산출물_v2.md` §0-1의 보도·정류장 2노드 통합안이다(보드 확보 조건). 아래는 공통 통신·승인 사용법이며, 이동 건별 상태 전이·노드 간 인계·경로 실행·완료 검증까지 구현된 코드는 아니다.
1. 노드마다 `config.DEVICE_ID`(예: `route`, `cane`)와 `config.POS`(대시보드 지도 좌표 0~100)를 다르게 정한다. USB 모드면 노드마다 `serial_bridge.py`를 하나씩 띄운다(포트만 다르게).
2. 중계 서버를 `AGENT=1`로 띄운다(음성까지 쓰려면 `TTS=1`). 그러면 다음처럼 움직인다.
   - 어느 노드의 jev 조치가 바뀌면 chat 모델이 전체 노드 상태를 보고 **제안 하나**를 만든다. 형식은 `{"speech", "target": 노드 하나, "level": 0~3, "reason", "map_note"}`이고, 대시보드에 '승인 대기'로 뜬다.
   - 호출은 최소 8초 간격이다. 그 사이의 변화는 버리지 않고 최신 1건만 간격이 끝난 뒤 처리한다. 실행 한 번에 `AGENT_MAX_CALLS`(기본 300)회까지만 부른다.
   - **대시보드에서 사람이 '승인'을 눌러야** 명령과 음성이 나간다. 승인할 때 다음 중 하나라도 해당하면 실행하지 않고 폐기한다: 60초가 지났다 / 제안 뒤 관련 노드의 상황 키(`k`)나 조치가 바뀌었다 / 관련 노드가 15초 넘게 보고하지 않았다.
   - 승인된 명령은 15초 동안 대상 노드의 poll(1초마다, API 비용 없음) 응답에 `cmd`, `cmd_id`로 실린다. 피코는 같은 `cmd_id`를 다시 적용하지 않고, `CMD_HOLD_S`(10초) 동안 단계를 **올리기만** 한다.
   - 음성(`speech`)은 승인된 것만, 한 번에 하나씩 노트북 스피커로 읽는다(macOS 한국어 음성 Yuna, 없으면 기본 음성. Windows는 System.Speech). 실패해도 화면 안내는 남는다.
3. 진동모터(지팡이 등)는 `config.VIBRO_PIN = 21`로 켠다. GPIO에 직접 물리지 말고 NPN 트랜지스터(예: 2N2222)와 1kΩ 베이스 저항, 역기전력 다이오드(1N4148)를 거친다.

## 4. 배선 안전
- RP2040 GPIO는 3.3V 전용이다. HC-SR04 ECHO는 1kΩ/2kΩ로 분압한다. 서보는 VBUS나 별도 5V로 공급하고 GND를 공통으로 묶는다.
- 초음파 맞은편에 반사판을 둔다. 반사가 없으면 센서 오류(파랑)로 처리된다.

## 5. 비용(문서 단가 기준 추정)
- jev는 입력 $0.042/100만 토큰이다. 1,000회(회당 800토큰)여도 약 $0.034다. 피코는 상황이 바뀔 때와 10초마다만 묻는다.
- deepseek-v4.1-flash 에이전트 제안 1건은 실호출 기준 입력 약 330토큰, 출력(추론 포함) 약 360~760토큰이다. 단가로 계산하면 약 $0.0003~0.0005다. 요청서 초안은 버튼을 누를 때만 만들어진다.
- `typesafe/jev`는 ZDR 헤더(`x-cmd-zdr: 1`)를 지원하지 않는다. 사람 이름·얼굴·번호판 같은 개인정보는 보내지 않는다. `deepseek/deepseek-v4.1-flash`는 이 헤더를 붙인 요청에 HTTP 200으로 응답했다(2026-10-31). 현재 서버는 이 헤더를 붙이지 않으므로, 자유 문장을 보내는 기능을 만들 때 추가한다.
