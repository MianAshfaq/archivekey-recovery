from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def _first_existing(paths: list[str | Path]) -> Path | None:
    for candidate in paths:
        if not candidate:
            continue
        resolved = shutil.which(str(candidate)) or str(candidate)
        path = Path(resolved)
        if path.is_file():
            return path.resolve()
    return None


@dataclass(frozen=True)
class Toolchain:
    john: Path | None
    rar2john: Path | None
    zip2john: Path | None
    unrar: Path | None
    seven_zip: Path | None

    @classmethod
    def discover(cls, john_directory: str = "") -> "Toolchain":
        roots: list[Path] = []
        if john_directory:
            roots.append(Path(john_directory).expanduser())

        workspace = Path(__file__).resolve().parents[2]
        roots.extend(workspace.glob(".recovery-tools/**/run"))
        roots.extend(Path.cwd().glob(".recovery-tools/**/run"))

        john_candidates: list[str | Path] = ["john.exe", "john"]
        rar_candidates: list[str | Path] = ["rar2john.exe", "rar2john"]
        zip_candidates: list[str | Path] = ["zip2john.exe", "zip2john"]
        for root in roots:
            john_candidates.insert(0, root / "john.exe")
            rar_candidates.insert(0, root / "rar2john.exe")
            zip_candidates.insert(0, root / "zip2john.exe")

        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        return cls(
            john=_first_existing(john_candidates),
            rar2john=_first_existing(rar_candidates),
            zip2john=_first_existing(zip_candidates),
            unrar=_first_existing(
                ["UnRAR.exe", "unrar", Path(program_files) / "WinRAR" / "UnRAR.exe"]
            ),
            seven_zip=_first_existing(
                ["7z.exe", "7zz.exe", "7z", "7zz", Path(program_files) / "7-Zip" / "7z.exe"]
            ),
        )

    def describe(self) -> str:
        def mark(value: Path | None) -> str:
            return str(value) if value else "not found"

        return (
            f"Legacy John backend (optional): {mark(self.john)}\n"
            f"Legacy RAR hash helper (optional): {mark(self.rar2john)}\n"
            f"Legacy ZIP hash helper (optional): {mark(self.zip2john)}\n"
            f"UnRAR: {mark(self.unrar)}\n"
            f"7-Zip: {mark(self.seven_zip)}"
        )
