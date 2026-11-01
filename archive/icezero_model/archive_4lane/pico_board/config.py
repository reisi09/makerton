# ICE-ZERO 보드(Pico #1) 설정. 현장에서 팀이 고치는 값만 모았다.
# API 키는 여기에 적지 않는다. 서버 ICEZERO_TOKEN과 맞출 때는 TOKEN만 같은 값으로 둔다.

TRANSPORT = "usb"            # "usb"(기본): USB 시리얼 @@TEL/@@LED / "wifi": 핫스팟 HTTP
BOARD_ID = "board-1"
TELEMETRY_MS = 1000          # 텔레메트리 주기(ms)
LOOP_MS = 50                 # 메인 루프 주기(ms). 칸 LED 2Hz 깜박임을 놓치지 않을 만큼 짧게

# Wi-Fi 모드 전용
WIFI_SSID = "my-hotspot"     # 휴대폰 핫스팟은 반드시 2.4GHz(피코 W는 5GHz·캡티브 포털 불가)
WIFI_PASSWORD = "change-me"
WIFI_RETRY_MS = 10000        # 끊겨 있으면 이 간격으로 재연결을 '시작만' 한다(기다리지 않는다)
SERVER_URL = "http://192.168.43.10:8000/api/board/telemetry"  # 노트북 IP: macOS `ipconfig getifaddr en0`
TOKEN = ""                   # 서버 ICEZERO_TOKEN과 같은 값. 비어 있으면 X-Token 헤더를 보내지 않는다

# 핀 (GP 번호)
PIN_DS = 4                   # DS18B20 2개 데이터선(4.7kΩ 풀업 → 3V3)
PIN_WET = 26                 # 젖음센서 AO (ADC0)
PIN_WARN_LED = 15            # 교량 주의 LED (220Ω)
LED_MODE = "neopixel"        # "neopixel": WS2812 8개 DIN=GP16 / "gpio": 단색 LED 8개 GP6~GP13
PIN_NEOPIXEL = 16
PIN_CELL_LEDS = (6, 7, 8, 9, 10, 11, 12, 13)   # LED_MODE="gpio"일 때 루프 순서대로
LED_BRIGHT = 48              # neopixel 밝기 0~255. 낮게 둔다(눈부심·전류)
LED_STALE_MS = 10000         # 서버 LED 명령이 이보다 오래 없으면 칸 LED를 끈다

# 센서·경고 규칙
DS_CONV_MS = 750             # DS18B20 12bit 변환 대기. 그동안 루프는 계속 돈다(비차단)
PIECE_INDEX = 0              # 부팅 로그의 ROM 목록에서 시험편이 몇 번째인지. 배선 보고 고친다
WARN_ON_C = 1.0              # 이 온도 이하이고 젖었으면 주의 LED
FREEZE_C = 0.0               # 이 온도 이하면 젖음과 무관하게 주의 LED
WARN_OFF_COUNT = 3           # 켜짐 조건이 이만큼 연속 거짓이면 끈다(히스테리시스)

# 젖음 판정 보정 방법:
#   1) 시험편을 마른 채로 두고 시리얼 로그의 @@TEL wet_raw 값을 읽는다(예: 61000).
#   2) 물을 묻혀 다시 읽는다(예: 18000).
#   3) 두 값의 중간을 WET_THRESHOLD에 넣는다(예: 40000).
#   4) 모듈에 따라 젖을 때 값이 작아지면 WET_WHEN_LOW=True, 커지면 False.
WET_THRESHOLD = 30000
WET_WHEN_LOW = True
