#include "car_hw.h"
#include "car_config.h"
#include "main.h"
#include <string.h>

extern TIM_HandleTypeDef htim1, htim3, htim4, htim5, htim10, htim11, htim13;
extern UART_HandleTypeDef huart1, huart3;

#define RX_SIZE 128U
#define TX_SIZE 512U

static CarLineDiagnostics line_diagnostics;
static uint32_t line_seen_ms;
static bool line_seen;

typedef struct {
  TIM_HandleTypeDef *timer;
  GPIO_TypeDef *trig_port;
  uint16_t trig_pin;
  GPIO_TypeDef *echo_port;
  uint16_t echo_pin;
} RangeProbe;

/* L, C, R: each timer has its own CH1. Board pins follow V3.1. */
static const RangeProbe probes[CAR_RANGE_COUNT] = {
  {&htim10, US_L_TRIG_GPIO_Port, US_L_TRIG_Pin, US_L_ECHO_GPIO_Port, US_L_ECHO_Pin},
  {&htim11, US_C_TRIG_GPIO_Port, US_C_TRIG_Pin, US_C_ECHO_GPIO_Port, US_C_ECHO_Pin},
  {&htim13, US_R_TRIG_GPIO_Port, US_R_TRIG_Pin, US_R_ECHO_GPIO_Port, US_R_ECHO_Pin}
};
typedef struct {
  UART_HandleTypeDef *uart;
  volatile uint8_t rx_data[RX_SIZE];
  volatile uint8_t rx_head, rx_tail;
  volatile bool rx_corrupt;
  uint8_t rx_byte;
  char partial[96];
  unsigned partial_length;
  bool partial_overflow, ready;
  uint8_t tx_data[TX_SIZE];
  volatile uint16_t tx_head, tx_tail;
  uint8_t tx_byte;
  volatile bool tx_active;
} UartComm;

/* Index 0 preserves the existing JDY-31 default; CH340 is an independent port. */
static UartComm comm_ports[] = {{.uart = &huart3}, {.uart = &huart1}};
#define COMM_PORT_COUNT (sizeof(comm_ports) / sizeof(comm_ports[0]))
static unsigned reply_port, next_read_port;
static volatile uint16_t range_mm[CAR_RANGE_COUNT];
static volatile uint32_t range_seen_ms[CAR_RANGE_COUNT];
static volatile bool range_seen[CAR_RANGE_COUNT];
static volatile CarRangeDiagnostics range_diagnostics[CAR_RANGE_COUNT];
static volatile bool range_completed[CAR_RANGE_COUNT];
static uint32_t range_start_ms, last_trigger_ms;
static uint16_t rise_tick, range_start_tick;
static volatile uint8_t range_side;
static uint8_t next_side;
static volatile uint8_t range_stage; /* 0 idle, 1 rising, 2 falling */
static bool timing_healthy;
static const char *init_stage = "NEVER";
static uint16_t last_encoder_left, last_encoder_right;
static CarServoParams servo_params = {CAR_SERVO_DEFAULT_CENTER_US, CAR_SERVO_DEFAULT_SPAN_US};

static uint32_t irq_lock(void) {
  uint32_t mask = __get_PRIMASK();
  __disable_irq();
  return mask;
}

static void irq_unlock(uint32_t mask) {
  if (mask == 0U) __enable_irq();
}

static bool delay_us(uint16_t microseconds) {
  uint16_t start = (uint16_t)__HAL_TIM_GET_COUNTER(&htim10);
  for (uint32_t spins = 0U; spins < CAR_DELAY_SPIN_LIMIT; ++spins) {
    if ((uint16_t)((uint16_t)__HAL_TIM_GET_COUNTER(&htim10) - start) >= microseconds)
      return true;
  }
  return false;
}

