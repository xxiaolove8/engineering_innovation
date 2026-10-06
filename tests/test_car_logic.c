#include "car_logic.h"
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

static CarInputs sample(uint32_t now, uint8_t bits, uint16_t left_mm, uint16_t right_mm) {
  CarInputs in = {.now_ms=now, .line_bits=bits, .left_mm=left_mm,
    .right_mm=right_mm, .center_mm=500, .left_valid=true, .right_valid=true,
    .center_valid=true, .dt_ms=10};
  return in;
}

static void tick(CarController *car, uint32_t now, uint8_t bits, uint16_t left, uint16_t right) {
  CarInputs in = sample(now, bits, left, right);
  CarLogic_Tick(car, &in);
}

static void pid_parameter_bounds(void) {
  const struct { const char *name; size_t offset; float maximum; } parameters[] = {
    {"line_kp",offsetof(CarPidParams,line_kp),200.0f},
    {"line_ki",offsetof(CarPidParams,line_ki),100.0f},
    {"line_kd",offsetof(CarPidParams,line_kd),10.0f},
    {"speed_kp",offsetof(CarPidParams,speed_kp),50.0f},
    {"speed_ki",offsetof(CarPidParams,speed_ki),50.0f},
    {"speed_kd",offsetof(CarPidParams,speed_kd),10.0f},
    {"target_ticks",offsetof(CarPidParams,target_ticks),500.0f},
    {"feedforward_pwm",offsetof(CarPidParams,feedforward_pwm),500.0f},
    {"differential_gain",offsetof(CarPidParams,differential_gain),1.0f},
    {"curve_slowdown",offsetof(CarPidParams,curve_slowdown),1.0f}
  };
  for (unsigned i=0U; i<sizeof(parameters)/sizeof(parameters[0]); ++i) {
    CarPidParams p=CarPid_DefaultParams();
    assert(CarPid_SetParam(&p,parameters[i].name,parameters[i].maximum));
    assert(CarPid_ValidParams(&p));
    CarPidParams previous=p;
    assert(!CarPid_SetParam(&p,parameters[i].name,parameters[i].maximum+1.0f));
    assert(!CarPid_SetParam(&p,parameters[i].name,-1.0f));
    assert(!CarPid_SetParam(&p,parameters[i].name,NAN));
    assert(!CarPid_SetParam(&p,parameters[i].name,INFINITY));
    assert(memcmp(&p,&previous,sizeof(p))==0);
    float invalid=parameters[i].maximum+1.0f;
    memcpy((uint8_t *)&p+parameters[i].offset,&invalid,sizeof(invalid));
    assert(!CarPid_ValidParams(&p));
  }
  CarPidParams p=CarPid_DefaultParams();
  assert(!CarPid_SetParam(&p,"target_ticks",0.0f));
  assert(!CarPid_SetParam(NULL,"target_ticks",1.0f));
  assert(!CarPid_SetParam(&p,NULL,1.0f) && !CarPid_ValidParams(NULL));
}

