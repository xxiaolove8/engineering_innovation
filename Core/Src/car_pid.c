#include "car_pid.h"
#include <math.h>
#include <stddef.h>
#include <string.h>

#define MAX_AUTO_PWM 500.0f
#define LINE_I_LIMIT 2.0f
#define SPEED_I_LIMIT 100.0f
#define D_FILTER 0.2f

typedef struct {
  const char *name;
  size_t offset;
  float maximum;
  bool positive;
} CarPidParameter;

/* Command updates and flash-record validation share the same bounds. */
static const CarPidParameter parameters[] = {
  {"line_kp", offsetof(CarPidParams, line_kp), 200.0f, false},
  {"line_ki", offsetof(CarPidParams, line_ki), 100.0f, false},
  {"line_kd", offsetof(CarPidParams, line_kd), 10.0f, false},
  {"speed_kp", offsetof(CarPidParams, speed_kp), 50.0f, false},
  {"speed_ki", offsetof(CarPidParams, speed_ki), 50.0f, false},
  {"speed_kd", offsetof(CarPidParams, speed_kd), 10.0f, false},
  {"target_ticks", offsetof(CarPidParams, target_ticks), 500.0f, true},
  {"feedforward_pwm", offsetof(CarPidParams, feedforward_pwm), MAX_AUTO_PWM, false},
  {"differential_gain", offsetof(CarPidParams, differential_gain), 1.0f, false},
  {"curve_slowdown", offsetof(CarPidParams, curve_slowdown), 1.0f, false}
};

static bool parameter_valid(const CarPidParameter *parameter, float value) {
  return isfinite(value) && value <= parameter->maximum &&
         (parameter->positive ? value > 0.0f : value >= 0.0f);
}

static float clamp(float value, float low, float high) {
  return value < low ? low : (value > high ? high : value);
}

CarPidParams CarPid_DefaultParams(void) {
  return (CarPidParams){
    .line_kp = 27.0f, .line_ki = 0.0f, .line_kd = 0.09f,
    .speed_kp = 3.0f, .speed_ki = 1.0f, .speed_kd = 0.0f,
    .target_ticks = 20.0f, .feedforward_pwm = 250.0f,
    .differential_gain = 0.35f, .curve_slowdown = 0.35f
  };
}

bool CarPid_ValidParams(const CarPidParams *params) {
  if (params == NULL) return false;
  for (unsigned i = 0; i < sizeof(parameters) / sizeof(parameters[0]); ++i) {
    float value;
    memcpy(&value, (const uint8_t *)params + parameters[i].offset, sizeof(value));
    if (!parameter_valid(&parameters[i], value)) return false;
  }
  return true;
}

bool CarPid_SetParam(CarPidParams *params, const char *name, float value) {
  if (params == NULL || name == NULL) return false;
  for (unsigned i = 0; i < sizeof(parameters) / sizeof(parameters[0]); ++i) {
    if (strcmp(name, parameters[i].name) != 0) continue;
    if (!parameter_valid(&parameters[i], value)) return false;
    memcpy((uint8_t *)params + parameters[i].offset, &value, sizeof(value));
    return true;
  }
  return false;
}

void CarPid_Reset(CarPidRuntime *runtime) {
  if (runtime != NULL) memset(runtime, 0, sizeof(*runtime));
}

float CarPid_LineStep(const CarPidParams *params, CarPidRuntime *runtime,
                      float line_error, float dt_seconds) {
  return CarPid_LineStepLimited(params, runtime, line_error, dt_seconds, 200.0f);
}

float CarPid_LineStepLimited(const CarPidParams *params, CarPidRuntime *runtime,
                             float line_error, float dt_seconds, float maximum_us) {
  if (params == NULL || runtime == NULL || !isfinite(dt_seconds) || dt_seconds <= 0.0f ||
      !isfinite(line_error) || !isfinite(maximum_us) || maximum_us < 0.0f) return 0.0f;
  CarPidAxis *axis = &runtime->line;
  float derivative = 0.0f;
  if (axis->initialized)
    derivative = D_FILTER * (line_error - axis->previous) / dt_seconds +
                 (1.0f - D_FILTER) * axis->derivative;
  axis->previous = line_error;
  axis->derivative = derivative;
  axis->initialized = true;
  float candidate = clamp(axis->integral + line_error * dt_seconds,
                          -LINE_I_LIMIT, LINE_I_LIMIT);
  float raw = params->line_kp * line_error + params->line_ki * candidate +
              params->line_kd * derivative;
  if (maximum_us == 0.0f) axis->integral = 0.0f;
  else if (!((raw > maximum_us && line_error > 0.0f) ||
             (raw < -maximum_us && line_error < 0.0f))) axis->integral = candidate;
  runtime->line_error = line_error;
  return clamp(params->line_kp * line_error +
               params->line_ki * axis->integral +
               params->line_kd * derivative, -maximum_us, maximum_us);
}

