"""Prevent CubeMX, compiled pin macros and the archived V3.1 baseline drifting."""
import csv
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PinoutTests(unittest.TestCase):
    def test_all_24_signals_match_archived_baseline(self):
        doc = (ROOT / "docs/2026929PINOUT.md").read_text(encoding="utf-8")
        table = doc.split("## 2.", 1)[1].split("## 3.", 1)[0]
        pins = []
        for line in table.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 7 and re.fullmatch(r"P[A-G]\d+", cells[2]):
                pins.append((cells[1], cells[2], cells[4].split(" / ")[0]))
        self.assertEqual(len(pins), 24)
        header = (ROOT / "Core/Inc/main.h").read_text(encoding="utf-8")
        ioc = dict(line.split("=", 1) for line in (ROOT / "if_car.ioc").read_text().splitlines() if "=" in line)
        with (ROOT / "pinout.csv").open(newline="", encoding="utf-8") as stream:
            exported = {row["Name"]: row for row in csv.DictReader(stream)}
        with (ROOT / "board_pinout.csv").open(newline="", encoding="utf-8") as stream:
            connectors = {row["Network"]: row for row in csv.DictReader(stream)}
        for name, pin, mode in pins:
            with self.subTest(signal=name):
                self.assertIn(f"#define {name}_Pin GPIO_PIN_{pin[2:]}", header)
                self.assertIn(f"#define {name}_GPIO_Port GPIO{pin[1]}", header)
                self.assertEqual(ioc[f"{pin}.GPIO_Label"], name)
                signal = "GPIO_Input" if "GPIO Input" in mode else "GPIO_Output" if "GPIO Output" in mode else mode
                self.assertEqual(ioc[f"{pin}.Signal"], ("S_" if signal.startswith("TIM") else "") + signal)
                self.assertEqual(exported[pin]["Signal"], signal)
                self.assertEqual(exported[pin]["Label"], name)
                self.assertEqual(connectors[name]["GPIO"], pin)
        self.assertEqual(ioc["PG10.PinState"], "GPIO_PIN_SET")
        self.assertEqual(exported["PF3"]["Signal"], "")
        self.assertEqual(exported["PA0-WKUP"]["Signal"], "")

    def test_timer_clocks_and_interrupt_routes(self):
        ioc = dict(line.split("=", 1) for line in (ROOT / "if_car.ioc").read_text().splitlines() if "=" in line)
        for timer, divisor in ((10, 168), (11, 168), (13, 84)):
            self.assertEqual(int(ioc[f"TIM{timer}.Prescaler"]), divisor - 1)
            self.assertEqual(ioc[f"TIM{timer}.Period"], "65535")
        self.assertEqual(ioc["TIM3.Period"], "65535")
        self.assertEqual(ioc["TIM5.Period"], "4199")
        self.assertEqual(ioc["RCC.PLLQ"], "7")
        interrupts = (ROOT / "Core/Src/stm32f4xx_it.c").read_text()
        for vector, timer in (("TIM1_UP_TIM10", 10), ("TIM1_TRG_COM_TIM11", 11), ("TIM8_UP_TIM13", 13)):
            self.assertIn(f"NVIC.{vector}_IRQn", ioc)
            block = interrupts.split(f"void {vector}_IRQHandler(void)", 1)[1].split("}", 1)[0]
            self.assertIn(f"HAL_TIM_IRQHandler(&htim{timer})", block)

    def test_onboard_ch340_matches_usart1_not_bluetooth_usart3(self):
        header = (ROOT / "Core/Inc/main.h").read_text(encoding="utf-8")
        ioc = dict(line.split("=", 1) for line in (ROOT / "if_car.ioc").read_text().splitlines() if "=" in line)
        with (ROOT / "pinout.csv").open(newline="", encoding="utf-8") as stream:
            exported = {row["Name"]: row for row in csv.DictReader(stream)}
        with (ROOT / "board_pinout.csv").open(newline="", encoding="utf-8") as stream:
            connectors = {row["Network"]: row for row in csv.DictReader(stream)}
        for name, pin, signal, position in (("UART1_TX", "PA9", "USART1_TX", "101"),
                                            ("UART1_RX", "PA10", "USART1_RX", "102")):
            with self.subTest(signal=name):
                self.assertIn(f"#define {name}_Pin GPIO_PIN_{pin[2:]}", header)
                self.assertIn(f"#define {name}_GPIO_Port GPIOA", header)
                self.assertEqual(ioc[f"{pin}.GPIO_Label"], name)
                self.assertEqual(ioc[f"{pin}.Signal"], signal)
                self.assertEqual(exported[pin]["Signal"], signal)
                self.assertEqual(exported[pin]["Position"], position)
                self.assertEqual(connectors[name]["GPIO"], pin)
        for uart in (1, 3):
            self.assertEqual(ioc[f"USART{uart}.BaudRate"], "9600")
        self.assertIn("NVIC.USART1_IRQn", ioc)
        interrupts = (ROOT / "Core/Src/stm32f4xx_it.c").read_text()
        block = interrupts.split("void USART1_IRQHandler(void)", 1)[1].split("}", 1)[0]
        self.assertIn("HAL_UART_IRQHandler(&huart1)", block)


if __name__ == "__main__":
    unittest.main()
