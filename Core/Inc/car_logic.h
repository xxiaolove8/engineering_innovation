#ifndef CAR_LOGIC_H
#define CAR_LOGIC_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
  CAR_IDLE, CAR_ARMED, CAR_FOLLOW, CAR_AVOID_OUT, CAR_AVOID_PASS,
  CAR_AVOID_IN, CAR_RECOVER, CAR_FINISHED, CAR_DEBUG, CAR_FAULT
} CarState;

typedef enum {
  CAR_FAULT_NONE, CAR_FAULT_LINE_LOST, CAR_FAULT_RANGE, CAR_FAULT_RECOVERY,
  CAR_FAULT_RACE_TIMEOUT, CAR_FAULT_BLOCKED
} CarFault;

typedef struct {
  uint32_t now_ms;
  uint8_t line_bits;       /* bit 0 is the leftmost sensor; 1 means black */
  uint16_t left_mm;
  uint16_t right_mm;
  bool left_valid;
  bool right_valid;
} CarInputs;

typedef struct {
  int16_t left_pwm;        /* signed permille, -1000..1000 */
  int16_t right_pwm;
  uint16_t steer_us;
} CarOutputs;

typedef struct {
  CarState state;
  CarFault fault;
  CarOutputs output;
  uint32_t state_since_ms;
  uint32_t race_since_ms;
  uint32_t last_line_ms;
  uint32_t debug_deadline_ms;
  uint32_t finish_since_ms;
  uint32_t last_avoid_ms;
  uint8_t obstacles;
  int8_t avoid_direction;
  int16_t previous_error;
} CarController;

void CarLogic_Init(CarController *car);
void CarLogic_Tick(CarController *car, const CarInputs *input);
bool CarLogic_Arm(CarController *car, uint32_t now_ms);
bool CarLogic_Debug(CarController *car, uint32_t now_ms);
bool CarLogic_DebugDrive(CarController *car, int16_t left, int16_t right,
                         uint16_t steer_us, uint32_t now_ms);
void CarLogic_Stop(CarController *car, uint32_t now_ms);
const char *CarLogic_StateName(CarState state);

#endif
