#ifndef CAR_PID_H
#define CAR_PID_H

#include <stdbool.h>
#include <stdint.h>

/* Speed is measured in encoder counts per 10 ms. The calibration value
 * target_ticks must be checked on the actual car before racing. */
typedef struct {
  float line_kp, line_ki, line_kd;
  float speed_kp, speed_ki, speed_kd;
  float target_ticks;
  float feedforward_pwm;
  float differential_gain;
  float curve_slowdown;
} CarPidParams;

typedef struct {
  float integral;
  float previous;
  float derivative;
  bool initialized;
} CarPidAxis;

typedef struct {
  CarPidAxis line;
  CarPidAxis left_speed;
  CarPidAxis right_speed;
  float line_error;
  float left_measured;
  float right_measured;
  float left_target;
  float right_target;
} CarPidRuntime;

CarPidParams CarPid_DefaultParams(void);
bool CarPid_ValidParams(const CarPidParams *params);
bool CarPid_SetParam(CarPidParams *params, const char *name, float value);
void CarPid_Reset(CarPidRuntime *runtime);
void CarPid_MeasureSpeed(CarPidRuntime *runtime, int32_t left_delta,
                         int32_t right_delta, float dt_seconds);
float CarPid_LineStep(const CarPidParams *params, CarPidRuntime *runtime,
                      float line_error, float dt_seconds);
/* Runtime pulse excursion also bounds the integral's anti-windup. */
float CarPid_LineStepLimited(const CarPidParams *params, CarPidRuntime *runtime,
                             float line_error, float dt_seconds, float maximum_us);
void CarPid_SpeedStep(const CarPidParams *params, CarPidRuntime *runtime,
                      float steering, float speed_scale,
                      int32_t left_delta, int32_t right_delta,
                      float dt_seconds, int16_t *left_pwm, int16_t *right_pwm);
/* Independent forward targets with the session's DEBUG output/anti-windup limit. */
void CarPid_DebugSpeedStep(const CarPidParams *params, CarPidRuntime *runtime,
                           float left_target, float right_target,
                           int32_t left_delta, int32_t right_delta,
                           float dt_seconds, uint16_t pwm_limit,
                           int16_t *left_pwm, int16_t *right_pwm);

#endif
