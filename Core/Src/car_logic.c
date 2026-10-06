#include "car_logic.h"
#include "car_config.h"
#include <stddef.h>
#include <math.h>


static uint16_t clamp_steer(const CarController *car, int32_t value) {
  uint16_t minimum = CarServo_MinUs(&car->servo_params);
  uint16_t maximum = CarServo_MaxUs(&car->servo_params);
  if (value < (int32_t)minimum) return minimum;
  if (value > (int32_t)maximum) return maximum;
  return (uint16_t)value;
}

static void stopped(CarController *car) {
  car->output.left_pwm = 0;
  car->output.right_pwm = 0;
  car->output.steer_us = car->servo_params.center_us;
  car->debug_speed_active = false;
  CarPid_Reset(&car->pid);
}

static void fault(CarController *car, CarFault reason, uint32_t now) {
  car->fault = reason;
  car->state = CAR_FAULT;
  car->state_since_ms = now;
  car->debug_pwm_limit = CAR_DEBUG_DEFAULT_PWM_LIMIT;
  stopped(car);
}

static void enter(CarController *car, CarState state, uint32_t now) {
  car->state = state;
  car->state_since_ms = now;
  if (state != CAR_DEBUG) car->debug_pwm_limit = CAR_DEBUG_DEFAULT_PWM_LIMIT;
  if (state != CAR_FOLLOW) car->finish_since_ms = 0U;
}

static void reset_control(CarController *car) {
  /* A command can arrive between encoder samples. Keep that last measured
   * speed while resetting targets/integrators, avoiding artificial zero dips
   * in CTRL? every time the PC renews manual control. */
  float left = car->pid.left_measured;
  float right = car->pid.right_measured;
  CarPid_Reset(&car->pid);
  car->pid.left_measured = left;
  car->pid.right_measured = right;
}

void CarLogic_Init(CarController *car) {
  if (car == NULL) return;
  *car = (CarController){0};
  car->state = CAR_IDLE;
  car->debug_pwm_limit = CAR_DEBUG_DEFAULT_PWM_LIMIT;
  car->pid_params = CarPid_DefaultParams();
  car->servo_params = CarServo_DefaultParams();
  stopped(car);
}

bool CarLogic_SetServoParams(CarController *car, const CarServoParams *params) {
  if (car == NULL || car->state != CAR_IDLE || !CarServo_ValidParams(params)) return false;
  car->servo_params = *params;
  stopped(car);
  return true;
}

void CarLogic_Stop(CarController *car, uint32_t now_ms) {
  if (car == NULL) return;
  stopped(car);
  car->fault = CAR_FAULT_NONE;
  enter(car, CAR_IDLE, now_ms);
}

bool CarLogic_Arm(CarController *car, uint32_t now_ms) {
  if (car == NULL || car->state != CAR_IDLE) return false;
  car->fault = CAR_FAULT_NONE;
  car->obstacles = 0;
  car->range_missing = false;
  car->start_line_cleared = false;
  car->finish_since_ms = 0;
  car->last_avoid_ms = 0;
  stopped(car);
  enter(car, CAR_ARMED, now_ms);
  return true;
}

bool CarLogic_Debug(CarController *car, uint32_t now_ms) {
  if (car == NULL || car->state != CAR_IDLE) return false;
  stopped(car);
  car->debug_pwm_limit = CAR_DEBUG_DEFAULT_PWM_LIMIT;
  car->debug_deadline_ms = now_ms;
  enter(car, CAR_DEBUG, now_ms);
  return true;
}

bool CarLogic_DebugLimit(CarController *car, uint16_t limit) {
  if (car == NULL || car->state != CAR_DEBUG || limit < 1U || limit > 1000U ||
      car->output.left_pwm != 0 || car->output.right_pwm != 0 ||
      car->debug_speed_active) return false;
  car->debug_pwm_limit = limit;
  return true;
}

bool CarLogic_DebugDrive(CarController *car, int16_t left, int16_t right,
                         uint16_t steer_us, uint32_t now_ms) {
  if (car == NULL || car->state != CAR_DEBUG ||
      left < -(int16_t)car->debug_pwm_limit || left > (int16_t)car->debug_pwm_limit ||
      right < -(int16_t)car->debug_pwm_limit || right > (int16_t)car->debug_pwm_limit ||
      steer_us < CarServo_MinUs(&car->servo_params) ||
      steer_us > CarServo_MaxUs(&car->servo_params)) return false;
  reset_control(car);
  car->debug_speed_active = false;
  car->output.left_pwm = left;
  car->output.right_pwm = right;
  car->output.steer_us = steer_us;
  car->debug_deadline_ms = now_ms;
  return true;
}

