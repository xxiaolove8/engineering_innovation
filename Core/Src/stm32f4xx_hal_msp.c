/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file         stm32f4xx_hal_msp.c
  * @brief        This file provides code for the MSP Initialization
  *               and de-Initialization codes.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
#include "main.h"

void HAL_MspInit(void) {
  __HAL_RCC_SYSCFG_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();
}

static void alternate(GPIO_TypeDef *port, uint16_t pins, uint32_t af, uint32_t pull) {
  GPIO_InitTypeDef gpio = {0};
  gpio.Pin = pins;
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Pull = pull;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  gpio.Alternate = af;
  HAL_GPIO_Init(port, &gpio);
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim) {
  IRQn_Type irq;
  if (htim->Instance == TIM1) { __HAL_RCC_TIM1_CLK_ENABLE(); return; }
  if (htim->Instance == TIM5) { __HAL_RCC_TIM5_CLK_ENABLE(); return; }
  __HAL_RCC_GPIOF_CLK_ENABLE();
  if (htim->Instance == TIM10) {
    __HAL_RCC_TIM10_CLK_ENABLE();
    alternate(US_L_ECHO_GPIO_Port, US_L_ECHO_Pin, GPIO_AF3_TIM10, GPIO_NOPULL);
    irq = TIM1_UP_TIM10_IRQn;
  } else if (htim->Instance == TIM11) {
    __HAL_RCC_TIM11_CLK_ENABLE();
    alternate(US_C_ECHO_GPIO_Port, US_C_ECHO_Pin, GPIO_AF3_TIM11, GPIO_NOPULL);
    irq = TIM1_TRG_COM_TIM11_IRQn;
  } else if (htim->Instance == TIM13) {
    __HAL_RCC_TIM13_CLK_ENABLE();
    alternate(US_R_ECHO_GPIO_Port, US_R_ECHO_Pin, GPIO_AF9_TIM13, GPIO_NOPULL);
    irq = TIM8_UP_TIM13_IRQn;
  } else return;
  HAL_NVIC_SetPriority(irq, 5, 0);
  HAL_NVIC_EnableIRQ(irq);
}

void HAL_TIM_Encoder_MspInit(TIM_HandleTypeDef *htim) {
  if (htim->Instance == TIM3) {
    __HAL_RCC_TIM3_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    alternate(GPIOC, ENC_L_A_Pin | ENC_L_B_Pin, GPIO_AF2_TIM3, GPIO_PULLUP);
  } else if (htim->Instance == TIM4) {
    __HAL_RCC_TIM4_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    alternate(GPIOB, ENC_R_A_Pin | ENC_R_B_Pin, GPIO_AF2_TIM4, GPIO_PULLUP);
  }
}

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *htim) {
  if (htim->Instance == TIM1) {
    __HAL_RCC_GPIOE_CLK_ENABLE();
    alternate(SERVO_PWM_GPIO_Port, SERVO_PWM_Pin, GPIO_AF1_TIM1, GPIO_NOPULL);
  } else if (htim->Instance == TIM5) {
    __HAL_RCC_GPIOA_CLK_ENABLE();
    alternate(GPIOA, DRV_PWMA_Pin | DRV_PWMB_Pin, GPIO_AF2_TIM5, GPIO_NOPULL);
  }
}

void HAL_TIM_Base_MspDeInit(TIM_HandleTypeDef *htim) {
  if (htim->Instance == TIM1) __HAL_RCC_TIM1_CLK_DISABLE();
  else if (htim->Instance == TIM5) __HAL_RCC_TIM5_CLK_DISABLE();
  else if (htim->Instance == TIM10) {
    __HAL_RCC_TIM10_CLK_DISABLE();
    HAL_GPIO_DeInit(US_L_ECHO_GPIO_Port, US_L_ECHO_Pin);
  } else if (htim->Instance == TIM11) {
    __HAL_RCC_TIM11_CLK_DISABLE();
    HAL_GPIO_DeInit(US_C_ECHO_GPIO_Port, US_C_ECHO_Pin);
  } else if (htim->Instance == TIM13) {
    __HAL_RCC_TIM13_CLK_DISABLE();
    HAL_GPIO_DeInit(US_R_ECHO_GPIO_Port, US_R_ECHO_Pin);
  }
  /* Shared NVIC vectors remain enabled for their other peripheral. */
}

void HAL_TIM_Encoder_MspDeInit(TIM_HandleTypeDef *htim) {
  if (htim->Instance == TIM3) {
    __HAL_RCC_TIM3_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOC, ENC_L_A_Pin | ENC_L_B_Pin);
  } else if (htim->Instance == TIM4) {
    __HAL_RCC_TIM4_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOB, ENC_R_A_Pin | ENC_R_B_Pin);
  }
}

void HAL_UART_MspInit(UART_HandleTypeDef *huart) {
  IRQn_Type irq;
  if (huart->Instance == USART1) {
    __HAL_RCC_USART1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    alternate(GPIOA, UART1_TX_Pin | UART1_RX_Pin, GPIO_AF7_USART1, GPIO_NOPULL);
    irq = USART1_IRQn;
  } else if (huart->Instance == USART3) {
    __HAL_RCC_USART3_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    alternate(GPIOB, UART3_TX_Pin | UART3_RX_Pin, GPIO_AF7_USART3, GPIO_NOPULL);
    irq = USART3_IRQn;
  } else return;
  HAL_NVIC_SetPriority(irq, 6, 0);
  HAL_NVIC_EnableIRQ(irq);
}

void HAL_UART_MspDeInit(UART_HandleTypeDef *huart) {
  if (huart->Instance == USART1) {
    __HAL_RCC_USART1_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOA, UART1_TX_Pin | UART1_RX_Pin);
    HAL_NVIC_DisableIRQ(USART1_IRQn);
  } else if (huart->Instance == USART3) {
    __HAL_RCC_USART3_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOB, UART3_TX_Pin | UART3_RX_Pin);
    HAL_NVIC_DisableIRQ(USART3_IRQn);
  }
}
