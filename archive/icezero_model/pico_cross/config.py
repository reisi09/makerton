# ICE-ZERO 사거리 모형 — Pico #1 설정. 현장에서 팀이 직접 고치는 값만 모았다.
# 계약(CONTRACT_CROSS.md 5절)의 핀과 상수를 그대로 옮겼다. 바꾸면 계약도 함께 고친다.
# 비밀값(API 키)은 여기에 적지 않는다. 서버와 주고받는 것은 USB 시리얼뿐이다.

# ── 갈래 순서 ──
ARM_ORDER = ("N", "E", "S", "W")   # 보드 위쪽이 북쪽. LED 체인·서보 목록도 이 순서다.

# ── 서보 살포기 SG90 ×4 ──
SERVO_PINS = (18, 19, 20, 21)      # 서보 신호선: N=GP18, E=GP19, S=GP20, W=GP21
SERVO_FREQ = 50                    # SG90 규격 50Hz(20ms 주기)
SERVO_CLOSED_DEG = 0               # 닫힘 각도(알갱이가 떨어지지 않는 위치)
SERVO_OPEN_DEG = 60                # 열림 각도(알갱이가 미끄럼판으로 흘러내리는 위치)
SERVO_DUTY_MIN = 1638              # duty_u16 0.5ms 펄스(스타터와 같은 값)
SERVO_DUTY_MAX = 8192              # duty_u16 2.5ms 펄스(스타터와 같은 값)

# ── 살포 큐 ──
QUEUE_MAX = 4                      # 실행 중일 때 대기시킬 수 있는 명령 수(갈래 4개)
SPRAY_MS_MIN = 50                  # 받아들이는 살포 시간 하한(ms). 너무 짧으면 안 움직인다
SPRAY_MS_MAX = 5000                # 받아들이는 살포 시간 상한(ms). 너무 길면 큐가 막힌다
DONE_KEEP = 16                     # 끝난 seq를 기억하는 개수(재전송 요청에 spray_done 재응답)

# ── 갈래 LED ──
LED_MODE = "neopixel"              # "neopixel": WS2812 4픽셀 / "gpio": 단색 LED 4개
PIN_NEOPIXEL = 16                  # WS2812 DIN(330Ω 경유 권장). 픽셀 순서 N,E,S,W
PIN_ARM_LEDS = (6, 7, 8, 9)        # LED_MODE="gpio"일 때 N=GP6, E=GP7, S=GP8, W=GP9
LED_BRIGHT = 48                    # neopixel 밝기 0~255. 낮게 둔다(눈부심·전류)
LED_STALE_MS = 10000               # 맥 명령이 이보다 오래 없으면 갈래 LED를 끈다

# ── DS18B20 ×2 (교량 시험편·공기) ──
PIN_DS = 4                         # 데이터선 GP4. 4.7kΩ 풀업 → 3V3(센서 2개 공통)
DS_CONV_MS = 750                   # 12bit 변환 대기. 그동안 루프는 계속 돈다(비차단)
PIECE_INDEX = 0                    # 부팅 로그 ROM 목록에서 시험편이 몇 번째인지. 배선 보고 고친다
TEMP_BAD = 85.0                    # 전원 직후 85.0은 '측정 실패' 값이므로 버린다

# ── 젖음센서 ──
PIN_WET = 26                       # AO → GP26(ADC0). 모듈 전원 3V3
WET_THRESHOLD = 30000              # ADC raw 임계값(0~65535). 마른 값/젖은 값의 중간으로 맞춘다
WET_WHEN_LOW = True                # 젖을 때 raw가 작아지는 모듈이면 True, 커지면 False

# ── 교량 주의 LED·부저 ──
PIN_WARN_LED = 15                  # 교량 주의 LED(220Ω). 맥과 무관하게 로컬 규칙으로 켠다
WARN_ON_C = 1.0                    # 이 온도 이하이고 젖었으면 주의 LED
FREEZE_C = 0.0                     # 이 온도 이하면 젖음과 무관하게 주의 LED
WARN_OFF_COUNT = 3                 # 켜짐 조건이 이만큼 연속 거짓이면 끈다(히스테리시스)
BUZZER = True                      # 부저를 달았으면 True. 없으면 False로 두면 조용히 넘어간다
PIN_BUZZER = 17                    # 능동 부저 신호선. 살포 시작 때 짧게 울린다
BEEP_MS = 60                       # 살포 시작 알림 길이(ms). 루프를 막지 않는다

# ── 통신·루프 ──
TELEMETRY_MS = 1000                # '@@TEL' 주기(ms)
LOOP_MS = 20                       # 메인 루프 주기(ms). 2Hz 깜박임과 600ms 살포를 놓치지 않을 만큼 짧게
CMD_MAX_LEN = 600                  # USB 한 줄 최대 길이(글자). 넘으면 버린다

# 젖음 판정 보정 방법:
#   1) 시험편을 마른 채로 두고 시리얼 로그의 @@TEL wet_raw 값을 읽는다(예: 61000).
#   2) 물을 묻혀 다시 읽는다(예: 18000).
#   3) 두 값의 중간을 WET_THRESHOLD에 넣는다(예: 40000).
#   4) 젖을 때 값이 작아지면 WET_WHEN_LOW=True, 커지면 False.
