"""Deterministic blocking fake for the XL430 transport seam."""

from __future__ import annotations

import threading
import time

from hiyelx.drivers.dynamixel.constants import EXPECTED_MODEL_NUMBER


class FakeDynamixelTransport:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.model_number = EXPECTED_MODEL_NUMBER
        self.registers: dict[int, int] = {}
        self.failures: dict[str, list[Exception | None]] = {}
        self.delay_seconds = 0.0
        self.max_concurrent_calls = 0
        self.blocked_key: str | None = None
        self.block_entered = threading.Event()
        self.block_release = threading.Event()
        self.block_completed = threading.Event()
        self._active_calls = 0
        self._active_lock = threading.Lock()

    def fail_next(self, key: str, error: Exception | None = None) -> None:
        self.failures.setdefault(key, []).append(error or RuntimeError(key))

    def open_port(self) -> None:
        self._perform("open_port", "open_port")

    def set_baud_rate(self, baud_rate: int) -> None:
        self._perform("set_baud_rate", f"set_baud_rate:{baud_rate}")

    def ping(self, motor_id: int) -> int:
        self._perform("ping", f"ping:{motor_id}")
        return self.model_number

    def read(self, motor_id: int, address: int, size: int) -> int:
        key = f"read:{address}"
        self._perform(key, f"read:{motor_id}:{address}:{size}")
        return self.registers.get(address, 0)

    def write(self, motor_id: int, address: int, size: int, value: int) -> None:
        key = f"write:{address}"
        self._perform(key, f"write:{motor_id}:{address}:{size}:{value}")
        self.registers[address] = value

    def close_port(self) -> None:
        self._perform("close_port", "close_port")

    def _perform(self, key: str, event: str) -> None:
        with self._active_lock:
            self._active_calls += 1
            self.max_concurrent_calls = max(self.max_concurrent_calls, self._active_calls)
        try:
            self.events.append(event)
            if key == self.blocked_key:
                self.block_entered.set()
                self.block_release.wait()
                self.block_completed.set()
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            failures = self.failures.get(key)
            if failures:
                failure = failures.pop(0)
                if failure is not None:
                    raise failure
        finally:
            with self._active_lock:
                self._active_calls -= 1
