/***************************************************************

总线马达ID  24 25 26 27
总线MP3	ID	28
			
***************************************************************/

#include "tb_rcc.h"
#include "tb_gpio.h"
#include "tb_global.h"
#include "tb_delay.h"
#include "tb_type.h"
#include "tb_usart.h"
#include "tb_timer.h"

#include "ADC.h"
#include "PS2_SONY.h"
#include "w25q64.h"

#include <stdio.h>
#include <string.h>
#include <math.h>

#define CYCLE 1000
#define PS2_LED_RED  		0x73
#define PS2_LED_GRN  		0x41
#define PSX_BUTTON_NUM 		16
#define PS2_MAX_LEN 		64

#define MD_ID1	24
#define MD_ID2	25
#define MD_ID3	26
#define MD_ID4	27

void system_init(void);
void beep_led_dis_init(void);
void handle_nled(void);
void soft_reset(void);

void car_pwm_set(int car_left, int car_right);
void handle_ps2(void);
void handle_button(void);
void parse_psx_buf(unsigned char *buf, unsigned char mode);
void handle_car(void);

void handle_uart(void);
void parse_cmd(u8 *cmd);

void action_save(u8 *str);
int get_action_index(u8 *str);
void print_group(int start, int end);
void int_exchange(int *int1, int *int2);
void erase_sector(int start, int end);

void do_group_once(int group_num); 
void handle_action(void);
u8 check_dj_state(void);

void do_action(u8 *uart_receive_buf);
void replace_char(u8*str, u8 ch1, u8 ch2);
//void car_io_set(int car_left, int car_right);



u8 psx_buf[9]={0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}; 	//
const char *pre_cmd_set_red[PSX_BUTTON_NUM] = {
	"<PS2_RED01:#005P0600T2000!^$DST:5!>",	//L2						  
	"<PS2_RED02:#005P2400T2000!^$DST:5!>",	//R2						  
	"<PS2_RED03:#004P0600T2000!^$DST:4!>",	//L1						  
	"<PS2_RED04:#004P2400T2000!^$DST:4!>",	//R1			
	"<PS2_RED05:#002P2400T2000!^$DST:2!>",	//RU						  
	"<PS2_RED06:#003P0600T2000!^$DST:3!>",	//RR						  
	"<PS2_RED07:#002P0600T2000!^$DST:2!>",	//RD						  
	"<PS2_RED08:#003P2400T2000!^$DST:3!>",	//RL				
	"<PS2_RED09:$DGT:0-60,1!>",			//SE							  
	"<PS2_RED10:$DWD!>",					//AL						  
	"<PS2_RED11:$DWA!>",					//AR						  
	"<PS2_RED12:$DJR!>",					//ST			
	"<PS2_RED13:#001P0600T2000!^$DST:1!>",	//LU						  
	"<PS2_RED14:#000P0600T2000!^$DST:0!>",	//LR								  
	"<PS2_RED15:#001P2400T2000!^$DST:1!>",	//LD						  
	"<PS2_RED16:#000P2400T2000!^$DST:0!>",	//LL						
		
};

const char *pre_cmd_set_grn[PSX_BUTTON_NUM] = {
	"<PS2_GRN01:$!>",	//L2						  
	"<PS2_GRN02:$!>",	//R2						  
	"<PS2_GRN03:$!>",	//L1						  
	"<PS2_GRN04:$!>",	//R1			
	"<PS2_GRN05:$!>",	//RU						  
	"<PS2_GRN06:$!>",	//RR						  
	"<PS2_GRN07:$!>",	//RD						  
	"<PS2_GRN08:$!>",	//RL				
	"<PS2_GRN09:$!>",			//SE							  
	"<PS2_GRN10:$!>",					//AL-NO						  
	"<PS2_GRN11:$!>",					//AR-NO						  
	"<PS2_GRN12:$!>",				//ST			
	"<PS2_GRN13:$!>",	//LU						  
	"<PS2_GRN14:$!>",	//LR								  
	"<PS2_GRN15:$!>",	//LD						  
	"<PS2_GRN16:$!>",	//LL						  
};

