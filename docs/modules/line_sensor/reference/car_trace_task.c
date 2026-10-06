#include "trace_task.h"
#include "app_motor.h"  // 包含电机控制函数
#include <math.h>
#include <string.h>

// 电机控制函数适配层 Motor control function adaptation layer
#define Contrl_Pwm    Motion_Set_Pwm    // PWM直接控制 PWM direct control
#define Contrl_Speed  Motion_Set_Speed  // 速度闭环控制 Speed closed-loop control

// 外部全局变量声明 External global variable declaration
extern uint16_t g_sensor_data[GRAYSCALE_SENSOR_CHANNELS];

/**
 * @brief 限制值在指定范围内
 *        Limit value within specified range
 */
static inline float clamp_float(float value, float min_val, float max_val) {
    if (value < min_val) return min_val;
    if (value > max_val) return max_val;
    return value;
}

static inline int16_t clamp_int16(int16_t value, int16_t min_val, int16_t max_val) {
    if (value < min_val) return min_val;
    if (value > max_val) return max_val;
    return value;
}

bool check_sensors_safe(line_following_t* controller, uint16_t* sensor_values) {
    /**
     * 上电安全锁检查，当传感器全亮或全灭时不启动小车，防止乱跑
     * Power-on safety lock check, do not start the car when the sensors are all on or all off to prevent random movement
     */
    uint16_t first_value = sensor_values[0];

    for (int i = 1; i < GRAYSCALE_SENSOR_CHANNELS; i++) {
        if (sensor_values[i] != first_value) {
            return true;  // 传感器值不全相同，安全 Sensor values are not all the same, safe
        }
    }

    return false;  // 传感器全亮或全灭，不安全 All sensors on or off, unsafe
}

float calculate_error(line_following_t* controller, uint16_t* sensor_values, uint16_t line_raw_value) {
    /**
     * 计算偏差值 Calculate the deviation value
     */
    float weighted_sum = 0.0f;
    int active_sensors = 0;

    for (int i = 0; i < GRAYSCALE_SENSOR_CHANNELS; i++) {
        if (sensor_values[i] == line_raw_value) {
            weighted_sum += controller->sensor_weights[i];
            active_sensors++;
        }
    }

    // 如果没有检测到线，返回上次偏差（丢线处理）
    // If no line is detected, return the last deviation (line loss handling)
    if (active_sensors == 0) {
        return controller->last_error;
    }

    // 计算加权平均偏差
    // Calculate weighted average deviation
    float error = weighted_sum / active_sensors;
    return error;
}

float pid_control(line_following_t* controller, float error) {
    /**
     * PID控制计算 PID control calculation
     */

    // 添加死区，忽略微小偏差 / Add dead zone to ignore small deviations
    if (fabsf(error) < 0.6f) {
        error = 0.0f;
    }

    // 检测过零点，清零积分 / Detect zero crossing, clear integral
    if ((controller->last_error > 0 && error < 0) ||
        (controller->last_error < 0 && error > 0)) {
        controller->integral = 0.0f;  // 偏差过零，清空积分/ Clear integral when deviation crosses zero
    }

    // 动态调整积分限幅 / Dynamically adjust integral limit
    float integral_limit;
    if (fabsf(error) > 3.0f) {          // 大偏差时 / Large deviation
        integral_limit = 80.0f;
    } else if (fabsf(error) > 1.5f) {   // 中等偏差时 / Medium deviation
        integral_limit = 50.0f;
    } else {                            // 小偏差时 / Small deviation
        integral_limit = 20.0f;
    }

    // 积分项，使用动态限幅 / Integral term with dynamic limit
    controller->integral += error;
    controller->integral = clamp_float(controller->integral, -integral_limit, integral_limit);

    // 微分项 / Derivative term
    float derivative = error - controller->last_error;

    // PID计算 / PID calculation
    float output = (controller->kp * error +
                   controller->ki * controller->integral +
                   controller->kd * derivative);

    // 更新上次偏差 / Update last error
    controller->last_error = error;

    return output;
}

void differential_speed_control(line_following_t* controller, float pid_output,
                                int16_t* left_speed, int16_t* right_speed) {
    /**
     * 差速控制 Differential speed control
     */
    int16_t left = controller->base_speed + (int16_t)pid_output;
    int16_t right = controller->base_speed - (int16_t)pid_output;

    // 速度限制 / Speed limit
    *left_speed = clamp_int16(left, -controller->max_speed, controller->max_speed);
    *right_speed = clamp_int16(right, -controller->max_speed, controller->max_speed);
}

void follow_line(line_following_t* controller, uint16_t* sensor_values,
                 uint16_t line_raw_value) {
    /**
     * 巡线主函数 Main line following function
     */

    // 检查安全锁 / Check safety lock
    if (controller->motor_locked) {
        if (check_sensors_safe(controller, sensor_values)) {
            controller->motor_locked = false;  // 解锁 / Unlock
        } else {
            Contrl_Speed(0, 0, 0, 0);  // 确保电机停止 / Ensure motors are stopped
            return;
        }
    }

    // 计算偏差 / Calculate deviation
    float error = calculate_error(controller, sensor_values, line_raw_value);

    // PID控制计算 / PID control calculation
    float pid_output = pid_control(controller, error);

    // 差速控制 / Differential speed control
    int16_t left_speed, right_speed;
    differential_speed_control(controller, pid_output, &left_speed, &right_speed);

    // 控制电机 (M1,M2为左轮，M3,M4为右轮) - 使用速度闭环控制
    // Control motors (M1,M2 are left wheels, M3,M4 are right wheels) - Using speed closed-loop control
    Contrl_Speed(left_speed, left_speed, right_speed, right_speed);
}
