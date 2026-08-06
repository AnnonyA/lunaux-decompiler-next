from __future__ import annotations

import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / ".lunaux-windows.json"
VENV_DIR = ROOT / ".venv"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_EXTERNAL_TIMEOUT = 45
UNLUAU_URL = "https://github.com/atrexus/unluau"

BG = "#0b1120"
PANEL = "#111a2e"
PANEL_ALT = "#17233b"
TEXT = "#e7eefc"
MUTED = "#93a4bf"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6aa0ff"
SUCCESS = "#42d392"
WARNING = "#f5b942"


@dataclass(slots=True)
class LauncherConfig:
    native_path: str = ""
    unluau_path: str = ""
    backend_mode: str = "auto"
    external_timeout_seconds: int = DEFAULT_EXTERNAL_TIMEOUT
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @classmethod
    def load(cls) -> LauncherConfig:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        return cls(
            native_path=str(data.get("native_path", "")),
            unluau_path=str(data.get("unluau_path", "")),
            backend_mode=str(data.get("backend_mode", "auto")),
            external_timeout_seconds=int(
                data.get("external_timeout_seconds", DEFAULT_EXTERNAL_TIMEOUT)
            ),
            host=str(data.get("host", DEFAULT_HOST)),
            port=int(data.get("port", DEFAULT_PORT)),
        )

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


