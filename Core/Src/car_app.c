#include "car_app.h"
#include "car_hw.h"
#include "car_logic.h"
#include "car_pid_store.h"
#include "car_config.h"
#include "stm32f4xx_hal.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <ctype.h>
#include <math.h>

static CarController car;
static CarInputs sample;
static int32_t encoder_left_delta;
static int32_t encoder_right_delta;
static uint32_t last_control_ms;
static bool initialized;

static void hardware_fault(uint32_t now_ms) {
  CarHw_Stop();
  if (car.state != CAR_FAULT || car.fault != CAR_FAULT_HARDWARE) {
    CarLogic_Stop(&car, now_ms);
    car.state = CAR_FAULT;
    car.fault = CAR_FAULT_HARDWARE;
  }
  sample.left_valid = sample.center_valid = sample.right_valid = false;
  sample.line_bits = 0U;
  encoder_left_delta = encoder_right_delta = 0;
}

bool CarApp_Init(void) {
  initialized = false;
  sample = (CarInputs){0};
  encoder_left_delta = encoder_right_delta = 0;
  CarLogic_Init(&car);
  CarPidParams saved_params;
  if (CarPidStore_Load(&saved_params)) car.pid_params = saved_params;
  CarServoParams saved_servo;
  if (CarServoStore_Load(&saved_servo)) (void)CarLogic_SetServoParams(&car, &saved_servo);
  /* Load both layers before TIM1 starts: no default-center pulse on startup. */
  (void)CarHw_SetServoParams(&car.servo_params);
  if (!CarHw_CommInit()) { CarHw_Stop(); return false; }
  bool hardware_ready = CarHw_Init();
  last_control_ms = HAL_GetTick();
  initialized = true;
  if (!hardware_ready) hardware_fault(last_control_ms);
  return true;
}

void CarApp_EmergencyStop(void) {
  CarHw_EmergencyStop();
  if (initialized) {
    CarHw_Stop();
    if (CarHw_Ready()) CarLogic_Stop(&car, HAL_GetTick());
    else hardware_fault(HAL_GetTick());
  }
}

static void status(void) {
  char line[160];
  int count = snprintf(line, sizeof(line),
      "STAT %s %u %u %d %d %d %ld %ld %u %d %d %u\n",
      CarLogic_StateName(car.state), (unsigned)car.fault,
      (unsigned)sample.line_bits,
      sample.left_valid ? (int)sample.left_mm : -1,
      sample.center_valid ? (int)sample.center_mm : -1,
      sample.right_valid ? (int)sample.right_mm : -1,
      (long)encoder_left_delta, (long)encoder_right_delta,
      (unsigned)car.obstacles, (int)car.output.left_pwm,
      (int)car.output.right_pwm, (unsigned)car.output.steer_us);
  if (count > 0 && count < (int)sizeof(line)) CarHw_Send(line);
}

static void pid_status(void) {
  const CarPidParams *p = &car.pid_params;
  char line[120];
  int count = snprintf(line, sizeof(line),
      "PID %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f\n",
      (double)p->line_kp, (double)p->line_ki, (double)p->line_kd,
      (double)p->speed_kp, (double)p->speed_ki, (double)p->speed_kd,
      (double)p->target_ticks, (double)p->feedforward_pwm,
      (double)p->differential_gain, (double)p->curve_slowdown);
  if (count > 0 && count < (int)sizeof(line)) CarHw_Send(line);
}

static void servo_status(void) {
  char line[32];
  snprintf(line, sizeof(line), "SERVO %u %u\n", (unsigned)car.servo_params.center_us,
           (unsigned)car.servo_params.span_us);
  CarHw_Send(line);
}

static void servo_apply(const CarServoParams *params) {
  /* Callers check IDLE and the complete pair before either layer is changed. */
  (void)CarLogic_SetServoParams(&car, params);
  (void)CarHw_SetServoParams(params);
}

static void range_status(unsigned side) {
  CarRangeDiagnostics d;
  if (!CarHw_RangeDiagnostics(side, &d)) return;
  char line[160];
  int count = snprintf(line, sizeof(line),
      "RANGE %c %s %u %u %u %d %lu %lu %lu %lu %lu %lu %u %u %lu %u\n",
      "LCR"[side], CarHw_RangeStateName(d.state), (unsigned)d.valid,
      (unsigned)d.echo_high, (unsigned)d.pulse_us, d.valid ? (int)d.distance_mm : -1,
      (unsigned long)d.age_ms, (unsigned long)d.triggers, (unsigned long)d.rises,
      (unsigned long)d.falls, (unsigned long)d.timeouts, (unsigned long)d.errors,
      (unsigned)d.counter, (unsigned)d.prescaler, (unsigned long)d.flags,
      (unsigned)d.timer_running);
  if (count > 0 && count < (int)sizeof(line)) CarHw_Send(line);
}

