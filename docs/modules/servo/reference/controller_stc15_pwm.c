/*---------------------------------------------------------------------*/
/* --- STC MCU Limited ------------------------------------------------*/
/* --- STC15Fxx 系列 使用增强型PWM控制舞台灯光示例---------------------*/
/* --- Mobile: (86)13922805190 ----------------------------------------*/
/* --- Fax: 86-0513-55012956,55012947,55012969 ------------------------*/
/* --- Tel: 86-0513-55012928,55012929,55012966-------------------------*/
/* --- Web: www.STCMCU.com --------------------------------------------*/
/* --- Web: www.GXWMCU.com --------------------------------------------*/
/* 如果要在程序中使用此代码,请在程序中注明使用了STC的资料及程序        */
/* 如果要在文章中应用此代码,请在文章中注明使用了STC的资料及程序        */
/*---------------------------------------------------------------------*/

//本示例在Keil开发环境下请选择Intel的8058芯片型号进行编译
//若无特别说明,工作频率一般为11.0592MHz


#include "pwm.h"

#define CYCLE 1000

void pwm_init(unsigned short cycle){
    
//		P0M0 &= ~0xc0;
//    P0M1 &= ~0xc0;
//    P0 &= ~0xc0;                    //设置P0.6/.P0.7电平
//    
//		P2M0 |= 0x0e;
//    P2M1 &= ~0x0e;
//    P2 &= ~0x0e;                    //设置P2.1/P2.2/P2.3电平
//    
//		P3M0 |= 0x80;
//    P3M1 &= ~0x80;
//    P3 &= ~0x80;                    //设置P3.7电平

    P_SW2 |= 0x80;
    PWMCKS = 0x1F;
    PWMC = cycle;                   //设置PWM周期
    PWM2T1 = 1;
    PWM2T2 = 0;
    PWM2CR = 0x00;                  //PWM2输出到P3.7
    PWM3T1 = 1;
    PWM3T2 = 0;
    PWM3CR = 0x00;                  //PWM3输出到P2.1
    PWM4T1 = 1;
    PWM4T2 = 0;
    PWM4CR = 0x00;                  //PWM4输出到P2.2
    PWM5T1 = 1;
    PWM5T2 = 0;
    PWM5CR = 0x00;                  //PWM5输出到P2.3
    PWM6T1 = 1;
    PWM6T2 = 0;
    PWM6CR = 0x08;                  //PWM6输出到P0.7
    PWM7T1 = 1;
    PWM7T2 = 0;
    PWM7CR = 0x08;                  //PWM7输出到P0.6
    PWMCFG = 0x00;                  //配置PWM的输出初始电平
    PWMCR = 0x3f;                   //使能PWM信号输出
    PWMCR |= 0x80;                  //使能PWM模块
    P_SW2 &= ~0x80;
}

void PWM2_SetPwmWide(unsigned short Wide)
{
    if (Wide == 0)
    {
        PWMCR &= ~0x01;
        PWM2 = 0;
    }
    else if (Wide >= CYCLE)
    {
        PWMCR &= ~0x01;
        PWM2 = 1;
    }
    else
    {
        P_SW2 |= 0x80;
        PWM2T1 = Wide;
        P_SW2 &= ~0x80;
        PWMCR |= 0x01;
    }
}

void PWM3_SetPwmWide(unsigned short Wide)
{
    if (Wide == 0)
    {
        PWMCR &= ~0x02;
        PWM3 = 0;
    }
    else if (Wide >= CYCLE)
    {
        PWMCR &= ~0x02;
        PWM3 = 1;
    }
    else
    {
        P_SW2 |= 0x80;
        PWM3T1 = Wide;
        P_SW2 &= ~0x80;
        PWMCR |= 0x02;
    }
}

void PWM4_SetPwmWide(unsigned short Wide)
{
    if (Wide == 0)
    {
        PWMCR &= ~0x04;
        PWM4 = 0;
    }
    else if (Wide >= CYCLE)
    {
        PWMCR &= ~0x04;
        PWM4 = 1;
    }
    else
    {
        P_SW2 |= 0x80;
        PWM4T1 = Wide;
        P_SW2 &= ~0x80;
        PWMCR |= 0x04;
    }
}

void PWM5_SetPwmWide(unsigned short Wide)
{
    if (Wide == 0)
    {
        PWMCR &= ~0x08;
        PWM5 = 0;
    }
    else if (Wide >= CYCLE)
    {
        PWMCR &= ~0x08;
        PWM5 = 1;
    }
    else
    {
        P_SW2 |= 0x80;
        PWM5T1 = Wide;
        P_SW2 &= ~0x80;
        PWMCR |= 0x08;
    }
}

/*
void PWM6_SetPwmWide(unsigned short Wide)
{
    if (Wide == 0)
    {
        PWMCR &= ~0x10;
        PWM6 = 0;
    }
    else if (Wide == CYCLE)
    {
        PWMCR &= ~0x10;
        PWM6 = 1;
    }
    else
    {
        P_SW2 |= 0x80;
        PWM6T1 = Wide;
        P_SW2 &= ~0x80;
        PWMCR |= 0x10;
    }
}

void PWM7_SetPwmWide(unsigned short Wide)
{
    if (Wide == 0)
    {
        PWMCR &= ~0x20;
        PWM7 = 0;
    }
    else if (Wide == CYCLE)
    {
        PWMCR &= ~0x20;
        PWM7 = 1;
    }
    else
    {
        P_SW2 |= 0x80;
        PWM7T1 = Wide;
        P_SW2 &= ~0x80;
        PWMCR |= 0x20;
    }
}
*/