static void debug_speed_control(void) {
  CarController car;
  CarLogic_Init(&car);
  assert(!CarLogic_DebugSpeed(NULL, 20.0f, 20.0f, 0U));
  assert(!CarLogic_DebugSpeed(&car, 20.0f, 20.0f, 0U));
  assert(CarLogic_Debug(&car, 0U));
  const float invalid[] = {-1.0f, 500.1f, NAN, INFINITY, -INFINITY};
  for (unsigned i=0U; i<sizeof(invalid)/sizeof(invalid[0]); ++i) {
    assert(!CarLogic_DebugSpeed(&car, invalid[i], 20.0f, 1U));
    assert(!CarLogic_DebugSpeed(&car, 20.0f, invalid[i], 1U));
  }
  assert(car.debug_deadline_ms == 0U && !car.debug_speed_active);

  /* Direct PWM now reports normalized speed magnitude without PID targets. */
  assert(CarLogic_DebugDrive(&car, 120, -160, 1600U, 1U));
  CarInputs in=sample(20U, 0U, 0U, 0U);
  in.dt_ms=20U; in.encoder_left_delta=12; in.encoder_right_delta=-18;
  CarLogic_Tick(&car, &in);
  assert(car.output.left_pwm == 120 && car.output.right_pwm == -160);
  assert(car.pid.left_measured == 6.0f && car.pid.right_measured == 9.0f);
  assert(car.pid.left_target == 0.0f && car.pid.right_target == 0.0f);
  assert(CarLogic_DebugDrive(&car, 120, -160, 1600U, 20U));
  assert(car.pid.left_measured == 6.0f && car.pid.right_measured == 9.0f);

  /* A DEBUG limit must also bound anti-windup, rather than clipping AUTO output. */
  assert(CarLogic_DebugSpeed(&car, 500.0f, 500.0f, 20U));
  tick(&car, 30U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 300 && car.output.right_pwm == 300);
  assert(car.output.steer_us == 1500U);
  assert(car.pid.left_speed.integral == 0.0f && car.pid.right_speed.integral == 0.0f);
  assert(CarLogic_DebugSpeed(&car, 0.0f, 20.0f, 30U));
  tick(&car, 40U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 0 && car.output.right_pwm > 0);
  assert(car.pid.left_target == 0.0f && car.pid.right_target == 20.0f);
  assert(car.pid.left_speed.integral == 0.0f);
  assert(CarLogic_DebugSpeed(&car, 0.0f, 0.0f, 40U));
  assert(car.output.left_pwm == 0 && car.output.right_pwm == 0);
  assert(!car.debug_speed_active && car.pid.right_target == 0.0f);

  car.pid_params.feedforward_pwm=0.0f;
  car.pid_params.speed_kp=1.0f;
  car.pid_params.speed_ki=2.0f;
  assert(CarLogic_DebugSpeed(&car, 10.0f, 10.0f, 100U));
  tick(&car, 110U, 0U, 0U, 0U);
  float integral=car.pid.left_speed.integral;
  assert(integral > 0.0f);
  /* 200 ms keepalives preserve accumulated controller state. */
  for (uint32_t now=300U; now<=900U; now+=200U) {
    assert(CarLogic_DebugSpeed(&car, 10.0f, 10.0f, now));
    assert(car.pid.left_speed.integral == integral);
    tick(&car, now+10U, 0U, 0U, 0U);
    assert(car.pid.left_speed.integral > integral);
    integral=car.pid.left_speed.integral;
  }
  tick(&car, 1399U, 0U, 0U, 0U);
  assert(car.output.left_pwm > 0);
  tick(&car, 1400U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 0 && car.output.right_pwm == 0);
  assert(!car.debug_speed_active && car.pid.left_target == 0.0f);
  tick(&car, 1410U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 0); /* No stored target can restart after timeout. */

  assert(CarLogic_DebugSpeed(&car, 10.0f, 20.0f, 1500U));
  tick(&car, 1510U, 0U, 0U, 0U);
  assert(CarLogic_DebugDrive(&car, -100, 100, 1500U, 1520U));
  assert(!car.debug_speed_active && car.pid.left_speed.integral == 0.0f);
  assert(car.pid.left_target == 0.0f && car.pid.right_target == 0.0f);
  tick(&car, 1530U, 0U, 0U, 0U);
  assert(car.output.left_pwm == -100 && car.output.right_pwm == 100);
  assert(CarLogic_DebugSpeed(&car, 10.0f, 10.0f, 1540U));
  CarLogic_Stop(&car, 1550U);
  assert(car.state == CAR_IDLE && !car.debug_speed_active && car.output.left_pwm == 0);
  assert(!CarLogic_DebugSpeed(&car, 10.0f, 10.0f, 1560U));
  in=sample(1570U, 0U, 0U, 0U);
  in.encoder_left_delta=-7; in.encoder_right_delta=9;
  CarLogic_Tick(&car, &in);
  assert(car.output.left_pwm == 0 && car.pid.left_target == 0.0f);
  assert(car.pid.left_measured == 7.0f && car.pid.right_measured == 9.0f);

  assert(CarLogic_Debug(&car, UINT32_MAX-100U));
  assert(CarLogic_DebugSpeed(&car, 10.0f, 10.0f, UINT32_MAX-100U));
  tick(&car, 100U, 0U, 0U, 0U);
  assert(car.output.left_pwm > 0);
  tick(&car, 400U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 0 && !car.debug_speed_active);

  /* Existing automatic output ceiling remains 500 permille. */
  CarPidParams params=CarPid_DefaultParams();
  CarPidRuntime runtime={0};
  params.feedforward_pwm=500.0f;
  int16_t left=0, right=0;
  CarPid_SpeedStep(&params, &runtime, 0.0f, 1.0f, 0, 0, 0.01f, &left, &right);
  assert(left == 500 && right == 500);
  CarPid_Reset(&runtime);
  params.feedforward_pwm=290.0f; params.speed_kp=1.0f; params.speed_ki=1.0f;
  CarPid_DebugSpeedStep(&params, &runtime, 20.0f, 20.0f, 0, 0, 0.01f,
                        300U, &left, &right);
  assert(left == 300 && right == 300 && runtime.left_speed.integral == 0.0f);
  CarPid_Reset(&runtime);
  CarPid_DebugSpeedStep(&params, &runtime, 20.0f, 20.0f, 0, 0, 0.01f,
                        1000U, &left, &right);
  assert(left == 310 && right == 310 && runtime.left_speed.integral > 0.0f);
  CarPid_Reset(&runtime);
  CarPid_DebugSpeedStep(&params, &runtime, 500.0f, 500.0f, 0, 0, 0.01f,
                        1000U, &left, &right);
  assert(left == 1000 && right == 1000 && runtime.left_speed.integral == 0.0f);
}

