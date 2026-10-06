#include "car_pid_store.h"
#include "stm32f4xx_hal.h"
#include <stddef.h>
#include <string.h>

#ifndef PID_FLASH_BASE
#define PID_FLASH_BASE 0x080E0000UL
#endif
#ifndef PID_FLASH_BYTES
#define PID_FLASH_BYTES (128UL * 1024UL)
#endif
#define PID_MAGIC 0x50494431UL   /* PID1: record format version */
#define SERVO_MAGIC 0x53525631UL /* SRV1: independent servo calibration */
#define PID_COMMIT 0x434D5431UL  /* CMT1: programmed only after payload */

typedef struct {
  uint32_t magic;
  uint32_t sequence;
  union {
    CarPidParams pid;
    struct {
      CarServoParams params;
      uint8_t reserved[36];
    } servo;
  } payload;
  uint32_t checksum;
  uint32_t commit;
} PidFlashRecord;

_Static_assert(sizeof(CarPidParams) == 40U, "PID parameter format changed");
_Static_assert(sizeof(CarServoParams) == 4U, "Servo parameter format changed");
_Static_assert(sizeof(PidFlashRecord) == 56U, "Flash record must be word aligned");
_Static_assert(offsetof(PidFlashRecord, payload) == 8U, "PID1 payload offset changed");
_Static_assert(offsetof(PidFlashRecord, checksum) == 48U, "PID1 checksum offset changed");

static uint32_t checksum(const PidFlashRecord *record) {
  const uint8_t *bytes = (const uint8_t *)record;
  uint32_t result = 2166136261UL;
  for (size_t i = 0; i < offsetof(PidFlashRecord, checksum); ++i)
    result = (result ^ bytes[i]) * 16777619UL;
  return result;
}

static bool slot_erased(const PidFlashRecord *slot) {
  const volatile uint32_t *words = (const volatile uint32_t *)slot;
  for (size_t i = 0; i < sizeof(*slot) / sizeof(uint32_t); ++i)
    if (words[i] != 0xFFFFFFFFUL) return false;
  return true;
}

static bool slot_valid(const PidFlashRecord *slot, PidFlashRecord *copy) {
  if ((slot->magic != PID_MAGIC && slot->magic != SERVO_MAGIC) ||
      slot->commit != PID_COMMIT) return false;
  memcpy(copy, slot, sizeof(*copy));
  if (copy->checksum != checksum(copy)) return false;
  return copy->magic == PID_MAGIC ? CarPid_ValidParams(&copy->payload.pid) :
                                   CarServo_ValidParams(&copy->payload.servo.params);
}

static const PidFlashRecord *slot_at(size_t index) {
  return (const PidFlashRecord *)(PID_FLASH_BASE + index * sizeof(PidFlashRecord));
}

static bool latest_record(uint32_t magic, PidFlashRecord *latest,
                          size_t *first_blank, bool *any_valid) {
  bool found = false;
  const size_t slots = PID_FLASH_BYTES / sizeof(PidFlashRecord);
  if (first_blank != NULL) *first_blank = slots;
  if (any_valid != NULL) *any_valid = false;
  for (size_t i = 0; i < slots; ++i) {
    const PidFlashRecord *slot = slot_at(i);
    if (first_blank != NULL && *first_blank == slots && slot_erased(slot))
      *first_blank = i;
    PidFlashRecord candidate;
    if (!slot_valid(slot, &candidate)) continue;
    if (any_valid != NULL) *any_valid = true;
    if (candidate.magic == magic &&
        (!found || candidate.sequence > latest->sequence)) {
      *latest = candidate;
      found = true;
    }
  }
  return found;
}

bool CarPidStore_Load(CarPidParams *params) {
  if (params == NULL) return false;
  PidFlashRecord latest;
  if (!latest_record(PID_MAGIC, &latest, NULL, NULL)) return false;
  *params = latest.payload.pid;
  return true;
}

bool CarPidStore_Matches(const CarPidParams *params) {
  if (!CarPid_ValidParams(params)) return false;
  CarPidParams saved;
  return CarPidStore_Load(&saved) && memcmp(&saved, params, sizeof(saved)) == 0;
}

static bool save_record(uint32_t magic, const void *params, size_t params_size) {
  PidFlashRecord latest;
  size_t first_blank;
  bool any_valid;
  bool found = latest_record(magic, &latest, &first_blank, &any_valid);
  if (found && memcmp(&latest.payload, params, params_size) == 0)
    return true; /* Avoid unnecessary flash wear. */
  const size_t slots = PID_FLASH_BYTES / sizeof(PidFlashRecord);
  if (found && latest.sequence == UINT32_MAX) return false;
  uint32_t sequence = found ? latest.sequence + 1U : 1U;
  bool erase = first_blank == slots && !any_valid;
  if (first_blank == slots && any_valid) return false; /* Preserve both groups. */
  if (erase) first_blank = 0U;

  PidFlashRecord record = {
    .magic = magic, .sequence = sequence, .commit = PID_COMMIT
  };
  memcpy(&record.payload, params, params_size);
  record.checksum = checksum(&record);

  if (HAL_FLASH_Unlock() != HAL_OK) return false;
  __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_EOP | FLASH_FLAG_OPERR |
                         FLASH_FLAG_WRPERR | FLASH_FLAG_PGAERR |
                         FLASH_FLAG_PGPERR | FLASH_FLAG_PGSERR);
  bool ok = true;
  if (erase) {
    FLASH_EraseInitTypeDef config = {
      .TypeErase = FLASH_TYPEERASE_SECTORS,
      .Sector = FLASH_SECTOR_11,
      .NbSectors = 1U,
      .VoltageRange = FLASH_VOLTAGE_RANGE_3
    };
    uint32_t failed_sector = 0xFFFFFFFFUL;
    ok = HAL_FLASHEx_Erase(&config, &failed_sector) == HAL_OK;
  }
  const uintptr_t address = PID_FLASH_BASE +
                            first_blank * sizeof(PidFlashRecord);
  const size_t payload_words = offsetof(PidFlashRecord, commit) / sizeof(uint32_t);
  for (size_t i = 0; ok && i < payload_words; ++i) {
    uint32_t word;
    memcpy(&word, (const uint8_t *)&record + i * sizeof(word), sizeof(word));
    ok = HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD,
                           address + i * sizeof(word), word) == HAL_OK;
  }
  if (ok)
    ok = HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD,
                           address + offsetof(PidFlashRecord, commit),
                           PID_COMMIT) == HAL_OK;
  HAL_FLASH_Lock();

  PidFlashRecord verify;
  return ok && slot_valid((const PidFlashRecord *)address, &verify) &&
         verify.magic == magic && memcmp(&verify.payload, params, params_size) == 0;
}

bool CarPidStore_Save(const CarPidParams *params) {
  return CarPid_ValidParams(params) && save_record(PID_MAGIC, params, sizeof(*params));
}

bool CarServoStore_Load(CarServoParams *params) {
  if (params == NULL) return false;
  PidFlashRecord latest;
  if (!latest_record(SERVO_MAGIC, &latest, NULL, NULL)) return false;
  *params = latest.payload.servo.params;
  return true;
}

bool CarServoStore_Matches(const CarServoParams *params) {
  if (!CarServo_ValidParams(params)) return false;
  CarServoParams saved;
  return CarServoStore_Load(&saved) && memcmp(&saved, params, sizeof(saved)) == 0;
}

bool CarServoStore_Save(const CarServoParams *params) {
  return CarServo_ValidParams(params) &&
         save_record(SERVO_MAGIC, params, sizeof(*params));
}
