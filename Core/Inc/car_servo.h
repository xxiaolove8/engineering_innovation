#ifndef CAR_SERVO_H
#define CAR_SERVO_H

#include <stdbool.h>
#include <stdint.h>

/* Pulse widths, not angles. Mechanical travel must be calibrated on the car. */
#define CAR_SERVO_PULSE_MIN_US 500U
#define CAR_SERVO_PULSE_MAX_US 2500U
#define CAR_SERVO_DEFAULT_CENTER_US 1500U
#define CAR_SERVO_DEFAULT_SPAN_US 200U

typedef struct {
  uint16_t center_us;
  uint16_t span_us; /* Symmetric excursion: center_us +/- span_us. */
} CarServoParams;

static inline CarServoParams CarServo_DefaultParams(void) {
  return (CarServoParams){CAR_SERVO_DEFAULT_CENTER_US, CAR_SERVO_DEFAULT_SPAN_US};
}

static inline bool CarServo_ValidParams(const CarServoParams *params) {
  return params != 0 && params->center_us >= CAR_SERVO_PULSE_MIN_US &&
         params->center_us <= CAR_SERVO_PULSE_MAX_US &&
         params->span_us <= params->center_us - CAR_SERVO_PULSE_MIN_US &&
         params->span_us <= CAR_SERVO_PULSE_MAX_US - params->center_us;
}

static inline uint16_t CarServo_MinUs(const CarServoParams *params) {
  return (uint16_t)(params->center_us - params->span_us);
}

static inline uint16_t CarServo_MaxUs(const CarServoParams *params) {
  return (uint16_t)(params->center_us + params->span_us);
}

#endif
