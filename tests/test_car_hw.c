#include "car_hw.h"
#include "car_app.h"
#include "car_config.h"
#include "car_pid_store.h"
#include "main.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

GPIO_TypeDef gpio_a, gpio_b, gpio_c, gpio_e, gpio_f, gpio_g;
TIM_TypeDef tim1, tim3, tim4, tim5, tim10, tim11, tim13;
TIM_HandleTypeDef htim1={.Instance=TIM1}, htim3={.Instance=TIM3};
TIM_HandleTypeDef htim4={.Instance=TIM4}, htim5={.Instance=TIM5};
TIM_HandleTypeDef htim10={.Instance=TIM10,.Channel=1}, htim11={.Instance=TIM11,.Channel=1};
TIM_HandleTypeDef htim13={.Instance=TIM13,.Channel=1};
UART_HandleTypeDef huart1, huart3;
static uint32_t now_ms, irq_mask, last_address_tick;
static uint8_t *rx_byte, *tx_byte, *usb_rx_byte, *usb_tx_byte;
static uint8_t black_bits=0xa5;
static unsigned line_reads, triggers[3];
static TIM_HandleTypeDef *capture;
static bool clock_frozen, capture_start_error;
typedef enum { START_NONE, START_BASE, START_PWM, START_ENCODER } StartFailure;
static StartFailure start_failure;
static TIM_HandleTypeDef *failed_timer;
static uint32_t failed_channel;
static bool uart_receive_error;
static UART_HandleTypeDef *uart_failed_port;
static CarServoParams saved_servo;
static bool servo_store_valid, servo_save_ok=true;
static uint32_t servo_start_pulse;
void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *timer);
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart);
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *uart);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart);

uint32_t FakeCounter(TIM_HandleTypeDef *timer) {
  if (timer == &htim10 && (timer->Instance->CR1 & TIM_CR1_CEN) && !clock_frozen)
    timer->Instance->CNT = (uint16_t)(timer->Instance->CNT + 1U);
  return timer->Instance->CNT;
}
void FakeCompare(TIM_HandleTypeDef *timer, uint32_t channel, uint32_t value) {
  if (channel == TIM_CHANNEL_1) timer->Instance->CCR1=value;
  else if (channel == TIM_CHANNEL_3) timer->Instance->CCR3=value;
  else if (channel == TIM_CHANNEL_4) timer->Instance->CCR4=value;
  else assert(0);
}
uint32_t __get_PRIMASK(void) { return irq_mask; }
void __disable_irq(void) { irq_mask=1U; }
void __enable_irq(void) { irq_mask=0U; }
uint32_t HAL_GetTick(void) { return now_ms; }
HAL_StatusTypeDef HAL_TIM_Base_Start(TIM_HandleTypeDef *timer) {
  if ((start_failure==START_BASE && timer==failed_timer) || timer->base_started) return HAL_ERROR;
  timer->base_started=1U;
  timer->Instance->CR1 |= TIM_CR1_CEN;
  return HAL_OK;
}
HAL_StatusTypeDef HAL_TIM_PWM_Start(TIM_HandleTypeDef *timer, uint32_t channel) {
  assert((timer==&htim1 && channel==TIM_CHANNEL_1) ||
         (timer==&htim5 && (channel==TIM_CHANNEL_3 || channel==TIM_CHANNEL_4)));
  uint32_t bit=1U<<(channel/4U);
  if ((start_failure==START_PWM && timer==failed_timer && channel==failed_channel) ||
      (timer->started_channels & bit)) return HAL_ERROR;
  timer->started_channels |= bit;
  if (timer==&htim1) {
    servo_start_pulse=timer->Instance->CCR1;
    assert(timer->Instance->EGR & TIM_EGR_UG);
  }
  return HAL_OK;
}
HAL_StatusTypeDef HAL_TIM_Encoder_Start(TIM_HandleTypeDef *timer, uint32_t channel) {
  assert((timer==&htim3 || timer==&htim4) && channel==TIM_CHANNEL_ALL);
  if ((start_failure==START_ENCODER && timer==failed_timer) || (timer->started_channels & 3U))
    return HAL_ERROR;
  timer->started_channels |= 3U;
  return HAL_OK;
}
HAL_StatusTypeDef HAL_TIM_IC_Start_IT(TIM_HandleTypeDef *timer, uint32_t channel) {
  assert(channel==TIM_CHANNEL_1 && capture==NULL);
  if (capture_start_error) return HAL_ERROR;
  capture=timer; return HAL_OK;
}
HAL_StatusTypeDef HAL_TIM_IC_Stop_IT(TIM_HandleTypeDef *timer, uint32_t channel) {
  assert(channel==TIM_CHANNEL_1 && timer==capture);
  timer->Instance->CR1 &= ~TIM_CR1_CEN; capture=NULL; return HAL_OK;
}
uint32_t HAL_TIM_ReadCapturedValue(TIM_HandleTypeDef *timer, uint32_t channel) {
  assert(channel==TIM_CHANNEL_1); return timer->Instance->CCR1;
}
void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pins, GPIO_PinState state) {
  if (state==GPIO_PIN_SET) port->ODR |= pins;
  else port->ODR &= ~pins;
  if (port==GPIOF) last_address_tick=tim10.CNT;
  if (port==GPIOA && state==GPIO_PIN_SET) {
    if (pins==US_L_TRIG_Pin) ++triggers[0];
    else if (pins==US_C_TRIG_Pin) ++triggers[1];
    else if (pins==US_R_TRIG_Pin) ++triggers[2];
  }
}
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pins) {
  if (port==GPIOC && pins==GRAY_OUT_Pin) {
    assert((uint16_t)(tim10.CNT-last_address_tick)>=500U); /* Updated vendor F103 source. */
    ++line_reads;
    return black_bits & (1U<<(gpio_f.ODR&7U)) ? GPIO_PIN_RESET : GPIO_PIN_SET;
  }
  assert(port==GPIOF && (pins==US_L_ECHO_Pin || pins==US_C_ECHO_Pin || pins==US_R_ECHO_Pin));
  return port->IDR & pins ? GPIO_PIN_SET : GPIO_PIN_RESET;
}
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *uart, uint8_t *byte, uint16_t count) {
  assert((uart==&huart3 || uart==&huart1) && count==1U);
  if (uart_receive_error || uart==uart_failed_port) return HAL_ERROR;
  if (uart->rx_busy) return HAL_BUSY;
  uart->rx_busy=1U;
  if (uart==&huart3) rx_byte=byte;
  else usb_rx_byte=byte;
  return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *uart, uint8_t *byte, uint16_t count) {
  assert((uart==&huart3 || uart==&huart1) && count==1U);
  if (uart==&huart3) { assert(tx_byte==NULL); tx_byte=byte; }
  else { assert(usb_tx_byte==NULL); usb_tx_byte=byte; }
  return HAL_OK;
}
bool CarPidStore_Load(CarPidParams *params) { (void)params; return false; }
bool CarPidStore_Save(const CarPidParams *params) { (void)params; return true; }
bool CarPidStore_Matches(const CarPidParams *params) { (void)params; return false; }
bool CarServoStore_Load(CarServoParams *params) {
  if (!servo_store_valid || !CarServo_ValidParams(&saved_servo)) return false;
  *params=saved_servo;
  return true;
}
bool CarServoStore_Save(const CarServoParams *params) {
  if (!servo_save_ok || !CarServo_ValidParams(params)) return false;
  saved_servo=*params;
  servo_store_valid=true;
  return true;
}
bool CarServoStore_Matches(const CarServoParams *params) {
  return servo_store_valid && params->center_us==saved_servo.center_us &&
         params->span_us==saved_servo.span_us;
}

