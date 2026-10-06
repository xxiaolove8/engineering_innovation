#include "stm32f4xx.h"
#include <assert.h>
#include <stdio.h>

SCB_Type fake_scb;
RCC_TypeDef fake_rcc;
/* Model an aligned application vector table, independent of boot memory mapping. */
_Alignas(512) const uint32_t g_pfnVectors[] = {0x20020000U, 0x08000101U};
static unsigned barrier_stage;
void SystemInit(void);

void FakeSystemDsb(void) {
  assert(barrier_stage == 0U);
  assert(SCB->VTOR == (uint32_t)(uintptr_t)g_pfnVectors);
  barrier_stage = 1U;
}

void FakeSystemIsb(void) {
  assert(barrier_stage == 1U);
  assert(SCB->VTOR == (uint32_t)(uintptr_t)g_pfnVectors);
  barrier_stage = 2U;
}

int main(void) {
  const uint32_t inherited_vectors[] = {
    0x1FFF0000U, /* STM32F407 ROM bootloader state seen in the engineering record. */
    0x00000000U, /* Normal reset: boot-selected memory alias. */
    0x20000000U  /* A software loader may have used RAM vectors. */
  };
  for (unsigned i = 0U; i < sizeof(inherited_vectors) / sizeof(inherited_vectors[0]); ++i) {
    SCB->VTOR = inherited_vectors[i];
    SCB->CPACR = 0x200U;
    barrier_stage = 0U;
    SystemInit(); /* Compile/call the production source, not a duplicate implementation. */
    assert(SCB->VTOR == (uint32_t)(uintptr_t)g_pfnVectors);
    assert(barrier_stage == 2U);
    assert(SCB->CPACR == (0x200U | (3U << 20U) | (3U << 22U)));
  }
  puts("system startup vector relocation tests passed");
  return 0;
}
