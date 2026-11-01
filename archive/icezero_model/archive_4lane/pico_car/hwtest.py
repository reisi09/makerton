# 배선 시험용 스크립트. 주행 로직(main.py)은 돌지 않는다. Thonny에서 이 파일을 열고 실행(F5)한다.
#
#   python/micropython pico_car/hwtest.py
#
# 시험 순서: 왼쪽 앞 1초 → 왼쪽 뒤 1초 → 오른쪽 앞 1초 → 오른쪽 뒤 1초 → 둘 다 앞 1초
#            → 서보 열기/닫기 → 경광 LED 5회
# 차를 바닥에서 들어 올리고(바퀴가 헛돌게) 실행한다.
# 바퀴가 반대로 돌면 config.LEFT_INVERT / RIGHT_INVERT를 True로 바꾼다.
# 살포통이 반대로 움직이면 config.SERVO_OPEN_DEG / SERVO_CLOSED_DEG를 바꾼다.
import time

import config
from machine import PWM, Pin
from main import Motors, servo_duty


def run_step(motors, label, left, right, seconds=1):
    print(" - %s (1초)" % label)
    motors.set(left, right)
    time.sleep(seconds)
    motors.stop()
    time.sleep(0.3)


def motor_test():
    print("모터·서보·LED 배선 시험: %s 드라이버" % config.DRIVER)
    motors = Motors(config)
    servo = PWM(Pin(config.PIN_SERVO))
    servo.freq(50)
    led = Pin(config.PIN_LED, Pin.OUT)
    servo.duty_u16(servo_duty(config.SERVO_CLOSED_DEG))

    print("차를 바닥에서 들어 올렸는지 확인한다. 3초 뒤 시작한다.")
    time.sleep(3)
    try:
        run_step(motors, "왼쪽 바퀴 앞으로", 0.6, 0.0)
        run_step(motors, "왼쪽 바퀴 뒤로", -0.6, 0.0)
        run_step(motors, "오른쪽 바퀴 앞으로", 0.0, 0.6)
        run_step(motors, "오른쪽 바퀴 뒤로", 0.0, -0.6)
        run_step(motors, "두 바퀴 앞으로", 0.6, 0.6)

        print(" - 서보 열기(%.0f도)" % config.SERVO_OPEN_DEG)
        servo.duty_u16(servo_duty(config.SERVO_OPEN_DEG))
        time.sleep(1)
        print(" - 서보 닫기(%.0f도)" % config.SERVO_CLOSED_DEG)
        servo.duty_u16(servo_duty(config.SERVO_CLOSED_DEG))
        time.sleep(1)

        print(" - 경광 LED 5회")
        for _ in range(5):
            led.value(1)
            time.sleep(0.2)
            led.value(0)
            time.sleep(0.2)
    finally:
        motors.stop()
        servo.duty_u16(servo_duty(config.SERVO_CLOSED_DEG))
        led.value(0)
    print("시험이 끝났다. 라인센서·초음파는 config.DIAG=True로 두고 main.py를 실행해 확인한다.")


if __name__ == "__main__":
    motor_test()
