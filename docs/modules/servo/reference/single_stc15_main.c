/*
单片机：STC15W4K61S4/IAP15W4K61S4 内部晶振：22.1184	
*/
#include "stc15.h"

//舵机 IO 口定义 用P0的8个IO测试
sbit dj0 = P0^0;
sbit dj1 = P0^1;
sbit dj2 = P0^2;
sbit dj3 = P0^3;
sbit dj4 = P0^4;
sbit dj5 = P0^5;
sbit dj6 = P0^6;
sbit dj7 = P0^7;

void delay_ms(unsigned int t);		//简单的延时

void dj_io_init(void);				//舵机 IO 初始化
void dj_io_set(u8 index, u8 level);	//舵机 IO 电平设置
void timer1_init(void);				//舵机 定时器初始化
void timer1_reset(int t_us);		//舵机 定时器初值重装

//舵机脉冲数组
int duoji_pulse[8] = {1500,1500,1500,1500,1500,1500,1500,1500} , i;

void main(void) {
	//IO初始化
	dj_io_init();
	//舵机定时器初始化
	timer1_init();
    while (1) {
		for(i=0;i<8;i++) {
			duoji_pulse[i] = 1000;//循环把8个舵机位置设定到1000
		}
		delay_ms(1000);
		for(i=0;i<8;i++) {
			duoji_pulse[i] = 2000;//循环把8个舵机位置设定到2000
		}
		delay_ms(1000);
	}
}

void dj_io_init(void) {
	//设置标准IO
	P0M1=0x00;			           
	P0M0=0x00;
}

void dj_io_set(u8 index, u8 level) {
	switch(index) {
		case 0:dj0 = level;break;
		case 1:dj1 = level;break;
		case 2:dj2 = level;break;
		case 3:dj3 = level;break;
		case 4:dj4 = level;break;
		case 5:dj5 = level;break;
		case 6:dj6 = level;break;
		case 7:dj7 = level;break;
		default:break;
	}
}

void delay_ms(unsigned int t) {
	int t1;
	while(t--) {
		t1 = 3000;
		while(t1--);
	}
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


void timer1_reset(int t_us) {
	//本来应该x22.1184 但由于单片机用的内部晶振，有一定误差，调整到下面这个值 频率差不多50HZ
	TL1 = (int)(65536-20.4184*t_us);
	TH1 = (int)(65536-20.4184*t_us) >> 8;
}

void T1_IRQ(void) interrupt 3 {
	static volatile u8 flag = 0;
	static volatile u8 duoji_index1 = 0;
	int temp;

	if(duoji_index1 == 8) {
		duoji_index1 = 0;
	}
	
	if(!flag) {
		timer1_reset((unsigned int)(duoji_pulse[duoji_index1]));
		dj_io_set(duoji_index1, 1);
	} else {
		temp = 2500 - (unsigned int)(duoji_pulse[duoji_index1]);
		if(temp < 20)temp = 20;
		timer1_reset(temp);
		dj_io_set(duoji_index1, 0);
		duoji_index1 ++;
	}
	flag = !flag;
}

