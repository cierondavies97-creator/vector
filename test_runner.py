"""Test runner utilities."""

from __future__ import annotations

import subprocess

from config import AppConfig


class TestRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def run(self) -> subprocess.CompletedProcess[str]:
        command = self.config.test_command
        return subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
        )
