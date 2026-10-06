#include <stdio.h>
#include "timer.h"
#include "global.h"
#include "io.h"

#define FOSC 22118400L  
#define T1MS (65536-FOSC/1000)      //1T模式
u32 systick_ms = 0;

u32 get_systick_ms(void) {
	return systick_ms;
} 

//1000微秒@22.1184MHz 自动重装模式
void timer0_init(void) {
	AUXR |= 0x80;		//定时器时钟1T模式
	TMOD &= 0xF0;		//设置定时器模式
	TL0 = 0x9A;		//设置定时初值
	TH0 = 0xA9;		//设置定时初值
	TF0 = 0;		//清除TF0标志
	TR0 = 1;		//定时器0开始计时
	ET0 = 1;			//定时器0开始计时
	EA	= 1;			//总开关
}

void timer1_init(void) {
	AUXR |= 0x40;		//定时器时钟1T模式
	TMOD &= 0x0F;		//设置定时器模式
	TMOD |= 0x10;		//设置定时器模式
	TL1 = 0x00;			//设置定时初值
	TH1 = 0x28;			//设置定时初值
	TF1 = 0;			//清除TF1标志
	TR1 = 1;			//定时器1开始计时
	ET1 = 1;			//定时器0开始计时
	EA	= 1;			//总开关
}

/*
void timer0_reset(int t_us) {
	TL0 = (int)(65536-22.1184*t_us);
	TH0 = (int)(65536-22.1184*t_us) >> 8;
}
*/

void timer1_reset(int t_us) {
	//本来应该x22.1184 但由于单片机用的内部晶振，有一定误差，调整到下面这个值 频率差不多50HZ
	TL1 = (int)(65536-20.4184*t_us);
	TH1 = (int)(65536-20.4184*t_us) >> 8;
}

float abs_float(float value) {
	if(value>0) {
		return value;
	}
	return (-value);
}

void duoji_inc_handle(u8 index) {	
	if(duoji_doing[index].inc != 0) {
		if(abs_float(duoji_doing[index].aim - duoji_doing[index].cur) <= abs_float(duoji_doing[index].inc + duoji_doing[index].inc)) {
			duoji_doing[index].cur = duoji_doing[index].aim;
			duoji_doing[index].inc = 0;
		} else {
			duoji_doing[index].cur += duoji_doing[index].inc;
		}
	}
}


void T0_IRQ(void) interrupt 1 {
	//timer0_reset(1000);
	systick_ms ++;
}

void T1_IRQ(void) interrupt 3 {

	static volatile u8 flag = 0;
	static volatile u8 duoji_index1 = 0;
	int temp;

	if(duoji_index1 == 8) {
		duoji_index1 = 0;
	}
	
	if(!flag) {
		timer1_reset((unsigned int)(duoji_doing[duoji_index1].cur));
		//timer1_reset(500*DJ_P);
		dj_io_set(duoji_index1, 1);
		duoji_inc_handle(duoji_index1);
	} else {
		temp = 2500 - (unsigned int)(duoji_doing[duoji_index1].cur);
		if(temp < 20)temp = 20;
		timer1_reset(temp);
		//timer1_reset(2000*DJ_P);
		dj_io_set(duoji_index1, 0);
		duoji_index1 ++;
	}
	flag = !flag;
	
}