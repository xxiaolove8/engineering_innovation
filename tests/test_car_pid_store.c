#include "car_pid_store.h"
#include "stm32f4xx_hal.h"
#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

uint32_t fake_flash[128U * 1024U / 4U];
static int write_budget = INT_MAX;
static unsigned program_calls;
static unsigned erase_calls;

HAL_StatusTypeDef HAL_FLASH_Unlock(void) { return HAL_OK; }
HAL_StatusTypeDef HAL_FLASH_Lock(void) { return HAL_OK; }

HAL_StatusTypeDef HAL_FLASHEx_Erase(FLASH_EraseInitTypeDef *config,
                                   uint32_t *failed_sector) {
  (void)failed_sector;
  if (config->Sector != FLASH_SECTOR_11) return HAL_ERROR;
  ++erase_calls;
  memset(fake_flash, 0xFF, sizeof(fake_flash));
  return HAL_OK;
}

HAL_StatusTypeDef HAL_FLASH_Program(uint32_t type, uintptr_t address,
                                   uint64_t data) {
  ++program_calls;
  if (type != FLASH_TYPEPROGRAM_WORD || write_budget-- <= 0 ||
      address < (uintptr_t)fake_flash ||
      address + 4U > (uintptr_t)fake_flash + sizeof(fake_flash) ||
      (address & 3U) != 0U) return HAL_ERROR;
  uint32_t *word = (uint32_t *)address;
  if (*word != 0xFFFFFFFFU) return HAL_ERROR;
  *word = (uint32_t)data;
  return HAL_OK;
}

static void reset_flash(void) {
  memset(fake_flash, 0xFF, sizeof(fake_flash));
  write_budget = INT_MAX;
  program_calls = 0U;
  erase_calls = 0U;
}

static void assert_pid(const CarPidParams *expected) {
  CarPidParams loaded;
  assert(CarPidStore_Load(&loaded));
  assert(memcmp(expected, &loaded, sizeof(loaded)) == 0);
  assert(CarPidStore_Matches(expected));
}

static void assert_servo(const CarServoParams *expected) {
  CarServoParams loaded;
  assert(CarServoStore_Load(&loaded));
  assert(memcmp(expected, &loaded, sizeof(loaded)) == 0);
  assert(CarServoStore_Matches(expected));
}

/* The original PID1 on-flash layout is deliberately independent of the new
 * shared-record implementation, to check upgrades retain old calibration. */
typedef struct {
  uint32_t magic;
  uint32_t sequence;
  CarPidParams params;
  uint32_t checksum;
  uint32_t commit;
} LegacyPidRecord;

static void install_legacy_pid(const CarPidParams *params) {
  LegacyPidRecord record = {
    .magic = 0x50494431UL, .sequence = 7U,
    .params = *params, .commit = 0x434D5431UL
  };
  _Static_assert(sizeof(LegacyPidRecord) == 56U, "Legacy PID1 record size");
  const uint8_t *bytes = (const uint8_t *)&record;
  uint32_t hash = 2166136261UL;
  for (size_t i = 0U; i < offsetof(LegacyPidRecord, checksum); ++i)
    hash = (hash ^ bytes[i]) * 16777619UL;
  record.checksum = hash;
  memcpy(fake_flash, &record, sizeof(record));
}

static void occupy_blanks(void) {
  for (size_t i = 0U; i < sizeof(fake_flash) / sizeof(fake_flash[0]); ++i)
    if (fake_flash[i] == 0xFFFFFFFFU) fake_flash[i] = 0U;
}

