# 제설차 실험 스크립트. 서버·Wi-Fi 없이 차 Pico 하나로 돈다. Thonny에서 열고 실행(F5)한다.
# 배선이 맞는지부터 보려면 hwtest.py를 먼저 돌린다.
#
# 맨 위 MODE만 바꿔서 쓴다.
#   "calib" : 바닥에서 바퀴 CALIB_REVS바퀴만큼 앞으로 간다. 간 거리를 자로 재서 config.WHEEL_D_MM을 고친다.
#   "run"   : 서버가 order ["N"]을 줬을 때와 같은 계획을 RUNS번 돈다
#             (기지에서 나와 교차로 → N 끝까지 밀고 후진 → 기지로 후진해 들어감).
#
# 차를 북동쪽 기지 차고 안에 출입구(서쪽)를 보게 놓고 시작한다. 멈추려면 Thonny의 Stop(Ctrl+F2).
# 왕복이 끝날 때마다 출발점에서 얼마나 벗어났는지 재 두면 RUNS번 쌓인 오차가 보인다.

import math

import car_core
import config
from main import Motors, sleep_ms, sleep_us

MODE = "run"          # "calib" 또는 "run"
RUNS = 1              # run: 왕복 횟수. 사이에 5초 쉰다
CALIB_REVS = 2        # calib: 바퀴 회전 수. 많을수록 지름 오차가 작아진다
STEP_US = config.STEP_US
                      # 스텝 간격(µs). 눈 조각을 밀다 바퀴가 헛돌면 1500~2000으로 올려 본다


def push(motors, left, right, steps):
    for _ in range(steps):
        motors.step(left, right)
        sleep_us(STEP_US)
    motors.off()


def sweep(motors):
    """order ["N"] 계획을 끝까지 민다. (전진 스텝, 후진 스텝)을 돌려준다."""
    segs = car_core.plan_for_order(["N"])
    for seg in segs:
        if seg["kind"] == "turn":
            print(" - 회전 %.0f도 (%d스텝)" % (seg["deg"], seg["steps"]))
        else:
            print(" - %s %.0fmm (%d스텝)" % ("전진" if seg["dir"] > 0 else "후진", seg["mm"], seg["steps"]))
    print("   예상 %.1f초" % car_core.plan_seconds(segs, STEP_US))
    mission = car_core.Mission(segs, car_core.Pose())
    fwd = back = 0
    try:
        while not mission.done:
            left, right, _, _ = mission.step()
            motors.step(left, right)
            if left > 0 and right > 0:
                fwd += 1
            elif left < 0 and right < 0:
                back += 1
            sleep_us(STEP_US)
    finally:
        motors.off()
    return fwd, back


def calib(motors):
    steps = config.STEPS_PER_REV * CALIB_REVS
    expect = math.pi * config.WHEEL_D_MM * CALIB_REVS
    print("출발점에 표시한다. 3초 뒤 바퀴 %d바퀴(%d스텝) 앞으로 간다." % (CALIB_REVS, steps))
    sleep_ms(3000)
    push(motors, 1, 1, steps)
    print("지금 WHEEL_D_MM %.1f이면 %.0fmm를 가야 한다." % (config.WHEEL_D_MM, expect))
    print("다르면 config.WHEEL_D_MM = 간 거리(mm) / %.2f 로 고친다." % (math.pi * CALIB_REVS))
    print("한쪽으로 휘면 두 바퀴 지름이 다르다. 작은 쪽 병뚜껑에 고무줄을 더 감는다.")


def run(motors):
    for i in range(RUNS):
        print("왕복 %d/%d. 3초 뒤 출발한다." % (i + 1, RUNS))
        sleep_ms(3000)
        fwd, back = sweep(motors)
        print("   끝. 전진 %d스텝, 후진 %d스텝. 출발점에서 벗어난 거리를 잰다." % (fwd, back))
        if i + 1 < RUNS:
            sleep_ms(5000)


def main():
    motors = Motors(config)
    try:
        if MODE == "calib":
            calib(motors)
        elif MODE == "run":
            run(motors)
        else:
            print('MODE는 "calib" 또는 "run"이다.')
    finally:
        motors.off()


if __name__ == "__main__":
    main()
