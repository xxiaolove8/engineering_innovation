/*
	1、串口1调试		ok
	2、串口2调试		ok
	3、定时器0调试		ok
	4、定时器1调试		ok
	5、PS2手柄调试		ok
	6、4通道PWM调试		ok
	7、舵机调试			ok
	8、W25Q64存储调试	ok
	
	调试的过程：
	如上，一个一个模块调通，最后组合
	左边的目录结构就是正队每一个模块调试好做成一个模块文件，便于移植
	
	看程序方法：
	看程序的时候，从main文件的main函数看起
	基本的程序思路是
	主函数->各个模块初始化->大循环while(1) 
						  ->中断(串口、定时器等)
	大家在深究本程序时，建议大家先去了解各个模块的原理，然后看懂文件结构和程序结构，最后再细究算法问题
*/

#include <stdio.h>
#include <string.h>
#include "stc15.h"
#include "uart.h"
#include "delay.h"
#include "io.h"
#include "ps2.h"
#include "pwm.h"
#include "timer.h"
#include "w25q64.h"
#include "global.h"
#include "adc.h"


#define PS2_LED_RED  		0x73
#define PS2_LED_GRN  		0x41
#define PSX_BUTTON_NUM 		16
#define PS2_MAX_LEN 		64

#define CAR_PWM				0
#define VOL_CH				7


void led_beep_start(void);
void handle_ps2(void);
void handle_nled(void);
void handle_car(void);
void handle_uart(void);
void handle_button(void);
void parse_psx_buf(unsigned char *buf, unsigned char mode);
void parse_cmd(u8 *cmd);

void action_save(u8 *str);
int get_action_index(u8 *str);//获取动作序号
void print_group(int start, int end);
void int_exchange(int *int1, int *int2);
void erase_sector(int start, int end);

void do_group_once(int group_num); 
void handle_action(void);
u8 check_dj_state(void);//检查舵机状态，是否全部到位

void do_action(u8 *uart_receive_buf);
void replace_char(u8*str, u8 ch1, u8 ch2);
void car_pwm_set(int car_left, int car_right);
//void car_io_set(int car_left, int car_right);

void handle_uart_get(void);
void handle_warning(void);

#define CYCLE   1000     										//
u8 psx_buf[9]={0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}; 	//
code const char *pre_cmd_set_red[PSX_BUTTON_NUM] = {
	"<PS2_RED01:#005P2400T2000!^$DST:5!>",	//L2						  
	"<PS2_RED02:#005P0600T2000!^$DST:5!>",		//R2						  
	"<PS2_RED03:#004P0600T2000!^$DST:4!>",		//L1						  
	"<PS2_RED04:#004P2400T2000!^$DST:4!>",	//R1			
	"<PS2_RED05:#002P2400T2000!^$DST:2!>",	//RU						  
	"<PS2_RED06:#003P2400T2000!^$DST:3!>",	//RR						  
	"<PS2_RED07:#002P0600T2000!^$DST:2!>",		//RD						  
	"<PS2_RED08:#003P0600T2000!^$DST:3!>",		//RL				
	"<PS2_RED09:$!>",				//SE							  
	"<PS2_RED10:$DWD!>",					//AL						  
	"<PS2_RED11:$DWA!>",					//AR						  
	"<PS2_RED12:$DJR!>",					//ST			
	"<PS2_RED13:#001P0600T2000!^$DST:1!>",		//LU						  
	"<PS2_RED14:#000P0600T2000!^$DST:0!>",		//LR								  
	"<PS2_RED15:#001P2400T2000!^$DST:1!>",	//LD						  
	"<PS2_RED16:#000P2400T2000!^$DST:0!>",	//LL						
		
};

code const char *pre_cmd_set_GRNe[PSX_BUTTON_NUM] = {
	"<PS2_GRN01:#005P2400T2000!^$DST:5!>",	//L2						  
	"<PS2_GRN02:#005P0600T2000!^$DST:5!>",		//R2						  
	"<PS2_GRN03:#004P0600T2000!^$DST:4!>",		//L1						  
	"<PS2_GRN04:#004P2400T2000!^$DST:4!>",	//R1			
	"<PS2_GRN05:#002P2400T2000!^$DST:2!>",	//RU						  
	"<PS2_GRN06:#003P2400T2000!^$DST:3!>",	//RR						  
	"<PS2_GRN07:#002P0600T2000!^$DST:2!>",		//RD						  
	"<PS2_GRN08:#003P0600T2000!^$DST:3!>",		//RL				
	"<PS2_GRN09:$!>",				//SE							  
	"<PS2_GRN10:$!>",						//AL-NO						  
	"<PS2_GRN11:$!>",						//AR-NO						  
	"<PS2_GRN12:$DJR!>",					//ST			
	"<PS2_GRN13:#001P0600T2000!^$DST:1!>",		//LU						  
	"<PS2_GRN14:#000P0600T2000!^$DST:0!>",		//LR								  
	"<PS2_GRN15:#001P2400T2000!^$DST:1!>",	//LD						  
	"<PS2_GRN16:#000P2400T2000!^$DST:0!>",	//LL						  
};

