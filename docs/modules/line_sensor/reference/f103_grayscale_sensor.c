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
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE); //使能PB端口时钟	Enable PB port clock
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_0|GPIO_Pin_1|GPIO_Pin_2;//PA0->AD0 PA1->AD1 PA2->AD2
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;      //推挽输出	Push-pull output
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	  //50M
	GPIO_Init(GPIOA, &GPIO_InitStructure);
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_3;//PA3->OUT
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN_FLOATING; // 浮空输入 Floating input
    GPIO_Init(GPIOA, &GPIO_InitStructure);
}

//读取所有8个通道的灰度值 read all 8 channels grayscale values
void Grayscale_Sensor_Read_All(uint16_t* sensor_values)
{
    uint8_t i;
    for (i = 0; i < GRAYSCALE_SENSOR_CHANNELS; i++)
    {
        _select_channel(i);
        _delay_us(500);
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
    _delay_us(500);
    return Read_OUT_value();
}

