/****************************************************************************************
*STM32      JDY31			 	OLED
*5V					5V					3V3
*GND				GND					GND
*PB6				RX							
*PB7				TX								
*PB8										SCL				
*PB9										SDA		
*
* hex发送01，板载LED亮
*    发送02，板载LED灭
*OLED可不接
*
*   HC06波特率9600；HC05波特率38400
*
****************************************************************************************/

#include "stm32f10x.h"                  // Device header
#include "Delay.h"
#include "OLED.h"
#include "Serial.h"
#include "LED.h"
#include "PWM.h"

uint8_t RxData;			//定义用于接收串口数据的变量
int HC=38400;        //HC05波特率38400；其他波特率9600

int main(void)
{
	/*模块初始化*/
	OLED_Init();		//OLED初始化
	LED_Init();
	/*显示静态字符串*/
	OLED_FOREVER();
	
	/*串口初始化*/
	Serial_Init();		//串口初始化
//	OLED_ShowString(1,2,"XX");
	while (1)
	{
		if (Serial_GetRxFlag() == 1)			//检查串口接收数据的标志位
		{
			OLED_FOREVER();
			RxData = Serial_GetRxData();		//获取串口接收的数据
			Serial_SendByte(RxData);			//串口将收到的数据回传回去，用于测试
			if(RxData==01)
			{
				OLED_FOREVER();
				OLED_ShowString(3,6,"OPEN");
				GPIO_ResetBits(GPIOC, GPIO_Pin_13);
			}else if(RxData==02)
			{
				OLED_FOREVER();
				OLED_ShowString(3,6,"CLOSE");
				GPIO_SetBits(GPIOC, GPIO_Pin_13);
			}
			OLED_ShowHexNum(2, 8, RxData, 2);	//显示串口接收的数据
		}
	}
}
