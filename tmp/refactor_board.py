from pathlib import Path
import csv
import re

root = Path(__file__).resolve().parents[1]
pins = [
    ('PA2', 'DRV_PWMA', 'TIM5_CH3'), ('PA3', 'DRV_PWMB', 'TIM5_CH4'),
    ('PC0', 'DRV_AIN1', 'GPIO_Output'), ('PC1', 'DRV_AIN2', 'GPIO_Output'),
    ('PC2', 'DRV_BIN1', 'GPIO_Output'), ('PC3', 'DRV_BIN2', 'GPIO_Output'),
    ('PC4', 'DRV_STBY', 'GPIO_Output'),
    ('PC6', 'ENC_L_A', 'TIM3_CH1'), ('PC7', 'ENC_L_B', 'TIM3_CH2'),
    ('PB6', 'ENC_R_A', 'TIM4_CH1'), ('PB7', 'ENC_R_B', 'TIM4_CH2'),
    ('PE9', 'SERVO_PWM', 'TIM1_CH1'),
    ('PB10', 'UART3_TX', 'USART3_TX'), ('PB11', 'UART3_RX', 'USART3_RX'),
    ('PF0', 'GRAY_AD0', 'GPIO_Output'), ('PF1', 'GRAY_AD1', 'GPIO_Output'),
    ('PF2', 'GRAY_AD2', 'GPIO_Output'), ('PC5', 'GRAY_OUT', 'GPIO_Input'),
    ('PA1', 'US_L_TRIG', 'GPIO_Output'), ('PF6', 'US_L_ECHO', 'TIM10_CH1'),
    ('PA5', 'US_C_TRIG', 'GPIO_Output'), ('PF7', 'US_C_ECHO', 'TIM11_CH1'),
    ('PA7', 'US_R_TRIG', 'GPIO_Output'), ('PF8', 'US_R_ECHO', 'TIM13_CH1'),
    ('PG10', 'SRAM_CS', 'GPIO_Output'),
]

path = root / 'Core/Inc/main.h'
s = path.read_text()
start = re.search(r'#define \w+_Pin ', s).start()
end = s.index('/* USER CODE BEGIN Private defines */', start)
defines = ''.join(f'#define {name}_Pin GPIO_PIN_{pin[2:]}\n#define {name}_GPIO_Port GPIO{pin[1]}\n'
                  for pin, name, _ in pins)
path.write_text(s[:start] + defines + '\n' + s[end:])

path = root / 'Core/Src/main.c'
s = path.read_text().replace('#include "car_app.h"', '#include "car_app.h"\n#include "car_config.h"')
replacements = {'htim2': 'htim3', 'htim3': 'htim5', 'htim9': 'htim10',
                'TIM2': 'TIM3', 'TIM3': 'TIM5', 'TIM9': 'TIM10',
                'MX_TIM2_Init': 'MX_TIM3_Init', 'MX_TIM3_Init': 'MX_TIM5_Init',
                'MX_TIM9_Init': 'MX_TIM10_Init'}
s = re.sub(r'\b(?:' + '|'.join(replacements) + r')\b', lambda m: replacements[m[0]], s)
s = s.replace('TIM2_Init', 'TEMP_ENCODER_Init').replace('TIM3_Init', 'TIM5_Init').replace('TEMP_ENCODER_Init', 'TIM3_Init').replace('TIM9_Init', 'TIM10_Init') if False else s
s = s.replace('TIM_HandleTypeDef htim10;', 'TIM_HandleTypeDef htim10;\nTIM_HandleTypeDef htim11;\nTIM_HandleTypeDef htim13;')
s = s.replace('static void MX_TIM10_Init(void);', 'static void MX_TIM10_Init(void);\nstatic void MX_TIM11_Init(void);\nstatic void MX_TIM13_Init(void);')
s = s.replace('  MX_TIM10_Init();', '  MX_TIM10_Init();\n  MX_TIM11_Init();\n  MX_TIM13_Init();')
s = s.replace('htim3.Init.Period = 4294967295;', 'htim3.Init.Period = 65535;')
start = s.index('static void MX_TIM5_Init(void)\n{')
end = s.index('/**', start)
block = s[start:end].replace('TIM_CHANNEL_1', 'TIM_CHANNEL_3').replace('TIM_CHANNEL_2', 'TIM_CHANNEL_4')
block = block.replace('htim5.Init.Period = 4199;', 'htim5.Init.Period = CAR_MOTOR_PERIOD_TICKS - 1U;')
s = s[:start] + block + s[end:]
start = s.index('static void MX_TIM10_Init(void)\n{')
end = s.index('/**', start)
block = s[start:end]
second = block.index('  if (HAL_TIM_IC_ConfigChannel(&htim10, &sConfigIC, TIM_CHANNEL_2)')
second_end = block.index('  /* USER CODE BEGIN', second)
block = (block[:second] + block[second_end:]).replace('TIM9_Init', 'TIM10_Init')
s = s[:start] + block + block.replace('TIM10', 'TIM11').replace('htim10', 'htim11') + \
    block.replace('TIM10', 'TIM13').replace('htim10', 'htim13').replace('Prescaler = 167', 'Prescaler = 83') + s[end:]
