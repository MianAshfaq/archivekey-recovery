from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from archivekey.engine import RecoveryConfig, RecoveryEngine, RecoveryError
from archivekey.tools import Toolchain


class ArchiveKeyApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ArchiveKey Recovery")
        self.geometry("850x720")
        self.minsize(760, 620)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.engine: RecoveryEngine | None = None
        self.worker: threading.Thread | None = None

        self.archive_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.john_var = tk.StringVar()
        self.years_var = tk.StringVar(value=f"1947, 2000-{datetime.now().year}")
        self.limit_var = tk.StringVar(value="250000")
        self.authorized_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self._build()
        self.after(150, self._drain_events)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="ArchiveKey Recovery", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="Private, local password recovery for archives you own or are authorized to access.",
        ).pack(anchor="w", pady=(0, 14))

        file_frame = ttk.LabelFrame(root, text="Archive and output", padding=10)
        file_frame.pack(fill="x")
        self._path_row(file_frame, "Archive", self.archive_var, self._browse_archive, 0)
        self._path_row(file_frame, "Output folder", self.output_var, self._browse_output, 1)
        self._path_row(file_frame, "Legacy tools (optional)", self.john_var, self._browse_john, 2)

        clues = ttk.LabelFrame(root, text="What do you remember?", padding=10)
        clues.pack(fill="both", expand=False, pady=10)
        ttk.Label(clues, text="Exact passwords to try (one per line)").grid(row=0, column=0, sticky="w")
        ttk.Label(clues, text="Words, places, countries, acronyms (one per line)").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.exact_text = tk.Text(clues, height=7, wrap="none")
        self.clue_text = tk.Text(clues, height=7, wrap="none")
        self.exact_text.grid(row=1, column=0, sticky="nsew")
        self.clue_text.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        clues.columnconfigure(0, weight=1)
        clues.columnconfigure(1, weight=1)

        options = ttk.Frame(root)
        options.pack(fill="x")
        ttk.Label(options, text="Likely years/ranges").grid(row=0, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.years_var, width=34).grid(row=1, column=0, sticky="w")
        ttk.Label(options, text="Candidate limit").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Entry(options, textvariable=self.limit_var, width=14).grid(row=1, column=1, sticky="w", padx=(14, 0))
        ttk.Button(options, text="Check tools", command=self._check_tools).grid(row=1, column=2, padx=14)

        ttk.Checkbutton(
            root,
            text="I own this archive or have explicit authorization to recover its password.",
            variable=self.authorized_var,
        ).pack(anchor="w", pady=10)

        controls = ttk.Frame(root)
        controls.pack(fill="x")
        self.start_button = ttk.Button(controls, text="Start recovery", command=self._start)
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self._cancel, state="disabled")
        self.start_button.pack(side="left")
        self.cancel_button.pack(side="left", padx=8)
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")

        log_frame = ttk.LabelFrame(root, text="Recovery log", padding=8)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _path_row(self, parent, label, variable, command, row) -> None:
        ttk.Label(parent, text=label, width=16).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2)
        parent.columnconfigure(1, weight=1)

    def _browse_archive(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("Archives", "*.rar *.zip *.7z"), ("All files", "*.*")])
        if selected:
            archive = Path(selected)
            self.archive_var.set(selected)
            self.output_var.set(str(archive.with_name(archive.stem + "-recovered")))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            archive_stem = Path(self.archive_var.get()).stem or "recovered"
            self.output_var.set(str(Path(selected) / f"{archive_stem}-recovered"))

    def _browse_john(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            self.john_var.set(selected)

    def _check_tools(self) -> None:
        messagebox.showinfo("Detected tools", Toolchain.discover(self.john_var.get()).describe())

    @staticmethod
    def _lines(widget: tk.Text) -> tuple[str, ...]:
        return tuple(line for line in widget.get("1.0", "end").splitlines() if line.strip())

    def _parse_years(self) -> tuple[int, ...]:
        years: set[int] = set()
        for part in self.years_var.get().split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = (int(value.strip()) for value in part.split("-", 1))
                if end < start or end - start > 200:
                    raise ValueError(f"Invalid year range: {part}")
                years.update(range(start, end + 1))
            else:
                years.add(int(part))
        return tuple(sorted(years))

    def _start(self) -> None:
        if not self.authorized_var.get():
            messagebox.showerror("Authorization required", "Confirm that you own or are authorized to access the archive.")
            return
        try:
            archive = Path(self.archive_var.get())
            output = Path(self.output_var.get())
            limit = int(self.limit_var.get())
            if not 1 <= limit <= 5_000_000:
                raise ValueError("Candidate limit must be between 1 and 5,000,000.")
            config = RecoveryConfig(
                archive=archive,
                output_directory=output,
                exact_passwords=self._lines(self.exact_text),
                clues=self._lines(self.clue_text),
                years=self._parse_years(),
                max_candidates=limit,
                john_directory=self.john_var.get(),
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self._set_running(True)
        self._log("Starting recovery. The original archive will not be changed.")
        self.engine = RecoveryEngine(lambda text: self.events.put(("log", text)))

        def work() -> None:
            try:
                result = self.engine.run(config)
                self.events.put(("done", result))
            except Exception as exc:
                self.events.put(("error", exc))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _cancel(self) -> None:
        if self.engine:
            self.engine.cancel()
            self.status_var.set("Cancelling...")

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.status_var.set("Recovering..." if running else "Ready")

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "error":
                    self._set_running(False)
                    self._log(f"ERROR: {payload}")
                    messagebox.showerror("Recovery failed", str(payload))
                elif kind == "done":
                    self._set_running(False)
                    result = payload
                    if result.cancelled:
                        self._log("Recovery cancelled.")
                    elif result.password:
                        self._log(f"RECOVERED PASSWORD: {result.password}")
                        self._log(f"Candidates tested: {result.candidates_tested:,}")
                        if result.matched_rule:
                            self._log(f"Winning rule: {result.matched_rule}")
                        messagebox.showinfo(
                            "Password recovered",
                            f"Password: {result.password}\n"
                            f"Candidates tested: {result.candidates_tested:,}\n"
                            f"Rule: {result.matched_rule or 'exact/legacy'}\n\n"
                            f"Extracted to:\n{result.output_directory}",
                        )
                    else:
                        self._log("No match in this candidate set. Add stronger clues or expand the plan.")
                        messagebox.showwarning("Not recovered", "No supplied or generated candidate matched.")
        except queue.Empty:
            pass
        self.after(150, self._drain_events)


if __name__ == "__main__":
    ArchiveKeyApp().mainloop()