static void debug_pwm_limits(void) {
  CarController car;
  CarLogic_Init(&car);
  assert(car.debug_pwm_limit == 300U);
  assert(!CarLogic_DebugLimit(NULL, 1000U));
  assert(!CarLogic_DebugLimit(&car, 1000U));
  assert(CarLogic_Debug(&car, 0U));
  assert(!CarLogic_DebugLimit(&car, 0U) && !CarLogic_DebugLimit(&car, 1001U));
  assert(!CarLogic_DebugDrive(&car, 1000, 0, 1500U, 1U));
  assert(!CarLogic_DebugDrive(&car, 0, -1000, 1500U, 1U));
  assert(car.debug_pwm_limit == 300U && car.debug_deadline_ms == 0U);
  assert(CarLogic_DebugLimit(&car, 1U));
  assert(!CarLogic_DebugDrive(&car, 2, 0, 1500U, 1U));
  assert(CarLogic_DebugLimit(&car, 1000U));
  tick(&car, 2000U, 0U, 0U, 0U);
  assert(car.debug_pwm_limit == 1000U && car.output.left_pwm == 0);
  assert(car.debug_deadline_ms == 0U); /* Unlock does not renew motion. */
  assert(CarLogic_DebugDrive(&car, 1000, -1000, 1500U, 2000U));
  assert(!CarLogic_DebugLimit(&car, 300U));
  assert(car.debug_pwm_limit == 1000U && car.debug_deadline_ms == 2000U);
  assert(CarLogic_DebugDrive(&car, 0, 0, 1500U, 2010U));
  tick(&car, 3000U, 0U, 0U, 0U);
  assert(car.debug_pwm_limit == 1000U); /* Button release retains session limit. */
  assert(CarLogic_DebugSpeed(&car, 500.0f, 0.0f, 3000U));
  assert(!CarLogic_DebugLimit(&car, 300U)); /* Active target before first tick. */
  tick(&car, 3010U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 1000 && car.output.right_pwm == 0);
  assert(car.pid.left_speed.integral == 0.0f);
  assert(CarLogic_DebugSpeed(&car, 0.0f, 0.0f, 3020U));
  assert(CarLogic_DebugLimit(&car, 600U));
  tick(&car, 4000U, 0U, 0U, 0U);
  assert(car.debug_pwm_limit == 600U);
  assert(CarLogic_DebugDrive(&car, 600, 0, 1500U, 4000U));
  tick(&car, 4499U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 600 && car.debug_pwm_limit == 600U);
  tick(&car, 4500U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 0 && car.debug_pwm_limit == 300U);
  assert(!CarLogic_DebugDrive(&car, 600, 0, 1500U, 4510U));
  assert(CarLogic_DebugLimit(&car, 1000U));
  assert(CarLogic_DebugSpeed(&car, 500.0f, 0.0f, 5000U));
  tick(&car, 5500U, 0U, 0U, 0U);
  assert(!car.debug_speed_active && car.debug_pwm_limit == 300U);
  assert(CarLogic_DebugLimit(&car, 1000U));
  CarLogic_Stop(&car, 5510U);
  assert(car.state == CAR_IDLE && car.debug_pwm_limit == 300U);
  assert(CarLogic_Arm(&car, 5520U));
  assert(!CarLogic_DebugLimit(&car, 1000U));
  CarLogic_Stop(&car, 5530U);
  assert(CarLogic_Debug(&car, 5540U));
  assert(car.debug_pwm_limit == 300U);
  assert(CarLogic_DebugLimit(&car, 1000U));
  car.state = CAR_FAULT; /* Hardware-fault handling also leaves DEBUG. */
  tick(&car, 5550U, 0U, 0U, 0U);
  assert(car.debug_pwm_limit == 300U && car.output.left_pwm == 0);
}

