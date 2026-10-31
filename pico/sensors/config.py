# ICE-ZERO 기지 Pico #1(Pico 2 W, USB 시리얼). 제설기지 관제실 안에 둔다.
# 계약(CONTRACT.md 6절)의 핀과 상수를 그대로 옮겼다. 바꾸면 계약도 함께 고친다.
# 비밀값은 여기에 적지 않는다. 맥과 주고받는 것은 USB 시리얼뿐이다.
#
# 기지 안 배치(계약 9절)
#   기지 외곽 약 320(동서)×230(남북). 서쪽이 차고(bay), 동쪽이 관제실이다.
#   관제실: Pico #1 · 대형 브레드보드 · 1602 LCD · 부저 · 3색 LED.
#   차고 뒤벽 범퍼판 뒤에 도킹 스위치, 사일로 출구 아래에 보충 게이트 SG90, 지붕에 네오픽셀 링.
#   DHT11 4개는 차고·관제실이 아니라 갈래 길가 기둥에 있고 전선으로 관제실까지 끌어온다.

# ── 갈래 순서 ──
ARM_ORDER = ("N", "E", "S", "W")   # 보드 위쪽이 북쪽. DHT11·링 픽셀 순서도 이 순서다.

# ── DHT11 ×4 (갈래 길가 기둥) ──
# 모듈에 풀업 저항이 붙어 있어 3V3와 데이터선만 이으면 된다. 내부 풀업은 쓰지 않는다.
DHT_PINS = (2, 3, 4, 5)            # N=GP2, E=GP3, S=GP4, W=GP5
DHT_INTERVAL_MS = 2000             # 센서 하나를 다시 읽기까지 최소 간격. DHT11 규격이 1초 이상이다
DHT_HOLD_MS = 10000                # 읽기에 실패해도 마지막 정상값을 이만큼은 유지한다
# DHT11이 재는 범위는 0~50°C, 0~100%RH다. 이 밖의 값은 잡음으로 보고 실패 처리한다.
DHT_T_MIN = 0.0
DHT_T_MAX = 50.0
DHT_RH_MIN = 0.0
DHT_RH_MAX = 100.0

# ── 수위감지(젖음) AO ──
# 그늘이 가장 깊은 W 갈래 길가(−300, −95)에 둔다. 경고의 wet 가지도 W 갈래 온도를 본다.
PIN_WET = 26                       # GP26(ADC0). 모듈 전원 3V3
WET_THRESHOLD = 40000              # ADC raw(0~65535) 임계값. 젖은/마른 값의 중간으로 맞춘다
WET_WHEN_LOW = True                # 젖을 때 raw가 작아지는 모듈이면 True, 커지면 False

# ── 조도(선택, W 그늘) AO ──
LIGHT_ENABLE = True                # 조도 모듈을 달았으면 True. 없으면 False로 두면 light_raw는 null
PIN_LIGHT = 27                     # GP27(ADC1)

# ── OLED 0.91" SSD1306 128×32 (I2C0) ──
I2C_ID = 0                         # I2C0: SDA GP0, SCL GP1
PIN_SDA = 0
PIN_SCL = 1
I2C_FREQ = 400000                  # OLED와 1602 LCD가 같은 버스를 쓴다
OLED_ADDR = 0x3C
OLED_W = 128
OLED_H = 32
OLED_MS = 500                      # OLED·LCD 다시 그리는 주기(ms)

# ── I2C 1602 LCD(기지 전광판, 선택, PCF8574 백팩) ──
LCD = True                         # LCD가 없으면 False로 두면 조용히 넘어간다
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# ── 3색 LED 모듈(로컬 경고) ──
PIN_LED_R = 10
PIN_LED_G = 11
PIN_LED_B = 12
LED_ACTIVE_HIGH = True             # 모듈이 애노드 공통이면 False로 둔다

# ── 부저 ──
BUZZER = True                      # 능동 부저를 달았으면 True
PIN_BUZZER = 13
BEEP_MS = 120                      # 경고가 켜질 때 우는 길이(ms). 루프는 막지 않는다

# ── 도킹 스위치(차고 뒤벽 택트, 풀업) ──
PIN_DOCK = 14                      # 눌리면 0 = 제설차가 도킹함
DOCK_DEBOUNCE_MS = 50              # 이만큼 같은 값이 유지돼야 인정한다
DOCK_SETTLE_MS = 1000              # 도킹이 이만큼 이어져야 자동 보충을 시작한다

# ── 보충 게이트 SG90(사일로 출구 패들) ──
PIN_GATE = 15                      # 닫힘 0°, 열림 60°
GATE_FREQ = 50                     # SG90 규격 50Hz(20ms 주기)
GATE_CLOSED_DEG = 0
GATE_OPEN_DEG = 60
GATE_DUTY_MIN = 1638               # duty_u16 0.5ms 펄스
GATE_DUTY_MAX = 8192               # duty_u16 2.5ms 펄스
REFILL_AUTO = True                 # 자동 보충을 쓸지. False면 @@REFILL 수동만 동작한다
REFILL_MS = 800                    # 게이트를 여는 시간(ms)
REFILL_COOLDOWN_MS = 20000         # 마지막 보충 뒤 이만큼은 자동 보충을 쉰다

# ── 네오픽셀 WS2812 링(기지 지붕 경광등 + 갈래 상태) ──
RING = True                        # 링을 달았으면 True. 없으면 False
PIN_RING = 16                      # DIN GP16(330Ω 경유 권장)
RING_PIXELS = 8                    # 4갈래 × 2픽셀
RING_PER_ARM = 2                   # 갈래 하나가 쓰는 픽셀 수
RING_BRIGHT = 48                   # 0~255. 눈부심·전류를 줄이려 낮게 둔다
SHOW_STALE_MS = 10000              # 맥 @@SHOW가 이보다 오래 없으면 링을 끈다

# ── 로컬 경고 규칙(맥과 무관) ──
WARN_T = 3.0                       # 실내 시연 기본값: 이 온도 이하
WARN_RH = 85                       # 이 습도 이상이면 경고 후보
WARN_T_FIELD = 1.0                 # 실제 설치(겨울 야외)에서는 WARN_T 대신 이 값을 쓴다
WARN_OFF_COUNT = 3                 # 켜짐 조건이 이만큼 연속 거짓이면 끈다(히스테리시스)

# ── 통신·루프 ──
TELEMETRY_MS = 2000                # '@@TEL' 주기(ms)
LOOP_MS = 20                       # 메인 루프 주기(ms). 2초 주기·게이트 닫기·디바운스를 놓치지 않게
CMD_MAX_LEN = 400                  # USB 한 줄 최대 길이(글자). 넘으면 버린다

# 젖음 판정 보정 방법:
#   1) 센서를 마른 채로 두고 @@TEL의 wet_raw를 읽는다(예: 61000).
#   2) 물을 묻혀 다시 읽는다(예: 18000).
#   3) 두 값의 중간을 WET_THRESHOLD에 넣는다(예: 40000).
#   4) 젖을 때 값이 작아지면 WET_WHEN_LOW=True, 커지면 False.
#
# 자동 보충 확인 방법:
#   1) 차를 차고에 밀어 넣어 도킹 스위치를 누른다. 1초 뒤 게이트가 열렸다 0.8초 뒤 닫힌다.
#   2) @@TEL의 dock/refills/refilling으로 확인한다. 한 번 도킹하면 한 번만 연다.
#   3) 도킹한 채로 @@REFILL {"ms":800}을 보내면 수동으로 한 번 더 연다.