u32 save_addr_sector = 0, save_action_index_bak = 0;
#define ACTION_SIZE 256

u8 group_do_ok = 1;
int do_start_index, do_time, group_num_start, group_num_end, group_num_times;

u8 car_dw = 1;

/*
	代码从main里开始执行
	在进入大循环while(1)之前都为各个模块的初始化
	最后在大循环处理持续执行的事情

	另外注意uart中的串口中断，接收数据处理
	timer中的定时器中断，舵机的脉冲收发就在那里
*/

void main(void) {
	//IO初始化
	io_init();
	
	//P10通道初始化，用于读取AD 电压值
	adc_init(VOL_CH);
	
	//全局变量初始化
	global_init();
	
	//手柄初始化
	psx_init();
	
	//串口1初始化
	uart1_init();
	uart1_close();
	uart1_open();
	
	//串口2初始化
	uart2_init();
	uart2_close();
	uart2_open();
	
	//串口1 2 发送数据测试OK
	uart1_send_str("uart1_init OK!");
	uart2_send_str("uart2_init OK!");
		
	//定时器0、1初始化
	timer0_init();
	timer1_init();
		
	//pwm模块初始化
	pwm_init(CYCLE);
	
	//存储器初始化，读取ID进行校验，若错误则长鸣不往下执行
	w25x_init();
	while(w25x_readId()!= W25Q64)beep_on();
	
	//LED灯和蜂鸣器闪烁表示初始化完毕
	led_beep_start();
			
    while (1) {
		//指示灯闪烁处理
		handle_nled();
		//手柄数据收发处理
		handle_ps2();
		//手柄按键处理
		handle_button();
		//手柄摇杆处理，映射到小车驱动上
		handle_car();
		//处理串口接收到的数据
		handle_uart();
		//处理执行动作组的问题
		handle_action();
		//处理串口在接收到存储数据后关闭定时器，防止影响接收
		handle_uart_get();
		//电压检测处理 P17为检测口
		handle_warning();
	}
}


void led_beep_start(void) {
	beep_on();nled_on();mdelay(100);beep_off();nled_off();mdelay(100);
	beep_on();nled_on();mdelay(100);beep_off();nled_off();mdelay(100);
	beep_on();nled_on();mdelay(100);beep_off();nled_off();mdelay(100);
	return;
}

void handle_nled(void) {
	static u32 systick_ms_bak = 0;
	
	if(get_systick_ms() - systick_ms_bak >= 500) {
		systick_ms_bak = get_systick_ms();
		nled_switch();
	}
}

void handle_ps2(void) {
	static u32 systick_ms_bak = 0;
	if(get_systick_ms() - systick_ms_bak < 20) {
		return;
	}
	systick_ms_bak = get_systick_ms();
	psx_write_read(psx_buf);
	
	
#if 0	
	sprintf(cmd_return, "0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x\r\n", 
	(int)psx_buf[0], (int)psx_buf[1], (int)psx_buf[2], (int)psx_buf[3],
	(int)psx_buf[4], (int)psx_buf[5], (int)psx_buf[6], (int)psx_buf[7], (int)psx_buf[8]);
	uart1_send_str(cmd_return);
#endif 	
	
	return;
}

int abs_int(int int1, int int2) {
	if(int1 > int2)return (int1-int2);
	return (int2-int1);
}

void handle_car(void) {
	static int car_left_bak=0, car_right_bak=0;
	int car_left, car_right;
	
	if(psx_buf[1] != PS2_LED_RED)return;
	car_right = (127 - psx_buf[8]) * 8;
	car_left = (psx_buf[6] - 127) * 8;
	
	if(abs_int(car_left_bak,car_left) < 20 && abs_int(car_right_bak,car_right) < 20)return;
	
	if(abs_int(car_left_bak,car_left) > 40)car_left_bak = car_left;
	if(abs_int(car_right_bak,car_right) > 40)car_right_bak = car_right;
	
	car_pwm_set(car_left_bak, car_right_bak);

}