u32 save_addr_sector = 0, save_action_index_bak = 0;
#define ACTION_SIZE 0x80

u8 group_do_ok = 1;
int do_start_index, do_time, group_num_start, group_num_end, group_num_times;

u8 car_dw = 1;


/*-------------------------------------------------------------------------------------------------------
*  程序从这里执行				
*  这个启动代码 完成时钟配置 使用外部晶振作为STM32的运行时钟 并倍频到72M最快的执行速率
-------------------------------------------------------------------------------------------------------*/

int main(void) {	
	tb_rcc_init();
	tb_gpio_init();
	tb_global_init();
	nled_init();
	beep_init();
	dj_io_init();
		
	//w25q64 init
	W25Q_Init();	//动作组存储芯片初始化
	if(W25Q_TYPE != W25Q64){
		while(1)beep_on();
	}
		
	//ADC_init();
	PSX_init();	//手柄初始化
	
	//舵机 定时器初始化
	TIM2_Int_Init(20000, 71);
	
	//小车 pwm 初始化
	TIM3_Pwm_Init(1000, 239);
	TIM4_Pwm_Init(1000, 239);
	car_pwm_set(0,0);

	
	//串口初始化
	tb_usart1_init(115200);
	uart1_open();
	
	tb_usart2_init(115200);
	uart2_open();
	
	tb_usart3_init(115200);
	uart3_open();
	
	tb_interrupt_open();
	
	//总线输出
	zx_uart_send_str((u8 *)"#255P1500T2000!");
	
	//系统滴答时钟初始化	
	SysTick_Int_Init();	
	
	//蜂鸣器LED 名叫闪烁 示意系统启动
	beep_led_dis_init();
	while(1) {			
		handle_nled();		//处理信号灯
		handle_ps2();		//处理手柄
		handle_button();	//处理手柄按钮
		handle_car();		//处理摇杆控制小车
		handle_uart();		//处理串口接收数据
		handle_action();	//处理动作组
	}
}

void beep_led_dis_init(void) {
	beep_on();nled_on();tb_delay_ms(100);beep_off();nled_off();tb_delay_ms(100);
	beep_on();nled_on();tb_delay_ms(100);beep_off();nled_off();tb_delay_ms(100);
	beep_on();nled_on();tb_delay_ms(100);beep_off();nled_off();tb_delay_ms(100);
}

void handle_nled(void) {
	static u32 time_count=0;
	static u8 flag = 0;
	if(systick_ms-time_count > 1000)  {
		time_count = systick_ms;
		if(flag) {
			nled_on();
		} else {
			nled_off();
		}
		flag= ~flag;
	}
}


void soft_reset(void) {
	__set_FAULTMASK(1);     
	NVIC_SystemReset();
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

	
	if(car_right>0) {
		TIM_SetCompare4(TIM4,1);
		TIM_SetCompare3(TIM4,car_right);
	} else {
		TIM_SetCompare4(TIM4,-car_right);
		TIM_SetCompare3(TIM4,1);
		
	}

	if(car_left>0) {
		TIM_SetCompare4(TIM3,1);
		TIM_SetCompare3(TIM3,car_left);
	} else {
		TIM_SetCompare4(TIM3,-car_left);
		TIM_SetCompare3(TIM3,1);
		
	}	
	
//	sprintf((char *)cmd_return, "#024P%dT0!#025P%dT0!", 
//	(int)(1500+car_left), (int)(1500+car_right));
//	zx_uart_send_str(cmd_return);
	
//	sprintf((char *)cmd_return, "#%dP%dT0!#%dP%dT0!", 
//	MD_ID3, 1500+car_left, MD_ID4, 1500+car_right);
//	zx_uart_send_str(cmd_return);
	
	return;
}



