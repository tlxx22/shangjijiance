import os
import unittest
from unittest.mock import patch

from src.official_startup_notify import notify_startup_async


class TestOfficialStartupNotify(unittest.TestCase):
	def test_no_environment_no_send(self):
		calls = []

		def stub_sender(*, cfg, text, timeout_s=10.0):
			calls.append((cfg, text, timeout_s))
			return {"code": 0}

		with patch.dict(os.environ, {}, clear=True):
			notify_startup_async(server_meta={"pid": "1"}, sender=stub_sender, async_send=False)

		self.assertEqual(calls, [])

	def test_sany_official_sends_once(self):
		calls = []

		def stub_sender(*, cfg, text, timeout_s=10.0):
			calls.append((cfg, text, timeout_s))
			return {"code": 0}

		with patch.dict(os.environ, {"environment": "sany_official"}, clear=True):
			notify_startup_async(
				server_meta={"pid": "123", "bind": "0.0.0.0:80", "workers": "5"},
				sender=stub_sender,
				async_send=False,
			)

		self.assertEqual(len(calls), 1)
		_, text, _ = calls[0]
		self.assertIn("启动通知（sany_official）", text)
		self.assertIn("时间(Asia/Shanghai):", text)
		self.assertIn("host:", text)
		self.assertIn("pid:", text)


if __name__ == "__main__":
	unittest.main()