void handle_button(void) {
	static unsigned char psx_button_bak[2] = {0};
	if((psx_button_bak[0] == psx_buf[3])
	&& (psx_button_bak[1] == psx_buf[4])) {			
	} else {
		parse_psx_buf(psx_buf+3, psx_buf[1]);
		psx_button_bak[0] = psx_buf[3];
		psx_button_bak[1] = psx_buf[4];
	}
	return;
}

void parse_psx_buf(unsigned char *buf, unsigned char mode) {
	u8 i, pos = 0;
	static u16 bak=0xffff, temp, temp2;
	temp = (buf[0]<<8) + buf[1];
	
	if(bak != temp) {
		temp2 = temp;
		temp &= bak;
		for(i=0;i<16;i++) {
			if((1<<i) & temp) {
			} else {
				if((1<<i) & bak) {	//press
															
					memset(uart_receive_buf, 0, sizeof(uart_receive_buf));					
					if(mode == PS2_LED_RED) {
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_red[i], strlen(pre_cmd_set_red[i]));
					} else if(mode == PS2_LED_GRN) {
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_GRNe[i], strlen(pre_cmd_set_GRNe[i]));
					} else continue;
					
					pos = str_contain_str(uart_receive_buf, "^");
					if(pos) uart_receive_buf[pos-1] = '\0';
					if(str_contain_str(uart_receive_buf, "$")) {
						//uart1_close();
						uart1_get_ok = 1;
						uart1_mode = 1;
						strcpy(cmd_return, uart_receive_buf+11);
						strcpy(uart_receive_buf, cmd_return);
					} else if(str_contain_str(uart_receive_buf, "#")) {
						//uart1_close();
						uart1_get_ok = 1;
						uart1_mode = 2;
						strcpy(cmd_return, uart_receive_buf+11);
						strcpy(uart_receive_buf, cmd_return);
					}
					
					uart1_send_str(uart_receive_buf);
					
					bak = 0xffff;
				} else {//release
										
					memset(uart_receive_buf, 0, sizeof(uart_receive_buf));					
					if(mode == PS2_LED_RED) {
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_red[i], strlen(pre_cmd_set_red[i]));
					} else if(mode == PS2_LED_GRN) {
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_GRNe[i], strlen(pre_cmd_set_GRNe[i]));
					} else continue;	
					
					pos = str_contain_str(uart_receive_buf, "^");
					if(pos) {
						if(str_contain_str(uart_receive_buf+pos, "$")) {
							//uart1_close();
							uart1_get_ok = 1;
							uart1_mode = 1;
							strcpy(cmd_return, uart_receive_buf+pos);
							cmd_return[strlen(cmd_return) - 1] = '\0';
							strcpy(uart_receive_buf, cmd_return);
						} else if(str_contain_str(uart_receive_buf+pos, "#")) {
							//uart1_close();
							uart1_get_ok = 1;
							uart1_mode = 2;
							strcpy(cmd_return, uart_receive_buf+pos);
							cmd_return[strlen(cmd_return) - 1] = '\0';
							strcpy(uart_receive_buf, cmd_return);
						}
						uart1_send_str(uart_receive_buf);
					}	
				}

			}
		}
		bak = temp2;
		beep_on();mdelay(50);beep_off();
	}	
	return;
}

void handle_uart(void) {
	if(uart1_get_ok) {
		if(uart1_mode == 1) {					//命令模式
			//uart1_send_str("cmd:");
			//uart1_send_str(uart_receive_buf);
			parse_cmd(uart_receive_buf);			
		} else if(uart1_mode == 2) {			//单个舵机模式
			//uart1_send_str("sig:");
			//uart1_send_str(uart_receive_buf);
			do_action(uart_receive_buf);
		} else if(uart1_mode == 3) {		//多个舵机模式
			//uart1_send_str("group:");
			//uart1_send_str(uart_receive_buf);
			//总线下发
			do_action(uart_receive_buf);
		} else if(uart1_mode == 4) {		//保存模式
			//uart1_send_str("save:");
			//uart1_send_str(uart_receive_buf);
			action_save(uart_receive_buf);
		} 
		uart1_mode = 0;
		uart1_get_ok = 0;
		//uart1_open();
	}

	return;
}

