import unittest

from host.protocol import CarClient, SimLink, Status


class ProtocolTests(unittest.TestCase):
    def test_status_validation(self):
        status = Status.parse("STAT FOLLOW 0 12 500 -1 8 -4 2 250 250 1500")
        self.assertEqual(status.line_bits, 12)
        self.assertIsNone(status.right_mm)
        with self.assertRaises(ValueError):
            Status.parse("STAT FOLLOW 0 99 500 500 0 0 0 0 0 1500")

    def test_mode_guards_and_debug_deadman(self):
        link = SimLink()
        client = CarClient(link)
        client.debug()
        with self.assertRaises(RuntimeError):
            client.arm()
        with self.assertRaises(ValueError):
            client.drive(301, 0, 1500)
        client.drive(200, -100, 1550)
        self.assertEqual(client.status().motor_left, 200)
        link.last_drive -= 1
        self.assertEqual(client.status().motor_left, 0)
        client.stop()
        self.assertEqual(client.status().state, "IDLE")

    def test_auto_is_read_only_until_stop(self):
        client = CarClient(SimLink())
        client.arm()
        with self.assertRaises(RuntimeError):
            client.debug()
        with self.assertRaises(RuntimeError):
            client.drive(100, 100, 1500)
        client.close()
        self.assertEqual(client.status().state, "ARMED")


if __name__ == "__main__":
    unittest.main()