static void servo_calibration(void) {
  CarController car;
  CarLogic_Init(&car);
  assert(car.servo_params.center_us == 1500U && car.servo_params.span_us == 200U);
  const CarServoParams invalid[] = {{499U,0U}, {2501U,0U}, {500U,1U},
    {2500U,1U}, {1500U,1001U}, {1600U,901U}};
  CarServoParams calibration = {1600U,100U};
  assert(!CarLogic_SetServoParams(NULL, &calibration));
  assert(!CarLogic_SetServoParams(&car, NULL));
  for (unsigned i=0U; i<sizeof(invalid)/sizeof(invalid[0]); ++i) {
    assert(!CarServo_ValidParams(&invalid[i]));
    assert(!CarLogic_SetServoParams(&car, &invalid[i]));
    assert(car.servo_params.center_us == 1500U && car.output.steer_us == 1500U);
  }
  assert(CarLogic_SetServoParams(&car, &calibration));
  assert(car.output.steer_us == 1600U);
  assert(CarLogic_Debug(&car, 0U));
  assert(!CarLogic_SetServoParams(&car, &(CarServoParams){1500U,200U}));
  assert(!CarLogic_DebugDrive(&car, 0, 0, 1499U, 1U));
  assert(!CarLogic_DebugDrive(&car, 0, 0, 1701U, 1U));
  assert(CarLogic_DebugDrive(&car, 100, 100, 1500U, 1U));
  tick(&car, 501U, 0U, 0U, 0U);
  assert(car.output.left_pwm == 0 && car.output.steer_us == 1600U);
  assert(CarLogic_DebugLimit(&car, 1000U));
  assert(CarLogic_DebugDrive(&car, 0, 0, 1700U, 510U));
  tick(&car, 1009U, 0U, 0U, 0U);
  assert(car.output.steer_us == 1700U && car.debug_pwm_limit == 1000U);
  tick(&car, 1010U, 0U, 0U, 0U);
  assert(car.output.steer_us == 1600U && car.debug_pwm_limit == 300U);
  assert(car.output.left_pwm == 0 && car.output.right_pwm == 0);
  assert(!car.debug_speed_active && car.pid.left_target == 0.0f && car.pid.right_target == 0.0f);
  assert(CarLogic_DebugSpeed(&car, 10.0f, 10.0f, 1020U));
  assert(car.output.steer_us == 1600U);
  CarLogic_Stop(&car, 0U);
  assert(car.output.steer_us == 1600U);

  car.pid_params.line_kp=200.0f;
  car.pid_params.line_ki=100.0f;
  car.pid_params.line_kd=0.0f;
  assert(CarLogic_Arm(&car, 0U));
  tick(&car, 3000U, 0x80U, 500U, 500U);
  assert(car.output.steer_us == 1700U && car.pid.line.integral == 0.0f);
  assert(car.pid.left_target > car.pid.right_target);
  tick(&car, 3010U, 0x01U, 500U, 500U);
  assert(car.output.steer_us == 1500U && car.pid.line.integral == 0.0f);
  assert(car.pid.left_target < car.pid.right_target);
  tick(&car, 3020U, 0x18U, 150U, 500U);
  assert(car.state == CAR_AVOID_OUT && car.output.steer_us == 1690U);
  tick(&car, 3520U, 0U, 500U, 500U);
  assert(car.state == CAR_AVOID_PASS && car.output.steer_us == 1600U);
  tick(&car, 4420U, 0U, 500U, 500U);
  assert(car.state == CAR_AVOID_IN && car.output.steer_us == 1510U);
  tick(&car, 4920U, 0U, 500U, 500U);
  assert(car.state == CAR_RECOVER && car.output.steer_us == 1510U);
  tick(&car, 7420U, 0U, 500U, 500U);
  assert(car.state == CAR_FAULT && car.output.steer_us == 1600U);

  /* A wider calibrated range must not retain the old +/-200 PID limit. */
  CarLogic_Stop(&car, 0U);
  assert(CarLogic_SetServoParams(&car, &(CarServoParams){1500U,350U}));
  assert(CarLogic_Arm(&car, 0U));
  tick(&car, 3000U, 0x80U, 500U, 500U);
  assert(car.output.steer_us == 1850U);

  /* Zero span locks the servo and disables steering-based differential safely. */
  CarLogic_Stop(&car, 0U);
  assert(CarLogic_SetServoParams(&car, &(CarServoParams){1550U,0U}));
  assert(CarLogic_Arm(&car, 0U));
  tick(&car, 3000U, 0x80U, 500U, 500U);
  assert(car.output.steer_us == 1550U && car.pid.line.integral == 0.0f);
  assert(car.pid.left_target == car.pid.right_target && isfinite(car.pid.left_target));
  tick(&car, 3010U, 0x18U, 150U, 500U);
  assert(car.output.steer_us == 1550U && car.pid.left_target == car.pid.right_target);
  CarLogic_Stop(&car, 0U);
  assert(CarLogic_Debug(&car, 0U));
  assert(!CarLogic_DebugDrive(&car, 0, 0, 1551U, 1U));
  assert(CarLogic_DebugDrive(&car, 0, 0, 1550U, 1U));

  /* Valid endpoints include the full electrical range, or a locked endpoint. */
  assert(CarServo_ValidParams(&(CarServoParams){1500U,1000U}));
  assert(CarServo_ValidParams(&(CarServoParams){500U,0U}));
  assert(CarServo_ValidParams(&(CarServoParams){2500U,0U}));
  CarPidRuntime runtime={0};
  CarPidParams params=CarPid_DefaultParams();
  params.line_kp=0.0f; params.line_ki=100.0f; params.line_kd=0.0f;
  assert(CarPid_LineStepLimited(&params, &runtime, 5.0f, 0.1f, 20.0f) == 0.0f);
  assert(runtime.line.integral == 0.0f); /* Saturating I cannot wind up. */
  assert(CarPid_LineStepLimited(&params, &runtime, -5.0f, 0.1f, 20.0f) == 0.0f);
  runtime.line.integral=1.0f;
  assert(CarPid_LineStepLimited(&params, &runtime, 1.0f, 0.01f, 0.0f) == 0.0f);
  assert(runtime.line.integral == 0.0f);
}