/*
	$DST!
	$DST:x!
	$RST!
	$CGP:%d-%d!
	$DEG:%d-%d!
	$DGS:x!
	$DGT:%d-%d,%d!
	$DCR:%d,%d!
	$DWA!
	$DWD!
	$DJR!
	$GETA!
*/

void parse_cmd(u8 *cmd) {
	//u32 uint1;
	u16 pos, i, index;
	int int1, int2;
	
	//uart1_send_str(cmd);
	
	if(pos = str_contain_str(uart_receive_buf, "$DST!"), pos) {
		group_do_ok  = 1;
		for(i=0;i<DJ_NUM;i++) {
			duoji_doing[i].inc = 0;	
			duoji_doing[i].aim = duoji_doing[i].cur;
		}
		zx_uart_send_str("#255PDST!");
	} else if(pos = str_contain_str(uart_receive_buf, "$DST:"), pos) {
		if(sscanf(cmd, "$DST:%d!", &index)) {
			duoji_doing[index].inc = 0;	
			duoji_doing[index].aim = duoji_doing[index].cur;
			sprintf(cmd_return, "#%03dPDST!", (int)index);
			zx_uart_send_str(cmd_return);
		}
		
		
	} else if(pos = str_contain_str(uart_receive_buf, "$RST!"), pos) {		
		IAP_CONTR = 0X20;
	//存储的扇区 编号 W25Q64 总共有 8*1024/4 = 2048
	} else if(pos = str_contain_str(uart_receive_buf, "$CGP:"), pos) {		
		if(sscanf(cmd, "$CGP:%d-%d!", &int1, &int2)) {
			print_group(int1, int2);
		}
	} else if(pos = str_contain_str(uart_receive_buf, "$DEG:"), pos) {		
		if(sscanf(cmd, "$DEG:%d-%d!", &int1, &int2)) {
			erase_sector(int1, int2);
		}
	} else if(pos = str_contain_str(uart_receive_buf, "$DGS:"), pos) {		
		if(sscanf(cmd, "$DGS:%d!", &int1)) {
			do_group_once(int1);
			group_do_ok = 1;
		}
	} else if(pos = str_contain_str(uart_receive_buf, "$DGT:"), pos) {		
		if(sscanf(cmd, "$DGT:%d-%d,%d!", &group_num_start, &group_num_end, &group_num_times)) {
			if(group_num_start != group_num_end) {
				do_start_index = group_num_start;
				group_do_ok = 0;
			} else {
				do_group_once(group_num_start);
			}
			do_time = group_num_times;
		}
	} else if(pos = str_contain_str(uart_receive_buf, "$DCR:"), pos) {		
		if(sscanf(cmd, "$DCR:%d,%d!", &int1, &int2)) {
//#ifdef CAR_PWM
			car_pwm_set(int1, int2);
//#else
			//car_io_set(int1, int2);
			
//#endif	
		}
	} else if(pos = str_contain_str(uart_receive_buf, "$DWA!"), pos) {		
		car_dw--;
		if(car_dw == 0)car_dw = 1;
		beep_on();mdelay(100);beep_off();
	} else if(pos = str_contain_str(uart_receive_buf, "$DWD!"), pos) {		
		car_dw++;
		if(car_dw == 4)car_dw = 3;
		beep_on();mdelay(100);beep_off();
	} else if(pos = str_contain_str(uart_receive_buf, "$CAR_FARWARD!"), pos) {		
		car_pwm_set(1000, 1000);
	} else if(pos = str_contain_str(uart_receive_buf, "$CAR_BACKWARD!"), pos) {		
		car_pwm_set(-1000, -1000);
	} else if(pos = str_contain_str(uart_receive_buf, "$CAR_LEFT!"), pos) {		
		car_pwm_set(-1000, 1000);
	} else if(pos = str_contain_str(uart_receive_buf, "$CAR_RIGHT!"), pos) {		
		car_pwm_set(1000, -1000);
	} else if(pos = str_contain_str(uart_receive_buf, "$DJR!"), pos) {	
		zx_uart_send_str("#255P1500T2000!");		
		for(i=0;i<DJ_NUM;i++) {
			duoji_doing[i].aim  = 1500;
			duoji_doing[i].time = 2000;
			duoji_doing[i].inc = (duoji_doing[i].aim -  duoji_doing[i].cur) / (duoji_doing[i].time/20.000);
		}
	} else if(pos = str_contain_str(uart_receive_buf, "$GETA!"), pos) {		
		uart1_send_str("AAA");
	} else {
		
	}
}