bool CarLogic_DebugSpeed(CarController *car, float left_target, float right_target,
                         uint32_t now_ms) {
  if (car == NULL || car->state != CAR_DEBUG ||
      !isfinite(left_target) || !isfinite(right_target) ||
      left_target < 0.0f || left_target > 500.0f ||
      right_target < 0.0f || right_target > 500.0f) return false;
  /* Repeated identical commands renew the deadman without clearing the I/D
   * state. A new target or a mode switch starts a fresh step response. */
  if (!car->debug_speed_active || car->pid.left_target != left_target ||
      car->pid.right_target != right_target) reset_control(car);
  car->pid.left_target = left_target;
  car->pid.right_target = right_target;
  car->debug_speed_active = left_target > 0.0f || right_target > 0.0f;
  car->output.steer_us = car->servo_params.center_us;
  car->debug_deadline_ms = now_ms;
  if (left_target == 0.0f) car->output.left_pwm = 0;
  if (right_target == 0.0f) car->output.right_pwm = 0;
  return true;
}

static float line_error(uint8_t bits) {
  int16_t sum = 0;
  int16_t count = 0;
  for (unsigned i = 0; i < CAR_LINE_SENSOR_COUNT; ++i) {
    if ((bits & (1U << i)) != 0U) {
      sum += (int16_t)(2 * (int)i - (int)(CAR_LINE_SENSOR_COUNT - 1U));
      ++count;
    }
  }
  return count == 0 ? 0.0f : (float)sum * 5.0f /
         ((float)count * (float)(CAR_LINE_SENSOR_COUNT - 1U));
}

static float control_dt(const CarInputs *in) {
  uint16_t milliseconds = in->dt_ms == 0U ? 10U : in->dt_ms;
  return (float)(milliseconds > 200U ? 200U : milliseconds) / 1000.0f;
}

static void drive_auto(CarController *car, const CarInputs *in,
                       uint16_t steer_us, float speed_scale) {
  car->output.steer_us = clamp_steer(car, steer_us);
  float steering = car->servo_params.span_us == 0U ? 0.0f :
    ((float)car->output.steer_us - (float)car->servo_params.center_us) /
    (float)car->servo_params.span_us;
  CarPid_SpeedStep(&car->pid_params, &car->pid, steering, speed_scale,
                   in->encoder_left_delta, in->encoder_right_delta,
                   control_dt(in), &car->output.left_pwm,
                   &car->output.right_pwm);
}

static void follow(CarController *car, const CarInputs *in, uint8_t bits) {
  float correction = CarPid_LineStepLimited(&car->pid_params, &car->pid,
      line_error(bits), control_dt(in), (float)car->servo_params.span_us);
  uint16_t steer = clamp_steer(car, (int32_t)((float)car->servo_params.center_us + correction));
  drive_auto(car, in, steer, 1.0f);
}

static void avoid(CarController *car, const CarInputs *in, int8_t direction) {
  int32_t excursion = (int32_t)car->servo_params.span_us * 9 / 10;
  uint16_t steer = clamp_steer(car, (int32_t)car->servo_params.center_us + excursion * direction);
  drive_auto(car, in, steer, 0.88f);
}

