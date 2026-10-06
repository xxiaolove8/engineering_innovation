#ifndef CAR_PID_STORE_H
#define CAR_PID_STORE_H

#include "car_pid.h"
#include "car_servo.h"

/* Sector 11 is reserved by STM32F407xx_FLASH.ld. Records are appended and
 * committed last, so an interrupted write leaves the previous record valid. */
bool CarPidStore_Load(CarPidParams *params);
bool CarPidStore_Save(const CarPidParams *params);
bool CarPidStore_Matches(const CarPidParams *params);

/* Servo calibration has its own record type in the same append-only sector.
 * Saving either parameter group preserves the other group's last good record. */
bool CarServoStore_Load(CarServoParams *params);
bool CarServoStore_Save(const CarServoParams *params);
bool CarServoStore_Matches(const CarServoParams *params);

#endif