void action_save(u8 *str) {
	int action_index = 0;
	
	//uart1_send_str(uart_receive_buf);
	
	action_index = get_action_index(str);
	//<G0001#001...>
	if((action_index == -1) || str[6] != '#'){
	//if( action_index == -1 ){
		uart1_send_str("E");
		return;
	}
	//save_action_index_bak++;
	if(action_index*ACTION_SIZE % W25Q64_SECTOR_SIZE == 0)w25x_erase_sector(action_index*ACTION_SIZE/W25Q64_SECTOR_SIZE);
	replace_char(str, '<', '{');
	replace_char(str, '>', '}');
	w25x_write(str, action_index*ACTION_SIZE, strlen(str) + 1);
	uart1_send_str(str);
	uart1_send_str("A");
	return;	
}

int get_action_index(u8 *str) {
	int index = 0;
	//uart_send_str(str);
	while(*str) {
		if(*str == 'G') {
			str++;
			while((*str != '#') && (*str != '$')) {
				index = index*10 + *str-'0';
				str++;	
			}
			return index;
		} else {
			str++;
		}
	}
	return -1;
}

void print_group(int start, int end) {
	if(start > end) {
		int_exchange(&start, &end);
	}
	for(;start<=end;start++) {
		memset(uart_receive_buf, 0, sizeof(uart_receive_buf));
		w25x_read(uart_receive_buf, start*ACTION_SIZE, ACTION_SIZE);
		uart1_send_str(uart_receive_buf);
		uart1_send_str("\r\n");
	}
}


void int_exchange(int *int1, int *int2) {
	int int_temp;
	int_temp = *int1;
	*int1 = *int2;
	*int2 = int_temp;
}

void erase_sector(int start, int end) {
	if(start > end) {
		int_exchange(&start, &end);
	}
	if(end >= 127)end = 127;
	for(;start<=end;start++) {
		SpiFlashEraseSector(start);
		sprintf(cmd_return, "$Erase %d OK!", start);
		uart1_send_str(cmd_return);
	}
	save_action_index_bak = 0;
}



void do_group_once(int group_num) {
	//uart1_close();
	memset(uart_receive_buf, 0, sizeof(uart_receive_buf));
	w25x_read(uart_receive_buf, group_num*ACTION_SIZE, ACTION_SIZE);
	do_action(uart_receive_buf);
	sprintf(cmd_return, "do_group_once %d OK\r\n", group_num);
	uart1_send_str(cmd_return);
	//uart1_open();
}



void handle_action(void) {
	if(check_dj_state() == 0 && group_do_ok == 0) {
		do_group_once(do_start_index);
		
		if(group_num_start<group_num_end) {
			if(do_start_index == group_num_end) {
				do_start_index = group_num_start;
				if(group_num_times != 0) {
					do_time--;
					if(do_time == 0) {
						group_do_ok = 1;
					}
					uart1_send_str("$Group Do ok!\r\n");
				}
				return;
			}
			do_start_index++;
		} else {
			if(do_start_index == group_num_end) {
				do_start_index = group_num_start;
				if(group_num_times != 0) {
					do_time--;
					if(do_time == 0) {
						group_do_ok = 1;
					}
					uart1_send_str("$Group Do ok!\r\n");
				}
				return;
			}
			do_start_index--;
		}
	}
	
}

u8 check_dj_state(void) {
	int i;
	float inc = 0;
	for(i=0;i<DJ_NUM;i++) {
		inc += duoji_doing[i].inc;
		if(inc)return 1;
	}
	return 0;
}

