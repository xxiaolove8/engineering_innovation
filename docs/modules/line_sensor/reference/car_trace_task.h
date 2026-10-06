#ifndef __TRACE_TASK_H__
#define __TRACE_TASK_H__

#include <stdint.h>
#include <stdbool.h>
#include "grayscale_sensor.h"  // 包含传感器头文件，获取GRAYSCALE_SENSOR_CHANNELS定义

typedef struct {
    // PID参数 PID Parameters
    float kp;               // 比例系数 Proportional coefficient
    float ki;               // 积分系数 Integral coefficient
    float kd;               // 微分系数 Derivative coefficient

    float last_error;       // 上次偏差 Last error
    float integral;         // 积分累加 Integral accumulation

    // 控制参数 Control Parameters
    int16_t base_speed;     // 基础速度 Base speed
    int16_t max_speed;      // 最大速度 Max speed

    // 传感器权重 Sensor weights (8个传感器的位置权重)
    float sensor_weights[8];

    // 安全锁标志位 Safety lock flag
    bool motor_locked;      // 初始锁定电机，防止乱跑 Initially lock motors to prevent random movement

} line_following_t;

extern line_following_t g_line_controller;

void line_following_init(line_following_t* controller);
bool check_sensors_safe(line_following_t* controller, uint16_t* sensor_values);
float calculate_error(line_following_t* controller, uint16_t* sensor_values, uint16_t line_raw_value);
float pid_control(line_following_t* controller, float error);
void differential_speed_control(line_following_t* controller, float pid_output,
                                int16_t* left_speed, int16_t* right_speed);
void follow_line(line_following_t* controller, uint16_t* sensor_values,
                 uint16_t line_raw_value);

#endif