int main(void) {
  CarPidParams initial = CarPid_DefaultParams();
  CarPidParams tuned = initial;
  tuned.line_kp = 32.5f;
  CarServoParams servo_initial = CarServo_DefaultParams();
  CarServoParams servo_tuned = {1520U, 280U};
  CarServoParams servo_next = {1540U, 300U};
  CarPidParams loaded;
  CarServoParams servo_loaded;

  reset_flash();
  assert(!CarPidStore_Load(&loaded));
  assert(!CarServoStore_Load(&servo_loaded));
  assert(!CarPidStore_Load(NULL));
  assert(!CarServoStore_Load(NULL));
  assert(!CarPidStore_Save(NULL));
  assert(!CarServoStore_Save(NULL));
  assert(!CarPidStore_Matches(NULL));
  assert(!CarServoStore_Matches(NULL));
  CarServoParams invalid = {1500U, 1001U};
  assert(!CarServoStore_Save(&invalid));
  assert(!CarServoStore_Matches(&invalid));
  invalid = (CarServoParams){499U, 0U};
  assert(!CarServoStore_Save(&invalid));
  invalid = (CarServoParams){2501U, 0U};
  assert(!CarServoStore_Save(&invalid));
  assert(program_calls == 0U && erase_calls == 0U);

  /* Old PID1 records and both new record types coexist in unchanged slots. */
  install_legacy_pid(&initial);
  assert_pid(&initial);
  assert(!CarServoStore_Load(&servo_loaded));
  assert(CarServoStore_Save(&servo_initial)); /* Slot 1. */
  assert(CarPidStore_Save(&tuned));           /* Slot 2. */
  assert(CarServoStore_Save(&servo_tuned));   /* Slot 3. */
  assert_pid(&tuned);
  assert_servo(&servo_tuned);
  unsigned calls = program_calls;
  assert(CarPidStore_Save(&tuned));
  assert(CarServoStore_Save(&servo_tuned));
  assert(program_calls == calls && erase_calls == 0U);
  assert(fake_flash[2U * (56U / 4U) + 1U] == 8U); /* PID sequence follows PID1. */
  assert(fake_flash[3U * (56U / 4U) + 1U] == 2U); /* Servo sequence is independent. */

  /* An interrupted first servo write never becomes a saved calibration. */
  reset_flash();
  write_budget = 13; /* All words except the commit word. */
  assert(!CarServoStore_Save(&servo_initial));
  assert(!CarServoStore_Load(&servo_loaded));
  write_budget = INT_MAX;
  assert(CarPidStore_Save(&initial));
  assert_pid(&initial);
  assert(CarServoStore_Save(&servo_initial));
  assert_servo(&servo_initial);

  /* Either group's interrupted update preserves both last good records. */
  reset_flash();
  assert(CarPidStore_Save(&initial));         /* Slot 0. */
  assert(CarServoStore_Save(&servo_initial)); /* Slot 1. */
  write_budget = 3;
  assert(!CarPidStore_Save(&tuned));          /* Partial slot 2. */
  assert_pid(&initial);
  assert_servo(&servo_initial);
  write_budget = INT_MAX;
  assert(CarServoStore_Save(&servo_tuned));   /* Slot 3. */
  assert_pid(&initial);
  assert_servo(&servo_tuned);
  write_budget = 13;
  assert(!CarServoStore_Save(&servo_next));   /* Uncommitted slot 4. */
  assert_pid(&initial);
  assert_servo(&servo_tuned);
  write_budget = INT_MAX;
  assert(CarPidStore_Save(&tuned));           /* Slot 5. */
  assert(CarServoStore_Save(&servo_next));    /* Slot 6. */
  assert_pid(&tuned);
  assert_servo(&servo_next);

  /* A corrupt committed record falls back to the preceding complete record. */
  fake_flash[5U * (56U / 4U) + 2U] ^= 1U;
  assert_pid(&initial);
  assert_servo(&servo_next);
  assert(!CarPidStore_Matches(&tuned));
  fake_flash[6U * (56U / 4U) + 2U] ^= 1U;
  assert_servo(&servo_tuned);
  assert(!CarServoStore_Matches(&servo_next));
  assert(CarPidStore_Save(&tuned));
  assert(CarServoStore_Save(&servo_next));
  assert_pid(&tuned);
  assert_servo(&servo_next);

  /* Full storage preserves the last valid calibration instead of erasing it. */
  occupy_blanks();
  assert(!CarPidStore_Save(&initial));
  assert(!CarServoStore_Save(&servo_initial));
  assert_pid(&tuned);
  assert_servo(&servo_next);
  assert(erase_calls == 0U);

  /* The other record type alone is sufficient to prevent sector erasure. */
  reset_flash();
  assert(CarServoStore_Save(&servo_tuned));
  occupy_blanks();
  assert(!CarPidStore_Save(&initial));
  assert(!CarPidStore_Load(&loaded));
  assert_servo(&servo_tuned);
  assert(erase_calls == 0U);
  reset_flash();
  assert(CarPidStore_Save(&tuned));
  occupy_blanks();
  assert(!CarServoStore_Save(&servo_initial));
  assert(!CarServoStore_Load(&servo_loaded));
  assert_pid(&tuned);
  assert(erase_calls == 0U);

  /* Erasure is allowed only when neither group has any valid calibration. */
  memset(fake_flash, 0, sizeof(fake_flash));
  assert(!CarPidStore_Load(&loaded));
  assert(!CarServoStore_Load(&servo_loaded));
  assert(CarServoStore_Save(&servo_initial));
  assert(erase_calls == 1U);
  assert_servo(&servo_initial);
  assert(CarPidStore_Save(&initial));
  assert_pid(&initial);
  assert_servo(&servo_initial);
  puts("car_pid_store tests passed");
  return 0;
}
