# 배선 시험용 스크립트. 주행 로직(main.py의 loop)은 돌지 않는다. Thonny에서 열고 실행(F5)한다.
#
#   왼쪽 1바퀴 정·역 → 오른쪽 1바퀴 정·역 → 두 바퀴 함께 반 바퀴
#   MOTORS_ONLY = False면 이어서 서보 열기/닫기 → 초음파 5회 → 버튼 5초 → LED 3색·부저
#
# 바퀴를 보드에서 들어 올리고(헛돌게) 실행한다. 1바퀴는 %d스텝이라 한 번에 약 %.1f초 걸린다.
# 바퀴가 반대로 돌면 config.LEFT_INVERT / RIGHT_INVERT를 뒤집는다.
# 살포통이 반대로 움직이면 config.SERVO_OPEN_DEG / SERVO_CLOSED_DEG를 바꾼다.
# 초음파가 늘 None이면 ECHO 분압(1kΩ·2kΩ)과 핀 번호를 확인한다.

import car_core
import config
from main import Buzzer, Button, Led, Motors, Servo, Sonar, sleep_ms, sleep_us, ticks_ms

MOTORS_ONLY = True    # 사거리 제설차는 모터만 단다. 서보·초음파·버튼·LED·부저까지 보려면 False


def spin(motors, left, right, steps):
    """스텝 steps번 민다."""
    for _ in range(steps):
        motors.step(left, right)
        sleep_us(config.STEP_US)
    motors.off()
    sleep_ms(300)


def motor_test(motors):
    one_rev = config.STEPS_PER_REV
    print(" ── 모터 (한 바퀴 = %d스텝, 약 %.1f초)" % (one_rev, one_rev * config.STEP_US / 1000000.0))
    print(" - 왼쪽 정방향")
    spin(motors, 1, 0, one_rev)
    print(" - 왼쪽 역방향")
    spin(motors, -1, 0, one_rev)
    print(" - 오른쪽 정방향")
    spin(motors, 0, 1, one_rev)
    print(" - 오른쪽 역방향")
    spin(motors, 0, -1, one_rev)
    print(" - 두 바퀴 함께 정방향(차가 앞으로 가야 한다)")
    spin(motors, 1, 1, one_rev // 2)


def servo_test(servo):
    print(" ── 서보")
    print(" - 열기 %d도" % config.SERVO_OPEN_DEG)
    servo.set(config.SERVO_OPEN_DEG)
    sleep_ms(1000)
    print(" - 닫기 %d도" % config.SERVO_CLOSED_DEG)
    servo.set(config.SERVO_CLOSED_DEG)
    sleep_ms(1000)


def sonar_test(sonar):
    print(" ── 초음파 5회")
    for i in range(5):
        cm = sonar.read_cm()
        if cm is None:
            print("   %d: 측정 없음(비었거나 분압·핀 확인)" % (i + 1))
        else:
            print("   %d: %.1fcm" % (i + 1, cm))
        sleep_ms(400)


def button_test(button, buzzer):
    print(" ── 버튼: 5초 동안 눌러 본다")
    start = ticks_ms()
    hits = 0
    while car_core.ticks_diff(ticks_ms(), start) < 5000:
        if button.pressed(ticks_ms()):
            hits += 1
            print("   눌림 %d" % hits)
            buzzer.beep(config.BEEP_MS, ticks_ms())
        buzzer.update(ticks_ms())
        sleep_ms(5)
    print("   눌림 횟수: %d (0이면 배선·풀업 확인)" % hits)


def led_test(led, buzzer):
    print(" ── LED·부저")
    for name, rgb in (("빨강", (True, False, False)),
                      ("초록", (False, True, False)),
                      ("파랑", (False, False, True)),
                      ("흰색", (True, True, True))):
        print(" - %s" % name)
        led.set(rgb[0], rgb[1], rgb[2])
        sleep_ms(500)
    led.set(False, False, False)
    print(" - 부저")
    buzzer.beep(200, ticks_ms())
    sleep_ms(400)
    buzzer.update(ticks_ms())


def main():
    print("제설차 배선 시험. 차를 들어 올렸는지 확인한다. 3초 뒤 시작한다.")
    sleep_ms(3000)
    motors = Motors(config)
    servo = Servo(config)
    led = Led(config)
    buzzer = Buzzer(config)
    button = Button(config)
    sonar = Sonar(config)
    try:
        motor_test(motors)
        if not MOTORS_ONLY:
            servo_test(servo)
            sonar_test(sonar)
            button_test(button, buzzer)
            led_test(led, buzzer)
    finally:
        motors.off()
        servo.set(config.SERVO_CLOSED_DEG)
        led.set(False, False, False)
        buzzer.pin.value(0)
    print("시험이 끝났다. 방향이 반대면 config.LEFT_INVERT / RIGHT_INVERT를 고친다.")


if __name__ == "__main__":
    main()