void CarLogic_Tick(CarController *car, const CarInputs *in) {
  if (car == NULL || in == NULL) return;
  uint32_t now = in->now_ms;
  uint8_t line = in->line_bits & CAR_LINE_MASK;
  if (car->state == CAR_IDLE || car->state == CAR_FAULT || car->state == CAR_FINISHED) {
    car->debug_pwm_limit = CAR_DEBUG_DEFAULT_PWM_LIMIT;
    stopped(car);
    CarPid_MeasureSpeed(&car->pid, in->encoder_left_delta,
                        in->encoder_right_delta, control_dt(in));
    return;
  }
  if (car->state == CAR_DEBUG) {
    /* Editing a stopped bench must not expire the unlock. Motion still needs
     * DRIVE/SPEED renewal; LIMIT commands never renew that deadman. */
    if ((car->output.left_pwm != 0 || car->output.right_pwm != 0 ||
         car->output.steer_us != car->servo_params.center_us || car->debug_speed_active) &&
        now - car->debug_deadline_ms >= CAR_DEBUG_DEADMAN_MS) {
      stopped(car);
      car->debug_pwm_limit = CAR_DEBUG_DEFAULT_PWM_LIMIT;
    }
    if (car->debug_speed_active)
      CarPid_DebugSpeedStep(&car->pid_params, &car->pid,
                            car->pid.left_target, car->pid.right_target,
                            in->encoder_left_delta, in->encoder_right_delta,
                            control_dt(in), car->debug_pwm_limit, &car->output.left_pwm,
                            &car->output.right_pwm);
    else
      CarPid_MeasureSpeed(&car->pid, in->encoder_left_delta,
                          in->encoder_right_delta, control_dt(in));
    return;
  }
  if (car->state == CAR_ARMED) {
    stopped(car);
    if (now - car->state_since_ms < CAR_ARM_DELAY_MS) return;
    if (!in->left_valid || !in->center_valid || !in->right_valid) {
      fault(car, CAR_FAULT_RANGE, now);
      return;
    }
    if (line == 0U) {
      fault(car, CAR_FAULT_LINE_LOST, now);
      return;
    }
    car->race_since_ms = now;
    car->last_line_ms = now;
    enter(car, CAR_FOLLOW, now);
  }
  if (now - car->race_since_ms >= CAR_MAX_RACE_MS) {
    fault(car, CAR_FAULT_RACE_TIMEOUT, now);
    return;
  }
  if (!in->left_valid || !in->center_valid || !in->right_valid) {
    /* Finish requires an uninterrupted observation while control is active. */
    car->finish_since_ms = 0U;
    if (!car->range_missing) {
      car->range_missing = true;
      car->range_lost_since_ms = now;
    }
    if (now - car->range_lost_since_ms >= CAR_RANGE_FAULT_MS) fault(car, CAR_FAULT_RANGE, now);
    else stopped(car);
    return;
  }
  if (car->range_missing && car->state >= CAR_AVOID_OUT && car->state <= CAR_RECOVER)
    car->state_since_ms += now - car->range_lost_since_ms;
  car->range_missing = false;
  /* Collision protection applies during cooldown and every avoidance phase too. */
  if (in->center_mm < CAR_FRONT_STOP_MM || in->left_mm < 30U || in->right_mm < 30U ||
      (in->left_mm < 130U && in->right_mm < 130U)) {
    fault(car, CAR_FAULT_BLOCKED, now);
    return;
  }
  switch (car->state) {
    case CAR_FOLLOW: {
      if (line != 0U) car->last_line_ms = now;
      if (line == 0U && now - car->last_line_ms >= CAR_LINE_LOST_MS) {
        fault(car, CAR_FAULT_LINE_LOST, now);
        return;
      }
      if (line != 0U && line != CAR_LINE_MASK) car->start_line_cleared = true;
      if (car->start_line_cleared && now - car->race_since_ms >= CAR_MIN_FINISH_MS && line == CAR_LINE_MASK) {
        if (car->finish_since_ms == 0U) car->finish_since_ms = now;
        if (now - car->finish_since_ms >= CAR_FINISH_HOLD_MS) {
          stopped(car);
          enter(car, CAR_FINISHED, now);
          return;
        }
      } else car->finish_since_ms = 0U;
      bool near_left = in->left_mm < CAR_OBSTACLE_MM;
      bool near_right = in->right_mm < CAR_OBSTACLE_MM;
      bool near_center = in->center_mm < CAR_OBSTACLE_MM;
      if (near_center || ((near_left || near_right) &&
                          now - car->last_avoid_ms >= CAR_AVOID_COOLDOWN_MS)) {
        car->avoid_direction = in->left_mm <= in->right_mm ? 1 : -1;
        enter(car, CAR_AVOID_OUT, now);
        car->pid.line = (CarPidAxis){0};
        avoid(car, in, car->avoid_direction);
        return;
      }
      if (line == 0U) {
        car->pid.line = (CarPidAxis){0};
        drive_auto(car, in, car->output.steer_us, 0.5f);
        return;
      }
      follow(car, in, line);
      return;
    }
    case CAR_AVOID_OUT:
      if (now - car->state_since_ms >= CAR_AVOID_OUT_MS) enter(car, CAR_AVOID_PASS, now);
      else { avoid(car, in, car->avoid_direction); return; }
      /* fall through */
    case CAR_AVOID_PASS:
      if (now - car->state_since_ms >= CAR_AVOID_PASS_MS) enter(car, CAR_AVOID_IN, now);
      else {
        drive_auto(car, in, car->servo_params.center_us, 0.88f);
        return;
      }
      /* fall through */
    case CAR_AVOID_IN:
      if (now - car->state_since_ms >= CAR_AVOID_IN_MS) enter(car, CAR_RECOVER, now);
      else { avoid(car, in, (int8_t)-car->avoid_direction); return; }
      /* fall through */
    case CAR_RECOVER:
      if (line != 0U) {
        if (car->obstacles < 255U) ++car->obstacles;
        car->last_avoid_ms = now;
        car->last_line_ms = now;
        enter(car, CAR_FOLLOW, now);
        follow(car, in, line);
      } else if (now - car->state_since_ms >= CAR_RECOVER_MS) {
        fault(car, CAR_FAULT_RECOVERY, now);
      } else avoid(car, in, (int8_t)-car->avoid_direction);
      return;
    default:
      fault(car, CAR_FAULT_BLOCKED, now);
      return;
  }
}

const char *CarLogic_StateName(CarState state) {
  static const char *names[] = {"IDLE", "ARMED", "FOLLOW", "AVOID_OUT", "AVOID_PASS",
    "AVOID_IN", "RECOVER", "FINISHED", "DEBUG", "FAULT"};
  return (unsigned)state < sizeof(names) / sizeof(names[0]) ? names[state] : "UNKNOWN";
}