static void feed_port(UART_HandleTypeDef *uart, const char *text) {
  uint8_t *byte = uart==&huart3 ? rx_byte : usb_rx_byte;
  while (*text) {
    assert(byte!=NULL && uart->rx_busy);
    *byte=(uint8_t)*text++;
    uart->rx_busy=0U; /* HAL marks the one-byte receive ready before its callback. */
    HAL_UART_RxCpltCallback(uart);
  }
}
static void feed(const char *text) { feed_port(&huart3,text); }
static void feed_bytes(const uint8_t *bytes, unsigned count) {
  for (unsigned i=0U; i<count; ++i) {
    assert(rx_byte!=NULL && huart3.rx_busy);
    *rx_byte=bytes[i];
    huart3.rx_busy=0U;
    HAL_UART_RxCpltCallback(&huart3);
  }
}
static void drain_port(UART_HandleTypeDef *uart, char *out) {
  uint8_t **byte = uart==&huart3 ? &tx_byte : &usb_tx_byte;
  unsigned i=0;
  while (*byte) {
    out[i++]=(char)**byte;
    *byte=NULL;
    HAL_UART_TxCpltCallback(uart);
    assert(i<512U);
  }
  out[i]='\0';
}
static void drain(char *out) { drain_port(&huart3,out); }
static void echo(TIM_HandleTypeDef *timer, uint16_t start, uint16_t width) {
  timer->Instance->CCR1=start;
  HAL_TIM_IC_CaptureCallback(timer);
  assert(timer->Instance->polarity==TIM_INPUTCHANNELPOLARITY_FALLING);
  timer->Instance->CCR1=(uint16_t)(start+width);
  HAL_TIM_IC_CaptureCallback(timer);
  assert(timer->Instance->CR1 & TIM_CR1_CEN);
}

static void set_time(uint32_t time) {
  uint32_t elapsed = time - now_ms;
  TIM_TypeDef *timers[] = {TIM10, TIM11, TIM13};
  for (unsigned i=0U; i<3U; ++i)
    if ((timers[i]->CR1 & TIM_CR1_CEN) && !clock_frozen)
      timers[i]->CNT = (uint16_t)(timers[i]->CNT + elapsed * 1000U);
  now_ms = time;
}

static void board_reset(void) {
  TIM_HandleTypeDef *timers[]={&htim1,&htim3,&htim4,&htim5,&htim10,&htim11,&htim13};
  for (unsigned i=0U;i<sizeof(timers)/sizeof(timers[0]);++i) {
    memset(timers[i]->Instance,0,sizeof(*timers[i]->Instance));
    timers[i]->base_started=timers[i]->started_channels=0U;
  }
  memset(&gpio_a,0,sizeof(gpio_a));
  memset(&gpio_c,0,sizeof(gpio_c));
  memset(&gpio_f,0,sizeof(gpio_f));
  memset(triggers,0,sizeof(triggers));
  tim5.ARR=CAR_MOTOR_PERIOD_TICKS-1U;
  tim10.PSC=tim11.PSC=167U; tim13.PSC=83U;
  huart1.rx_busy=huart3.rx_busy=0U;
  rx_byte=tx_byte=usb_rx_byte=usb_tx_byte=NULL;
  capture=NULL;
  now_ms=irq_mask=line_reads=last_address_tick=0U;
  clock_frozen=capture_start_error=uart_receive_error=false;
  uart_failed_port=NULL;
  start_failure=START_NONE;
  failed_timer=NULL;
  failed_channel=0U;
}

static void request(const char *command, char *response) {
  feed(command);
  CarApp_Loop();
  drain(response);
}

