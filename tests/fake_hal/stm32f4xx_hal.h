#ifndef TEST_FAKE_STM32F4XX_HAL_H
#define TEST_FAKE_STM32F4XX_HAL_H

#include <stdint.h>

extern uint32_t fake_flash[128U * 1024U / 4U];
#define PID_FLASH_BASE ((uintptr_t)fake_flash)
#define PID_FLASH_BYTES (128UL * 1024UL)

typedef enum { HAL_OK = 0, HAL_ERROR = 1 } HAL_StatusTypeDef;
typedef struct {
  uint32_t TypeErase;
  uint32_t Sector;
  uint32_t NbSectors;
  uint32_t VoltageRange;
} FLASH_EraseInitTypeDef;

#define FLASH_TYPEERASE_SECTORS 1U
#define FLASH_SECTOR_11 11U
#define FLASH_VOLTAGE_RANGE_3 3U
#define FLASH_TYPEPROGRAM_WORD 2U
#define FLASH_FLAG_EOP 1U
#define FLASH_FLAG_OPERR 2U
#define FLASH_FLAG_WRPERR 4U
#define FLASH_FLAG_PGAERR 8U
#define FLASH_FLAG_PGPERR 16U
#define FLASH_FLAG_PGSERR 32U
#define __HAL_FLASH_CLEAR_FLAG(flags) ((void)(flags))

HAL_StatusTypeDef HAL_FLASH_Unlock(void);
HAL_StatusTypeDef HAL_FLASH_Lock(void);
HAL_StatusTypeDef HAL_FLASHEx_Erase(FLASH_EraseInitTypeDef *config,
                                   uint32_t *failed_sector);
HAL_StatusTypeDef HAL_FLASH_Program(uint32_t type, uintptr_t address,
                                   uint64_t data);

#endif