s = s.replace('htim1.Init.Period = 19999;', 'htim1.Init.Period = CAR_SERVO_PERIOD_US - 1U;')
s = s.replace('sConfigOC.Pulse = 1500;', 'sConfigOC.Pulse = CAR_SERVO_CENTER_US;')
s = s.replace('huart3.Init.BaudRate = 9600;', 'huart3.Init.BaudRate = CAR_UART_BAUD;')
s = s.replace('RCC_OscInitStruct.PLL.PLLQ = 4;', 'RCC_OscInitStruct.PLL.PLLQ = 7;')
start = s.index('static void MX_GPIO_Init(void)\n{')
end = s.index('/* USER CODE BEGIN 4 */', start)
gpio = '''static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef gpio = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */
  /* Deassert SRAM CE before PF0..PF2 and PE9 share its address/data bus. */
  __HAL_RCC_GPIOG_CLK_ENABLE();
  HAL_GPIO_WritePin(SRAM_CS_GPIO_Port, SRAM_CS_Pin, GPIO_PIN_SET);
  gpio.Pin = SRAM_CS_Pin;
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Pull = GPIO_PULLUP;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(SRAM_CS_GPIO_Port, &gpio);
  /* USER CODE END MX_GPIO_Init_1 */

  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  HAL_GPIO_WritePin(GPIOC, DRV_AIN1_Pin|DRV_AIN2_Pin|DRV_BIN1_Pin|DRV_BIN2_Pin|DRV_STBY_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, US_L_TRIG_Pin|US_C_TRIG_Pin|US_R_TRIG_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOF, GRAY_AD0_Pin|GRAY_AD1_Pin|GRAY_AD2_Pin, GPIO_PIN_RESET);

  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Pin = DRV_AIN1_Pin|DRV_AIN2_Pin|DRV_BIN1_Pin|DRV_BIN2_Pin|DRV_STBY_Pin;
  HAL_GPIO_Init(GPIOC, &gpio);
  gpio.Pin = US_L_TRIG_Pin|US_C_TRIG_Pin|US_R_TRIG_Pin;
  HAL_GPIO_Init(GPIOA, &gpio);
  gpio.Pin = GRAY_AD0_Pin|GRAY_AD1_Pin|GRAY_AD2_Pin;
  HAL_GPIO_Init(GPIOF, &gpio);
  gpio.Pin = GRAY_OUT_Pin;
  gpio.Mode = GPIO_MODE_INPUT;
  HAL_GPIO_Init(GRAY_OUT_GPIO_Port, &gpio);
  /* USER CODE BEGIN MX_GPIO_Init_2 */
  /* USER CODE END MX_GPIO_Init_2 */
}

'''
s = s[:start] + gpio + s[end:]
path.write_text(s)

path = root / 'if_car.ioc'
lines = path.read_text().splitlines()
lines = [line for line in lines if not re.match(
    r'(Mcu\.(IP\d+|IPNb|Pin\d+|PinsNb)=|P[A-GH]\d+(?:-WKUP)?\.|TIM\d+\.|SH\.S_TIM|VP_TIM|NVIC\.TIM|RCC\.PLLQ=)', line)]
ips = ['NVIC', 'RCC', 'SYS', 'TIM1', 'TIM3', 'TIM4', 'TIM5', 'TIM10', 'TIM11', 'TIM13', 'USART3']
lines += [f'Mcu.IP{i}={ip}' for i, ip in enumerate(ips)] + [f'Mcu.IPNb={len(ips)}']
virtuals = ['VP_SYS_VS_Systick'] + [f'VP_TIM{t}_VS_ClockSourceINT' for t in (1, 5, 10, 11, 13)]
physical = [p for p, _, _ in pins] + ['PA13', 'PA14']
lines += [f'Mcu.Pin{i}={pin}' for i, pin in enumerate(physical + virtuals)] + [f'Mcu.PinsNb={len(physical + virtuals)}']
for pin, name, signal in pins:
    params = ['GPIO_Label']
    lines += [f'{pin}.GPIO_Label={name}', f'{pin}.Locked=true']
    if name.startswith('ENC_') or name == 'SRAM_CS':
        params += ['GPIO_PuPd']
        lines += [f'{pin}.GPIO_PuPd=GPIO_PULLUP']
    if name == 'SRAM_CS':
        params += ['PinState']
        lines += [f'{pin}.PinState=GPIO_PIN_SET']
    lines += [f'{pin}.GPIOParameters=' + ','.join(params)]
    lines += [f'{pin}.Signal=' + ('S_' if signal.startswith('TIM') else '') + signal]
    if signal.startswith('USART'): lines += [f'{pin}.Mode=Asynchronous']
