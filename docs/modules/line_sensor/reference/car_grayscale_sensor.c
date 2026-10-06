#include "grayscale_sensor.h"


static void _delay_us(volatile uint32_t us)
{
    delay_us(us);
}

//选择传感器通道 select sensor channel
static void _select_channel(uint8_t channel)
{
    SENSOR_AD0_WRITE((channel >> 0) & 0x01);  // bit0 -> AD0
    SENSOR_AD1_WRITE((channel >> 1) & 0x01);  // bit1 -> AD1
    SENSOR_AD2_WRITE((channel >> 2) & 0x01);  // bit2 -> AD2
}

//读取OUT引脚的值 read the value of OUT pin
static uint16_t Read_OUT_value(void)
{
    return SENSOR_OUT_READ();
}

//初始化灰度传感器所需的GPIO / init GPIO for grayscale sensor
void Grayscale_Sensor_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStructure;

    // 使能GPIO时钟 Enable GPIO clock (GPIOF和GPIOG) Enable GPIO clock (GPIOF and GPIOG)
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOF | RCC_APB2Periph_GPIOG, ENABLE);

    // 初始化地址线 AD0(PF15), AD1(PF14), AD2(PF13) 为输出 Init address lines AD0(PF15), AD1(PF14), AD2(PF13) as output
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_13 | GPIO_Pin_14 | GPIO_Pin_15;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;      // 推挽输出 Push-pull output
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOF, &GPIO_InitStructure);

    // 初始化OUT引脚 PG0 为数字量输入 Init OUT pin PG0 as digital input
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_0;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN_FLOATING; // 浮空输入 Floating input
    GPIO_Init(GPIOG, &GPIO_InitStructure);
}

//读取所有8个通道的灰度值 read all 8 channels grayscale values
void Grayscale_Sensor_Read_All(uint16_t* sensor_values)
{
    uint8_t i;
    for (i = 0; i < GRAYSCALE_SENSOR_CHANNELS; i++)
    {
        _select_channel(i);
        _delay_us(50);
        sensor_values[i] = Read_OUT_value();
    }
}

//读取单个指定通道的灰度值 read single specified channel grayscale value
uint16_t Grayscale_Sensor_Read_Single(uint8_t channel)
{
    if (channel >= GRAYSCALE_SENSOR_CHANNELS)
    {
        return 0; // 无效通道 // Invalid channel
    }
    _select_channel(channel);
    _delay_us(50);
    return Read_OUT_value();
}