static void control_status(void) {
  const CarPidRuntime *p = &car.pid;
  char line[120];
  int count = snprintf(line, sizeof(line),
      "CTRL %.2f %.2f %.2f %.2f %.2f %d %d %u\n",
      (double)p->line_error, (double)p->left_measured,
      (double)p->right_measured, (double)p->left_target,
      (double)p->right_target, (int)car.output.left_pwm,
      (int)car.output.right_pwm, (unsigned)car.output.steer_us);
  if (count > 0 && count < (int)sizeof(line)) CarHw_Send(line);
}

static bool drive_values(const char *text, int16_t *left, int16_t *right, uint16_t *steer) {
  long values[3];
  for (unsigned i = 0U; i < 3U; ++i) {
    char *end;
    errno = 0;
    values[i] = strtol(text, &end, 10);
    if (end == text || errno == ERANGE) return false;
    if (i < 2U && !isspace((unsigned char)*end)) return false;
    text = end;
  }
  while (isspace((unsigned char)*text)) ++text;
  if (*text != '\0' || values[0] < -1000 || values[0] > 1000 ||
      values[1] < -1000 || values[1] > 1000 || values[2] < (long)CarServo_MinUs(&car.servo_params) ||
      values[2] > (long)CarServo_MaxUs(&car.servo_params)) return false;
  *left = (int16_t)values[0];
  *right = (int16_t)values[1];
  *steer = (uint16_t)values[2];
  return true;
}

static bool debug_limit_value(const char *text, uint16_t *limit) {
  char *end;
  errno = 0;
  long value = strtol(text, &end, 10);
  if (end == text || errno == ERANGE || value < 1 || value > 1000) return false;
  while (isspace((unsigned char)*end)) ++end;
  if (*end != '\0') return false;
  *limit = (uint16_t)value;
  return true;
}

static bool servo_values(const char *text, CarServoParams *params) {
  long values[2];
  for (unsigned i = 0U; i < 2U; ++i) {
    char *end;
    errno = 0;
    values[i] = strtol(text, &end, 10);
    if (end == text || errno == ERANGE || values[i] < 0 || values[i] > UINT16_MAX)
      return false;
    if (i == 0U && !isspace((unsigned char)*end)) return false;
    text = end;
  }
  while (isspace((unsigned char)*text)) ++text;
  if (*text != '\0') return false;
  CarServoParams candidate = {(uint16_t)values[0], (uint16_t)values[1]};
  if (!CarServo_ValidParams(&candidate)) return false;
  *params = candidate;
  return true;
}

static bool speed_values(const char *text, float *left, float *right) {
  float values[2];
  for (unsigned i = 0U; i < 2U; ++i) {
    char *end;
    errno = 0;
    values[i] = strtof(text, &end);
    if (end == text || errno == ERANGE || !isfinite(values[i]) ||
        values[i] < 0.0f || values[i] > 500.0f) return false;
    /* Text protocol uses decimal/exponent syntax. strtof also accepts C hex
     * floats, which the PC client intentionally does not support. */
    for (const char *p = text; p < end; ++p)
      if (!isspace((unsigned char)*p) && !isdigit((unsigned char)*p) &&
          *p != '+' && *p != '-' && *p != '.' && *p != 'e' && *p != 'E') return false;
    if (i == 0U && !isspace((unsigned char)*end)) return false;
    text = end;
  }
  while (isspace((unsigned char)*text)) ++text;
  if (*text != '\0') return false;
  *left = values[0];
  *right = values[1];
  return true;
}