void handle_ps2(void) {
	static u32 systick_ms_bak = 0;
	if(systick_ms - systick_ms_bak < 20) {
		return;
	}
	systick_ms_bak = systick_ms;
	psx_write_read(psx_buf);
	
#if 0	
	sprintf((char *)cmd_return, "0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x,0x%02x\r\n", 
	(int)psx_buf[0], (int)psx_buf[1], (int)psx_buf[2], (int)psx_buf[3],
	(int)psx_buf[4], (int)psx_buf[5], (int)psx_buf[6], (int)psx_buf[7], (int)psx_buf[8]);
	uart1_send_str(cmd_return);
#endif 	
	
	return;
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
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_grn[i], strlen(pre_cmd_set_grn[i]));
					} else continue;
					
					pos = str_contain_str(uart_receive_buf, (u8 *)"^");
					if(pos) uart_receive_buf[pos-1] = '\0';
					if(str_contain_str(uart_receive_buf, (u8 *)"$")) {
						uart1_close();
						uart1_get_ok = 0;
						strcpy((char *)cmd_return, (char *)uart_receive_buf+11);
						strcpy((char *)uart_receive_buf, (char *)cmd_return);
						uart1_get_ok = 1;
						uart1_mode = 1;
					} else if(str_contain_str(uart_receive_buf, (u8 *)"#")) {
						uart1_close();
						uart1_get_ok = 0;
						strcpy((char *)cmd_return, (char *)uart_receive_buf+11);
						strcpy((char *)uart_receive_buf,(char *) cmd_return);
						uart1_get_ok = 1;
						uart1_mode = 2;
					}
					
					//uart1_send_str(uart_receive_buf);
					bak = 0xffff;
				} else {//release
										
					memset(uart_receive_buf, 0, sizeof(uart_receive_buf));					
					if(mode == PS2_LED_RED) {
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_red[i], strlen(pre_cmd_set_red[i]));
					} else if(mode == PS2_LED_GRN) {
						memcpy((char *)uart_receive_buf, (char *)pre_cmd_set_grn[i], strlen(pre_cmd_set_grn[i]));
					} else continue;	
					
					pos = str_contain_str(uart_receive_buf, (u8 *)"^");
					if(pos) {
						if(str_contain_str(uart_receive_buf+pos, (u8 *)"$")) {
							//uart1_close();
							//uart1_get_ok = 0;
							strcpy((char *)cmd_return, (char *)uart_receive_buf+pos);
							cmd_return[strlen((char *)cmd_return) - 1] = '\0';
							strcpy((char *)uart_receive_buf, (char *)cmd_return);
							parse_cmd(uart_receive_buf);
							//uart1_get_ok = 1;
							//uart1_mode = 1;
						} else if(str_contain_str(uart_receive_buf+pos, (u8 *)"#")) {
							//uart1_close();
							//uart1_get_ok = 0;
							strcpy((char *)cmd_return, (char *)uart_receive_buf+pos);
							cmd_return[strlen((char *)cmd_return) - 1] = '\0';
							strcpy((char *)uart_receive_buf, (char *)cmd_return);
							do_action(uart_receive_buf);
							//uart1_get_ok = 1;
							//uart1_mode = 2;
						}
						//uart1_send_str(uart_receive_buf);
					}	
				}

			}
		}
		bak = temp2;
		beep_on();mdelay(10);beep_off();
	}	
	return;
}
int abs_int(int int1) {
	if(int1 > 0)return int1;
	return (-int1);
}
void handle_car(void) {
	static int car_left, car_right, car_left_bak, car_right_bak;
	
	if(psx_buf[1] != PS2_LED_RED)return;
	
	if(abs_int(127 - psx_buf[8]) < 5 )psx_buf[8] = 127;
	if(abs_int(127 - psx_buf[6]) < 5 )psx_buf[6] = 127;
	
	car_left = (127 - psx_buf[8]) * 8;
	car_right = (127 - psx_buf[6]) * 8;
	
//	if(abs_int(car_left_bak-car_left) < 20 && abs_int(car_right_bak-car_right) < 20)return;
//	
//	if(abs_int(car_left_bak-car_left) > 40)car_left_bak = car_left;
//	if(abs_int(car_right_bak-car_right) > 40)car_right_bak = car_right;
	
	if(car_left != car_left_bak || car_right != car_right_bak) {
		car_pwm_set(car_left, car_right);
		car_left_bak = car_left;
		car_right_bak = car_right;
	}
}

