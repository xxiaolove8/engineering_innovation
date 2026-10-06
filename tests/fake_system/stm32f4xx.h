#ifndef FAKE_SYSTEM_STM32F4XX_H
#define FAKE_SYSTEM_STM32F4XX_H

#include <stdint.h>

/* Minimal register view for compiling the real CMSIS SystemInit/clock source. */
typedef struct {
  volatile uint32_t VTOR, CPACR;
} SCB_Type;
typedef struct {
  volatile uint32_t CFGR, PLLCFGR;
} RCC_TypeDef;
extern SCB_Type fake_scb;
extern RCC_TypeDef fake_rcc;
#define SCB (&fake_scb)
#define RCC (&fake_rcc)
#define __FPU_PRESENT 1U
#define __FPU_USED 1U
#define RCC_CFGR_SWS 0x0000000CU
#define RCC_CFGR_HPRE 0x000000F0U
#define RCC_PLLCFGR_PLLSRC 0x00400000U
#define RCC_PLLCFGR_PLLM 0x0000003FU
#define RCC_PLLCFGR_PLLN 0x00007FC0U
#define RCC_PLLCFGR_PLLP 0x00030000U

void FakeSystemDsb(void);
void FakeSystemIsb(void);
#define __DSB() FakeSystemDsb()
#define __ISB() FakeSystemIsb()

#endif
