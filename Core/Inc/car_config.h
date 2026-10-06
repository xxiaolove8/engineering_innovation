#ifndef CAR_CONFIG_H
#define CAR_CONFIG_H

/* Hardware baseline: docs/2026929PINOUT.md V3.1. Bench calibration lives here. */
#define CAR_LINE_SENSOR_COUNT 8U
#define CAR_LINE_MASK ((1U << CAR_LINE_SENSOR_COUNT) - 1U)
#define CAR_LINE_SETTLE_US 500U /* Updated F103 vendor source; PDF/car example use 50 us. */
#define CAR_LINE_BLACK_LEVEL GPIO_PIN_RESET
#define CAR_CONTROL_PERIOD_MS 10U
#define CAR_COMMANDS_PER_LOOP 2U
#define CAR_UART_BAUD 9600U /* USART3 JDY-31 (AT+BAUD4) and USART1 CH340: 8N1, no flow control. */
#define CAR_PROTOCOL_VERSION 2U

/* DS3218 supports 50-330 Hz, 500-2500 us. These are startup defaults only;
 * runtime center/span calibration is stored separately from PID in Flash. */
#define CAR_SERVO_PERIOD_US 20000U
#define CAR_SERVO_CENTER_US 1500U
#define CAR_SERVO_MIN_US 1300U
#define CAR_SERVO_MAX_US 1700U
#define CAR_STEER_DIRECTION 1 /* +1: increasing pulse turns the assembled car right. */
#define CAR_MOTOR_PERIOD_TICKS 4200U /* TIM5: 84 MHz / 4200 = 20 kHz. */

/* Scan CH1..CH8 left to right; adjust this map and polarity after bench checks. */
#define CAR_LINE_ADDRESS_MAP {0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U}
#define CAR_RANGE_COUNT 3U
#define CAR_RANGE_INTERVAL_MS 60U /* L, C, R sequentially; one probe every 180 ms. */
#define CAR_RANGE_TIMEOUT_MS 30U
#define CAR_RANGE_STALE_MS 600U
#define CAR_RANGE_TRIGGER_US 12U
#define CAR_RANGE_MIN_PULSE_US 100U
#define CAR_RANGE_MAX_PULSE_US 30000U
#define CAR_DELAY_SPIN_LIMIT 100000U /* Bound waits even if TIM10 stops counting. */
#define CAR_RANGE_FAULT_MS 800U
#define CAR_OBSTACLE_MM 230U
#define CAR_FRONT_STOP_MM 90U
#define CAR_ARM_DELAY_MS 3000U
#define CAR_MAX_RACE_MS 300000U
#define CAR_MIN_FINISH_MS 10000U
#define CAR_FINISH_HOLD_MS 20U
#define CAR_LINE_LOST_MS 600U
#define CAR_DEBUG_DEADMAN_MS 500U
#define CAR_AVOID_OUT_MS 500U
#define CAR_AVOID_PASS_MS 900U
#define CAR_AVOID_IN_MS 500U
#define CAR_RECOVER_MS 2500U
#define CAR_AVOID_COOLDOWN_MS 1500U

#endif
