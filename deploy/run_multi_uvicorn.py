from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


POLL_INTERVAL_SECONDS = 0.2
SHUTDOWN_GRACE_SECONDS = 10.0


def _parse_positive_int(name: str, default: str) -> int:
	raw_value = os.getenv(name, default)
	try:
		value = int(raw_value)
	except (TypeError, ValueError) as exc:
		raise SystemExit(f"[uvicorn-manager] {name} must be an integer, got: {raw_value!r}") from exc

	if value < 1:
		raise SystemExit(f"[uvicorn-manager] {name} must be >= 1, got: {value}")

	return value


class UvicornManager:
	def __init__(self) -> None:
		self.project_root = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
		self.workers = _parse_positive_int("WORKERS", "5")
		self.base_port = _parse_positive_int("UVICORN_BASE_PORT", "8001")
		self.last_port = self.base_port + self.workers - 1
		if self.last_port > 65535:
			raise SystemExit(
				f"[uvicorn-manager] UVICORN_BASE_PORT + WORKERS - 1 must be <= 65535, got: {self.last_port}"
			)
		self.processes: list[subprocess.Popen[bytes]] = []
		self.stopping = False
		self.exit_code = 0

	def _worker_command(self, process_num: int) -> list[str]:
		return ["sh", str(self.project_root / "deploy" / "run_uvicorn_worker.sh"), str(process_num)]

	def _forward_signal(self, signum: int) -> None:
		for process in self.processes:
			if process.poll() is None:
				try:
					process.send_signal(signum)
				except ProcessLookupError:
					pass

	def _kill_remaining(self) -> None:
		for process in self.processes:
			if process.poll() is None:
				try:
					process.kill()
				except ProcessLookupError:
					pass

	def _wait_for_stop(self) -> int:
		deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
		while time.monotonic() < deadline:
			if all(process.poll() is not None for process in self.processes):
				return self.exit_code
			time.sleep(POLL_INTERVAL_SECONDS)

		self._kill_remaining()
		for process in self.processes:
			try:
				process.wait(timeout=1)
			except subprocess.TimeoutExpired:
				pass

		return self.exit_code or 1

	def _handle_signal(self, signum: int, _frame) -> None:
		if self.stopping:
			return

		self.stopping = True
		self.exit_code = 128 + signum
		print(f"[uvicorn-manager] received signal {signum}, shutting down workers", file=sys.stderr, flush=True)
		self._forward_signal(signum)

	def _spawn_workers(self) -> None:
		print(
			f"[uvicorn-manager] starting {self.workers} uvicorn workers on 127.0.0.1:{self.base_port}~127.0.0.1:{self.last_port}",
			file=sys.stderr,
			flush=True,
		)

		for process_num in range(self.workers):
			try:
				process = subprocess.Popen(self._worker_command(process_num), cwd=self.project_root)
			except Exception:
				self.stopping = True
				self.exit_code = 1
				self._forward_signal(signal.SIGTERM)
				self._wait_for_stop()
				raise
			self.processes.append(process)

	def run(self) -> int:
		signal.signal(signal.SIGTERM, self._handle_signal)
		signal.signal(signal.SIGINT, self._handle_signal)

		self._spawn_workers()

		while True:
			for index, process in enumerate(self.processes):
				return_code = process.poll()
				if return_code is None:
					continue

				if self.stopping:
					if all(existing.poll() is not None for existing in self.processes):
						return self.exit_code
					continue

				self.stopping = True
				self.exit_code = return_code if return_code != 0 else 1
				print(
					f"[uvicorn-manager] worker {index} exited with code {return_code}, shutting down remaining workers",
					file=sys.stderr,
					flush=True,
				)
				self._forward_signal(signal.SIGTERM)
				return self._wait_for_stop()

			if self.stopping and all(process.poll() is not None for process in self.processes):
				return self.exit_code

			time.sleep(POLL_INTERVAL_SECONDS)


def main() -> int:
	return UvicornManager().run()


if __name__ == "__main__":
	sys.exit(main())