static void capture_stop(TIM_HandleTypeDef *timer) {
  HAL_TIM_IC_Stop_IT(timer, TIM_CHANNEL_1);
  /* HAL stop clears CEN; TIM10 also supplies the scanner's microsecond clock. */
  __HAL_TIM_ENABLE(timer);
}

static void range_fail(CarRangeState state, uint32_t now_ms) {
  range_diagnostics[range_side].state = state;
  range_diagnostics[range_side].flags = probes[range_side].timer->Instance->SR;
  range_seen[range_side] = false;
  range_completed[range_side] = true;
  range_seen_ms[range_side] = now_ms;
  if (range_stage != 0U) capture_stop(probes[range_side].timer);
  range_stage = 0U;
}

static void clock_failed(void) {
  uint32_t mask = irq_lock();
  timing_healthy = false;
  init_stage = "CLOCK";
  if (range_stage != 0U) capture_stop(probes[range_side].timer);
  range_stage = 0U;
  for (unsigned i = 0U; i < CAR_RANGE_COUNT; ++i) {
    range_seen[i] = false;
    range_diagnostics[i].state = CAR_RANGE_CLOCK_ERROR;
    ++range_diagnostics[i].errors;
    HAL_GPIO_WritePin(probes[i].trig_port, probes[i].trig_pin, GPIO_PIN_RESET);
  }
  CarHw_EmergencyStop();
  irq_unlock(mask);
}

bool CarHw_CommInit(void) {
  uint32_t mask = irq_lock();
  for (unsigned i = 0U; i < COMM_PORT_COUNT; ++i) {
    UartComm *comm = &comm_ports[i];
    UART_HandleTypeDef *uart = comm->uart;
    memset(comm, 0, sizeof(*comm));
    comm->uart = uart;
  }
  reply_port = next_read_port = 0U;
  irq_unlock(mask);
  bool any_ready = false;
  for (unsigned i = 0U; i < COMM_PORT_COUNT; ++i) {
    UartComm *comm = &comm_ports[i];
    comm->ready = HAL_UART_Receive_IT(comm->uart, &comm->rx_byte, 1U) == HAL_OK;
    any_ready |= comm->ready;
  }
  return any_ready;
}

bool CarHw_Ready(void) { return timing_healthy; }

const char *CarHw_InitStageName(void) { return init_stage; }

bool CarHw_SetServoParams(const CarServoParams *params) {
  if (!CarServo_ValidParams(params)) return false;
  servo_params = *params;
  CarHw_Stop();
  return true;
}

bool CarHw_Init(void) {
  static const char *const range_stages[CAR_RANGE_COUNT] = {"RANGE_L", "RANGE_C", "RANGE_R"};
  CarHw_Stop();
  line_seen = false;
  line_diagnostics = (CarLineDiagnostics){0};
  timing_healthy = false;
  range_stage = range_side = next_side = 0U;
  for (unsigned i = 0U; i < CAR_RANGE_COUNT; ++i) {
    range_seen[i] = false;
    range_completed[i] = false;
    range_mm[i] = 0U;
    range_seen_ms[i] = 0U;
    range_diagnostics[i] = (CarRangeDiagnostics){0};
    HAL_GPIO_WritePin(probes[i].trig_port, probes[i].trig_pin, GPIO_PIN_RESET);
  }
  for (unsigned i = 0U; i < CAR_RANGE_COUNT; ++i) {
    init_stage = range_stages[i];
    if (HAL_TIM_Base_Start(probes[i].timer) != HAL_OK) goto failed;
  }
  init_stage = "CLOCK";
  if (!delay_us(1U)) goto failed;
  init_stage = "SERVO_PWM";
  /* TIM1 CCR1 is preloaded. Transfer the saved center before exposing PWM. */
  htim1.Instance->EGR = TIM_EGR_UG;
  if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1) != HAL_OK) goto failed;
  init_stage = "MOTOR_L_PWM";
  if (HAL_TIM_PWM_Start(&htim5, TIM_CHANNEL_3) != HAL_OK) goto failed;
  init_stage = "MOTOR_R_PWM";
  if (HAL_TIM_PWM_Start(&htim5, TIM_CHANNEL_4) != HAL_OK) goto failed;
  init_stage = "ENCODER_L";
  if (HAL_TIM_Encoder_Start(&htim3, TIM_CHANNEL_ALL) != HAL_OK) goto failed;
  init_stage = "ENCODER_R";
  if (HAL_TIM_Encoder_Start(&htim4, TIM_CHANNEL_ALL) != HAL_OK) goto failed;
  last_encoder_left = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
  last_encoder_right = (uint16_t)__HAL_TIM_GET_COUNTER(&htim4);
  last_trigger_ms = HAL_GetTick() - CAR_RANGE_INTERVAL_MS;
  CarHw_Stop();
  timing_healthy = true;
  init_stage = "READY";
  return true;
