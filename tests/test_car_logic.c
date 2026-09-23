#include "car_logic.h"
#include <assert.h>
#include <stdio.h>

static CarInputs sample(uint32_t now, uint8_t bits, uint16_t left_mm, uint16_t right_mm) {
  CarInputs in = {now, bits, left_mm, right_mm, true, true};
  return in;
}

static void tick(CarController *car, uint32_t now, uint8_t bits, uint16_t left, uint16_t right) {
  CarInputs in = sample(now, bits, left, right);
  CarLogic_Tick(car, &in);
}

int main(void) {
  CarController car;
  CarLogic_Init(&car);
  assert(car.state == CAR_IDLE && car.output.left_pwm == 0);
  assert(!CarLogic_DebugDrive(&car, 100, 100, 1500, 0));
  assert(CarLogic_Arm(&car, 0));
  assert(!CarLogic_Debug(&car, 0));
  tick(&car, 2999, 0x0c, 500, 500);
  assert(car.state == CAR_ARMED && car.output.left_pwm == 0);
  tick(&car, 3000, 0x0c, 500, 500);
  assert(car.state == CAR_FOLLOW && car.output.left_pwm == 250);

  tick(&car, 3100, 0x0c, 150, 500);
  assert(car.state == CAR_AVOID_OUT && car.output.steer_us == 1680);
  tick(&car, 3600, 0, 500, 500);
  assert(car.state == CAR_AVOID_PASS && car.output.steer_us == 1500);
  tick(&car, 4500, 0, 500, 500);
  assert(car.state == CAR_AVOID_IN && car.output.steer_us == 1320);
  tick(&car, 5000, 0, 500, 500);
  assert(car.state == CAR_RECOVER);
  tick(&car, 5100, 0x0c, 500, 500);
  assert(car.state == CAR_FOLLOW && car.obstacles == 1);
  tick(&car, 5200, 0x0c, 150, 500);
  assert(car.state == CAR_FOLLOW && car.obstacles == 1); /* cooldown */
  tick(&car, 6000, 0, 500, 500);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_LINE_LOST);
  assert(car.output.left_pwm == 0 && car.output.right_pwm == 0);

  CarLogic_Stop(&car, 1000);
  assert(CarLogic_Debug(&car, 1000));
  assert(!CarLogic_DebugDrive(&car, 301, 0, 1500, 1001));
  assert(CarLogic_DebugDrive(&car, 200, -200, 1600, 1001));
  tick(&car, 1499, 0, 0, 0);
  assert(car.output.left_pwm == 200);
  tick(&car, 1501, 0, 0, 0);
  assert(car.state == CAR_DEBUG && car.output.left_pwm == 0);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x0c, 500, 500);
  car.obstacles = 4;
  tick(&car, 14000, 0x3f, 500, 500);
  assert(car.state == CAR_FOLLOW);
  tick(&car, 14020, 0x3f, 500, 500);
  assert(car.state == CAR_FINISHED && car.output.left_pwm == 0);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  CarInputs bad = sample(3000, 0x0c, 500, 500);
  bad.left_valid = false;
  CarLogic_Tick(&car, &bad);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RANGE);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x0c, 500, 500);
  tick(&car, 303000, 0x0c, 500, 500);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RACE_TIMEOUT);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x0c, 500, 500);
  tick(&car, 3100, 0x0c, 500, 120);
  assert(car.state == CAR_AVOID_OUT && car.output.steer_us == 1320);
  tick(&car, 3600, 0, 500, 500);
  tick(&car, 4500, 0, 500, 500);
  tick(&car, 5000, 0, 500, 500);
  tick(&car, 7500, 0, 500, 500);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RECOVERY);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x0c, 500, 500);
  tick(&car, 3100, 0x0c, 100, 100);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_BLOCKED);
  puts("car_logic tests passed");
  return 0;
}