static void hardware_failure_remains_diagnosable(const char *stage) {
  char response[512], expected[48];
  assert(CarApp_Init()); /* The UART is initialized even though an actuator failed. */
  assert(!CarHw_Ready() && strcmp(CarHw_InitStageName(),stage)==0);
  assert(huart3.rx_busy);
  request("PING\n",response); assert(strcmp(response,"PONG 2\n")==0);
  request("STATUS?\n",response); assert(strncmp(response,"STAT FAULT 6 0 -1 -1 -1 ",23U)==0);
  snprintf(expected,sizeof(expected),"HW 0 %s\n",stage);
  request("HW?\n",response); assert(strcmp(response,expected)==0);
  request("AUTO ARM\n",response); assert(strcmp(response,"ERR HARDWARE\n")==0);
  request("DEBUG\n",response); assert(strcmp(response,"ERR HARDWARE\n")==0);
  request("DRIVE 100 100 1500\n",response); assert(strcmp(response,"ERR HARDWARE\n")==0);
  request("SPEED 20 20\n",response); assert(strcmp(response,"ERR HARDWARE\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"ERR HARDWARE\n")==0);
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 300\n")==0);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);
  request("STATUS?\n",response); assert(strncmp(response,"STAT FAULT 6 ",13U)==0);
  request("IDLE\n",response); assert(strcmp(response,"OK\n")==0);
  request("STATUS?\n",response); assert(strncmp(response,"STAT FAULT 6 ",13U)==0);
  request("PID?\n",response); assert(strncmp(response,"PID ",4U)==0);
  request("LINE?\n",response); assert(strcmp(response,"ERR NOT_READY\n")==0);
  request("PID RESET\n",response); assert(strcmp(response,"ERR STATE\n")==0);
  set_time(CAR_CONTROL_PERIOD_MS+1U);
  CarApp_Loop();
  assert(line_reads==0U && triggers[0]==0U && triggers[1]==0U && triggers[2]==0U);
  assert(tim5.CCR3==0U && tim5.CCR4==0U);
  assert(!(gpio_c.ODR & DRV_STBY_Pin));
  assert(irq_mask==0U);
  CarApp_EmergencyStop();
  request("STATUS?\n",response); assert(strncmp(response,"STAT FAULT 6 ",13U)==0);
}

static void debug_speed_protocol(void) {
  char response[512];
  board_reset();
  assert(CarApp_Init());
  request("SPEED 20 20\n",response);
  assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  const char *invalid[] = {
    "SPEED nan 20\n", "SPEED 20 NaN\n", "SPEED inf 20\n",
    "SPEED 20 -inf\n", "SPEED 1e40 20\n", "SPEED 20 1e-80\n",
    "SPEED -1 20\n", "SPEED 20 501\n", "SPEED 20 20 extra\n",
    "SPEED 1+2\n", "SPEED 20\n", "SPEED 20 20x\n",
    "SPEED 0x1p4 20\n", "SPEED 20 0x1p4\n", "SPEED 2_0 20\n"
  };
  for (unsigned i=0U; i<sizeof(invalid)/sizeof(invalid[0]); ++i) {
    request(invalid[i],response);
    assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  }
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  request("SPEED 2.05e1 +19.25  \n",response);
  assert(strcmp(response,"OK\n")==0);
  tim3.CNT=12U; tim4.CNT=(uint16_t)-18;
  set_time(20U); CarApp_Loop();
  request("CTRL?\n",response);
  assert(strcmp(response,"CTRL 0.00 6.00 9.00 20.50 19.25 300 272 1500\n")==0);
  assert(tim5.CCR3 <= 1260U && tim5.CCR4 <= 1260U);
  /* PID edits/storage remain forbidden while the speed bench is active. */
  request("PID SET speed_kp 4\n",response); assert(strcmp(response,"ERR STATE\n")==0);
  request("PID SAVE\n",response); assert(strcmp(response,"ERR STATE\n")==0);
  request("PID RESET\n",response); assert(strcmp(response,"ERR STATE\n")==0);
  request("PID LOAD\n",response); assert(strcmp(response,"ERR STATE\n")==0);
  for (uint32_t now=200U; now<=800U; now+=200U) {
    set_time(now);
    request("SPEED 20.5 19.25\n",response); assert(strcmp(response,"OK\n")==0);
    assert(tim5.CCR3 > 0U && tim5.CCR4 > 0U);
  }
  set_time(1299U); CarApp_Loop();
  assert(tim5.CCR3 > 0U && tim5.CCR4 > 0U);
  set_time(1300U); CarApp_Loop();
  /* 1 ms does not schedule a control tick; the next tick must stop. */
  set_time(1309U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  request("CTRL?\n",response);
  assert(strcmp(response,"CTRL 0.00 0.00 0.00 0.00 0.00 0 0 1500\n")==0);
  set_time(1400U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);

  request("SPEED 20 20\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(1410U); CarApp_Loop();
  assert(tim5.CCR3 > 0U && tim5.CCR4 > 0U);
  request("SPEED 0 0\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(1420U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  request("SPEED 20 20\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(1430U); CarApp_Loop();
  request("DRIVE -100 120 1600\n",response); assert(strcmp(response,"OK\n")==0);
  tim3.CNT=(uint16_t)(tim3.CNT-8U); tim4.CNT=(uint16_t)(tim4.CNT+11U);
  set_time(1440U); CarApp_Loop();
  request("CTRL?\n",response);
  assert(strcmp(response,"CTRL 0.00 8.00 11.00 0.00 0.00 -100 120 1600\n")==0);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);
  request("SPEED 20 20\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  set_time(1450U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  request("AUTO ARM\n",response); assert(strcmp(response,"OK\n")==0);
  request("SPEED 20 20\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);
}

static void debug_limit_protocol(void) {
  char response[512];
  board_reset();
  assert(CarApp_Init());
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 300\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  request("DRIVE 1000 0 1500\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  const char *invalid[] = {
    "DEBUG LIMIT 0\n", "DEBUG LIMIT -1\n", "DEBUG LIMIT 1001\n",
    "DEBUG LIMIT 4294968296\n", "DEBUG LIMIT 1.5\n", "DEBUG LIMIT 1e3\n",
    "DEBUG LIMIT nan\n", "DEBUG LIMIT 0x3e8\n", "DEBUG LIMIT 1000 extra\n",
    "DEBUG LIMIT 1000x\n", "DEBUG LIMIT \n"
  };
  for (unsigned i=0U; i<sizeof(invalid)/sizeof(invalid[0]); ++i) {
    request(invalid[i],response);
    assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  }
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 1000\n")==0);
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U); /* Unlock cannot start motors. */
  set_time(1000U); CarApp_Loop();
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 1000\n")==0);
  request("DRIVE 1001 0 1500\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DRIVE 1000 -1000 1500\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(1010U); CarApp_Loop();
  assert(tim5.CCR3 == 4200U && tim5.CCR4 == 4200U);
  request("DEBUG LIMIT 300\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DRIVE 0 0 1500\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(1020U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  set_time(2000U); CarApp_Loop();
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 1000\n")==0);
  request("SPEED 500 0\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT 300\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  set_time(2010U); CarApp_Loop();
  assert(tim5.CCR3 == 4200U && tim5.CCR4 == 0U);
  request("SPEED 0 0\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT 800\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(2020U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  request("DRIVE 800 0 1500\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(2030U); CarApp_Loop();
  assert(tim5.CCR3 == 3360U);
  /* Read-only queries and rejected limit edits do not extend motion. */
  set_time(2510U);
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 800\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  assert(tim5.CCR3 == 3360U);
  set_time(2520U); CarApp_Loop();
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 300\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"OK\n")==0);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 300\n")==0);
  request("AUTO ARM\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"OK\n")==0);
  clock_frozen=true;
  set_time(2530U); CarApp_Loop();
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 300\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"ERR HARDWARE\n")==0);
  assert(tim5.CCR3 == 0U && tim5.CCR4 == 0U);
}

static void dual_uart_protocol(void) {
  char bluetooth[512], usb[512], line[96];
  board_reset();
  assert(CarApp_Init() && huart1.rx_busy && huart3.rx_busy);
  CarHw_Send("OK\n"); /* Existing callers default to USART3 until a command is read. */
  drain(bluetooth); drain_port(&huart1,usb);
  assert(strcmp(bluetooth,"OK\n")==0 && usb[0]=='\0');

  feed("PI"); feed_port(&huart1,"HW?");
  assert(!CarHw_ReadLine(line,sizeof(line)));
  feed("NG\r\n"); feed_port(&huart1,"\n");
  CarApp_Loop();
  drain(bluetooth); drain_port(&huart1,usb);
  assert(strcmp(bluetooth,"PONG 2\n")==0 && strcmp(usb,"HW 1 READY\n")==0);

  /* A backlog on either UART cannot consume both command slots every loop. */
  feed("PING\nSTATUS?\nPING\n"); feed_port(&huart1,"HW?\nPING\n");
  CarApp_Loop(); drain(bluetooth); drain_port(&huart1,usb);
  assert(strcmp(bluetooth,"PONG 2\n")==0 && strcmp(usb,"HW 1 READY\n")==0);
  CarApp_Loop(); drain(bluetooth); drain_port(&huart1,usb);
  assert(strncmp(bluetooth,"STAT IDLE 0 ",12U)==0 && strcmp(usb,"PONG 2\n")==0);
  CarApp_Loop(); drain(bluetooth); drain_port(&huart1,usb);
  assert(strcmp(bluetooth,"PONG 2\n")==0 && usb[0]=='\0');

  /* Both transmitters may be in flight; bytes and completion callbacks are separate. */
  feed("PING\n"); CarApp_Loop();
  assert(tx_byte!=NULL && usb_tx_byte==NULL);
  feed_port(&huart1,"HW?\n"); CarApp_Loop();
  assert(tx_byte!=NULL && usb_tx_byte!=NULL && tx_byte!=usb_tx_byte);
  drain_port(&huart1,usb); drain(bluetooth);
  assert(strcmp(usb,"HW 1 READY\n")==0 && strcmp(bluetooth,"PONG 2\n")==0);

  /* An error invalidates only that port's partial frame and receive buffer. */
  feed("PI"); feed_port(&huart1,"AU");
  assert(!CarHw_ReadLine(line,sizeof(line)));
  huart1.rx_busy=0U;
  HAL_UART_ErrorCallback(&huart1);
  assert(huart1.rx_busy && !CarHw_ReadLine(line,sizeof(line)));
  feed_port(&huart1,"TO ARM\n"); feed("NG\n");
  CarApp_Loop(); drain(bluetooth); drain_port(&huart1,usb);
  assert(strcmp(bluetooth,"PONG 2\n")==0 && usb[0]=='\0');
  feed_port(&huart1,"STATUS?\n"); CarApp_Loop(); drain_port(&huart1,usb);
  assert(strncmp(usb,"STAT IDLE 0 ",12U)==0);

  for (unsigned i=0U; i<140U; ++i) feed_port(&huart1,"X");
  feed("PING\n"); CarApp_Loop(); drain(bluetooth); drain_port(&huart1,usb);
  assert(strcmp(bluetooth,"PONG 2\n")==0 && usb[0]=='\0');
  feed_port(&huart1,"AUTO ARM\nPING\n"); CarApp_Loop(); drain_port(&huart1,usb);
  assert(strcmp(usb,"PONG 2\n")==0); /* Discard through newline, then recover. */

  /* Initial receive failure on one link does not disable the other link. */
  board_reset(); uart_failed_port=&huart1;
  assert(CarApp_Init() && huart3.rx_busy && !huart1.rx_busy);
  request("PING\n",bluetooth); assert(strcmp(bluetooth,"PONG 2\n")==0);
  drain_port(&huart1,usb); assert(usb[0]=='\0');
  board_reset(); uart_failed_port=&huart3;
  assert(CarApp_Init() && huart1.rx_busy && !huart3.rx_busy);
  feed_port(&huart1,"PING\nHW?\n"); CarApp_Loop(); drain_port(&huart1,usb);
  assert(strcmp(usb,"PONG 2\nHW 1 READY\n")==0);
  drain(bluetooth); assert(bluetooth[0]=='\0');

  board_reset(); clock_frozen=true;
  assert(CarApp_Init() && !CarHw_Ready());
  feed_port(&huart1,"PING\nHW?\n"); CarApp_Loop(); drain_port(&huart1,usb);
  assert(strcmp(usb,"PONG 2\nHW 0 CLOCK\n")==0);
  UART_HandleTypeDef unknown_uart={0};
  HAL_UART_RxCpltCallback(&unknown_uart);
  HAL_UART_ErrorCallback(&unknown_uart);
  HAL_UART_TxCpltCallback(&unknown_uart);
  assert(irq_mask==0U);
}

static void servo_protocol(void) {
  char response[512];
  servo_store_valid=false;
  servo_save_ok=true;
  board_reset();
  assert(CarApp_Init() && servo_start_pulse==1500U);
  request("SERVO?\n",response); assert(strcmp(response,"SERVO 1500 200\n")==0);
  request("SERVO STORE?\n",response); assert(strcmp(response,"SERVO STORE UNSAVED\n")==0);
  request("SERVO LOAD\n",response); assert(strcmp(response,"ERR EMPTY\n")==0);
  const char *invalid[]={
    "SERVO SET\n", "SERVO SET 1500\n", "SERVO SET 499 0\n",
    "SERVO SET 2501 0\n", "SERVO SET 500 1\n", "SERVO SET 2500 1\n",
    "SERVO SET 1500 1001\n", "SERVO SET 1600 901\n", "SERVO SET 1500 -1\n",
    "SERVO SET 1500 1.5\n", "SERVO SET 1e3 200\n", "SERVO SET nan 200\n",
    "SERVO SET 0x5dc 200\n", "SERVO SET 4294968796 200\n",
    "SERVO SET 1500 65536\n", "SERVO SET 1500 200x\n", "SERVO SET 1500 200 extra\n",
    "SERVO SET 1500+200\n"
  };
  for (unsigned i=0U; i<sizeof(invalid)/sizeof(invalid[0]); ++i) {
    request(invalid[i],response); assert(strcmp(response,"ERR PARAM\n")==0);
    assert(tim1.CCR1==1500U);
    request("SERVO?\n",response); assert(strcmp(response,"SERVO 1500 200\n")==0);
  }
  request("SERVO SET 1600 100\n",response); assert(strcmp(response,"OK\n")==0);
  assert(tim1.CCR1==1600U && tim5.CCR3==0U && tim5.CCR4==0U);
  request("SERVO?\n",response); assert(strcmp(response,"SERVO 1600 100\n")==0);
  request("CTRL?\n",response); assert(strstr(response," 0 0 1600\n")!=NULL);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  const char *mutations[]={"SERVO SET 1500 200\n","SERVO SAVE\n","SERVO LOAD\n","SERVO RESET\n"};
  for (unsigned i=0U; i<sizeof(mutations)/sizeof(mutations[0]); ++i) {
    request(mutations[i],response); assert(strcmp(response,"ERR STATE\n")==0);
  }
  request("DRIVE 0 0 1499\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DRIVE 0 0 1701\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DRIVE 100 100 1700\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(10U); CarApp_Loop(); assert(tim1.CCR1==1700U);
  set_time(500U); CarApp_Loop(); assert(tim1.CCR1==1600U && tim5.CCR3==0U);
  request("DRIVE 0 0 1500\n",response); assert(strcmp(response,"OK\n")==0);
  request("SPEED 20 20\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(510U); CarApp_Loop(); assert(tim1.CCR1==1600U);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0 && tim1.CCR1==1600U);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG LIMIT 1000\n",response); assert(strcmp(response,"OK\n")==0);
  request("DRIVE 0 0 1700\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(520U); CarApp_Loop(); assert(tim1.CCR1==1700U);
  set_time(1000U); CarApp_Loop(); assert(tim1.CCR1==1700U);
  set_time(1010U); CarApp_Loop(); assert(tim1.CCR1==1600U);
  request("DEBUG LIMIT?\n",response); assert(strcmp(response,"LIMIT 300\n")==0);
  request("CTRL?\n",response); assert(strstr(response,"0.00 0.00 0 0 1600\n")!=NULL);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);
  request("SERVO SAVE\n",response); assert(strcmp(response,"OK\n")==0);
  request("SERVO STORE?\n",response); assert(strcmp(response,"SERVO STORE SAVED\n")==0);
  request("SERVO SET 1700 300\n",response); assert(strcmp(response,"OK\n")==0);
  request("SERVO STORE?\n",response); assert(strcmp(response,"SERVO STORE UNSAVED\n")==0);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  request("DRIVE 0 0 1900\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(1020U); CarApp_Loop(); assert(tim1.CCR1==1900U);
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0 && tim1.CCR1==1700U);
  servo_save_ok=false;
  request("SERVO SAVE\n",response); assert(strcmp(response,"ERR FLASH\n")==0);
  servo_save_ok=true;
  request("SERVO RESET\n",response); assert(strcmp(response,"OK\n")==0 && tim1.CCR1==1500U);
  request("SERVO?\n",response); assert(strcmp(response,"SERVO 1500 200\n")==0);
  request("SERVO LOAD\n",response); assert(strcmp(response,"OK\n")==0 && tim1.CCR1==1600U);
  request("SERVO STORE?\n",response); assert(strcmp(response,"SERVO STORE SAVED\n")==0);

  /* Reboot reads the saved pair before the very first PWM output. */
  board_reset();
  assert(CarApp_Init() && servo_start_pulse==1600U && tim1.CCR1==1600U);
  request("SERVO?\n",response); assert(strcmp(response,"SERVO 1600 100\n")==0);
  request("AUTO ARM\n",response); assert(strcmp(response,"OK\n")==0);
  request("SERVO?\n",response); assert(strcmp(response,"SERVO 1600 100\n")==0);
  request("SERVO STORE?\n",response); assert(strcmp(response,"SERVO STORE SAVED\n")==0);
  for (unsigned i=0U; i<sizeof(mutations)/sizeof(mutations[0]); ++i) {
    request(mutations[i],response); assert(strcmp(response,"ERR STATE\n")==0);
  }
  request("STOP\n",response); assert(strcmp(response,"OK\n")==0);

  /* Last hardware boundary clamps untrusted output and rejects invalid pairs. */
  CarOutputs output={0,0,2500U};
  CarHw_Apply(&output); assert(tim1.CCR1==1700U);
  output.steer_us=500U;
  CarHw_Apply(&output); assert(tim1.CCR1==1500U);
  assert(!CarHw_SetServoParams(&(CarServoParams){1600U,901U}));
  output.steer_us=2500U;
  CarHw_Apply(&output); assert(tim1.CCR1==1700U);
  CarHw_EmergencyStop(); assert(tim1.CCR1==1600U);

  request("SERVO SET 1550 0\n",response); assert(strcmp(response,"OK\n")==0);
  request("DEBUG\n",response); assert(strcmp(response,"OK\n")==0);
  request("DRIVE 0 0 1551\n",response); assert(strcmp(response,"ERR STATE_OR_RANGE\n")==0);
  request("DRIVE 0 0 1550\n",response); assert(strcmp(response,"OK\n")==0);
  request("SPEED 20 20\n",response); assert(strcmp(response,"OK\n")==0);
  set_time(10U); CarApp_Loop(); assert(tim1.CCR1==1550U);
  clock_frozen=true;
  set_time(20U); CarApp_Loop(); assert(!CarHw_Ready() && tim1.CCR1==1550U);
  request("SERVO?\n",response); assert(strcmp(response,"SERVO 1550 0\n")==0);
  for (unsigned i=0U; i<sizeof(mutations)/sizeof(mutations[0]); ++i) {
    request(mutations[i],response); assert(strcmp(response,"ERR STATE\n")==0);
  }
  servo_store_valid=false;
  board_reset();
  assert(CarApp_Init() && servo_start_pulse==1500U);
}

int main(void) {
  servo_protocol();
  debug_speed_protocol();
  debug_limit_protocol();
  board_reset();
  tim3.CNT=65530U; tim4.CNT=3U;
  assert(CarHw_CommInit());
  assert(CarHw_Init());
  tim3.CNT=4U; tim4.CNT=65530U;
  int32_t left,right;
  CarHw_EncoderDeltas(&left,&right);
  assert(left==10 && right==-9); /* Both encoders are now 16 bit. */
  CarOutputs output={250,-300,1600};
  CarHw_Apply(&output);
  assert(tim5.CCR3==1050U && tim5.CCR4==1260U && tim1.CCR1==1600U);
  assert((gpio_c.ODR & DRV_AIN1_Pin) && (gpio_c.ODR & DRV_BIN2_Pin));
  CarHw_EmergencyStop();
  assert(gpio_c.BSRR==((uint32_t)DRV_STBY_Pin<<16U) && tim5.CCR3==0U && tim5.CCR4==0U);

  CarInputs in={0};
  CarHw_PollRange(0U);
  assert(capture==&htim10 && triggers[0]==1U);
  echo(&htim10,65000U,10000U); /* Capture wraps at 65536. */
  set_time(60U); CarHw_PollRange(now_ms);
  assert(capture==&htim11 && triggers[1]==1U);
  htim13.Instance->CCR1=100U; HAL_TIM_IC_CaptureCallback(&htim13); /* Ignore inactive timer. */
  echo(&htim11,100U,1000U);
  set_time(120U); CarHw_PollRange(now_ms);
  assert(capture==&htim13 && triggers[2]==1U);
  echo(&htim13,200U,2000U);
  CarHw_Snapshot(&in);
  assert(in.line_bits==0xa5 && line_reads==8U);
  CarLineDiagnostics line_diag;
  assert(CarHw_LineDiagnostics(&line_diag));
  assert(line_diag.raw_bits==0x5a && line_diag.line_bits==0xa5 && line_diag.age_ms==0U);
  assert(!CarHw_LineDiagnostics(NULL));
  assert(in.left_mm==1715U && in.center_mm==171U && in.right_mm==343U);
  assert(in.left_valid && in.center_valid && in.right_valid);

  CarRangeDiagnostics d;
  assert(CarHw_RangeDiagnostics(0U,&d));
  assert(d.state==CAR_RANGE_OK && d.pulse_us==10000U && d.triggers==1U);
  assert(d.rises==1U && d.falls==1U && d.valid && d.prescaler==167U && d.timer_running);
  assert(!CarHw_RangeDiagnostics(3U,&d) && !CarHw_RangeDiagnostics(0U,NULL));
  set_time(180U); CarHw_PollRange(now_ms);
  CarHw_Snapshot(&in);
  assert(in.left_valid); /* Preserve preceding sample while a new echo is pending. */
  set_time(210U); CarHw_PollRange(now_ms);
  CarHw_Snapshot(&in);
  assert(!in.left_valid); /* A disconnected probe must not look like clear space. */
  CarHw_RangeDiagnostics(0U,&d);
  assert(d.state==CAR_RANGE_NO_RISE && d.timeouts==1U && d.triggers==2U);
  gpio_f.IDR |= US_C_ECHO_Pin;
  set_time(240U); CarHw_PollRange(now_ms);
  CarHw_Snapshot(&in);
  assert(!in.center_valid && capture==NULL); /* Stuck HIGH must not look clear. */
  CarHw_RangeDiagnostics(1U,&d);
  assert(d.state==CAR_RANGE_ECHO_HIGH && d.echo_high && d.errors==1U && d.triggers==1U);
  gpio_f.IDR=0U;
  set_time(300U); CarHw_PollRange(now_ms);
  htim13.Instance->CCR1=0U; HAL_TIM_IC_CaptureCallback(&htim13);
  set_time(330U); CarHw_PollRange(now_ms);
  CarHw_Snapshot(&in);
  assert(!in.right_valid); /* Rising edge without falling edge is invalid. */
  CarHw_RangeDiagnostics(2U,&d);
  assert(d.state==CAR_RANGE_NO_FALL && d.rises==2U && d.falls==1U && d.timeouts==1U);
  set_time(360U); CarHw_PollRange(now_ms);
  echo(&htim10,100U,50U);
  CarHw_RangeDiagnostics(0U,&d);
  assert(d.state==CAR_RANGE_BAD_PULSE && !d.valid && d.pulse_us==50U);
  set_time(420U); CarHw_PollRange(now_ms);
  tim11.SR=TIM_FLAG_CC1OF;
  HAL_TIM_IC_CaptureCallback(&htim11);
  CarHw_RangeDiagnostics(1U,&d);
  assert(d.state==CAR_RANGE_OVERCAPTURE && !d.valid && (d.flags & TIM_FLAG_CC1OF));
  assert(!(tim11.SR & TIM_FLAG_CC1OF) && capture==NULL);
  set_time(480U); CarHw_PollRange(now_ms);
  set_time(511U); HAL_TIM_IC_CaptureCallback(&htim13);
  CarHw_RangeDiagnostics(2U,&d);
  assert(d.state==CAR_RANGE_LATE_ECHO && !d.valid && capture==NULL);
  set_time(540U); CarHw_PollRange(now_ms);
  tim10.SR=TIM_FLAG_CC1;
  set_time(570U); CarHw_PollRange(now_ms);
  CarHw_RangeDiagnostics(0U,&d);
  assert(d.state==CAR_RANGE_IRQ_MISSED && (d.flags & TIM_FLAG_CC1));
  capture_start_error=true;
  set_time(600U); CarHw_PollRange(now_ms);
  CarHw_RangeDiagnostics(1U,&d);
  assert(d.state==CAR_RANGE_START_ERROR && capture==NULL);
  capture_start_error=false;
  set_time(660U); CarHw_PollRange(now_ms);
  echo(&htim13,65000U,2000U);
  CarHw_RangeDiagnostics(2U,&d);
  assert(d.state==CAR_RANGE_OK && d.valid); /* Faults recover on the next complete pulse. */
  set_time(1261U); CarHw_Snapshot(&in);
  assert(!in.left_valid);
  CarHw_RangeDiagnostics(2U,&d);
  assert(!d.valid && d.age_ms==601U);
  clock_frozen=true;
  CarHw_PollRange(now_ms);
  assert(capture==NULL && !(gpio_a.ODR & (US_L_TRIG_Pin|US_C_TRIG_Pin|US_R_TRIG_Pin)));
  CarHw_Snapshot(&in); /* Frozen TIM10 returns; it cannot hang the control loop. */
  assert(!in.left_valid && !in.center_valid && !in.right_valid && in.line_bits==0U);
  CarHw_RangeDiagnostics(0U,&d);
  assert(d.state==CAR_RANGE_CLOCK_ERROR);
  CarHw_Apply(&output);
  assert(tim5.CCR3==0U && tim5.CCR4==0U && gpio_c.BSRR==((uint32_t)DRV_STBY_Pin<<16U));
  assert(!CarHw_Ready()); /* A stopped microsecond clock latches a hardware fault. */
  clock_frozen=false;

  char line[512];
  feed("PI"); assert(!CarHw_ReadLine(line,sizeof(line)));
  feed("NG\r\n"); assert(CarHw_ReadLine(line,sizeof(line)) && strcmp(line,"PING")==0);
  for (unsigned i=0U;i<140U;++i) feed("X");
  assert(!CarHw_ReadLine(line,sizeof(line)));
  feed("DRIVE 100 100 1500\n"); assert(!CarHw_ReadLine(line,sizeof(line)));
  feed("PING\n"); assert(CarHw_ReadLine(line,sizeof(line)) && strcmp(line,"PING")==0);

  /* A corrupted text line cannot execute the valid prefix before a NUL. */
  const uint8_t corrupt_command[] = "AUTO ARM\0garbage\nPING\n";
  feed_bytes(corrupt_command,sizeof(corrupt_command)-1U);
  assert(CarHw_ReadLine(line,sizeof(line)) && strcmp(line,"PING")==0);
  assert(!CarHw_ReadLine(line,sizeof(line)));

  board_reset(); /* Model MX peripheral initialization; HAL Start is not repeatable. */
  assert(CarApp_Init());
  request("LINE?\n",line); assert(strcmp(line,"ERR NOT_READY\n")==0);
  request("+CONNECTED:001122334455\r\nPING\n",line);
  assert(strcmp(line,"PONG 2\n")==0); /* Module logs cannot create an unmatched ERR. */
  feed("PING\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"PONG 2\n")==0);
  request("HW?\n",line); assert(strcmp(line,"HW 1 READY\n")==0);
  feed("STATUS?\n"); CarApp_Loop(); drain(line);
  assert(strncmp(line,"STAT IDLE 0 ",12U)==0);
  unsigned fields=1U;
  for (char *p=line;*p;++p) if (*p==' ') ++fields;
  assert(fields==13U);
  feed("RANGE? L\n"); CarApp_Loop(); drain(line);
  assert(strncmp(line,"RANGE L WAIT_RISE 0 0 0 -1 4294967295 1 0 0 0 0 ",48U)==0);
  fields=1U;
  for (char *p=line;*p;++p) if (*p==' ') ++fields;
  assert(fields==17U);
  feed("RANGE? X\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"ERR PARAM\n")==0);
  feed("RANGE? \n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"ERR PARAM\n")==0);
  feed("PING\nPING\nPING\nPING\nPING\n");
  set_time(now_ms+10U); CarApp_Loop(); drain(line);
  assert(strcmp(line,"PONG 2\nPONG 2\n")==0); /* Commands leave time for sensor/control work. */
  CarApp_Loop(); drain(line); assert(strcmp(line,"PONG 2\nPONG 2\n")==0);
  CarApp_Loop(); drain(line); assert(strcmp(line,"PONG 2\n")==0);
  request("LINE?\n",line); assert(strcmp(line,"LINE 90 165 0 500 0\n")==0);
  feed("DEBUG\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"OK\n")==0);
  feed("DRIVE 4294967396 100 1500\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"ERR STATE_OR_RANGE\n")==0); /* No overflow to small PWM. */
  feed("DRIVE 1+2+1500\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"ERR STATE_OR_RANGE\n")==0);
  feed("DRIVE 100 100 1500\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"OK\n")==0);
  feed("STOP\nAUTO ARM\n"); CarApp_Loop(); drain(line);
  assert(strcmp(line,"OK\nOK\n")==0);
  set_time(now_ms+CAR_ARM_DELAY_MS); CarApp_Loop();
  feed("STATUS?\n"); CarApp_Loop(); drain(line);
  assert(strncmp(line,"STAT FAULT 2 ",13U)==0);
  assert(tim5.CCR3==0U && tim5.CCR4==0U); /* Unplugged probes block autonomous launch. */

  board_reset(); clock_frozen=true;
  hardware_failure_remains_diagnosable("CLOCK");
  const struct { StartFailure failure; TIM_HandleTypeDef *timer; uint32_t channel; const char *stage; } faults[]={
    {START_BASE,&htim10,0U,"RANGE_L"}, {START_BASE,&htim11,0U,"RANGE_C"},
    {START_BASE,&htim13,0U,"RANGE_R"}, {START_PWM,&htim1,TIM_CHANNEL_1,"SERVO_PWM"},
    {START_PWM,&htim5,TIM_CHANNEL_3,"MOTOR_L_PWM"},
    {START_PWM,&htim5,TIM_CHANNEL_4,"MOTOR_R_PWM"},
    {START_ENCODER,&htim3,TIM_CHANNEL_ALL,"ENCODER_L"},
    {START_ENCODER,&htim4,TIM_CHANNEL_ALL,"ENCODER_R"},
  };
  for (unsigned i=0U;i<sizeof(faults)/sizeof(faults[0]);++i) {
    board_reset();
    start_failure=faults[i].failure;
    failed_timer=faults[i].timer;
    failed_channel=faults[i].channel;
    hardware_failure_remains_diagnosable(faults[i].stage);
  }
  board_reset(); uart_receive_error=true;
  assert(!CarApp_Init()); /* UART initialization failure remains fatal to main. */
  assert(!huart3.rx_busy && tim5.CCR3==0U && tim5.CCR4==0U);

  board_reset(); assert(CarApp_Init());
  set_time(CAR_CONTROL_PERIOD_MS);
  clock_frozen=true;
  request("PING\n",line); assert(strcmp(line,"PONG 2\n")==0);
  request("HW?\n",line); assert(strcmp(line,"HW 0 CLOCK\n")==0);
  request("STATUS?\n",line); assert(strncmp(line,"STAT FAULT 6 ",13U)==0);
  clock_frozen=false;
  request("STOP\n",line); assert(strcmp(line,"OK\n")==0);
  request("STATUS?\n",line); assert(strncmp(line,"STAT FAULT 6 ",13U)==0);
  board_reset(); assert(CarApp_Init());
  for (unsigned pattern=0U; pattern<256U; ++pattern) {
    black_bits=(uint8_t)pattern;
    CarHw_Snapshot(&in);
    assert(in.line_bits==pattern);
    assert(CarHw_LineDiagnostics(&line_diag));
    assert(line_diag.raw_bits==(uint8_t)(pattern^255U) && line_diag.line_bits==pattern);
  }
  set_time(123U);
  assert(CarHw_LineDiagnostics(&line_diag) && line_diag.age_ms==123U);
  request("LINE?\n",line); assert(strcmp(line,"LINE 0 255 0 500 123\n")==0);
  assert(tim5.CCR3==0U && tim5.CCR4==0U); /* Diagnostics never start the car. */
  dual_uart_protocol();
  puts("car_hw and car_app tests passed");
  return 0;
}