static void command(const char *line, uint32_t now_ms) {
  /* JDY-31 ENLOG emits unsolicited +... UART status lines. Never acknowledge
     them as car commands: an extra ERR would corrupt the next SPP response. */
  if (line[0] == '+') return;
  if (strcmp(line, "PING") == 0) {
    char pong[20];
    snprintf(pong, sizeof(pong), "PONG %u\n", (unsigned)CAR_PROTOCOL_VERSION);
    CarHw_Send(pong);
    return;
  }
  if (strcmp(line, "STATUS?") == 0) { status(); return; }
  if (strcmp(line, "LINE?") == 0) {
    CarLineDiagnostics d;
    if (!CarHw_LineDiagnostics(&d)) { CarHw_Send("ERR NOT_READY\n"); return; }
    char response[64];
    snprintf(response, sizeof(response), "LINE %u %u %u %u %lu\n",
             (unsigned)d.raw_bits, (unsigned)d.line_bits,
             (unsigned)(CAR_LINE_BLACK_LEVEL == GPIO_PIN_SET),
             (unsigned)CAR_LINE_SETTLE_US, (unsigned long)d.age_ms);
    CarHw_Send(response);
    return;
  }
  if (strcmp(line, "HW?") == 0) {
    char response[48];
    snprintf(response, sizeof(response), "HW %u %s\n", (unsigned)CarHw_Ready(), CarHw_InitStageName());
    CarHw_Send(response);
    return;
  }
  if (strncmp(line, "RANGE? ", 7U) == 0) {
    const char *sides = "LCR";
    const char *side = strchr(sides, line[7]);
    if (line[7] == '\0' || line[8] != '\0' || side == NULL) {
      CarHw_Send("ERR PARAM\n"); return;
    }
    range_status((unsigned)(side - sides));
    return;
  }
  if (strcmp(line, "PID?") == 0) { pid_status(); return; }
  if (strcmp(line, "SERVO?") == 0) { servo_status(); return; }
  if (strcmp(line, "SERVO STORE?") == 0) {
    CarHw_Send(CarServoStore_Matches(&car.servo_params) ?
               "SERVO STORE SAVED\n" : "SERVO STORE UNSAVED\n");
    return;
  }
  if (strcmp(line, "PID STORE?") == 0) {
    CarHw_Send(CarPidStore_Matches(&car.pid_params) ?
               "STORE SAVED\n" : "STORE UNSAVED\n");
    return;
  }
  if (strcmp(line, "CTRL?") == 0) { control_status(); return; }
  if (strcmp(line, "DEBUG LIMIT?") == 0) {
    char response[24];
    snprintf(response, sizeof(response), "LIMIT %u\n", (unsigned)car.debug_pwm_limit);
    CarHw_Send(response);
    return;
  }
  if (strncmp(line, "DEBUG LIMIT ", 12U) == 0) {
    if (!CarHw_Ready()) { CarHw_Send("ERR HARDWARE\n"); return; }
    uint16_t limit;
    CarHw_Send(debug_limit_value(line + 12U, &limit) &&
               CarLogic_DebugLimit(&car, limit) ? "OK\n" : "ERR STATE_OR_RANGE\n");
    return;
  }
  if (strcmp(line, "STOP") == 0 || strcmp(line, "IDLE") == 0) {
    if (CarHw_Ready()) CarLogic_Stop(&car, now_ms);
    else hardware_fault(now_ms);
    CarHw_Stop();
    CarHw_Send("OK\n");
    return;
  }
  if (!CarHw_Ready() && (strcmp(line, "AUTO ARM") == 0 || strcmp(line, "DEBUG") == 0 ||
                        strncmp(line, "DRIVE ", 6U) == 0 ||
                        strncmp(line, "SPEED ", 6U) == 0)) {
    CarHw_Send("ERR HARDWARE\n");
    return;
  }
  if (strcmp(line, "AUTO ARM") == 0) {
    CarHw_Send(CarLogic_Arm(&car, now_ms) ? "OK\n" : "ERR STATE\n");
    return;
  }
  if (strcmp(line, "DEBUG") == 0) {
    CarHw_Send(CarLogic_Debug(&car, now_ms) ? "OK\n" : "ERR STATE\n");
    return;
  }
  if (strcmp(line, "SERVO RESET") == 0) {
    if (!CarHw_Ready() || car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    CarServoParams defaults = CarServo_DefaultParams();
    servo_apply(&defaults);
    CarHw_Send("OK\n");
    return;
  }
  if (strcmp(line, "SERVO LOAD") == 0) {
    if (!CarHw_Ready() || car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    CarServoParams saved;
    if (!CarServoStore_Load(&saved)) { CarHw_Send("ERR EMPTY\n"); return; }
    servo_apply(&saved);
    CarHw_Send("OK\n");
    return;
  }
  if (strcmp(line, "SERVO SAVE") == 0) {
    if (!CarHw_Ready() || car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    CarHw_Stop();
    CarHw_Send(CarServoStore_Save(&car.servo_params) ? "OK\n" : "ERR FLASH\n");
    return;
  }
  if (strncmp(line, "SERVO SET ", 10U) == 0 || strcmp(line, "SERVO SET") == 0) {
    if (!CarHw_Ready() || car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    CarServoParams candidate;
    if (!servo_values(line + (line[9] == ' ' ? 10U : 9U), &candidate)) {
      CarHw_Send("ERR PARAM\n"); return;
    }
    servo_apply(&candidate);
    CarHw_Send("OK\n");
    return;
  }
  if (strcmp(line, "PID RESET") == 0) {
    if (car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    car.pid_params = CarPid_DefaultParams();
    CarPid_Reset(&car.pid);
    CarHw_Send("OK\n");
    return;
  }
  if (strcmp(line, "PID LOAD") == 0) {
    if (car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    CarPidParams saved;
    if (!CarPidStore_Load(&saved)) { CarHw_Send("ERR EMPTY\n"); return; }
    car.pid_params = saved;
    CarPid_Reset(&car.pid);
    CarHw_Send("OK\n");
    return;
  }
  if (strcmp(line, "PID SAVE") == 0) {
    if (car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    CarHw_Stop();
    CarHw_Send(CarPidStore_Save(&car.pid_params) ? "OK\n" : "ERR FLASH\n");
    return;
  }
  if (strncmp(line, "PID SET ", 8) == 0) {
    if (car.state != CAR_IDLE) { CarHw_Send("ERR STATE\n"); return; }
    char name[32], value_text[32], extra;
    if (sscanf(line + 8, "%31s %31s %c", name, value_text, &extra) != 2) {
      CarHw_Send("ERR PARAM\n"); return;
    }
    char *end;
    float value = strtof(value_text, &end);
    if (*end != '\0' || !CarPid_SetParam(&car.pid_params, name, value)) {
      CarHw_Send("ERR PARAM\n"); return;
    }
    CarPid_Reset(&car.pid);
    CarHw_Send("OK\n");
    return;
  }
  if (strncmp(line, "DRIVE ", 6U) == 0) {
    int16_t left, right;
    uint16_t steer;
    bool valid = drive_values(line + 6U, &left, &right, &steer);
    CarHw_Send(valid && CarLogic_DebugDrive(&car, left, right, steer, now_ms) ?
               "OK\n" : "ERR STATE_OR_RANGE\n");
    return;
  }
  if (strncmp(line, "SPEED ", 6U) == 0) {
    float left, right;
    bool valid = speed_values(line + 6U, &left, &right);
    CarHw_Send(valid && CarLogic_DebugSpeed(&car, left, right, now_ms) ?
               "OK\n" : "ERR STATE_OR_RANGE\n");
    return;
  }
  CarHw_Send("ERR COMMAND\n");
}

void CarApp_Loop(void) {
  if (!initialized) return;
  uint32_t now_ms = HAL_GetTick();
  if (CarHw_Ready()) CarHw_PollRange(now_ms);
  if (!CarHw_Ready()) hardware_fault(HAL_GetTick());
  char line[96];
  for (unsigned count = 0U; count < CAR_COMMANDS_PER_LOOP; ++count) {
    if (!CarHw_ReadLine(line, sizeof(line))) break;
    command(line, HAL_GetTick());
  }
  if (!CarHw_Ready()) return;
  now_ms = HAL_GetTick();
  if (now_ms - last_control_ms >= CAR_CONTROL_PERIOD_MS) {
    uint32_t elapsed_ms = now_ms - last_control_ms;
    last_control_ms = now_ms;
    CarHw_Snapshot(&sample);
    if (!CarHw_Ready()) { hardware_fault(HAL_GetTick()); return; }
    CarHw_EncoderDeltas(&encoder_left_delta, &encoder_right_delta);
    sample.encoder_left_delta = encoder_left_delta;
    sample.encoder_right_delta = encoder_right_delta;
    sample.dt_ms = (uint16_t)(elapsed_ms > 200U ? 200U : elapsed_ms);
    CarLogic_Tick(&car, &sample);
    CarHw_Apply(&car.output);
  }
}
