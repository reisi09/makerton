# 팀마다 고쳐 쓰는 설정. Command Code API 키는 여기에 넣지 않는다(노트북 중계 서버만 가진다).
TRANSPORT = "usb"               # "usb"(기본): USB 케이블 + 노트북 serial_bridge.py / "wifi": 핫스팟 HTTP(첫날 점검 통과 시)
WIFI_SSID = "my-hotspot"        # wifi 모드만. 휴대폰 핫스팟은 반드시 2.4GHz (피코 W는 5GHz·캡티브 포털 불가)
WIFI_PASSWORD = "change-me"
RELAY_URL = "http://192.168.43.10:8000/decide"  # wifi 모드만. 노트북 IP: macOS `ipconfig getifaddr en0`, Windows `ipconfig`
RELAY_TOKEN = "team-secret"     # wifi 모드만. 중계 서버 RELAY_TOKEN과 같은 값
DEVICE_ID = "pico-1"
PROFILE = "access_space"        # relay/profiles.json의 키
REFLEX = False                  # True면 로컬 규칙보다 낮은 단계로 내려가지 않음(안전 경고형). 기본은 AI 판단 우선
ASK_INTERVAL_S = 10             # 상태가 그대로여도 이 간격마다 AI에 다시 묻는다
OCCUPIED_CM = 15                # 이 거리보다 가까우면 점유로 본다
NOTICE_S, WARN_S, STAFF_S = 5, 15, 30   # 시연용으로 줄인 시간(초). profiles.json의 context 문장과 같게 맞춘다
BUZZER = False                  # 부저는 기본으로 끈다(경보음이 또 다른 소음 민원이 되지 않게)
POS = [20, 50]                  # 대시보드 노드 지도 위치(0~100). 노드마다 다르게
POLL_S = 1                      # 다른 노드 때문에 에이전트가 보낸 명령을 몇 초마다 확인할지(API 비용 없음). 0이면 끔
CMD_HOLD_S = 10                 # 에이전트 명령을 유지하는 시간(단계를 올리기만 함)
VIBRO_PIN = None               # 진동모터 핀(예: 21). 반드시 NPN 트랜지스터·다이오드를 거쳐 구동한다
