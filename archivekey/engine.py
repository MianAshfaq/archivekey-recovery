from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .candidates import Candidate, generate_ranked_candidates
from .rar5 import Rar5FormatError, Rar5Target
from .tools import Toolchain


LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class RecoveryConfig:
    archive: Path
    output_directory: Path
    exact_passwords: tuple[str, ...]
    clues: tuple[str, ...]
    years: tuple[int, ...]
    max_candidates: int = 250_000
    john_directory: str = ""


@dataclass(frozen=True)
class RecoveryResult:
    password: str | None
    output_directory: Path | None
    candidates_generated: int
    cancelled: bool = False
    candidates_tested: int = 0
    matched_rule: str | None = None


class RecoveryError(RuntimeError):
    pass


class RecoveryEngine:
    def __init__(self, log: LogCallback = print) -> None:
        self.log = log
        self.cancel_event = threading.Event()
        self._process: subprocess.Popen[str] | None = None

    def cancel(self) -> None:
        self.cancel_event.set()
        process = self._process
        if process and process.poll() is None:
            process.terminate()

    def run(self, config: RecoveryConfig) -> RecoveryResult:
        archive = config.archive.resolve()
        if not archive.is_file():
            raise RecoveryError(f"Archive not found: {archive}")

        extension = archive.suffix.lower()
        if extension not in {".rar", ".zip", ".7z"}:
            raise RecoveryError("Supported archive types are RAR, ZIP, and 7z.")

        tools = Toolchain.discover(config.john_directory)
        self.log(tools.describe())
        ranked_candidates = generate_ranked_candidates(
            config.exact_passwords, config.clues, config.years, config.max_candidates
        )
        candidates = [candidate.value for candidate in ranked_candidates]
        self.log(f"Generated {len(candidates):,} probability-ranked candidates.")
        if ranked_candidates:
            preview = ", ".join(candidate.value for candidate in ranked_candidates[:5])
            self.log(f"First candidates: {preview}")
        if not ranked_candidates:
            raise RecoveryError("Add at least one possible password guess or remembered clue.")

        # RAR 5 is verified by ArchiveKey's own PBKDF2 implementation. No John
        # process or per-candidate UnRAR launch is required for this path.
        if extension == ".rar":
            try:
                target = Rar5Target.from_archive(archive)
                self.log(
                    "Native RAR 5 verifier: "
                    f"PBKDF2-HMAC-SHA256, {target.iterations:,} iterations."
                )
                password, tested, matched_rule = self._native_rar5_attack(
                    target, ranked_candidates
                )
                if self.cancel_event.is_set():
                    return RecoveryResult(
                        None, None, len(candidates), cancelled=True, candidates_tested=tested
                    )
                if not password:
                    return RecoveryResult(None, None, len(candidates), candidates_tested=tested)
                if not self._verify(archive, password, tools):
                    raise RecoveryError("Native password match failed external archive verification.")
                output = self._extract(archive, password, config.output_directory, tools)
                return RecoveryResult(
                    password,
                    output,
                    len(candidates),
                    candidates_tested=tested,
                    matched_rule=matched_rule,
                )
            except Rar5FormatError as exc:
                self.log(f"Native RAR 5 parsing unavailable ({exc}); using legacy backend.")

        # User-supplied guesses are cheap to verify for legacy/non-RAR5 formats.
        for password in config.exact_passwords:
            if self.cancel_event.is_set():
                return RecoveryResult(None, None, len(candidates), cancelled=True)
            if self._verify(archive, password, tools):
                output = self._extract(archive, password, config.output_directory, tools)
                return RecoveryResult(password, output, len(candidates))

        password = self._john_wordlist_attack(archive, extension, candidates, tools)
        if self.cancel_event.is_set():
            return RecoveryResult(None, None, len(candidates), cancelled=True)
        if not password:
            return RecoveryResult(None, None, len(candidates))
        if not self._verify(archive, password, tools):
            raise RecoveryError("A candidate was reported but archive verification failed.")
        output = self._extract(archive, password, config.output_directory, tools)
        return RecoveryResult(password, output, len(candidates))

    def _native_rar5_attack(
        self, target: Rar5Target, candidates: list[Candidate]
    ) -> tuple[str | None, int, str | None]:
        workers = max(1, min(32, os.cpu_count() or 1))
        batch_size = max(16, workers * 4)
        tested = 0
        started = time.monotonic()
        last_log = started
        self.log(f"Starting native recovery with {workers} CPU workers...")

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="archivekey") as pool:
            for offset in range(0, len(candidates), batch_size):
                if self.cancel_event.is_set():
                    return None, tested, None
                batch = candidates[offset : offset + batch_size]
                results = list(pool.map(target.matches, (candidate.value for candidate in batch)))
                for index, matched in enumerate(results):
                    if matched:
                        candidate = batch[index]
                        tested += index + 1
                        elapsed = max(time.monotonic() - started, 0.001)
                        self.log(
                            f"Password matched after {tested:,} candidates "
                            f"({tested / elapsed:,.0f} candidates/second)."
                        )
                        self.log(f"Winning rule: {candidate.rule}")
                        return candidate.value, tested, candidate.rule
                tested += len(batch)
                now = time.monotonic()
                if now - last_log >= 5:
                    elapsed = max(now - started, 0.001)
                    remaining = len(candidates) - tested
                    rate = tested / elapsed
                    eta = remaining / rate if rate else 0
                    self.log(
                        f"Tested {tested:,}/{len(candidates):,} at {rate:,.0f}/s; "
                        f"estimated {eta:,.0f}s remaining."
                    )
                    last_log = now
        return None, tested, None

    def _run_capture(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            check=False,
        )

    def _verify(self, archive: Path, password: str, tools: Toolchain) -> bool:
        if archive.suffix.lower() == ".rar" and tools.unrar:
            command = [str(tools.unrar), "lb", f"-p{password}", "--", str(archive)]
        elif tools.seven_zip:
            command = [str(tools.seven_zip), "t", "-y", f"-p{password}", str(archive)]
        else:
            return False
        result = self._run_capture(command)
        return result.returncode == 0

    def _hash_tool(self, extension: str, tools: Toolchain) -> Path:
        if extension == ".rar" and tools.rar2john:
            return tools.rar2john
        if extension == ".zip" and tools.zip2john:
            return tools.zip2john
        raise RecoveryError(
            f"No password-hash helper found for {extension}. Configure a John jumbo 'run' folder."
        )

    @staticmethod
    def _normalize_hash(raw: str, archive: Path) -> tuple[str, str]:
        lines = [line.strip() for line in raw.splitlines() if "$" in line]
        if not lines:
            raise RecoveryError("The archive hash could not be extracted.")
        line = lines[-1]
        marker = re.search(r"\$(?:rar5|rar3|pkzip2?|zip2)\$", line, re.IGNORECASE)
        if not marker:
            raise RecoveryError("The archive uses an unsupported encryption format.")
        hash_body = line[marker.start():]
        lowered = hash_body.lower()
        if lowered.startswith("$rar5$"):
            format_name = "RAR5"
        elif lowered.startswith("$rar3$"):
            format_name = "rar"
        elif lowered.startswith(("$pkzip$", "$pkzip2$")):
            format_name = "PKZIP"
        else:
            format_name = "ZIP"
        return f"{archive.name}:{hash_body}", format_name

    def _john_wordlist_attack(
        self, archive: Path, extension: str, candidates: list[str], tools: Toolchain
    ) -> str | None:
        if not tools.john:
            raise RecoveryError("John the Ripper jumbo was not found.")
        hash_tool = self._hash_tool(extension, tools)
        hash_result = self._run_capture([str(hash_tool), str(archive)])
        if hash_result.returncode != 0:
            raise RecoveryError(hash_result.stderr.strip() or "Hash extraction failed.")
        normalized_hash, format_name = self._normalize_hash(hash_result.stdout, archive)

        session_id = hashlib.sha256(str(archive).encode("utf-8")).hexdigest()[:12]
        state_root = Path.home() / ".archivekey" / session_id
        state_root.mkdir(parents=True, exist_ok=True)
        hash_file = state_root / "archive.hash"
        wordlist_file = state_root / "candidates.txt"
        pot_file = state_root / "recovered.pot"
        hash_file.write_text(normalized_hash + "\n", encoding="utf-8")
        wordlist_file.write_text("\n".join(candidates) + "\n", encoding="utf-8")

        command = [
            str(tools.john),
            f"--format={format_name}",
            f"--wordlist={wordlist_file}",
            f"--pot={pot_file}",
            str(hash_file),
        ]
        self.log("Starting checkpointable recovery pass...")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            command,
            cwd=tools.john.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        assert self._process.stdout is not None
        for line in self._process.stdout:
            clean = line.strip()
            if clean:
                self.log(clean)
            if self.cancel_event.is_set():
                self.cancel()
                break
        self._process.wait()
        self._process = None

        if not pot_file.exists():
            return None
        target_hash = normalized_hash.split(":", 1)[1]
        for line in pot_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(target_hash + ":"):
                return line[len(target_hash) + 1 :]
        return None

    def _extract(
        self, archive: Path, password: str, requested_output: Path, tools: Toolchain
    ) -> Path:
        base = requested_output.expanduser().resolve()
        output = base
        counter = 2
        while output.exists() and any(output.iterdir()):
            output = base.with_name(f"{base.name}-{counter}")
            counter += 1
        output.mkdir(parents=True, exist_ok=True)

        if archive.suffix.lower() == ".rar" and tools.unrar:
            command = [str(tools.unrar), "x", "-y", f"-p{password}", "--", str(archive), str(output) + os.sep]
        elif tools.seven_zip:
            command = [str(tools.seven_zip), "x", "-y", f"-p{password}", f"-o{output}", str(archive)]
        else:
            raise RecoveryError("No extraction tool is available.")
        self.log(f"Password verified. Extracting to {output}...")
        result = self._run_capture(command)
        if result.returncode != 0:
            raise RecoveryError(result.stderr.strip() or result.stdout.strip() or "Extraction failed.")
        self.log("Extraction completed successfully.")
        return output
