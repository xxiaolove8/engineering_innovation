#ifndef CAR_HW_H
#define CAR_HW_H

#include "car_logic.h"
#include <stdbool.h>
#include <stdint.h>

bool CarHw_Init(void);
void CarHw_PollRange(uint32_t now_ms);
void CarHw_Snapshot(CarInputs *input, uint32_t now_ms);
void CarHw_Apply(const CarOutputs *output);
void CarHw_Stop(void);
void CarHw_EncoderDeltas(int32_t *left, int32_t *right);
bool CarHw_ReadLine(char *destination, unsigned capacity);
void CarHw_Send(const char *message);

#endif