failed:
  CarHw_Stop();
  return false;
}

void CarHw_EmergencyStop(void) {
  /* Works even before handle initialization or from a CPU fault handler. */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  GPIOC->BSRR = (uint32_t)DRV_STBY_Pin << 16U;
  GPIOC->MODER = (GPIOC->MODER & ~(3UL << 8U)) | (1UL << 8U);
  TIM5->CCR3 = TIM5->CCR4 = 0U;
  TIM1->CCR1 = servo_params.center_us;
}

void CarHw_Stop(void) {
  CarHw_EmergencyStop();
  HAL_GPIO_WritePin(GPIOC, DRV_AIN1_Pin | DRV_AIN2_Pin | DRV_BIN1_Pin | DRV_BIN2_Pin,
                    GPIO_PIN_RESET);
  if (htim1.Instance != NULL)
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, servo_params.center_us);
}

static void motor_apply(int16_t demand, uint32_t channel,
                         GPIO_TypeDef *port1, uint16_t in1,
                         GPIO_TypeDef *port2, uint16_t in2) {
  uint16_t magnitude = (uint16_t)(demand < 0 ? -(int32_t)demand : demand);
  if (magnitude > 1000U) magnitude = 1000U;
  HAL_GPIO_WritePin(port1, in1, demand > 0 ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(port2, in2, demand < 0 ? GPIO_PIN_SET : GPIO_PIN_RESET);
  uint32_t period = __HAL_TIM_GET_AUTORELOAD(&htim5) + 1U;
  __HAL_TIM_SET_COMPARE(&htim5, channel, (uint32_t)magnitude * period / 1000U);
}

void CarHw_Apply(const CarOutputs *output) {
  if (output == NULL) return;
  if (!timing_healthy) { CarHw_Stop(); return; }
  int32_t pulse = (int32_t)servo_params.center_us + CAR_STEER_DIRECTION *
                  ((int32_t)output->steer_us - (int32_t)servo_params.center_us);
  uint16_t minimum = CarServo_MinUs(&servo_params), maximum = CarServo_MaxUs(&servo_params);
  if (pulse < (int32_t)minimum) pulse = minimum;
  if (pulse > (int32_t)maximum) pulse = maximum;
  __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, (uint32_t)pulse);
  HAL_GPIO_WritePin(DRV_STBY_GPIO_Port, DRV_STBY_Pin, GPIO_PIN_RESET);
  __HAL_TIM_SET_COMPARE(&htim5, TIM_CHANNEL_3, 0U);
  __HAL_TIM_SET_COMPARE(&htim5, TIM_CHANNEL_4, 0U);
  TIM5->EGR = TIM_EGR_UG; /* Commit preload zeros before changing direction. */
  motor_apply(output->left_pwm, TIM_CHANNEL_3, DRV_AIN1_GPIO_Port, DRV_AIN1_Pin,
              DRV_AIN2_GPIO_Port, DRV_AIN2_Pin);
  motor_apply(output->right_pwm, TIM_CHANNEL_4, DRV_BIN1_GPIO_Port, DRV_BIN1_Pin,
              DRV_BIN2_GPIO_Port, DRV_BIN2_Pin);
  TIM5->EGR = TIM_EGR_UG;
  if (output->left_pwm != 0 || output->right_pwm != 0)
    HAL_GPIO_WritePin(DRV_STBY_GPIO_Port, DRV_STBY_Pin, GPIO_PIN_SET);
}