static int16_t speed_step(CarPidAxis *axis, const CarPidParams *params,
                          float target, float measured, float dt_seconds,
                          float maximum_pwm) {
  if (target <= 0.0f) {
    *axis = (CarPidAxis){0};
    return 0;
  }
  float derivative = 0.0f;
  if (axis->initialized)
    derivative = D_FILTER * (measured - axis->previous) / dt_seconds +
                 (1.0f - D_FILTER) * axis->derivative;
  axis->previous = measured;
  axis->derivative = derivative;
  axis->initialized = true;
  float error = target - measured;
  float feedforward = params->feedforward_pwm * target / params->target_ticks;
  float candidate = clamp(axis->integral + error * dt_seconds,
                          -SPEED_I_LIMIT, SPEED_I_LIMIT);
  float raw = feedforward + params->speed_kp * error +
              params->speed_ki * candidate - params->speed_kd * derivative;
  if (!((raw > maximum_pwm && error > 0.0f) ||
        (raw < 0.0f && error < 0.0f))) axis->integral = candidate;
  raw = feedforward + params->speed_kp * error +
        params->speed_ki * axis->integral - params->speed_kd * derivative;
  return (int16_t)(clamp(raw, 0.0f, maximum_pwm) + 0.5f);
}

void CarPid_MeasureSpeed(CarPidRuntime *runtime, int32_t left_delta,
                         int32_t right_delta, float dt_seconds) {
  if (runtime == NULL || !isfinite(dt_seconds) || dt_seconds <= 0.0f) return;
  /* Encoder polarities depend on wiring. This is speed magnitude, including
   * reverse raw-PWM testing; STATUS? retains the signed encoder deltas. */
  runtime->left_measured = fabsf((float)left_delta) * 0.01f / dt_seconds;
  runtime->right_measured = fabsf((float)right_delta) * 0.01f / dt_seconds;
}

void CarPid_SpeedStep(const CarPidParams *params, CarPidRuntime *runtime,
                      float steering, float speed_scale,
                      int32_t left_delta, int32_t right_delta,
                      float dt_seconds, int16_t *left_pwm, int16_t *right_pwm) {
  if (params == NULL || runtime == NULL || left_pwm == NULL ||
      right_pwm == NULL || dt_seconds <= 0.0f) return;
  steering = clamp(steering, -1.0f, 1.0f);
  speed_scale = clamp(speed_scale, 0.0f, 1.0f);
  /* TIM3/TIM4 polarities may differ. Use magnitude for forward-only AUTO;
   * verify both signed encoder directions during bench setup. */
  CarPid_MeasureSpeed(runtime, left_delta, right_delta, dt_seconds);
  float base = params->target_ticks * speed_scale *
               (1.0f - params->curve_slowdown * fabsf(steering));
  float difference = params->differential_gain * steering;
  /* Positive steering is right: left rear wheel runs faster. */
  runtime->left_target = clamp(base * (1.0f + difference), 0.0f, 500.0f);
  runtime->right_target = clamp(base * (1.0f - difference), 0.0f, 500.0f);
  *left_pwm = speed_step(&runtime->left_speed, params, runtime->left_target,
                         runtime->left_measured, dt_seconds, MAX_AUTO_PWM);
  *right_pwm = speed_step(&runtime->right_speed, params, runtime->right_target,
                          runtime->right_measured, dt_seconds, MAX_AUTO_PWM);
}

void CarPid_DebugSpeedStep(const CarPidParams *params, CarPidRuntime *runtime,
                           float left_target, float right_target,
                           int32_t left_delta, int32_t right_delta,
                           float dt_seconds, uint16_t pwm_limit,
                           int16_t *left_pwm, int16_t *right_pwm) {
  if (params == NULL || runtime == NULL || left_pwm == NULL || right_pwm == NULL ||
      !isfinite(dt_seconds) || dt_seconds <= 0.0f ||
      !isfinite(left_target) || !isfinite(right_target) ||
      pwm_limit < 1U || pwm_limit > 1000U) return;
  CarPid_MeasureSpeed(runtime, left_delta, right_delta, dt_seconds);
  runtime->left_target = clamp(left_target, 0.0f, 500.0f);
  runtime->right_target = clamp(right_target, 0.0f, 500.0f);
  *left_pwm = speed_step(&runtime->left_speed, params, runtime->left_target,
                         runtime->left_measured, dt_seconds, (float)pwm_limit);
  *right_pwm = speed_step(&runtime->right_speed, params, runtime->right_target,
                          runtime->right_measured, dt_seconds, (float)pwm_limit);
}