void handle_uart(void) {
	if(uart1_get_ok) {
		if(uart1_mode == 1) {					//命令模式
			//uart1_send_str("cmd:");
			//uart1_send_str(uart_receive_buf);
			parse_cmd(uart_receive_buf);			
		} else if(uart1_mode == 2) {			//单个舵机调试
			//uart1_send_str("sig:");
			//uart1_send_str(uart_receive_buf);
			do_action(uart_receive_buf);
		} else if(uart1_mode == 3) {		//多路舵机调试
			//uart1_send_str("group:");
			//uart1_send_str(uart_receive_buf);
			do_action(uart_receive_buf);
		} else if(uart1_mode == 4) {		//存储模式
			//uart1_send_str("save:");
			//uart1_send_str(uart_receive_buf);
			action_save(uart_receive_buf);
		} 
		uart1_mode = 0;
		uart1_get_ok = 0;
		uart1_open();
	}

	return;
}


/*
	$DST!
	$DST:x!
	$RST!
	$SADR:x!
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
	int pos, i, index, int1, int2;
	
	//uart1_send_str(cmd);
	
	if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DST!"), pos) {
		group_do_ok  = 1;
		for(i=0;i<DJ_NUM;i++) {
			duoji_doing[i].inc = 0;	
			duoji_doing[i].aim = duoji_doing[i].cur;
		}
		zx_uart_send_str((u8 *)"#255PDST!");
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DST:"), pos) {
		if(sscanf((char *)cmd, "$DST:%d!", &index)) {
			duoji_doing[index].inc = 0;	
			duoji_doing[index].aim = duoji_doing[index].cur;
			sprintf((char *)cmd_return, "#%03dPDST!\r\n", (int)index);
			zx_uart_send_str(cmd_return);
			memset(cmd_return, 0, sizeof(cmd_return));
		}
		
		
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$RST!"), pos) {		

		//????? ?? W25Q64 ??? 8*1024/4 = 2048
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$CGP:"), pos) {		
		if(sscanf((char *)cmd, "$CGP:%d-%d!", &int1, &int2)) {
			print_group(int1, int2);
		}
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DEG:"), pos) {		
		if(sscanf((char *)cmd, "$DEG:%d-%d!", &int1, &int2)) {
			erase_sector(int1, int2);
		}
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DGS:"), pos) {		
		if(sscanf((char *)cmd, "$DGS:%d!", &int1)) {
			do_group_once(int1);
			group_do_ok = 1;
		}
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DGT:"), pos) {		
		if(sscanf((char *)cmd, "$DGT:%d-%d,%d!", &group_num_start, &group_num_end, &group_num_times)) {
			if(group_num_start != group_num_end) {
				do_start_index = group_num_start;
			} else {
				do_group_once(group_num_start);
			}
			do_time = group_num_times;
			group_do_ok = 0;			
		}
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DCR:"), pos) {		
		if(sscanf((char *)cmd, "$DCR:%d,%d!", &int1, &int2)) {
			car_pwm_set(int1, int2);	
		}
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DWA!"), pos) {		
		car_dw--;
		if(car_dw == 0)car_dw = 1;
		beep_on();mdelay(100);beep_off();
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DWD!"), pos) {		
		car_dw++;
		if(car_dw == 4)car_dw = 3;
		beep_on();mdelay(100);beep_off();
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$CAR_FARWARD!"), pos) {		
		car_pwm_set(1000, 1000);
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$CAR_BACKWARD!"), pos) {		
		car_pwm_set(-1000, -1000);
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$CAR_LEFT!"), pos) {		
		car_pwm_set(1000, -1000);
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$CAR_RIGHT!"), pos) {		
		car_pwm_set(-1000, 1000);
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$DJR!"), pos) {	
		zx_uart_send_str((u8 *)"#255P1500T2000!\r\n");
		for(i=0;i<DJ_NUM;i++) {
			duoji_doing[i].aim = 1500;
			duoji_doing[i].time = 2000;
			duoji_doing[i].inc = (duoji_doing[i].aim -  duoji_doing[i].cur) / (duoji_doing[i].time/20.000);
		}
	} else if(pos = str_contain_str(uart_receive_buf, (u8 *)"$GETA!"), pos) {		
		uart1_send_str((u8 *)"AAA");
	} else {
		
	}
}



void action_save(u8 *str) {
	int action_index = 0;
	action_index = get_action_index(str);
	if((action_index == -1) || str[6] != '#'){
		uart1_send_str((u8 *)"E");
		return;
	}
	//save_action_index_bak++;
	if(action_index*ACTION_SIZE % W25Q64_SECTOR_SIZE == 0)w25x_erase_sector(action_index*ACTION_SIZE);
	replace_char(str, '<', '{');
	replace_char(str, '>', '}');
	w25x_write(str, save_addr_sector*W25Q64_SECTOR_SIZE + action_index*ACTION_SIZE, strlen((char *)str) + 1);
	//uart1_send_str(uart_receive_buf);
	uart1_send_str((u8 *)"A");
	return;	
}

int get_action_index(u8 *str) {
	u16 index = 0;
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
		w25x_read(uart_receive_buf, save_addr_sector*W25Q64_SECTOR_SIZE + start*ACTION_SIZE, ACTION_SIZE);
		uart1_send_str(uart_receive_buf);
		uart1_send_str((u8 *)"\r\n");
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
	for(;start<=end;start++) {
		w25x_erase_sector(start*W25Q64_SECTOR_SIZE);
		sprintf((char *)cmd_return, "Erase %d OK!", start);
		uart1_send_str(cmd_return);
	}
	save_action_index_bak = 0;
}



void do_group_once(int group_num) {
	memset(uart_receive_buf, 0, sizeof(uart_receive_buf));
	w25x_read(uart_receive_buf, save_addr_sector*W25Q64_SECTOR_SIZE + group_num*ACTION_SIZE, ACTION_SIZE);
	do_action(uart_receive_buf);
	sprintf((char *)cmd_return, "do_group_once %d OK\r\n", group_num);
	uart1_send_str(cmd_return);
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
				}
				return;
			}
			do_start_index--;
		}
	}
	
}

u8 check_dj_state(void) {
	int i;
	float	inc = 0;
	for(i=0;i<DJ_NUM;i++) {
		inc += duoji_doing[i].inc;
		if(inc)return 1;
	}
	return 0;
}

void do_action(u8 *uart_receive_buf) {
	u16 index, pwm, time,i;
	zx_uart_send_str(uart_receive_buf);
	i = 0;
	while(uart_receive_buf[i]) {
		if(uart_receive_buf[i] == '#') {
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
			
			if(index < DJ_NUM && (pwm<=2500)&& (pwm>=500) && (time<=10000)) {
				//duoji_doing[index].inc = 0;
				if(duoji_doing[index].cur == pwm)pwm += 0.1;
				if(time < 20)time = 20;
				duoji_doing[index].aim = pwm;
				duoji_doing[index].time = time;
				duoji_doing[index].inc = (duoji_doing[index].aim -  duoji_doing[index].cur) / (duoji_doing[index].time/20.000);
			}

			//sprintf(cmd_return, "#%dP%dT%d!\r\n", index, pwm, time, duoji_doing[index].inc);
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

/*
void car_io_set(int car_left, int car_right) {
	if(car_left>100) {
		car_set(1,1);
		car_set(2,0);
	} else if(car_left<-100) {
		car_set(1,0);
		car_set(2,1);
	} else {
		car_set(1,0);
		car_set(2,0);
	}
	
	if(car_right>100) {
		car_set(3,1);
		car_set(4,0);
	} else if(car_right<-100) {
		car_set(3,0);
		car_set(4,1);
	} else {
		car_set(3,0);
		car_set(4,0);
	}	
}*/


