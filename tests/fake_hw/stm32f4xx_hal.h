#ifndef FAKE_HW_HAL_H
#define FAKE_HW_HAL_H
#include <stdint.h>
#include <stddef.h>

typedef enum { HAL_OK, HAL_ERROR, HAL_BUSY } HAL_StatusTypeDef;
typedef enum { GPIO_PIN_RESET, GPIO_PIN_SET } GPIO_PinState;
typedef struct { uint32_t MODER, BSRR, ODR, IDR; } GPIO_TypeDef;
typedef struct { uint32_t CNT, ARR, CCR1, CCR3, CCR4, EGR, CR1, PSC, SR, polarity; } TIM_TypeDef;
typedef struct {
  TIM_TypeDef *Instance;
  uint32_t Channel, base_started, started_channels;
} TIM_HandleTypeDef;
typedef struct { uint32_t rx_busy; } UART_HandleTypeDef;
extern GPIO_TypeDef gpio_a, gpio_b, gpio_c, gpio_e, gpio_f, gpio_g;
extern TIM_TypeDef tim1, tim3, tim4, tim5, tim10, tim11, tim13;
#define GPIOA (&gpio_a)
#define GPIOB (&gpio_b)
#define GPIOC (&gpio_c)
#define GPIOE (&gpio_e)
#define GPIOF (&gpio_f)
#define GPIOG (&gpio_g)
#define TIM1 (&tim1)
#define TIM3 (&tim3)
#define TIM4 (&tim4)
#define TIM5 (&tim5)
#define TIM10 (&tim10)
#define TIM11 (&tim11)
#define TIM13 (&tim13)
#define GPIO_PIN_0 (1U << 0)
#define GPIO_PIN_1 (1U << 1)
#define GPIO_PIN_2 (1U << 2)
#define GPIO_PIN_3 (1U << 3)
#define GPIO_PIN_4 (1U << 4)
#define GPIO_PIN_5 (1U << 5)
#define GPIO_PIN_6 (1U << 6)
#define GPIO_PIN_7 (1U << 7)
#define GPIO_PIN_8 (1U << 8)
#define GPIO_PIN_9 (1U << 9)
#define GPIO_PIN_10 (1U << 10)
#define GPIO_PIN_11 (1U << 11)
#define TIM_CHANNEL_1 0U
#define TIM_CHANNEL_3 8U
#define TIM_CHANNEL_4 12U
#define TIM_CHANNEL_ALL 60U
#define HAL_TIM_ACTIVE_CHANNEL_1 1U
#define TIM_INPUTCHANNELPOLARITY_RISING 0U
#define TIM_INPUTCHANNELPOLARITY_FALLING 1U
#define TIM_FLAG_CC1 2U
#define TIM_FLAG_CC1OF 512U
#define TIM_EGR_UG 1U
#define TIM_CR1_CEN 1U
#define __HAL_RCC_GPIOC_CLK_ENABLE() ((void)0)
#define __HAL_TIM_GET_AUTORELOAD(h) ((h)->Instance->ARR)
#define __HAL_TIM_GET_COUNTER(h) FakeCounter(h)
#define __HAL_TIM_SET_COMPARE(h,c,v) FakeCompare(h,c,v)
#define __HAL_TIM_ENABLE(h) ((h)->Instance->CR1 |= TIM_CR1_CEN)
#define __HAL_TIM_CLEAR_FLAG(h,f) ((h)->Instance->SR &= ~(f))
#define __HAL_TIM_SET_CAPTUREPOLARITY(h,c,p) ((void)(c), (h)->Instance->polarity=(p))
uint32_t FakeCounter(TIM_HandleTypeDef *timer);
void FakeCompare(TIM_HandleTypeDef *timer, uint32_t channel, uint32_t value);
uint32_t __get_PRIMASK(void);
void __disable_irq(void);
void __enable_irq(void);
uint32_t HAL_GetTick(void);
HAL_StatusTypeDef HAL_TIM_Base_Start(TIM_HandleTypeDef *timer);
HAL_StatusTypeDef HAL_TIM_PWM_Start(TIM_HandleTypeDef *timer, uint32_t channel);
HAL_StatusTypeDef HAL_TIM_Encoder_Start(TIM_HandleTypeDef *timer, uint32_t channel);
HAL_StatusTypeDef HAL_TIM_IC_Start_IT(TIM_HandleTypeDef *timer, uint32_t channel);
HAL_StatusTypeDef HAL_TIM_IC_Stop_IT(TIM_HandleTypeDef *timer, uint32_t channel);
uint32_t HAL_TIM_ReadCapturedValue(TIM_HandleTypeDef *timer, uint32_t channel);
void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pins, GPIO_PinState state);
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pins);
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *uart, uint8_t *byte, uint16_t count);
HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *uart, uint8_t *byte, uint16_t count);
#endif