static uint8_t scan_line(void) {
  static const uint8_t addresses[CAR_LINE_SENSOR_COUNT] = CAR_LINE_ADDRESS_MAP;
  uint8_t result = 0U;
  uint8_t raw = 0U;
  for (uint8_t index = 0U; index < CAR_LINE_SENSOR_COUNT; ++index) {
    uint8_t address = addresses[index];
    HAL_GPIO_WritePin(GRAY_AD0_GPIO_Port, GRAY_AD0_Pin, (address & 1U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GRAY_AD1_GPIO_Port, GRAY_AD1_Pin, (address & 2U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GRAY_AD2_GPIO_Port, GRAY_AD2_Pin, (address & 4U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    if (!delay_us(CAR_LINE_SETTLE_US)) {
      line_seen = false;
      clock_failed();
      return 0U;
    }
    GPIO_PinState level = HAL_GPIO_ReadPin(GRAY_OUT_GPIO_Port, GRAY_OUT_Pin);
    if (level == GPIO_PIN_SET) raw |= (uint8_t)(1U << index);
    if (level == CAR_LINE_BLACK_LEVEL)
      result |= (uint8_t)(1U << index);
  }
  line_diagnostics.raw_bits = raw;
  line_diagnostics.line_bits = result;
  line_seen_ms = HAL_GetTick();
  line_seen = true;
  return result;
}

bool CarHw_LineDiagnostics(CarLineDiagnostics *diagnostics) {
  if (diagnostics == NULL || !timing_healthy || !line_seen) return false;
  *diagnostics = line_diagnostics;
  diagnostics->age_ms = HAL_GetTick() - line_seen_ms;
  return true;
}

void CarHw_PollRange(uint32_t now_ms) {
  if (!timing_healthy) return;
  uint32_t mask = irq_lock();
  const RangeProbe *probe = &probes[range_side];
  if (range_stage != 0U) {
    if (now_ms - range_start_ms >= CAR_RANGE_TIMEOUT_MS) {
      ++range_diagnostics[range_side].timeouts;
      CarRangeState reason = range_stage == 1U ? CAR_RANGE_NO_RISE : CAR_RANGE_NO_FALL;
      if ((probe->timer->Instance->CR1 & TIM_CR1_CEN) == 0U ||
          (uint16_t)__HAL_TIM_GET_COUNTER(probe->timer) == range_start_tick)
        reason = CAR_RANGE_CLOCK_ERROR;
      else if ((probe->timer->Instance->SR & (TIM_FLAG_CC1 | TIM_FLAG_CC1OF)) != 0U)
        reason = CAR_RANGE_IRQ_MISSED;
      /* No echo cannot distinguish clear space from a disconnected sensor. */
      range_fail(reason, now_ms);
    }
    irq_unlock(mask);
    return;
  }
  if (now_ms - last_trigger_ms < CAR_RANGE_INTERVAL_MS) {
    irq_unlock(mask);
    return;
  }
  range_side = next_side;
  next_side = (uint8_t)((next_side + 1U) % CAR_RANGE_COUNT);
  probe = &probes[range_side];
  last_trigger_ms = range_start_ms = now_ms;
  range_diagnostics[range_side].pulse_us = 0U;
  range_diagnostics[range_side].flags = 0U;
  if (HAL_GPIO_ReadPin(probe->echo_port, probe->echo_pin) == GPIO_PIN_SET) {
    ++range_diagnostics[range_side].errors;
    range_fail(CAR_RANGE_ECHO_HIGH, now_ms);
    irq_unlock(mask); /* Stuck HIGH is an invalid measurement, never clear space. */
    return;
  }
  __HAL_TIM_CLEAR_FLAG(probe->timer, TIM_FLAG_CC1 | TIM_FLAG_CC1OF);
  __HAL_TIM_SET_CAPTUREPOLARITY(probe->timer, TIM_CHANNEL_1, TIM_INPUTCHANNELPOLARITY_RISING);
  range_start_tick = (uint16_t)__HAL_TIM_GET_COUNTER(probe->timer);
  if (HAL_TIM_IC_Start_IT(probe->timer, TIM_CHANNEL_1) != HAL_OK) {
    ++range_diagnostics[range_side].errors;
    range_fail(CAR_RANGE_START_ERROR, now_ms);
    irq_unlock(mask);
    return;
  }
  range_stage = 1U;
  range_diagnostics[range_side].state = CAR_RANGE_WAIT_RISE;
  ++range_diagnostics[range_side].triggers;
  HAL_GPIO_WritePin(probe->trig_port, probe->trig_pin, GPIO_PIN_SET);
  bool clock_ok = delay_us(CAR_RANGE_TRIGGER_US);
  HAL_GPIO_WritePin(probe->trig_port, probe->trig_pin, GPIO_PIN_RESET);
  if (!clock_ok) clock_failed();
  irq_unlock(mask);
}

void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *htim) {
  if (range_stage == 0U || htim != probes[range_side].timer ||
      htim->Channel != HAL_TIM_ACTIVE_CHANNEL_1) return;
  uint32_t now_ms = HAL_GetTick();
  if ((htim->Instance->SR & TIM_FLAG_CC1OF) != 0U) {
    ++range_diagnostics[range_side].errors;
    range_fail(CAR_RANGE_OVERCAPTURE, now_ms);
    __HAL_TIM_CLEAR_FLAG(htim, TIM_FLAG_CC1OF);
    return;
  }
  if (now_ms - range_start_ms >= CAR_RANGE_TIMEOUT_MS) {
    ++range_diagnostics[range_side].timeouts;
    range_fail(CAR_RANGE_LATE_ECHO, now_ms);
    return;
  }
  uint16_t tick = (uint16_t)HAL_TIM_ReadCapturedValue(htim, TIM_CHANNEL_1);
  if (range_stage == 1U) {
    ++range_diagnostics[range_side].rises;
    rise_tick = tick;
    range_stage = 2U;
    range_diagnostics[range_side].state = CAR_RANGE_WAIT_FALL;
    __HAL_TIM_SET_CAPTUREPOLARITY(htim, TIM_CHANNEL_1, TIM_INPUTCHANNELPOLARITY_FALLING);
  } else {
    uint16_t pulse_us = (uint16_t)(tick - rise_tick);
    ++range_diagnostics[range_side].falls;
    range_diagnostics[range_side].pulse_us = pulse_us;
    if (pulse_us < CAR_RANGE_MIN_PULSE_US || pulse_us > CAR_RANGE_MAX_PULSE_US) {
      ++range_diagnostics[range_side].errors;
      range_fail(CAR_RANGE_BAD_PULSE, now_ms);
      return;
    }
    range_mm[range_side] = (uint16_t)((uint32_t)pulse_us * 343U / 2000U);
    range_seen_ms[range_side] = now_ms;
    range_seen[range_side] = range_completed[range_side] = true;
    range_diagnostics[range_side].state = CAR_RANGE_OK;
    range_stage = 0U;
    capture_stop(htim);
  }
}

bool CarHw_RangeDiagnostics(unsigned side, CarRangeDiagnostics *diagnostics) {
  if (side >= CAR_RANGE_COUNT || diagnostics == NULL) return false;
  uint32_t mask = irq_lock();
  *diagnostics = range_diagnostics[side];
  uint32_t age = HAL_GetTick() - range_seen_ms[side];
  diagnostics->valid = range_seen[side] && age <= CAR_RANGE_STALE_MS;
  diagnostics->age_ms = range_completed[side] ? age : UINT32_MAX;
  diagnostics->distance_mm = range_mm[side];
  diagnostics->echo_high = HAL_GPIO_ReadPin(probes[side].echo_port, probes[side].echo_pin) == GPIO_PIN_SET;
  diagnostics->counter = (uint16_t)__HAL_TIM_GET_COUNTER(probes[side].timer);
  diagnostics->prescaler = (uint16_t)probes[side].timer->Instance->PSC;
  diagnostics->flags |= probes[side].timer->Instance->SR;
  diagnostics->timer_running = (probes[side].timer->Instance->CR1 & TIM_CR1_CEN) != 0U;
  irq_unlock(mask);
  return true;
}

const char *CarHw_RangeStateName(CarRangeState state) {
  static const char *const names[] = {
    "NEVER", "WAIT_RISE", "WAIT_FALL", "OK", "NO_RISE", "NO_FALL", "ECHO_HIGH",
    "START_ERROR", "BAD_PULSE", "OVERCAPTURE", "CLOCK_ERROR", "LATE_ECHO", "IRQ_MISSED"
  };
  return (unsigned)state < sizeof(names) / sizeof(names[0]) ? names[state] : "UNKNOWN";
}

void CarHw_Snapshot(CarInputs *input) {
  if (input == NULL) return;
  input->line_bits = scan_line();
  uint32_t mask = irq_lock();
  uint32_t now_ms = HAL_GetTick(); /* Capture timestamps may advance during scanning. */
  input->now_ms = now_ms;
  input->left_mm = range_mm[0];
  input->center_mm = range_mm[1];
  input->right_mm = range_mm[2];
  input->left_valid = range_seen[0] && now_ms - range_seen_ms[0] <= CAR_RANGE_STALE_MS;
  input->center_valid = range_seen[1] && now_ms - range_seen_ms[1] <= CAR_RANGE_STALE_MS;
  input->right_valid = range_seen[2] && now_ms - range_seen_ms[2] <= CAR_RANGE_STALE_MS;
  irq_unlock(mask);
}

void CarHw_EncoderDeltas(int32_t *left, int32_t *right) {
  uint16_t current_left = (uint16_t)__HAL_TIM_GET_COUNTER(&htim3);
  uint16_t current_right = (uint16_t)__HAL_TIM_GET_COUNTER(&htim4);
  if (left != NULL) *left = (int16_t)(current_left - last_encoder_left);
  if (right != NULL) *right = (int16_t)(current_right - last_encoder_right);
  last_encoder_left = current_left;
  last_encoder_right = current_right;
}

static UartComm *comm_for_uart(UART_HandleTypeDef *uart) {
  for (unsigned i = 0U; i < COMM_PORT_COUNT; ++i)
    if (comm_ports[i].uart == uart) return &comm_ports[i];
  return NULL;
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
  UartComm *comm = comm_for_uart(huart);
  if (comm == NULL) return;
  uint8_t next = (uint8_t)((comm->rx_head + 1U) % RX_SIZE);
  if (next != comm->rx_tail) {
    comm->rx_data[comm->rx_head] = comm->rx_byte;
    comm->rx_head = next;
  } else comm->rx_corrupt = true;
  HAL_UART_Receive_IT(comm->uart, &comm->rx_byte, 1U);
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart) {
  UartComm *comm = comm_for_uart(huart);
  if (comm == NULL) return;
  comm->rx_corrupt = true;
  HAL_UART_Receive_IT(comm->uart, &comm->rx_byte, 1U);
}

static void tx_kick(UartComm *comm) {
  if (!comm->ready || comm->tx_active || comm->tx_tail == comm->tx_head) return;
  comm->tx_byte = comm->tx_data[comm->tx_tail];
  comm->tx_active = true;
  if (HAL_UART_Transmit_IT(comm->uart, &comm->tx_byte, 1U) != HAL_OK) comm->tx_active = false;
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart) {
  UartComm *comm = comm_for_uart(huart);
  if (comm == NULL || !comm->tx_active) return;
  comm->tx_tail = (uint16_t)((comm->tx_tail + 1U) % TX_SIZE);
  comm->tx_active = false;
  tx_kick(comm);
}

static bool read_port_line(UartComm *comm, char *destination, unsigned capacity) {
  if (!comm->ready) return false;
  uint32_t mask = irq_lock();
  if (comm->rx_corrupt) {
    comm->rx_tail = comm->rx_head;
    comm->rx_corrupt = false;
    comm->partial_length = 0U;
    comm->partial_overflow = true; /* Discard through next newline after a dropped byte. */
  }
  irq_unlock(mask);
  while (comm->rx_tail != comm->rx_head) {
    uint8_t byte = comm->rx_data[comm->rx_tail];
    comm->rx_tail = (uint8_t)((comm->rx_tail + 1U) % RX_SIZE);
    if (byte == '\r') continue;
    if (byte == '\n') {
      if (!comm->partial_overflow && comm->partial_length > 0U && comm->partial_length + 1U <= capacity) {
        mask = irq_lock();
        if (comm->rx_corrupt) {
          comm->rx_tail = comm->rx_head;
          comm->rx_corrupt = false;
          comm->partial_length = 0U;
          comm->partial_overflow = true;
          irq_unlock(mask);
          return false;
        }
        memcpy(destination, comm->partial, comm->partial_length);
        destination[comm->partial_length] = '\0';
        comm->partial_length = 0U;
        irq_unlock(mask);
        return true;
      }
      comm->partial_length = 0U;
      comm->partial_overflow = false;
      continue;
    }
    /* The protocol is ASCII text. In particular, an embedded NUL must not let
       strcmp/strtol execute a valid command prefix from a corrupted frame. */
    if ((byte < 0x20U && byte != '\t') || byte > 0x7EU) comm->partial_overflow = true;
    else if (comm->partial_length + 1U < sizeof(comm->partial) && !comm->partial_overflow)
      comm->partial[comm->partial_length++] = (char)byte;
    else comm->partial_overflow = true;
  }
  return false;
}

bool CarHw_ReadLine(char *destination, unsigned capacity) {
  if (destination == NULL || capacity == 0U) return false;
  uint32_t mask = irq_lock();
  for (unsigned i = 0U; i < COMM_PORT_COUNT; ++i) tx_kick(&comm_ports[i]);
  irq_unlock(mask);
  for (unsigned offset = 0U; offset < COMM_PORT_COUNT; ++offset) {
    unsigned index = (next_read_port + offset) % COMM_PORT_COUNT;
    if (read_port_line(&comm_ports[index], destination, capacity)) {
      reply_port = index;
      next_read_port = (index + 1U) % COMM_PORT_COUNT;
      return true;
    }
  }
  return false;
}

void CarHw_Send(const char *message) {
  if (message == NULL) return;
  size_t count = strlen(message);
  if (count == 0U || count > 160U) return;
  UartComm *comm = &comm_ports[reply_port];
  if (!comm->ready) return;
  uint32_t mask = irq_lock();
  uint16_t used = (uint16_t)((comm->tx_head + TX_SIZE - comm->tx_tail) % TX_SIZE);
  if (count <= (TX_SIZE - 1U - used)) {
    for (size_t i = 0; i < count; ++i) {
      comm->tx_data[comm->tx_head] = (uint8_t)message[i];
      comm->tx_head = (uint16_t)((comm->tx_head + 1U) % TX_SIZE);
    }
    tx_kick(comm);
  }
  irq_unlock(mask);
}