int main(void) {
  pid_parameter_bounds();
  debug_speed_control();
  debug_pwm_limits();
  servo_calibration();
  CarController car;
  CarLogic_Init(&car);
  assert(car.state == CAR_IDLE && car.output.left_pwm == 0);
  assert(!CarLogic_DebugDrive(&car, 100, 100, 1500, 0));
  assert(CarLogic_Arm(&car, 0));
  assert(!CarLogic_Debug(&car, 0));
  tick(&car, 2999, 0x18, 500, 500);
  assert(car.state == CAR_ARMED && car.output.left_pwm == 0);
  tick(&car, 3000, 0x18, 500, 500);
  assert(car.state == CAR_FOLLOW && car.output.left_pwm > 0 && car.output.left_pwm <= 500);

  int16_t initial_pwm = car.output.left_pwm;
  CarInputs measured = sample(3010, 0x18, 500, 500);
  measured.encoder_left_delta = 30;
  measured.encoder_right_delta = -30;
  CarLogic_Tick(&car, &measured);
  assert(car.output.left_pwm < initial_pwm && car.output.right_pwm < initial_pwm);

  tick(&car, 3100, 0x18, 150, 500);
  assert(car.state == CAR_AVOID_OUT && car.output.steer_us == 1680);
  assert(car.pid.left_target > car.pid.right_target);
  tick(&car, 3600, 0, 500, 500);
  assert(car.state == CAR_AVOID_PASS && car.output.steer_us == 1500);
  tick(&car, 4500, 0, 500, 500);
  assert(car.state == CAR_AVOID_IN && car.output.steer_us == 1320);
  tick(&car, 5000, 0, 500, 500);
  assert(car.state == CAR_RECOVER);
  tick(&car, 5100, 0x18, 500, 500);
  assert(car.state == CAR_FOLLOW && car.obstacles == 1);
  tick(&car, 5200, 0x18, 150, 500);
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
  tick(&car, 3000, 0x18, 500, 500);
  assert(car.obstacles == 0); /* A missed count must not disable finish detection. */
  tick(&car, 14000, 0xff, 500, 500);
  assert(car.state == CAR_FOLLOW);
  tick(&car, 14020, 0xff, 500, 500);
  assert(car.state == CAR_FINISHED && car.output.left_pwm == 0);

  /* An interrupted finish observation must start a fresh continuous hold. */
  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  tick(&car, 14000, 0xff, 500, 500);
  CarInputs interrupted_finish = sample(14010, 0xff, 500, 500);
  interrupted_finish.center_valid = false;
  CarLogic_Tick(&car, &interrupted_finish);
  assert(car.state == CAR_FOLLOW && car.output.left_pwm == 0);
  tick(&car, 14100, 0xff, 500, 500);
  assert(car.state == CAR_FOLLOW);
  tick(&car, 14120, 0xff, 500, 500);
  assert(car.state == CAR_FINISHED);

  /* Leaving FOLLOW for a maneuver also interrupts the finish observation. */
  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  tick(&car, 13990, 0xff, 500, 500);
  tick(&car, 14000, 0xff, 150, 500);
  assert(car.state == CAR_AVOID_OUT);
  tick(&car, 14500, 0, 500, 500);
  tick(&car, 15400, 0, 500, 500);
  tick(&car, 15900, 0, 500, 500);
  tick(&car, 15910, 0xff, 500, 500);
  tick(&car, 15920, 0xff, 500, 500);
  assert(car.state == CAR_FOLLOW);
  tick(&car, 15940, 0xff, 500, 500);
  assert(car.state == CAR_FINISHED);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  CarInputs bad = sample(3000, 0x18, 500, 500);
  bad.left_valid = false;
  CarLogic_Tick(&car, &bad);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RANGE);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  tick(&car, 303000, 0x18, 500, 500);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RACE_TIMEOUT);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  tick(&car, 3100, 0x18, 500, 120);
  assert(car.state == CAR_AVOID_OUT && car.output.steer_us == 1320);
  tick(&car, 3600, 0, 500, 500);
  tick(&car, 4500, 0, 500, 500);
  tick(&car, 5000, 0, 500, 500);
  tick(&car, 7500, 0, 500, 500);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RECOVERY);

  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  tick(&car, 3100, 0x18, 100, 100);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_BLOCKED);

  CarLogic_Stop(&car, 0);
  assert(CarPid_SetParam(&car.pid_params, "line_kp", 35.0f));
  assert(!CarPid_SetParam(&car.pid_params, "line_kp", 300.0f));
  assert(!CarPid_SetParam(&car.pid_params, "missing", 1.0f));
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x80, 500, 500);
  assert(car.state == CAR_FOLLOW && car.output.steer_us > 1500);
  assert(car.pid.left_target > car.pid.right_target);
  assert(car.output.left_pwm > car.output.right_pwm);

  /* Center-only obstacles choose the side with greater clearance. */
  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  CarInputs front = sample(3100, 0x18, 600, 400);
  front.center_mm = 180;
  CarLogic_Tick(&car, &front);
  assert(car.state == CAR_AVOID_OUT && car.avoid_direction == -1);
  front.now_ms = 3110;
  front.center_mm = 50;
  CarLogic_Tick(&car, &front);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_BLOCKED);

  /* Extremely close side returns used to fall into the 0..30 mm blind zone. */
  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  tick(&car, 3010, 0x18, 20, 500);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_BLOCKED);

  /* Missing range grace begins with the failure, independent of state age. */
  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0x18, 500, 500);
  CarInputs missing = sample(10000, 0x18, 500, 500);
  missing.center_valid = false;
  CarLogic_Tick(&car, &missing);
  assert(car.state == CAR_FOLLOW && car.output.left_pwm == 0);
  missing.now_ms = 10799;
  CarLogic_Tick(&car, &missing);
  assert(car.state == CAR_FOLLOW);
  missing.now_ms = 10800;
  CarLogic_Tick(&car, &missing);
  assert(car.state == CAR_FAULT && car.fault == CAR_FAULT_RANGE);

  /* All-black at the starting bar cannot be mistaken for the finish. */
  CarLogic_Stop(&car, 0);
  assert(CarLogic_Arm(&car, 0));
  tick(&car, 3000, 0xff, 500, 500);
  tick(&car, 14000, 0xff, 500, 500);
  tick(&car, 14020, 0xff, 500, 500);
  assert(car.state == CAR_FOLLOW && !car.start_line_cleared);

  /* Guard applies during the obstacle cooldown as well. */
  tick(&car, 14030, 0x18, 500, 500);
  car.last_avoid_ms = 14030;
  front = sample(14040, 0x18, 500, 500);
  front.center_mm = 180;
  CarLogic_Tick(&car, &front);
  assert(car.state == CAR_AVOID_OUT);
  missing = sample(14200, 0x18, 500, 500);
  missing.center_valid = false;
  CarLogic_Tick(&car, &missing);
  assert(car.output.left_pwm == 0);
  front = sample(14700, 0x18, 500, 500);
  CarLogic_Tick(&car, &front);
  assert(car.state == CAR_AVOID_OUT); /* Stopped time cannot complete the maneuver. */
  tick(&car, 15040, 0, 500, 500);
  assert(car.state == CAR_AVOID_PASS);
  puts("car_logic tests passed");
  return 0;
}
