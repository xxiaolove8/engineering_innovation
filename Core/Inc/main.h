/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
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

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *htim);

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define DRV_PWMA_Pin GPIO_PIN_2
#define DRV_PWMA_GPIO_Port GPIOA
#define DRV_PWMB_Pin GPIO_PIN_3
#define DRV_PWMB_GPIO_Port GPIOA
#define DRV_AIN1_Pin GPIO_PIN_0
#define DRV_AIN1_GPIO_Port GPIOC
#define DRV_AIN2_Pin GPIO_PIN_1
#define DRV_AIN2_GPIO_Port GPIOC
#define DRV_BIN1_Pin GPIO_PIN_2
#define DRV_BIN1_GPIO_Port GPIOC
#define DRV_BIN2_Pin GPIO_PIN_3
#define DRV_BIN2_GPIO_Port GPIOC
#define DRV_STBY_Pin GPIO_PIN_4
#define DRV_STBY_GPIO_Port GPIOC
#define ENC_L_A_Pin GPIO_PIN_6
#define ENC_L_A_GPIO_Port GPIOC
#define ENC_L_B_Pin GPIO_PIN_7
#define ENC_L_B_GPIO_Port GPIOC
#define ENC_R_A_Pin GPIO_PIN_6
#define ENC_R_A_GPIO_Port GPIOB
#define ENC_R_B_Pin GPIO_PIN_7
#define ENC_R_B_GPIO_Port GPIOB
#define SERVO_PWM_Pin GPIO_PIN_9
#define SERVO_PWM_GPIO_Port GPIOE
#define UART1_TX_Pin GPIO_PIN_9
#define UART1_TX_GPIO_Port GPIOA
#define UART1_RX_Pin GPIO_PIN_10
#define UART1_RX_GPIO_Port GPIOA
#define UART3_TX_Pin GPIO_PIN_10
#define UART3_TX_GPIO_Port GPIOB
#define UART3_RX_Pin GPIO_PIN_11
#define UART3_RX_GPIO_Port GPIOB
#define GRAY_AD0_Pin GPIO_PIN_0
#define GRAY_AD0_GPIO_Port GPIOF
#define GRAY_AD1_Pin GPIO_PIN_1
#define GRAY_AD1_GPIO_Port GPIOF
#define GRAY_AD2_Pin GPIO_PIN_2
#define GRAY_AD2_GPIO_Port GPIOF
#define GRAY_OUT_Pin GPIO_PIN_5
#define GRAY_OUT_GPIO_Port GPIOC
#define US_L_TRIG_Pin GPIO_PIN_1
#define US_L_TRIG_GPIO_Port GPIOA
#define US_L_ECHO_Pin GPIO_PIN_6
#define US_L_ECHO_GPIO_Port GPIOF
#define US_C_TRIG_Pin GPIO_PIN_5
#define US_C_TRIG_GPIO_Port GPIOA
#define US_C_ECHO_Pin GPIO_PIN_7
#define US_C_ECHO_GPIO_Port GPIOF
#define US_R_TRIG_Pin GPIO_PIN_7
#define US_R_TRIG_GPIO_Port GPIOA
#define US_R_ECHO_Pin GPIO_PIN_8
#define US_R_ECHO_GPIO_Port GPIOF
#define SRAM_CS_Pin GPIO_PIN_10
#define SRAM_CS_GPIO_Port GPIOG

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
