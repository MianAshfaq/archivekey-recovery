from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from archivekey.candidates import generate_ranked_candidates
from archivekey.engine import RecoveryConfig, RecoveryEngine
from archivekey.tools import Toolchain


# ArchiveKey's interface deliberately uses only the Python standard library so
# the packaged application remains small, auditable, and fully offline.
COLORS = {
    "window": "#08111f",
    "sidebar": "#0a1628",
    "surface": "#101d31",
    "surface_alt": "#14243b",
    "field": "#0b1729",
    "border": "#233754",
    "border_focus": "#3182f6",
    "accent": "#1677ff",
    "accent_hover": "#2c86ff",
    "cyan": "#22c7f2",
    "text": "#f4f7fb",
    "muted": "#91a3bc",
    "subtle": "#657892",
    "success": "#29c97c",
    "warning": "#f2b84b",
    "danger": "#ff667d",
}


def resource_path(relative: str) -> Path:
    """Resolve an asset both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


class ArchiveKeyApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ArchiveKey — Authorized Archive Recovery")
        self.geometry("1180x790")
        self.minsize(1040, 720)
        self.configure(bg=COLORS["window"])
        self.option_add("*Font", ("Segoe UI", 10))

        icon_path = resource_path("assets/archivekey.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.engine: RecoveryEngine | None = None
        self.worker: threading.Thread | None = None

        self.archive_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.john_var = tk.StringVar()
        self.years_var = tk.StringVar(value=f"1947, 2000-{datetime.now().year}")
        self.limit_var = tk.StringVar(value="250000")
        self.authorized_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready to begin")
        self.status_detail_var = tk.StringVar(value="Select an archive and add what you remember.")
        self._logo_image: tk.PhotoImage | None = None

        self._configure_styles()
        self._build()
        self.after(150, self._drain_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "ArchiveKey.Horizontal.TProgressbar",
            troughcolor=COLORS["field"],
            background=COLORS["accent"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
            bordercolor=COLORS["field"],
            thickness=8,
        )

    def _build(self) -> None:
        shell = tk.Frame(self, bg=COLORS["window"])
        shell.pack(fill="both", expand=True)
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(1, weight=1)

        self._build_sidebar(shell)
        self._build_workspace(shell)

    def _build_sidebar(self, parent: tk.Widget) -> None:
        sidebar = tk.Frame(parent, bg=COLORS["sidebar"], width=238)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        brand = tk.Frame(sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=24, pady=(24, 34))
        logo_path = resource_path("assets/archivekey-logo-72.png")
        if logo_path.exists():
            self._logo_image = tk.PhotoImage(file=str(logo_path))
            tk.Label(brand, image=self._logo_image, bg=COLORS["sidebar"]).pack(side="left")
        brand_text = tk.Frame(brand, bg=COLORS["sidebar"])
        brand_text.pack(side="left", padx=(12, 0))
        tk.Label(
            brand_text,
            text="ArchiveKey",
            bg=COLORS["sidebar"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w")
        tk.Label(
            brand_text,
            text="RECOVERY STUDIO",
            bg=COLORS["sidebar"],
            fg=COLORS["cyan"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(2, 0))

        tk.Label(
            sidebar,
            text="WORKFLOW",
            bg=COLORS["sidebar"],
            fg=COLORS["subtle"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", padx=26, pady=(0, 12))

        self._workflow_step(sidebar, "01", "Choose archive", "RAR, ZIP or 7Z", active=True)
        self._workflow_step(sidebar, "02", "Add what you remember", "Guesses, words, patterns")
        self._workflow_step(sidebar, "03", "Recover locally", "Test and extract safely")

        security = tk.Frame(
            sidebar,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        security.pack(side="bottom", fill="x", padx=18, pady=18)
        tk.Label(
            security,
            text="LOCAL-ONLY SECURITY",
            bg=COLORS["surface"],
            fg=COLORS["success"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", padx=14, pady=(13, 4))
        tk.Label(
            security,
            text="Your archive and clues stay\non this computer.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=14, pady=(0, 13))

    def _workflow_step(
        self,
        parent: tk.Widget,
        number: str,
        title: str,
        subtitle: str,
        active: bool = False,
    ) -> None:
        row = tk.Frame(parent, bg=COLORS["surface"] if active else COLORS["sidebar"])
        row.pack(fill="x", padx=12, pady=3)
        if active:
            tk.Frame(row, bg=COLORS["accent"], width=3).pack(side="left", fill="y")
        badge = tk.Label(
            row,
            text=number,
            bg=COLORS["accent"] if active else COLORS["surface_alt"],
            fg=COLORS["text"] if active else COLORS["muted"],
            width=3,
            font=("Segoe UI Semibold", 9),
            padx=3,
            pady=7,
        )
        badge.pack(side="left", padx=(12 if active else 15, 10), pady=11)
        copy = tk.Frame(row, bg=row["bg"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(
            copy,
            text=title,
            bg=row["bg"],
            fg=COLORS["text"] if active else COLORS["muted"],
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w")
        tk.Label(
            copy,
            text=subtitle,
            bg=row["bg"],
            fg=COLORS["subtle"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 0))

    def _build_workspace(self, parent: tk.Widget) -> None:
        workspace = tk.Frame(parent, bg=COLORS["window"])
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_rowconfigure(1, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        header = tk.Frame(workspace, bg=COLORS["window"])
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(22, 18))
        title_block = tk.Frame(header, bg=COLORS["window"])
        title_block.pack(side="left")
        tk.Label(
            title_block,
            text="Password recovery workspace",
            bg=COLORS["window"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 22),
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text="Build a focused candidate plan from the details only you know.",
            bg=COLORS["window"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))
        badge = tk.Label(
            header,
            text="  PRIVATE  •  OFFLINE  ",
            bg=COLORS["surface"],
            fg=COLORS["success"],
            font=("Segoe UI Semibold", 8),
            padx=8,
            pady=7,
        )
        badge.pack(side="right", anchor="n", pady=4)

        body = tk.Frame(workspace, bg=COLORS["window"])
        body.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 26))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=5, uniform="body")
        body.grid_columnconfigure(1, weight=3, uniform="body")

        left = tk.Frame(body, bg=COLORS["window"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1, minsize=250)

        right = tk.Frame(body, bg=COLORS["window"])
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        self._build_archive_card(left)
        self._build_clues_card(left)
        self._build_options_card(left)
        self._build_status_card(right)
        self._build_log_card(right)

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )

    def _section_heading(self, parent: tk.Widget, eyebrow: str, title: str, help_text: str) -> None:
        heading = tk.Frame(parent, bg=COLORS["surface"])
        heading.pack(fill="x", padx=18, pady=(10, 7))
        tk.Label(
            heading,
            text=eyebrow,
            bg=COLORS["surface"],
            fg=COLORS["cyan"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        tk.Label(
            heading,
            text=title,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w", pady=(1, 0))
        tk.Label(
            heading,
            text=help_text,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

    def _build_archive_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._section_heading(card, "STEP 01", "Archive details", "Choose the protected file and a safe extraction location.")
        fields = tk.Frame(card, bg=COLORS["surface"])
        fields.pack(fill="x", padx=18, pady=(0, 10))
        fields.grid_columnconfigure(1, weight=1)
        self._path_row(fields, "ARCHIVE FILE", self.archive_var, self._browse_archive, 0, "Choose file")
        self._path_row(fields, "OUTPUT FOLDER", self.output_var, self._browse_output, 1, "Browse")

    def _build_clues_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=1, column=0, sticky="nsew", pady=10)
        self._section_heading(
            card,
            "STEP 02",
            "What do you remember?",
            "Both boxes are mutated and mixed into a ranked recovery plan.",
        )
        columns = tk.Frame(card, bg=COLORS["surface"])
        columns.pack(fill="both", expand=True, padx=18, pady=(0, 17))
        columns.grid_columnconfigure(0, weight=1, uniform="clues")
        columns.grid_columnconfigure(1, weight=1, uniform="clues")
        columns.grid_rowconfigure(1, weight=1, minsize=96)

        self._field_label(columns, "PASSWORD GUESSES  ·  MUTATED", 0, 0)
        self._field_label(columns, "CLUE WORDS & PATTERNS  ·  MIXED", 0, 1, padx=(8, 0))
        self.exact_text = self._text_field(columns, "An old password variation")
        self.clue_text = self._text_field(columns, "Names, places, years, symbols")
        self.exact_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0), padx=(0, 8))
        self.clue_text.grid(row=1, column=1, sticky="nsew", pady=(6, 0), padx=(8, 0))

    def _build_options_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        content = tk.Frame(card, bg=COLORS["surface"])
        content.pack(fill="x", padx=18, pady=15)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)

        self._field_label(content, "LIKELY YEARS / RANGES", 0, 0)
        self._field_label(content, "CANDIDATE LIMIT", 0, 1, padx=(14, 0))
        self._entry(content, self.years_var).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._entry(content, self.limit_var).grid(row=1, column=1, sticky="ew", padx=(14, 0), pady=(6, 0))
        tools = tk.Frame(content, bg=COLORS["surface"])
        tools.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._button(tools, "Preview generated mix", self._preview_mix).pack(side="left")
        self._button(tools, "Check installed tools", self._check_tools).pack(side="left", padx=(8, 0))

    def _build_status_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        top = tk.Frame(card, bg=COLORS["surface"])
        top.pack(fill="x", padx=18, pady=(18, 10))
        self.status_dot = tk.Label(
            top,
            text="●",
            bg=COLORS["surface"],
            fg=COLORS["success"],
            font=("Segoe UI", 16),
        )
        self.status_dot.pack(side="left", anchor="n", padx=(0, 10))
        copy = tk.Frame(top, bg=COLORS["surface"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(
            copy,
            textvariable=self.status_var,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w")
        tk.Label(
            copy,
            textvariable=self.status_detail_var,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            wraplength=270,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(3, 0))

        self.progress = ttk.Progressbar(
            card,
            mode="determinate",
            value=0,
            style="ArchiveKey.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", padx=18, pady=(2, 14))

        auth = tk.Checkbutton(
            card,
            text="I own this archive or have explicit permission.",
            variable=self.authorized_var,
            bg=COLORS["surface"],
            activebackground=COLORS["surface"],
            fg=COLORS["muted"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["field"],
            font=("Segoe UI", 9),
            wraplength=250,
            justify="left",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        auth.pack(anchor="w", padx=14, pady=(0, 13))

        actions = tk.Frame(card, bg=COLORS["surface"])
        actions.pack(fill="x", padx=18, pady=(0, 18))
        actions.grid_columnconfigure(0, weight=1)
        self.start_button = self._button(actions, "Start recovery  →", self._start, primary=True)
        self.cancel_button = self._button(actions, "Cancel", self._cancel, danger=True)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.cancel_button.grid(row=0, column=1, sticky="e", padx=(7, 0))
        self.cancel_button.configure(state="disabled")

    def _build_log_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        header = tk.Frame(card, bg=COLORS["surface"])
        header.pack(fill="x", padx=17, pady=(14, 10))
        tk.Label(
            header,
            text="RECOVERY ACTIVITY",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).pack(side="left")
        tk.Label(
            header,
            text="LIVE",
            bg=COLORS["surface_alt"],
            fg=COLORS["cyan"],
            padx=7,
            pady=3,
            font=("Segoe UI Semibold", 7),
        ).pack(side="right")

        log_border = tk.Frame(card, bg=COLORS["border"], padx=1, pady=1)
        log_border.pack(fill="both", expand=True, padx=17, pady=(0, 17))
        self.log_text = tk.Text(
            log_border,
            state="disabled",
            wrap="word",
            bg=COLORS["field"],
            fg=COLORS["muted"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=10,
            font=("Cascadia Mono", 8),
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("time", foreground=COLORS["subtle"])
        self.log_text.tag_configure("success", foreground=COLORS["success"])
        self.log_text.tag_configure("error", foreground=COLORS["danger"])
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "Waiting for a recovery plan.\n", "time")
        self.log_text.configure(state="disabled")

    def _field_label(
        self,
        parent: tk.Widget,
        text: str,
        row: int,
        column: int,
        padx: tuple[int, int] = (0, 0),
    ) -> None:
        tk.Label(
            parent,
            text=text,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).grid(row=row, column=column, sticky="w", padx=padx)

    def _entry(self, parent: tk.Widget, variable: tk.StringVar) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            bg=COLORS["field"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            disabledbackground=COLORS["field"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border_focus"],
            font=("Segoe UI", 9),
        )

    def _text_field(self, parent: tk.Widget, placeholder: str) -> tk.Text:
        field = tk.Text(
            parent,
            height=5,
            wrap="none",
            bg=COLORS["field"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border_focus"],
            padx=10,
            pady=9,
            font=("Segoe UI", 9),
        )
        field._archivekey_placeholder_active = True  # type: ignore[attr-defined]
        field.insert("1.0", placeholder)
        field.configure(fg=COLORS["subtle"])

        def clear_placeholder(_event=None) -> None:
            if field._archivekey_placeholder_active:  # type: ignore[attr-defined]
                field.delete("1.0", "end")
                field.configure(fg=COLORS["text"])
                field._archivekey_placeholder_active = False  # type: ignore[attr-defined]

        def restore_placeholder(_event=None) -> None:
            if not field.get("1.0", "end").strip():
                field.delete("1.0", "end")
                field.insert("1.0", placeholder)
                field.configure(fg=COLORS["subtle"])
                field._archivekey_placeholder_active = True  # type: ignore[attr-defined]

        field.bind("<FocusIn>", clear_placeholder)
        field.bind("<FocusOut>", restore_placeholder)
        field.configure(takefocus=True)
        return field

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        primary: bool = False,
        danger: bool = False,
    ) -> tk.Button:
        background = COLORS["accent"] if primary else COLORS["surface_alt"]
        foreground = COLORS["text"] if not danger else "#ff9bac"
        active = COLORS["accent_hover"] if primary else COLORS["border"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=active,
            activeforeground=COLORS["text"],
            disabledforeground=COLORS["subtle"],
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            highlightthickness=0,
        )

    def _path_row(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.StringVar,
        command,
        row: int,
        button_text: str,
        optional: bool = False,
    ) -> None:
        label_text = f"{label}  ·  OPTIONAL" if optional else label
        tk.Label(
            parent,
            text=label_text,
            bg=COLORS["surface"],
            fg=COLORS["subtle"] if optional else COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).grid(row=row, column=0, sticky="w", pady=3)
        entry = self._entry(parent, variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(12, 8), pady=3, ipady=5)
        self._button(parent, button_text, command).grid(row=row, column=2, sticky="e", pady=3)

    def _browse_archive(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose an archive",
            filetypes=[("Supported archives", "*.rar *.zip *.7z"), ("All files", "*.*")],
        )
        if selected:
            archive = Path(selected)
            self.archive_var.set(selected)
            self.output_var.set(str(archive.with_name(archive.stem + "-recovered")))
            self.status_var.set("Archive selected")
            self.status_detail_var.set(archive.name)

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose a parent output folder")
        if selected:
            archive_stem = Path(self.archive_var.get()).stem or "recovered"
            self.output_var.set(str(Path(selected) / f"{archive_stem}-recovered"))

    def _browse_john(self) -> None:
        selected = filedialog.askdirectory(title="Locate optional legacy tools")
        if selected:
            self.john_var.set(selected)

    def _check_tools(self) -> None:
        description = Toolchain.discover(self.john_var.get()).describe()
        self._log(f"Tool check: {description}")
        messagebox.showinfo(
            "Installed extraction tools",
            "ArchiveKey uses these local programs only to verify and extract a recovered archive.\n\n"
            f"{description}",
        )

    def _preview_mix(self) -> None:
        try:
            limit = int(self.limit_var.get())
            if not 1 <= limit <= 5_000_000:
                raise ValueError("Candidate limit must be between 1 and 5,000,000.")
            guesses = self._lines(self.exact_text)
            clues = self._lines(self.clue_text)
            if not guesses and not clues:
                raise ValueError("Add at least one password guess or remembered clue first.")
            preview_limit = min(limit, 50_000)
            ranked = generate_ranked_candidates(
                guesses,
                clues,
                self._parse_years(),
                preview_limit,
            )
        except ValueError as exc:
            messagebox.showerror("Cannot preview this plan", str(exc))
            return

        direct_count = sum(candidate.rule == "possible-guess" for candidate in ranked)
        derived = [candidate for candidate in ranked if candidate.rule != "possible-guess"]
        rule_counts = Counter(candidate.rule for candidate in derived)
        strategy_text = "\n".join(
            f"• {rule}: {count:,}" for rule, count in rule_counts.most_common(7)
        )
        example_text = "\n".join(
            f"• {candidate.value}   ({candidate.rule})" for candidate in derived[:10]
        )
        capped_text = (
            f"\nPreview capped at {preview_limit:,}; the full plan may be larger."
            if len(ranked) == preview_limit and limit > preview_limit
            else ""
        )
        messagebox.showinfo(
            "Generated mix preview",
            f"Inputs: {len(guesses)} guesses + {len(clues)} clues\n"
            f"Plan preview: {len(ranked):,} candidates\n"
            f"Supplied literally: {direct_count:,}\n"
            f"Generated or mixed: {len(derived):,}{capped_text}\n\n"
            f"Largest strategy groups:\n{strategy_text or '• Direct guesses only'}\n\n"
            f"Generated examples:\n{example_text or '• No derived candidates'}",
        )
        self.status_var.set("Generated mix previewed")
        self.status_detail_var.set(
            f"{len(derived):,} derived candidates from {len(guesses) + len(clues)} remembered inputs."
        )
        self._log(
            f"Preview: {direct_count:,} supplied candidates and {len(derived):,} generated/mixed candidates."
        )

    @staticmethod
    def _lines(widget: tk.Text) -> tuple[str, ...]:
        if getattr(widget, "_archivekey_placeholder_active", False):
            return ()
        return tuple(line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip())

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
            messagebox.showerror(
                "Authorization required",
                "Confirm that you own this archive or have explicit permission to recover it.",
            )
            return
        try:
            archive = Path(self.archive_var.get())
            output = Path(self.output_var.get())
            limit = int(self.limit_var.get())
            if not archive.is_file():
                raise ValueError("Choose an existing RAR, ZIP, or 7Z archive.")
            if not str(output):
                raise ValueError("Choose an output folder.")
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
            messagebox.showerror("Review recovery settings", str(exc))
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
            self.status_var.set("Cancelling recovery")
            self.status_detail_var.set("Finishing the current verification safely…")
            self.status_dot.configure(fg=COLORS["warning"])

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        if running:
            self.status_var.set("Recovery in progress")
            self.status_detail_var.set("Testing the focused candidate plan locally…")
            self.status_dot.configure(fg=COLORS["cyan"])
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)

    def _log(self, message: str) -> None:
        lowered = message.lower()
        tag = "error" if "error" in lowered else "success" if "recover" in lowered and "starting" not in lowered else None
        self.log_text.configure(state="normal")
        self.log_text.insert("end", datetime.now().strftime("%H:%M:%S  "), "time")
        self.log_text.insert("end", message.rstrip() + "\n", tag or "")
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
                    self.status_var.set("Recovery stopped")
                    self.status_detail_var.set("Review the error in the activity log.")
                    self.status_dot.configure(fg=COLORS["danger"])
                    self._log(f"ERROR: {payload}")
                    messagebox.showerror("Recovery failed", str(payload))
                elif kind == "done":
                    self._set_running(False)
                    result = payload
                    if result.cancelled:
                        self.status_var.set("Recovery cancelled")
                        self.status_detail_var.set("You can adjust the plan and start again.")
                        self.status_dot.configure(fg=COLORS["warning"])
                        self._log("Recovery cancelled.")
                    elif result.password:
                        self.status_var.set("Password recovered")
                        self.status_detail_var.set(f"Verified after {result.candidates_tested:,} candidates.")
                        self.status_dot.configure(fg=COLORS["success"])
                        self.progress.configure(value=100)
                        self._log(f"RECOVERED PASSWORD: {result.password}")
                        self._log(f"Candidates tested: {result.candidates_tested:,}")
                        if result.matched_rule:
                            self._log(f"Winning rule: {result.matched_rule}")
                        open_folder = messagebox.askyesno(
                            "Password recovered",
                            f"Password: {result.password}\n"
                            f"Candidates tested: {result.candidates_tested:,}\n"
                            f"Rule: {result.matched_rule or 'direct guess/legacy'}\n\n"
                            f"Extracted to:\n{result.output_directory}\n\n"
                            "Open the recovered folder now?",
                        )
                        if open_folder and result.output_directory:
                            try:
                                os.startfile(str(result.output_directory))
                            except OSError:
                                pass
                    else:
                        self.status_var.set("Plan completed")
                        self.status_detail_var.set("No candidate matched. Refine the clues and try again.")
                        self.status_dot.configure(fg=COLORS["warning"])
                        self._log("No match in this candidate set. Add stronger clues or expand the plan.")
                        messagebox.showwarning(
                            "No match in this plan",
                            "No supplied or generated candidate matched. Add more personal clues or expand the plan.",
                        )
        except queue.Empty:
            pass
        self.after(150, self._drain_events)


def main() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    ArchiveKeyApp().mainloop()


if __name__ == "__main__":
    main()