class LunaUXInstaller:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = LauncherConfig.load()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.server_process: subprocess.Popen[str] | None = None
        self.busy = False

        self.root.title("LunaUX Next — Windows Launcher")
        self.root.geometry("960x720")
        self.root.minsize(840, 620)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._configure_styles()
        self._build_ui()
        self._refresh_status()
        self.root.after(100, self._drain_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Root.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Alt.TFrame", background=PANEL_ALT)
        style.configure(
            "Title.TLabel",
            background=BG,
            foreground=TEXT,
            font=("Segoe UI Semibold", 24),
        )
        style.configure(
            "Subtitle.TLabel",
            background=BG,
            foreground=MUTED,
            font=("Segoe UI", 10),
        )
        style.configure(
            "PanelTitle.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "Body.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=("Segoe UI", 9),
        )
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=PANEL,
            foreground=MUTED,
            padding=(16, 9),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL_ALT)],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="white",
            borderwidth=0,
            padding=(14, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", "#2d4265")],
        )
        style.configure(
            "Secondary.TButton",
            background=PANEL_ALT,
            foreground=TEXT,
            borderwidth=0,
            padding=(12, 9),
            font=("Segoe UI", 10),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#223354")],
        )
        style.configure(
            "Danger.TButton",
            background="#542b35",
            foreground="#ffd9de",
            borderwidth=0,
            padding=(12, 9),
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#6d3542")],
        )
        style.configure(
            "TEntry",
            fieldbackground="#0c1528",
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor="#2b3b59",
            padding=7,
        )
        style.configure(
            "TCombobox",
            fieldbackground="#0c1528",
            background="#0c1528",
            foreground=TEXT,
            arrowcolor=TEXT,
            padding=6,
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=(24, 20))
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer, style="Root.TFrame")
        header.pack(fill=X, pady=(0, 18))
        title_box = ttk.Frame(header, style="Root.TFrame")
        title_box.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(title_box, text="LunaUX Next", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            title_box,
            text="Multi-engine Roblox Luau decompiler and local API launcher",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        self.server_badge = tk.Label(
            header,
            text="●  Server stopped",
            bg=PANEL_ALT,
            fg=MUTED,
            padx=14,
            pady=8,
            font=("Segoe UI Semibold", 9),
        )
        self.server_badge.pack(side=RIGHT)

        self._build_status_cards(outer)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=BOTH, expand=True, pady=(16, 0))
        dashboard = ttk.Frame(notebook, style="Panel.TFrame", padding=18)
        engines = ttk.Frame(notebook, style="Panel.TFrame", padding=18)
        logs = ttk.Frame(notebook, style="Panel.TFrame", padding=12)
        notebook.add(dashboard, text="Dashboard")
        notebook.add(engines, text="Decompiler engines")
        notebook.add(logs, text="Logs")

        self._build_dashboard(dashboard)
        self._build_backend_tab(engines)
        self._build_logs(logs)

    def _build_status_cards(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="Root.TFrame")
        row.pack(fill=X)
        self.python_value = self._status_card(row, "Python", "Checking…")
        self.install_value = self._status_card(row, "Installation", "Checking…")
        self.backend_value = self._status_card(row, "Engine chain", "Checking…")

    def _status_card(
        self,
        parent: ttk.Frame,
        title: str,
        value: str,
    ) -> tk.Label:
        card = ttk.Frame(parent, style="Alt.TFrame", padding=(16, 13))
        card.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        tk.Label(
            card,
            text=title,
            bg=PANEL_ALT,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        label = tk.Label(
            card,
            text=value,
            bg=PANEL_ALT,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
        )
        label.pack(anchor="w", pady=(4, 0))
        return label

    def _build_dashboard(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Local service", style="PanelTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            parent,
            text=(
                "Install the project into an isolated environment, then start "
                "the API on your computer."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        controls = ttk.Frame(parent, style="Panel.TFrame")
        controls.pack(fill=X)
        self.install_button = ttk.Button(
            controls,
            text="Install / Update",
            style="Accent.TButton",
            command=self.install_or_update,
        )
        self.install_button.pack(side=LEFT, padx=(0, 8))
        self.start_button = ttk.Button(
            controls,
            text="Start server",
            style="Secondary.TButton",
            command=self.start_server,
        )
        self.start_button.pack(side=LEFT, padx=(0, 8))
        self.stop_button = ttk.Button(
            controls,
            text="Stop server",
            style="Danger.TButton",
            command=self.stop_server,
        )
        self.stop_button.pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            controls,
            text="API docs",
            style="Secondary.TButton",
            command=self.open_docs,
        ).pack(side=LEFT)

        ttk.Separator(parent).pack(fill=X, pady=18)

        ttk.Label(parent, text="Tools", style="PanelTitle.TLabel").pack(
            anchor="w"
        )
        tools = ttk.Frame(parent, style="Panel.TFrame")
        tools.pack(fill=X, pady=(12, 0))
        ttk.Button(
            tools,
            text="Run diagnostics",
            style="Secondary.TButton",
            command=self.run_doctor,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            tools,
            text="Open project folder",
            style="Secondary.TButton",
            command=self.open_folder,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            tools,
            text="Copy API URL",
            style="Secondary.TButton",
            command=self.copy_api_url,
        ).pack(side=LEFT)

        info = ttk.Frame(parent, style="Alt.TFrame", padding=16)
        info.pack(fill=X, pady=(20, 0))
        tk.Label(
            info,
            text=(
                "Recommended mode: Native → Unluau → Python. LunaUX tries the "
                "next engine automatically when one engine cannot recover a "
                "specific script. External binaries remain optional."
            ),
            bg=PANEL_ALT,
            fg=TEXT,
            justify=LEFT,
            wraplength=800,
            font=("Segoe UI", 10),
        ).pack(anchor="w")

    def _build_backend_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="Decompiler engine configuration",
            style="PanelTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text=(
                "Auto mode tries a compatible luna extension, then Unluau, "
                "then the portable Python engine. Paths may be left empty "
                "for automatic detection."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        ttk.Label(parent, text="Backend mode", style="Body.TLabel").pack(
            anchor="w"
        )
        self.mode_var = tk.StringVar(value=self.config.backend_mode)
        mode = ttk.Combobox(
            parent,
            textvariable=self.mode_var,
            values=("auto", "native", "unluau", "reconstructed"),
            state="readonly",
            width=24,
        )
        mode.pack(anchor="w", pady=(6, 12))

        ttk.Label(parent, text="luna.pyd path", style="Body.TLabel").pack(
            anchor="w"
        )
        native_row = ttk.Frame(parent, style="Panel.TFrame")
        native_row.pack(fill=X, pady=(6, 10))
        self.native_var = tk.StringVar(value=self.config.native_path)
        ttk.Entry(native_row, textvariable=self.native_var).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(0, 8),
        )
        ttk.Button(
            native_row,
            text="Browse…",
            style="Secondary.TButton",
            command=self.choose_native,
        ).pack(side=RIGHT)

        ttk.Label(
            parent,
            text="Unluau executable or .NET DLL",
            style="Body.TLabel",
        ).pack(anchor="w")
        unluau_row = ttk.Frame(parent, style="Panel.TFrame")
        unluau_row.pack(fill=X, pady=(6, 10))
        self.unluau_var = tk.StringVar(value=self.config.unluau_path)
        ttk.Entry(unluau_row, textvariable=self.unluau_var).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(0, 8),
        )
        ttk.Button(
            unluau_row,
            text="Browse…",
            style="Secondary.TButton",
            command=self.choose_unluau,
        ).pack(side=RIGHT, padx=(0, 8))
        ttk.Button(
            unluau_row,
            text="Upstream",
            style="Secondary.TButton",
            command=self.open_unluau,
        ).pack(side=RIGHT)

        server_row = ttk.Frame(parent, style="Panel.TFrame")
        server_row.pack(fill=X, pady=(10, 0))
        host_box = ttk.Frame(server_row, style="Panel.TFrame")
        host_box.pack(side=LEFT, padx=(0, 18))
        ttk.Label(host_box, text="Host", style="Body.TLabel").pack(anchor="w")
        self.host_var = tk.StringVar(value=self.config.host)
        ttk.Entry(host_box, textvariable=self.host_var, width=22).pack(
            pady=(6, 0)
        )
        port_box = ttk.Frame(server_row, style="Panel.TFrame")
        port_box.pack(side=LEFT, padx=(0, 18))
        ttk.Label(port_box, text="Port", style="Body.TLabel").pack(anchor="w")
        self.port_var = tk.StringVar(value=str(self.config.port))
        ttk.Entry(port_box, textvariable=self.port_var, width=10).pack(
            pady=(6, 0)
        )
        timeout_box = ttk.Frame(server_row, style="Panel.TFrame")
        timeout_box.pack(side=LEFT)
        ttk.Label(
            timeout_box,
            text="External timeout (seconds)",
            style="Body.TLabel",
        ).pack(anchor="w")
        self.timeout_var = tk.StringVar(
            value=str(self.config.external_timeout_seconds)
        )
        ttk.Entry(timeout_box, textvariable=self.timeout_var, width=12).pack(
            pady=(6, 0)
        )

        ttk.Button(
            parent,
            text="Save configuration",
            style="Accent.TButton",
            command=self.save_configuration,
        ).pack(anchor="w", pady=(18, 0))

    def _build_logs(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent, style="Panel.TFrame")
        toolbar.pack(fill=X, pady=(0, 8))
        ttk.Label(toolbar, text="Activity log", style="PanelTitle.TLabel").pack(
            side=LEFT
        )
        ttk.Button(
            toolbar,
            text="Clear",
            style="Secondary.TButton",
            command=self.clear_log,
        ).pack(side=RIGHT)

        text_frame = ttk.Frame(parent, style="Panel.TFrame")
        text_frame.pack(fill=BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.log_text = tk.Text(
            text_frame,
            bg="#07101f",
            fg="#c9d7ed",
            insertbackground=TEXT,
            selectbackground="#29456f",
            relief="flat",
            font=("Cascadia Mono", 9),
            wrap="word",
            yscrollcommand=scrollbar.set,
            padx=12,
            pady=12,
        )
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.configure(command=self.log_text.yview)
        self.log_text.configure(state="disabled")

    def _venv_python(self) -> Path:
        return VENV_DIR / "Scripts" / "python.exe"

    def _append_log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"[{timestamp}] {text.rstrip()}\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _post(self, kind: str, payload: object = None) -> None:
        self.events.put((kind, payload))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "busy":
                    self._set_busy(bool(payload))
                elif kind == "refresh":
                    self._refresh_status()
                elif kind == "server_stopped":
                    self.server_process = None
                    self._refresh_status()
                elif kind == "error":
                    messagebox.showerror("LunaUX Next", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        state = "disabled" if value else "normal"
        self.install_button.configure(state=state)
        self.start_button.configure(
            state=state if self.server_process is None else "disabled"
        )

    def _run_background(self, task: Callable[[], None]) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def runner() -> None:
            try:
                task()
            except Exception as exc:
                self._post("log", f"ERROR: {exc}")
                self._post("error", str(exc))
            finally:
                self._post("busy", False)
                self._post("refresh")

        threading.Thread(target=runner, daemon=True).start()

    def _creation_flags(self) -> int:
        if os.name == "nt":
            return subprocess.CREATE_NO_WINDOW
        return 0

    def _run_command(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> int:
        self._post("log", "> " + " ".join(command))
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=self._creation_flags(),
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._post("log", line.rstrip())
        return process.wait()

    def install_or_update(self) -> None:
        def task() -> None:
            if not self._venv_python().exists():
                self._post("log", "Creating isolated .venv environment…")
                code = self._run_command(
                    [sys.executable, "-m", "venv", str(VENV_DIR)]
                )
                if code:
                    raise RuntimeError("Could not create the virtual environment.")
            python = str(self._venv_python())
            if self._run_command(
                [python, "-m", "pip", "install", "--upgrade", "pip"]
            ):
                raise RuntimeError("pip upgrade failed.")
            if self._run_command(
                [python, "-m", "pip", "install", "-e", "."]
            ):
                raise RuntimeError("Project installation failed.")
            self._post("log", "Installation completed successfully.")

        self._run_background(task)

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["LUNAUX_BACKEND_MODE"] = self.config.backend_mode
        env["LUNAUX_BACKEND_MODULE"] = "luna"
        env["LUNAUX_EXTERNAL_TIMEOUT_SECONDS"] = str(
            self.config.external_timeout_seconds
        )
        if self.config.native_path:
            env["LUNAUX_NATIVE_PATH"] = self.config.native_path
        else:
            env.pop("LUNAUX_NATIVE_PATH", None)
        if self.config.unluau_path:
            env["LUNAUX_UNLUAU_PATH"] = self.config.unluau_path
        else:
            env.pop("LUNAUX_UNLUAU_PATH", None)
        return env

    def start_server(self) -> None:
        if self.server_process is not None and self.server_process.poll() is None:
            messagebox.showinfo(
                "LunaUX Next",
                "The local server is already running.",
            )
            return
        if not self._venv_python().exists():
            messagebox.showwarning("LunaUX Next", "Install the project first.")
            return
        if not self.save_configuration(show_message=False):
            return
        command = [
            str(self._venv_python()),
            "-m",
            "lunaux",
            "run",
            "--host",
            self.config.host,
            "--port",
            str(self.config.port),
        ]
        self._append_log("> " + " ".join(command))
        self.server_process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=self._environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=self._creation_flags(),
        )
        threading.Thread(target=self._read_server_output, daemon=True).start()
        self._refresh_status()
        self.root.after(700, self._check_health)

    def _read_server_output(self) -> None:
        process = self.server_process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._post("log", line.rstrip())
        process.wait()
        self._post("server_stopped")

    def stop_server(self) -> None:
        process = self.server_process
        if process is None or process.poll() is not None:
            self.server_process = None
            self._refresh_status()
            return
        self._append_log("Stopping local server…")
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        self.server_process = None
        self._refresh_status()

    def _check_health(self) -> None:
        if self.server_process is None or self.server_process.poll() is not None:
            return
        try:
            with urllib.request.urlopen(
                self.api_url + "/health",
                timeout=1.5,
            ) as response:
                if response.status == 200:
                    self._append_log("Server health check passed.")
        except (urllib.error.URLError, TimeoutError):
            self._append_log("Server started; health endpoint is not ready yet.")

    @property
    def api_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def run_doctor(self) -> None:
        if not self._venv_python().exists():
            messagebox.showwarning("LunaUX Next", "Install the project first.")
            return

        def task() -> None:
            code = self._run_command(
                [str(self._venv_python()), "-m", "lunaux", "doctor"],
                env=self._environment(),
            )
            if code:
                raise RuntimeError(
                    "Diagnostics reported an error. See the Logs tab."
                )

        self._run_background(task)

    def choose_native(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select LunaUX native backend",
            filetypes=(("Python extension", "*.pyd"), ("All files", "*.*")),
        )
        if selected:
            self.native_var.set(selected)

    def choose_unluau(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Unluau command-line build",
            filetypes=(
                ("Unluau executable or DLL", "*.exe *.dll"),
                ("All files", "*.*"),
            ),
        )
        if selected:
            self.unluau_var.set(selected)

    def open_unluau(self) -> None:
        webbrowser.open(UNLUAU_URL)

    def save_configuration(self, *, show_message: bool = True) -> bool:
        try:
            port = int(self.port_var.get())
            timeout = int(self.timeout_var.get())
        except ValueError:
            messagebox.showerror(
                "LunaUX Next",
                "Port and timeout must be whole numbers.",
            )
            return False
        if not 1 <= port <= 65535:
            messagebox.showerror(
                "LunaUX Next",
                "Port must be between 1 and 65535.",
            )
            return False
        if timeout <= 0:
            messagebox.showerror(
                "LunaUX Next",
                "External timeout must be greater than zero.",
            )
            return False
        native_path = self.native_var.get().strip()
        unluau_path = self.unluau_var.get().strip()
        if native_path and not Path(native_path).is_file():
            messagebox.showerror(
                "LunaUX Next",
                "The selected native backend does not exist.",
            )
            return False
        if unluau_path and not Path(unluau_path).is_file():
            messagebox.showerror(
                "LunaUX Next",
                "The selected Unluau executable or DLL does not exist.",
            )
            return False
        self.config = LauncherConfig(
            native_path=native_path,
            unluau_path=unluau_path,
            backend_mode=self.mode_var.get(),
            external_timeout_seconds=timeout,
            host=self.host_var.get().strip() or DEFAULT_HOST,
            port=port,
        )
        self.config.save()
        self._refresh_status()
        if show_message:
            messagebox.showinfo("LunaUX Next", "Configuration saved.")
        return True

    def open_docs(self) -> None:
        webbrowser.open(self.api_url + "/docs")

    def open_folder(self) -> None:
        if os.name == "nt":
            os.startfile(ROOT)
        else:
            webbrowser.open(ROOT.as_uri())

    def copy_api_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.api_url)
        self._append_log(f"Copied {self.api_url}")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")

    def _has_unluau(self) -> bool:
        if self.config.unluau_path and Path(self.config.unluau_path).is_file():
            return True
        candidates = (
            ROOT / "tools" / "unluau" / "unluau.exe",
            ROOT / "tools" / "unluau" / "Unluau.CLI.exe",
            ROOT / "tools" / "unluau" / "Unluau.CLI.dll",
        )
        if any(candidate.is_file() for candidate in candidates):
            return True
        return any(
            shutil.which(name)
            for name in ("unluau", "Unluau.CLI", "Unluau.CLI.exe")
        )

    def _refresh_status(self) -> None:
        architecture = platform.machine() or "unknown"
        self.python_value.configure(
            text=f"{platform.python_version()} · {architecture}"
        )
        installed = self._venv_python().exists()
        self.install_value.configure(
            text="Ready" if installed else "Not installed",
            fg=SUCCESS if installed else WARNING,
        )
        has_native = bool(
            self.config.native_path and Path(self.config.native_path).is_file()
        )
        has_unluau = self._has_unluau()
        if self.config.backend_mode == "native":
            backend_text = "Native only"
        elif self.config.backend_mode == "unluau":
            backend_text = "Unluau only"
        elif self.config.backend_mode == "reconstructed":
            backend_text = "Python only"
        elif has_native and has_unluau:
            backend_text = "Native → Unluau → Python"
        elif has_native:
            backend_text = "Native → Python"
        elif has_unluau:
            backend_text = "Unluau → Python"
        else:
            backend_text = "Auto-detect → Python"
        self.backend_value.configure(text=backend_text)

        running = (
            self.server_process is not None
            and self.server_process.poll() is None
        )
        self.server_badge.configure(
            text="●  Server running" if running else "●  Server stopped",
            fg=SUCCESS if running else MUTED,
        )
        self.start_button.configure(
            state="disabled" if running or self.busy else "normal"
        )
        self.stop_button.configure(state="normal" if running else "disabled")

    def on_close(self) -> None:
        self.stop_server()
        self.root.destroy()


def main() -> int:
    if os.name != "nt":
        print(
            "This launcher is designed for Windows. "
            "Use `python -m lunaux` on other systems."
        )
    root = tk.Tk()
    LunaUXInstaller(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
