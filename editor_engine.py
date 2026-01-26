"""Safe editing engine with rollback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from test_runner import TestRunner


@dataclass(frozen=True)
class EditResult:
    success: bool
    message: str
    original_path: str
    backup_path: str | None = None


class EditorEngine:
    def __init__(self, test_runner: TestRunner) -> None:
        self.test_runner = test_runner

    def edit_file(self, path: str, transform: Callable[[str], str]) -> EditResult:
        file_path = Path(path)
        original_content = file_path.read_text(encoding="utf-8")
        updated_content = transform(original_content)

        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        backup_path.write_text(original_content, encoding="utf-8")
        file_path.write_text(updated_content, encoding="utf-8")

        before = self.test_runner.run()
        if before.returncode != 0:
            file_path.write_text(original_content, encoding="utf-8")
            return EditResult(
                success=False,
                message="Pre-edit tests failed; rollback applied.",
                original_path=path,
                backup_path=backup_path.as_posix(),
            )

        after = self.test_runner.run()
        if after.returncode != 0:
            file_path.write_text(original_content, encoding="utf-8")
            return EditResult(
                success=False,
                message="Post-edit tests failed; rollback applied.",
                original_path=path,
                backup_path=backup_path.as_posix(),
            )

        return EditResult(
            success=True,
            message="Edit applied and tests passed.",
            original_path=path,
            backup_path=backup_path.as_posix(),
        )