lines += ['PA13.Mode=Serial_Wire', 'PA13.Signal=SYS_JTMS-SWDIO',
          'PA14.Mode=Serial_Wire', 'PA14.Signal=SYS_JTCK-SWCLK']
for timer, chans in ((1, (1,)), (5, (3, 4))):
    fields = ['Prescaler', 'Period']
    lines += [f'TIM{timer}.Prescaler={167 if timer == 1 else 0}', f'TIM{timer}.Period={19999 if timer == 1 else 4199}']
    for ch in chans:
        mode = f'PWM Generation{ch} CH{ch}'
        field = 'Channel-' + mode
        lines += [f'TIM{timer}.' + field.replace(' ', r'\ ') + f'=TIM_CHANNEL_{ch}',
                  f'SH.S_TIM{timer}_CH{ch}.0=TIM{timer}_CH{ch},{mode}', f'SH.S_TIM{timer}_CH{ch}.ConfNb=1']
        fields += [field]
        pulse = 'Pulse-' + mode
        lines += [f'TIM{timer}.' + pulse.replace(' ', r'\ ') + f'={1500 if timer == 1 else 0}']
        fields += [pulse]
    lines += [f'TIM{timer}.IPParameters=' + ','.join(fields)]
for timer in (3, 4):
    lines += [f'TIM{timer}.EncoderMode=TIM_ENCODERMODE_TI12', f'TIM{timer}.Period=65535',
              f'TIM{timer}.IC1Filter=4', f'TIM{timer}.IC2Filter=4',
              f'TIM{timer}.IPParameters=EncoderMode,Period,IC1Filter,IC2Filter']
    for ch in (1, 2):
        lines += [f'SH.S_TIM{timer}_CH{ch}.0=TIM{timer}_CH{ch},Encoder_Interface', f'SH.S_TIM{timer}_CH{ch}.ConfNb=1']
for timer in (10, 11, 13):
    lines += [f'TIM{timer}.Channel-Input_Capture1_from_TI1=TIM_CHANNEL_1',
              f'TIM{timer}.Prescaler={83 if timer == 13 else 167}', f'TIM{timer}.Period=65535',
              f'TIM{timer}.ICFilter_CH1=4',
              f'TIM{timer}.IPParameters=Channel-Input_Capture1_from_TI1,Prescaler,Period,ICFilter_CH1',
              f'SH.S_TIM{timer}_CH1.0=TIM{timer}_CH1,Input_Capture1_from_TI1', f'SH.S_TIM{timer}_CH1.ConfNb=1']
for timer in (1, 5, 10, 11, 13):
    lines += [f'VP_TIM{timer}_VS_ClockSourceINT.Mode=Internal', f'VP_TIM{timer}_VS_ClockSourceINT.Signal=TIM{timer}_VS_ClockSourceINT']
for irq in ('TIM1_UP_TIM10_IRQn', 'TIM1_TRG_COM_TIM11_IRQn', 'TIM8_UP_TIM13_IRQn'):
    lines += [f'NVIC.{irq}=true\\:5\\:0\\:false\\:false\\:true\\:true\\:true\\:true']
lines += ['RCC.PLLQ=7']
lines = [line.replace('RCC.48MHZClocksFreq_Value=84000000', 'RCC.48MHZClocksFreq_Value=48000000')
             .replace('RCC.PLLQCLKFreq_Value=84000000', 'RCC.PLLQCLKFreq_Value=48000000') for line in lines]
lines = [line.replace('PLLN,PLLQCLKFreq_Value', 'PLLN,PLLQ,PLLQCLKFreq_Value') for line in lines]
functions = ['SystemClock_Config', 'MX_GPIO_Init', 'MX_TIM1_Init', 'MX_TIM3_Init', 'MX_TIM5_Init',
             'MX_TIM4_Init', 'MX_TIM10_Init', 'MX_TIM11_Init', 'MX_TIM13_Init', 'MX_USART3_UART_Init']
for i, line in enumerate(lines):
    if line.startswith('ProjectManager.functionlistsort='):
        lines[i] = 'ProjectManager.functionlistsort=' + ','.join(
            f'{j+1}-{fn}-{fn[3:].split("_")[0] if fn.startswith("MX_") else "RCC"}-false-HAL-'
            + ('false' if j == 0 else 'true') for j, fn in enumerate(functions))
path.write_text('\n'.join(sorted(set(lines))) + '\n')

path = root / 'pinout.csv'
with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
mapping = {pin: (label, signal) for pin, label, signal in pins}
mapping |= {'PA13': ('', 'SYS_JTMS-SWDIO'), 'PA14': ('', 'SYS_JTCK-SWCLK')}
for row in rows:
    if row['Type'] in ('I/O', 'Input', 'Output'):
        label, signal = mapping.get(row['Name'], ('', ''))
        row.update(Label=label, Signal=signal, Type='Output' if signal == 'GPIO_Output' else 'Input' if signal == 'GPIO_Input' else 'I/O')
with path.open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), quoting=csv.QUOTE_ALL)
    writer.writeheader(); writer.writerows(rows)
