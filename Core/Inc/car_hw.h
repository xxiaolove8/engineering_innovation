#ifndef CAR_HW_H
#define CAR_HW_H

#include "car_logic.h"
#include <stdbool.h>
#include <stdint.h>

typedef enum {
  CAR_RANGE_NEVER, CAR_RANGE_WAIT_RISE, CAR_RANGE_WAIT_FALL, CAR_RANGE_OK,
  CAR_RANGE_NO_RISE, CAR_RANGE_NO_FALL, CAR_RANGE_ECHO_HIGH,
  CAR_RANGE_START_ERROR, CAR_RANGE_BAD_PULSE, CAR_RANGE_OVERCAPTURE,
  CAR_RANGE_CLOCK_ERROR, CAR_RANGE_LATE_ECHO, CAR_RANGE_IRQ_MISSED
} CarRangeState;

typedef struct {
  CarRangeState state;
  bool valid, echo_high, timer_running;
  uint16_t pulse_us, distance_mm, counter, prescaler;
  uint32_t age_ms; /* UINT32_MAX until the first completed attempt. */
  uint32_t triggers, rises, falls, timeouts, errors, flags;
} CarRangeDiagnostics;

typedef struct {
  uint8_t raw_bits, line_bits; /* Logical CH1..CH8; raw 1 = OUT high, line 1 = on line. */
  uint32_t age_ms;
} CarLineDiagnostics;

bool CarHw_CommInit(void); /* At least one UART works; actuator faults leave diagnostics available. */
bool CarHw_Init(void);
/* Install calibration before PWM startup; applying it also stops and centers. */
bool CarHw_SetServoParams(const CarServoParams *params);
bool CarHw_Ready(void);
const char *CarHw_InitStageName(void);
void CarHw_PollRange(uint32_t now_ms);
bool CarHw_RangeDiagnostics(unsigned side, CarRangeDiagnostics *diagnostics);
const char *CarHw_RangeStateName(CarRangeState state);
void CarHw_Snapshot(CarInputs *input);
bool CarHw_LineDiagnostics(CarLineDiagnostics *diagnostics);
void CarHw_Apply(const CarOutputs *output);
void CarHw_Stop(void);
void CarHw_EmergencyStop(void); /* No initialized handles, tick or interrupt required. */
void CarHw_EncoderDeltas(int32_t *left, int32_t *right);
/* Round-robin USART3/USART1 input; a successful read selects its reply port.
   Handle that command and send its responses before reading the next command. */
bool CarHw_ReadLine(char *destination, unsigned capacity);
void CarHw_Send(const char *message); /* Replies only to the most recently read command's UART. */

#endif