void do_action(u8 *uart_receive_buf) {
	u16 index,  time,i, lst_i, parse_ok;
	float pwm;
	zx_uart_send_str(uart_receive_buf);
	zx_uart_send_str("\r\n");
	i = 0;parse_ok = 0;
	while(uart_receive_buf[i]) {
		if(uart_receive_buf[i] == '#') {
			lst_i = i;
			index = 0;i++;
			while(uart_receive_buf[i] && uart_receive_buf[i] != 'P') {
				index = index*10 + uart_receive_buf[i]-'0';i++;
			}
		} else if(uart_receive_buf[i] == 'P') {
			pwm = 0;i++;
			while(uart_receive_buf[i] && uart_receive_buf[i] != 'T') {
				pwm = pwm*10 + uart_receive_buf[i]-'0';i++;
			}
		} else if(uart_receive_buf[i] == 'T') {
			time = 0;i++;
			while(uart_receive_buf[i] && uart_receive_buf[i] != '!') {
				time = time*10 + uart_receive_buf[i]-'0';i++;
			}
			
			/*if(i-lst_i != 14){
				continue;
			}*/
			
			if(index < DJ_NUM && (pwm<=2500)&& (pwm>=500) && (time<10000)) {
				//duoji_doing[index].inc = 0;
				if(duoji_doing[index].cur == pwm){
					duoji_doing[index].aim = pwm+0.1;
				} else {
					duoji_doing[index].aim = pwm;
				}
				if(time < 20)time = 20;
				
				duoji_doing[index].time = time;
				duoji_doing[index].inc = (duoji_doing[index].aim -  duoji_doing[index].cur) / (duoji_doing[index].time/20.000);
			}

			//sprintf(cmd_return, "#%dP%dT%d! %f \r\n", index, pwm, time, duoji_doing[index].inc);
			//uart1_send_str(cmd_return);
			
		} else {
			i++;
		}
	}	
}

void replace_char(u8*str, u8 ch1, u8 ch2) {
	while(*str) {
		if(*str == ch1) {
			*str = ch2;
		} 
		str++;
	}
	return;
}

void car_pwm_set(int car_left, int car_right) {
	
	if(car_left >= CYCLE)car_left = CYCLE-1;
	else if(car_left <= -CYCLE)car_left = -CYCLE+1;
	else if(car_left == 0)car_left = 1;
	
	if(car_right >= CYCLE)car_right = CYCLE-1;
	else if(car_right <= -CYCLE)car_right = -CYCLE+1;
	else if(car_right == 0)car_right = 1;
	
	//car_left = car_left/car_dw;
	//car_right = car_right/car_dw;
	
	if(car_left>0) {
		PWM2_SetPwmWide(car_left);
		PWM3_SetPwmWide(0);
	} else {
		PWM2_SetPwmWide(0);
		PWM3_SetPwmWide(-car_left);
	}
	
	if(car_right>0) {
		PWM4_SetPwmWide(car_right);
		PWM5_SetPwmWide(0);		
	} else {
		PWM4_SetPwmWide(0);
		PWM5_SetPwmWide(-car_right);
	}	
	
	return;
}

/*
void car_io_set(int car_left, int car_right) {

	sprintf(cmd_return, "car_io_set: %d,%d\r\n", car_left, car_right);
	uart1_send_str(cmd_return);
	
	
	if(car_left>100) {
		pwm4_io = 1;
		pwm5_io = 0;
	} else if(car_left<-100) {
		pwm4_io = 0;
		pwm5_io = 1;
	} else {
		pwm4_io = 0;
		pwm5_io = 0;
	}	
	
		if(car_right>100) {
		pwm2_io = 1;
		pwm3_io = 0;
	} else if(car_right<-100) {
		pwm2_io = 0;
		pwm3_io = 1;
	} else {
		pwm2_io = 0;
		pwm3_io = 0;
	}
	
}
*/

void handle_uart_get(void) {
	static u8 do_once1 = 0, do_once2 = 0;
	if(get_systick_ms() - get_uart_timeout() > 100) {
		if(!do_once1) {
			timer1_open();
			do_once1 = 1;
			do_once2 = 0;
		}
	} else {
		if(!do_once2) {
			timer1_close();
			do_once1 = 0;
			do_once2 = 1;
		}
	}
}

void handle_warning(void) {
	static u8 flag = 0, flag_count = 0;
	static u32 systick_ms_bak=0;
	static unsigned short adc7_value;
	if(get_systick_ms() - systick_ms_bak < 500)return;
	systick_ms_bak = get_systick_ms();
	adc7_value = adc_read(VOL_CH);
	
	if(((adc7_value/1023.0) * 5.0 * 4 > 5.2) && ((adc7_value/1023.0) * 5.0 * 4 < 6.5)) {
	//if((adc7_value/1023.0) * 5.0 * 4 < 6.5) {
		if(flag) {
			beep_on();
		} else {
			beep_off();
		}
		flag = !flag;
		flag_count = 0;
		sprintf(cmd_return, "ADC=%d\n", (int)adc7_value); 
		uart1_send_str(cmd_return);
	} else {
		flag_count++;
		if(flag_count == 1) {
			beep_off();
		} else {
			flag_count = 0;
		}
	}
	
	
}