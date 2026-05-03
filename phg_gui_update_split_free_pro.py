# -*- coding: utf-8 -*-
r"""
PHG LIVE GUI wrapper — DBD UNLOCK style

Положите этот файл / собранный exe в ту же папку, где находятся:
  service_phg.bat
  UNLOCK-1.bat
  UNLOCK-2.bat
  UNLOCK-ALL.bat
  keys.txt                 # ключи PRO, по одному на строку: xxx-xxx-xxx-xxxx
  images\logo.png
  images\logo2.png
  images\logo3.png
  images\logo4.png
  images\fone.png
  images\scratch.png          # необязательно: текстура поверх красных кнопок
  utils\test zapret.ps1

Для отображения логотипа нужен Pillow:
  pip install pillow

Сборка в exe:
  pip install pyinstaller pillow pystray
  pyinstaller --onefile --noconsole --name DBD-UNLOCK phg_gui_updated.py

Важно: запускать от имени администратора. Скрипт сам запросит права администратора.
"""

import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import random
import tempfile
import urllib.request
# winreg is imported lazily on Windows
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageTk, ImageSequence
except Exception:
    Image = ImageTk = None

try:
    import pystray
except Exception:
    pystray = None

APP_TITLE = "DBD UNLOCK - RU"
APP_FOOTER = "PHG-LIVE"
DISCLAIMER_TEXT = "Developed by a third-party team, not affiliated with BHVR"
IMAGES_DIR = Path("images")
UTILS_DIR = Path("utils")
LOGO_FILE = IMAGES_DIR / "logo.png"
ICON_FILE = IMAGES_DIR / "logo2.png"
SPLASH_FILE = IMAGES_DIR / "logo3.gif"
FOOTER_ICON_FILE = IMAGES_DIR / "logo4.png"
BACKGROUND_FILE = IMAGES_DIR / "fone.png"
SCRATCH_FILE = IMAGES_DIR / "scratch.png"
TEST_SCRIPT_FILE = UTILS_DIR / "test zapret.ps1"
KEYS_FILE = "keys.txt"
CONFIG_FILE = "phg_config.json"
CURRENT_VERSION = "1.0.0"
# Замените ссылку на свой version.json, например GitHub Releases или свой сайт.
UPDATE_INFO_URL = "https://example.com/phg/version.json"
KEY_LIFETIME_SECONDS = 30 * 24 * 60 * 60
KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{3}-[A-Za-z0-9]{3}-[A-Za-z0-9]{3}-[A-Za-z0-9]{4}$")

BG = "#000000"
PANEL = "#151618"
PANEL_2 = "#1c1d20"
BORDER = "#3a3d42"
BORDER_HOVER = "#686c74"
TEXT = "#f4f4f4"
MUTED = "#b8bac0"
DIM = "#858891"
RED = "#ff4d4d"
GREEN = "#4dff88"
YELLOW = "#ffd84d"
BLUE = "#5dade2"
DARK_RED = "#8d0000"
BRIGHT_RED = "#ff1616"
BUTTON_RED = "#b80000"
BUTTON_RED_HOVER = "#e10000"
BUTTON_RED_DARK = "#7f0000"

SERVICE_NAMES = ["Discord", "YouTube", "DBD", "Outlast", "Instagram", "Twitter", "TikTok"]
REGIONS = ["AUTO", "Europe", "Russia", "Turkey", "Germany", "Poland", "USA East", "USA West", "Asia"]
PING_RANGES = {
    "AUTO": (55, 85),
    "Europe": (40, 65),
    "Russia": (35, 60),
    "Turkey": (55, 80),
    "Germany": (38, 62),
    "Poland": (42, 66),
    "USA East": (110, 150),
    "USA West": (145, 190),
    "Asia": (90, 130),
}
DEFAULT_SERVICES = {name: (name in {"Discord", "DBD"}) for name in SERVICE_NAMES}


def is_windows() -> bool:
    return os.name == "nt"


def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if not is_windows() or is_admin():
        return
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = " ".join([f'"{a}"' for a in sys.argv[1:]])
    else:
        exe = sys.executable
        script = Path(__file__).resolve()
        params = f'"{script}" ' + " ".join([f'"{a}"' for a in sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    if rc <= 32:
        messagebox.showerror(APP_TITLE, "Не удалось запросить права администратора.")
    sys.exit(0)


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def asset_path(root_dir: Path, asset_dir: Path, relative_path: Path) -> Path:
    external = root_dir / relative_path
    if external.exists():
        return external
    return asset_dir / relative_path


def image_fit_size(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0 or max_w <= 0 or max_h <= 0:
        return max(1, max_w), max(1, max_h)
    scale = min(max_w / src_w, max_h / src_h, 1.0)
    return max(1, int(src_w * scale)), max(1, int(src_h * scale))


def method_title(path_or_name) -> str:
    name = Path(str(path_or_name)).name
    if name.lower().endswith((".bat", ".cmd")):
        name = Path(name).stem
    return name.replace("_", " ").strip()


def _create_hidden_startupinfo():
    if not is_windows():
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def _patch_start_to_background(line: str) -> str:
    stripped = line.lstrip()
    prefix = line[: len(line) - len(stripped)]
    low = stripped.lower()
    if not low.startswith("start"):
        return line
    if len(stripped) > 5 and not stripped[5].isspace():
        return line
    if re.search(r"(?i)(^|\s)/b(\s|$)", stripped):
        return line
    m = re.match(r"(?is)^start\s+(\"[^\"]*\")(.*)$", stripped)
    if m:
        return prefix + "start " + m.group(1) + " /B" + m.group(2)
    return prefix + "start /B " + stripped[5:].lstrip()


def make_hidden_method_bat(method: Path, root_dir: Path) -> Path:
    text = method.read_text(encoding="utf-8", errors="ignore").splitlines()
    patched = [_patch_start_to_background(line) for line in text]
    tmp = root_dir / "_phg_gui_hidden_method.cmd"
    header = ["@echo off", "chcp 65001 >nul", f'cd /d "{method.parent}"', f"rem generated from {method.name}"]
    tmp.write_text("\r\n".join(header + patched) + "\r\n", encoding="utf-8")
    return tmp


class GhostButton(tk.Canvas):
    def __init__(self, master, title: str, command=None, width=360, height=88, font_size=21):
        super().__init__(master, width=width, height=height, highlightthickness=0, bg=BUTTON_RED, cursor="hand2")
        self.command = command
        self.title = title
        self.width = width
        self.height = height
        self.font_size = font_size
        self.hovered = False
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self.draw())
        self.draw()

    def _enter(self, _event):
        self.hovered = True
        self.draw()

    def _leave(self, _event):
        self.hovered = False
        self.draw()

    def _click(self, _event):
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        w = max(10, self.winfo_width() or self.width)
        h = max(10, self.winfo_height() or self.height)
        fill = BUTTON_RED_HOVER if self.hovered else BUTTON_RED
        outline = "#ff3b3b" if self.hovered else BUTTON_RED_DARK
        self.create_rectangle(0, 0, w, h, fill=fill, outline=outline, width=1)
        self.create_polygon(w - 120, 0, w, 0, w, h, w - 28, h, fill="#9a0000", outline="")
        self.draw_scratch_texture(w, h)
        self.create_rectangle(1, 1, w - 1, h - 1, outline="#d62828", width=1)
        self.create_text(w / 2, h / 2, text=self.title, fill=TEXT, font=("Segoe UI", self.font_size, "bold"))

    def draw_scratch_texture(self, w: int, h: int):
        """Накладывает images/scratch.png поверх кнопки, если файл есть."""
        if not (Image and ImageTk):
            return
        try:
            scratch_path = asset_path(app_dir(), bundled_dir(), SCRATCH_FILE)
            if not scratch_path.exists():
                return
            texture = Image.open(scratch_path).convert("RGBA").resize((w, h), Image.LANCZOS)
            # Делаем текстуру лёгкой, чтобы она не забивала красную кнопку.
            alpha = texture.getchannel("A").point(lambda a: int(a * 2.0))
            texture.putalpha(alpha)
            self._scratch_ref = ImageTk.PhotoImage(texture)
            self.create_image(0, 0, image=self._scratch_ref, anchor="nw")
        except Exception:
            return


class SwitchRow(tk.Canvas):
    def __init__(self, master, title, value=False, command=None, width=720, height=50):
        super().__init__(master, width=width, height=height, highlightthickness=0, bg=BG, cursor="hand2")
        self.title = title
        self.value = bool(value)
        self.command = command
        self.hovered = False
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self.draw())
        self.draw()

    def rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _hover(self, val):
        self.hovered = val
        self.draw()

    def _click(self, _event):
        if self.command:
            self.command(self)

    def set_value(self, value):
        self.value = bool(value)
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width() or 720
        h = self.winfo_height() or 50
        fill = ""
        self.rounded_rect(1, 1, w - 1, h - 1, 14, fill="", outline=BORDER)
        self.create_text(54, h / 2, text=self.title, anchor="w", fill=TEXT, font=("Segoe UI", 12))
        sw, sh = 62, 28
        x = w - sw - 16
        y = (h - sh) / 2
        color = "#00c319" if self.value else "#4a4a4a"
        label = "ON" if self.value else "OFF"
        self.rounded_rect(x, y, x + sw, y + sh, 12, fill=color, outline="")
        knob_x = x + sw - 14 if self.value else x + 14
        self.create_oval(knob_x - 10, y + 4, knob_x + 10, y + sh - 4, fill="#f7f7f7", outline="")
        self.create_text(x + 18 if self.value else x + 42, y + sh / 2, text=label, fill="white", font=("Segoe UI", 8, "bold"))


class PHGGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.root_dir = app_dir()
        self.asset_dir = bundled_dir()
        self.current_method: Path | None = None
        self.method_process = None
        self.tray_icon = None
        self._tray_thread = None
        self.connected = False
        self.uptime_started_at: float | None = None
        self.logo_image = None
        self.current_page = "main"
        self.main_widgets = []
        self.settings_frame = None
        self.key_overlay = None
        self.config_path = self.root_dir / CONFIG_FILE
        self.config = self.load_config()
        self.config.setdefault("services", DEFAULT_SERVICES.copy())
        self.config.setdefault("auto_update", False)
        for _svc, _val in DEFAULT_SERVICES.items():
            self.config["services"].setdefault(_svc, _val)
        # Миграция старых конфигов: при первом запуске этой версии Discord и DBD включены по умолчанию.
        if not self.config.get("defaults_initialized_v3"):
            self.config["services"]["Discord"] = True
            self.config["services"]["DBD"] = True
            self.config["defaults_initialized_v3"] = True
            self.save_config()

        self.title(APP_TITLE)
        self.set_window_icon()
        self.geometry("1040x780")
        self.resizable(False, False)
        self.configure(bg=BG)

        self.methods = self.find_methods()
        saved_method = self.config.get("method", "")
        default_method = saved_method if saved_method else (self.methods[0].name if self.methods else "-")
        self.method_var = tk.StringVar(value=default_method)
        self.status_var = tk.StringVar(value="Отключено")
        self.connection_var = tk.StringVar(value="-")
        self.uptime_var = tk.StringVar(value="00:00:00")
        self.ping_var = tk.StringVar(value=self.estimate_ping_text(default_method))
        self.region_var = tk.StringVar(value=self.config.get("region", REGIONS[0]))

        self.splash_image = None
        self.bg_image = None
        self.footer_icon_image = None
        self.show_splash_screen()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_config(self):
        try:
            if self.config_path.exists():
                return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"services": DEFAULT_SERVICES.copy(), "region": REGIONS[0], "autostart": False, "auto_update": False}

    def save_config(self):
        try:
            self.config_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Не удалось сохранить настройки:\n{e}")

    def set_window_icon(self):
        try:
            logo_path = asset_path(self.root_dir, self.asset_dir, ICON_FILE)
            if logo_path.exists() and Image and ImageTk:
                img = Image.open(logo_path).convert("RGBA")
                icon = ImageTk.PhotoImage(img)
                self.iconphoto(True, icon)
                self._icon_ref = icon
        except Exception:
            pass

    def find_methods(self) -> list[Path]:
        files = []
        seen = set()

        # Ищем методы рядом с exe/py и внутри PyInstaller-пакета (_MEIPASS).
        # Это нужно, чтобы .bat файлы отображались в списке после сборки в exe.
        for base_dir in (self.root_dir, self.asset_dir):
            try:
                for p in base_dir.glob("*.bat"):
                    name_lower = p.name.lower()
                    if name_lower.startswith("service"):
                        continue
                    if name_lower in seen:
                        continue
                    seen.add(name_lower)
                    files.append(p)
            except Exception:
                pass

        return sorted(files, key=lambda x: x.name.lower())

    def is_pro(self) -> bool:
        key = self.config.get("license_key", "")
        activated_at = float(self.config.get("license_activated_at", 0) or 0)
        if not key or not activated_at:
            return False
        if time.time() - activated_at > KEY_LIFETIME_SECONDS:
            self.config.pop("license_key", None)
            self.config.pop("license_activated_at", None)
            self.save_config()
            return False
        return self.key_in_file(key)

    def key_in_file(self, key: str) -> bool:
        keys_path = asset_path(self.root_dir, self.asset_dir, Path(KEYS_FILE))
        if not keys_path.exists():
            return False
        try:
            keys = {line.strip().upper() for line in keys_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip() and not line.strip().startswith("#")}
            return key.strip().upper() in keys
        except Exception:
            return False

    def require_pro(self) -> bool:
        if self.is_pro():
            return True
        self.open_key_window()
        return False

    def activate_key(self, key: str) -> bool:
        key = key.strip().upper()
        if not KEY_PATTERN.match(key):
            messagebox.showerror(APP_TITLE, "Формат ключа должен быть xxx-xxx-xxx-xxxx")
            return False
        if not self.key_in_file(key):
            messagebox.showerror(APP_TITLE, f"Ключ не найден в файле {KEYS_FILE}.")
            return False
        self.config["license_key"] = key
        self.config["license_activated_at"] = time.time()
        self.save_config()
        self.refresh_license_badge()
        messagebox.showinfo(APP_TITLE, "Ключ активирован на 30 дней.")
        return True

    def refresh_license_badge(self):
        if hasattr(self, "license_badge"):
            pro = self.is_pro()
            self.license_badge.config(text="PRO" if pro else "FREE", fg=TEXT if pro else YELLOW, bg="#bb3434" if pro else BG)
        if hasattr(self, "draw_status_panel"):
            self.draw_status_panel()

    def estimate_ping_text(self, method_name: str | None = None) -> str:
        region = self.region_var.get() if hasattr(self, "region_var") else self.config.get("region", REGIONS[0])
        low, high = PING_RANGES.get(region, PING_RANGES["AUTO"])
        value = random.randint(low, high)
        return f"{value} ms"

    def update_live_ping(self):
        self.ping_var.set(self.estimate_ping_text())
        if hasattr(self, "draw_status_panel"):
            self.draw_status_panel()
        self.after(1400, self.update_live_ping)


    def show_splash_screen(self):
        self.splash = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.splash.pack(fill="both", expand=True)
        self.splash_frames = []
        self.splash_frame_index = 0
        self.splash_anim_job = None
        self.splash.bind("<Configure>", lambda _e: self.prepare_splash_frames())
        self.after(100, self.prepare_splash_frames)
        self.after(4000, self.finish_splash)

    def prepare_splash_frames(self):
        if not hasattr(self, "splash") or not self.splash.winfo_exists():
            return
        w = self.splash.winfo_width() or 1040
        h = self.splash.winfo_height() or 780
        splash_path = asset_path(self.root_dir, self.asset_dir, SPLASH_FILE)
        self.splash_frames = []
        self.splash_durations = []
        if Image and ImageTk and splash_path.exists():
            try:
                img = Image.open(splash_path)
                for frame in ImageSequence.Iterator(img):
                    fr = frame.convert("RGBA")
                    nw, nh = image_fit_size(fr.width, fr.height, int(w * 0.82), int(h * 0.82))
                    fr = fr.resize((nw, nh), Image.LANCZOS)
                    self.splash_frames.append(ImageTk.PhotoImage(fr))
                    self.splash_durations.append(max(40, int(frame.info.get("duration", 80) or 80)))
                if not self.splash_frames:
                    raise ValueError("empty gif")
                self.splash_frame_index = 0
                if self.splash_anim_job:
                    self.after_cancel(self.splash_anim_job)
                self.animate_splash()
                return
            except Exception:
                self.splash_frames = []
                self.splash_durations = []
        self.draw_splash_fallback()

    def animate_splash(self):
        if not hasattr(self, "splash") or not self.splash.winfo_exists() or not self.splash_frames:
            return
        c = self.splash
        c.delete("all")
        w = c.winfo_width() or 1040
        h = c.winfo_height() or 780
        c.create_rectangle(0, 0, w, h, fill=BG, outline="")
        img = self.splash_frames[self.splash_frame_index]
        c.create_image(w / 2, h / 2, image=img, anchor="center")
        delay = self.splash_durations[self.splash_frame_index] if self.splash_durations else 80
        self.splash_frame_index = (self.splash_frame_index + 1) % len(self.splash_frames)
        self.splash_anim_job = self.after(delay, self.animate_splash)

    def draw_splash_fallback(self):
        if not hasattr(self, "splash") or not self.splash.winfo_exists():
            return
        c = self.splash
        c.delete("all")
        w = c.winfo_width() or 1040
        h = c.winfo_height() or 780
        c.create_rectangle(0, 0, w, h, fill=BG, outline="")
        c.create_text(w / 2, h / 2, text=APP_TITLE, fill=TEXT, font=("Segoe UI", 34, "bold"))

    def finish_splash(self):
        if getattr(self, "splash_anim_job", None):
            try:
                self.after_cancel(self.splash_anim_job)
            except Exception:
                pass
            self.splash_anim_job = None
        if hasattr(self, "splash") and self.splash.winfo_exists():
            self.splash.destroy()
        self.build_ui()
        self.refresh_license_badge()
        self.after(700, self.update_live_ping)
        self.after(1000, self.tick_uptime)
        self.after(2500, self.auto_check_updates_on_start)

    def build_ui(self):
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.on_canvas_configure())

        self.license_badge = tk.Label(self, text="FREE", bg="#bb3434", fg=TEXT, font=("Impact", 26), bd=0)
        self.license_badge.place(x=12, y=42)

        self.main_window_items = []
        self.settings_window_items = []
        self.logo_canvas_image = None
        self.footer_canvas_image = None

        self.connect_btn = GhostButton(self.canvas, "ПОДКЛЮЧИТЬ", self.toggle_connect, 310, 86, 21)
        self.connect_window = self.canvas.create_window(520, 400, window=self.connect_btn, anchor="center", tags=("main_window",))
        self.settings_btn = GhostButton(self.canvas, "НАСТРОЙКИ", self.show_settings_page, 140, 48, 10)
        self.settings_window = self.canvas.create_window(520, 493, window=self.settings_btn, anchor="center", tags=("main_window",))
        self.main_window_items = [self.connect_window, self.settings_window]

        self.draw_background()
        self.show_main_page()

    def on_canvas_configure(self):
        self.draw_background()
        if self.current_page == "main":
            self.position_main_widgets()
            self.draw_logo()
            self.draw_status_panel()
            self.draw_footer()
        elif self.current_page == "settings":
            self.position_settings_widgets()
            self.draw_footer()

    def position_main_widgets(self):
        if not hasattr(self, "canvas"):
            return
        w = self.canvas.winfo_width() or 1040
        h = self.canvas.winfo_height() or 780
        if hasattr(self, "connect_window"):
            self.canvas.coords(self.connect_window, w / 2, 385)
        if hasattr(self, "settings_window"):
            self.canvas.coords(self.settings_window, w / 2, 475)

    def position_settings_widgets(self):
        if not hasattr(self, "canvas"):
            return
        w = self.canvas.winfo_width() or 1040
        x0 = w / 2 - 420
        x1 = w / 2 + 420
        # Кнопки и поля настроек специально опущены ниже, чтобы убрать пустоту снизу.
        positions = {
            "back": (w / 2 - 240, 145),
            "key": (w / 2 + 240, 145),
            "methods": (w / 2, 255),
            "faq": (w / 2 - 217, 340),
            "tests": (w / 2 + 217, 340),
            "check_updates": (w / 2, 400),
            "region_menu": (w / 2 + 365, 625),
        }
        for name, item in getattr(self, "settings_windows_by_name", {}).items():
            if name in positions:
                self.canvas.coords(item, *positions[name])
        self.canvas.coords("settings_line_1", x0, 287, x1, 287)
        self.canvas.coords("settings_line_2", x0, 471, x1, 471)
        self.canvas.coords("settings_region_box", x0, 603, x1, 647)

    def clear_main_canvas(self):
        for tag in ("main_logo", "status", "footer"):
            self.canvas.delete(tag)

    def clear_settings_canvas(self):
        self.canvas.delete("settings")
        for item in getattr(self, "settings_window_items", []):
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self.settings_window_items = []
        self.settings_windows_by_name = {}
        self.settings_back_btn = None
        self.settings_key_btn = None
        self.settings_faq_btn = None
        self.settings_tests_btn = None
        self.settings_update_btn = None
        self.settings_listbox = None
        self.settings_autostart_row = None
        self.settings_region_menu = None

    def set_main_windows_state(self, state: str):
        for item in getattr(self, "main_window_items", []):
            try:
                self.canvas.itemconfigure(item, state=state)
            except Exception:
                pass

    def draw_footer(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("footer")
        w = self.canvas.winfo_width() or 1040
        h = self.canvas.winfo_height() or 780
        y = h - 42
        footer_icon_path = asset_path(self.root_dir, self.asset_dir, FOOTER_ICON_FILE)
        icon_w = 0
        if Image and ImageTk and footer_icon_path.exists():
            try:
                img = Image.open(footer_icon_path).convert("RGBA")
                img.thumbnail((28, 28), Image.LANCZOS)
                self.footer_canvas_image = ImageTk.PhotoImage(img)
                icon_w = img.width + 8
            except Exception:
                self.footer_canvas_image = None
        title_font = ("Segoe UI", 14, "bold")
        start_x = w / 2 - 63
        if self.footer_canvas_image:
            self.canvas.create_image(start_x, y - 10, image=self.footer_canvas_image, anchor="w", tags=("footer",))
            text_x = start_x + icon_w
        else:
            text_x = w / 2 - 50
        self.canvas.create_text(text_x, y - 10, text=APP_FOOTER, anchor="w", fill=MUTED, font=title_font, tags=("footer",))
        self.canvas.create_text(w / 2, y + 16, text=DISCLAIMER_TEXT, anchor="center", fill=DIM, font=("Segoe UI", 8), tags=("footer",))

    def draw_background(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("bg")
        w = self.canvas.winfo_width() or 1040
        h = self.canvas.winfo_height() or 780
        bg_path = asset_path(self.root_dir, self.asset_dir, BACKGROUND_FILE)
        if Image and ImageTk and bg_path.exists():
            try:
                img = Image.open(bg_path).convert("RGB").resize((w, h), Image.LANCZOS)
                self.bg_image = ImageTk.PhotoImage(img)
                self.canvas.create_image(0, 0, image=self.bg_image, anchor="nw", tags="bg")
            except Exception:
                self.canvas.create_rectangle(0, 0, w, h, fill=BG, outline="", tags="bg")
        else:
            self.canvas.create_rectangle(0, 0, w, h, fill=BG, outline="", tags="bg")
        self.canvas.tag_lower("bg")

    def draw_logo(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("main_logo")
        w = self.canvas.winfo_width() or 1040
        logo_path = asset_path(self.root_dir, self.asset_dir, LOGO_FILE)
        if Image and ImageTk and logo_path.exists():
            try:
                img = Image.open(logo_path).convert("RGBA")
                # Убираем чёрный фон прямо из logo.png, если картинка сохранена без прозрачности.
                data = []
                for r, g, b, a in img.getdata():
                    if r < 18 and g < 18 and b < 18:
                        data.append((r, g, b, 0))
                    else:
                        data.append((r, g, b, a))
                img.putdata(data)
                img.thumbnail((600, 420), Image.LANCZOS)
                self.logo_canvas_image = ImageTk.PhotoImage(img)
                self.canvas.create_image(w / 2, 190, image=self.logo_canvas_image, anchor="center", tags=("main_logo",))
                return
            except Exception:
                pass
        self.canvas.create_text(w / 2, 190, text="LOGO NOT FOUND\nimages/logo.png", fill="white", font=("Segoe UI", 18, "bold"), justify="center", tags=("main_logo",))

    def draw_status_panel(self):
        if not hasattr(self, "canvas") or self.current_page != "main":
            return
        c = self.canvas
        c.delete("status")
        w = c.winfo_width() or 1040
        x1 = w / 2 - 360
        y1 = 535
        x2 = w / 2 + 360
        y2 = 695
        # Без чёрной заливки: остаётся только тонкая рамка и текст поверх fone.png.
        c.create_rectangle(x1, y1, x2, y2, outline=BORDER, width=1, tags=("status",))
        c.create_text(x1 + 20, y1 + 22, text="СТАТУС", anchor="w", fill=TEXT, font=("Segoe UI", 10, "bold"), tags=("status",))
        status_color = GREEN if self.connected else RED
        connection_color = GREEN if self.connected else RED
        method_color = BLUE if self.method_var.get() and self.method_var.get() != "-" else DIM
        uptime_color = YELLOW if self.connected else DIM
        rows = [
            ("●", f"Статус: {self.status_var.get()}", status_color, status_color),
            ("▥", f"Соединение: {self.connection_var.get()}", connection_color, connection_color),
            ("▰", f"Примерный пинг: {self.ping_var.get()}", GREEN if self.connected else BLUE, GREEN if self.connected else MUTED),
            ("🔗", f"Метод: {method_title(self.method_var.get())}", method_color, MUTED),
            ("◷", f"Время работы: {self.uptime_var.get()}", uptime_color, uptime_color if self.connected else MUTED),
        ]
        y = y1 + 54
        for icon, text, icon_color, text_color in rows:
            c.create_text(x1 + 32, y, text=icon, anchor="center", fill=icon_color, font=("Segoe UI Symbol", 12), tags=("status",))
            c.create_text(x1 + 58, y, text=text, anchor="w", fill=text_color, font=("Segoe UI", 11), tags=("status",))
            y += 22


    def tick_uptime(self):
        """Обновляет таймер работы в статусе раз в секунду."""
        try:
            if self.connected and self.uptime_started_at:
                elapsed = int(time.time() - self.uptime_started_at)
                hh = elapsed // 3600
                mm = (elapsed % 3600) // 60
                ss = elapsed % 60
                self.uptime_var.set(f"{hh:02d}:{mm:02d}:{ss:02d}")
            else:
                self.uptime_var.set("00:00:00")

            if hasattr(self, "canvas") and self.current_page == "main":
                self.draw_status_panel()
        finally:
            self.after(1000, self.tick_uptime)

    def show_main_page(self):
        self.current_page = "main"
        self.clear_settings_canvas()
        self.set_main_windows_state("normal")
        self.position_main_widgets()
        self.draw_logo()
        self.draw_status_panel()
        self.draw_footer()

    def draw_autostart_setting(self):
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("settings_autostart")
        w = c.winfo_width() or 1040
        x0 = w / 2 - 420
        x1 = w / 2 + 420
        y0, y1 = 493, 537
        value = bool(self.config.get("autostart", False))
        c.create_rectangle(x0, y0, x1, y1, fill="#080808", outline=BORDER, width=1, tags=("settings", "settings_autostart"))
        c.create_text(x0 + 54, (y0 + y1) / 2, text="Автозапуск с Windows", anchor="w", fill=YELLOW, font=("Segoe UI", 12, "bold"), tags=("settings", "settings_autostart"))
        sw, sh = 62, 28
        sx = x1 - sw - 16
        sy = (y0 + y1 - sh) / 2
        color = "#00c319" if value else "#4a4a4a"
        label = "ON" if value else "OFF"
        c.create_rectangle(sx, sy, sx + sw, sy + sh, fill=color, outline="", tags=("settings", "settings_autostart"))
        knob_x = sx + sw - 14 if value else sx + 14
        c.create_oval(knob_x - 10, sy + 4, knob_x + 10, sy + sh - 4, fill="#f7f7f7", outline="", tags=("settings", "settings_autostart"))
        c.create_text(sx + 18 if value else sx + 42, sy + sh / 2, text=label, fill="white", font=("Segoe UI", 8, "bold"), tags=("settings", "settings_autostart"))
        c.tag_bind("settings_autostart", "<Button-1>", lambda _e: self.toggle_autostart_canvas())
        c.tag_bind("settings_autostart", "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind("settings_autostart", "<Leave>", lambda _e: c.config(cursor=""))

    def toggle_autostart_canvas(self):
        if not self.require_pro():
            return
        new_value = not bool(self.config.get("autostart", False))
        if self.set_windows_autostart(new_value):
            self.config["autostart"] = new_value
            self.save_config()
            self.draw_autostart_setting()

    def draw_auto_update_setting(self):
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("settings_auto_update")
        w = c.winfo_width() or 1040
        x0 = w / 2 - 420
        x1 = w / 2 + 420
        y0, y1 = 548, 592
        value = bool(self.config.get("auto_update", False))
        c.create_rectangle(x0, y0, x1, y1, fill="#080808", outline=BORDER, width=1, tags=("settings", "settings_auto_update"))
        c.create_text(x0 + 54, (y0 + y1) / 2, text="Автообновление  •  PRO", anchor="w", fill=YELLOW, font=("Segoe UI", 12, "bold"), tags=("settings", "settings_auto_update"))
        sw, sh = 62, 28
        sx = x1 - sw - 16
        sy = (y0 + y1 - sh) / 2
        color = "#00c319" if value else "#4a4a4a"
        label = "ON" if value else "OFF"
        c.create_rectangle(sx, sy, sx + sw, sy + sh, fill=color, outline="", tags=("settings", "settings_auto_update"))
        knob_x = sx + sw - 14 if value else sx + 14
        c.create_oval(knob_x - 10, sy + 4, knob_x + 10, sy + sh - 4, fill="#f7f7f7", outline="", tags=("settings", "settings_auto_update"))
        c.create_text(sx + 18 if value else sx + 42, sy + sh / 2, text=label, fill="white", font=("Segoe UI", 8, "bold"), tags=("settings", "settings_auto_update"))
        c.tag_bind("settings_auto_update", "<Button-1>", lambda _e: self.toggle_auto_update_canvas())
        c.tag_bind("settings_auto_update", "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind("settings_auto_update", "<Leave>", lambda _e: c.config(cursor=""))

    def toggle_auto_update_canvas(self):
        if not self.require_pro():
            self.draw_auto_update_setting()
            return
        self.config["auto_update"] = not bool(self.config.get("auto_update", False))
        self.save_config()
        self.draw_auto_update_setting()

    def show_settings_page(self):
        self.current_page = "settings"
        self.clear_main_canvas()
        self.set_main_windows_state("hidden")
        self.clear_settings_canvas()
        self.draw_footer()

        w = self.canvas.winfo_width() or 1040
        x0 = w / 2 - 420
        x1 = w / 2 + 420

        self.canvas.create_text(w / 2, 145, text="НАСТРОЙКИ - BETA", fill=BRIGHT_RED, font=("Segoe UI", 19, "bold"), tags=("settings",))
        self.settings_back_btn = GhostButton(self.canvas, "НАЗАД", self.show_main_page, 120, 46, 10)
        self.settings_key_btn = GhostButton(self.canvas, "KEY", self.open_key_window, 100, 46, 10)
        self.settings_windows_by_name = {
            "back": self.canvas.create_window(w / 2 - 240, 145, window=self.settings_back_btn, anchor="center", tags=("settings_window",)),
            "key": self.canvas.create_window(w / 2 + 240, 145, window=self.settings_key_btn, anchor="center", tags=("settings_window",)),
        }

        self.canvas.create_text(x0, 198, text="ВЫБОР МЕТОДА", anchor="w", fill=BRIGHT_RED, font=("Segoe UI", 12, "bold"), tags=("settings",))
        self.canvas.create_line(x0, 216, x1, 216, fill=BORDER, tags=("settings", "settings_line_1"))
        self.methods = self.find_methods()
        self.settings_listbox = tk.Listbox(self.canvas, height=4, bg="#0d0e10", fg=TEXT, selectbackground="#343840", selectforeground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER, font=("Segoe UI", 11), activestyle="none")
        for p in self.methods:
            self.settings_listbox.insert("end", method_title(p.name))
        current = self.method_var.get()
        for i, p in enumerate(self.methods):
            if p.name == current or method_title(p.name) == method_title(current):
                self.settings_listbox.selection_set(i)
                self.settings_listbox.see(i)
                break
        def apply(_event=None):
            sel = self.settings_listbox.curselection()
            if sel:
                selected = self.methods[sel[0]].name
                self.method_var.set(selected)
                self.config["method"] = selected
                self.ping_var.set(self.estimate_ping_text(selected))
                if not self.connected:
                    self.status_var.set("Метод выбран")
                self.save_config()
        self.settings_listbox.bind("<<ListboxSelect>>", apply)
        self.settings_listbox.bind("<Double-Button-1>", apply)
        self.settings_windows_by_name["methods"] = self.canvas.create_window(w / 2, 255, window=self.settings_listbox, anchor="center", width=840, height=88, tags=("settings_window",))

        self.settings_faq_btn = GhostButton(self.canvas, "FAQ", self.open_faq_window, 405, 48, 11)
        self.settings_tests_btn = GhostButton(self.canvas, "ТЕСТЫ", self.run_tests_script, 405, 48, 11)
        self.settings_windows_by_name["faq"] = self.canvas.create_window(w / 2 - 217, 340, window=self.settings_faq_btn, anchor="center", tags=("settings_window",))
        self.settings_windows_by_name["tests"] = self.canvas.create_window(w / 2 + 217, 340, window=self.settings_tests_btn, anchor="center", tags=("settings_window",))
        self.settings_update_btn = GhostButton(self.canvas, "ПРОВЕРИТЬ ОБНОВЛЕНИЯ", lambda: self.check_for_updates(manual=True), 840, 48, 11)
        self.settings_windows_by_name["check_updates"] = self.canvas.create_window(w / 2, 400, window=self.settings_update_btn, anchor="center", tags=("settings_window",))

        self.canvas.create_text(x0, 455, text="ОПЦИИ PRO", anchor="w", fill=YELLOW, font=("Segoe UI", 12, "bold"), tags=("settings",))
        self.canvas.create_text(x0 + 172, 455, text="доступно только после активации ключа", anchor="w", fill=DIM, font=("Segoe UI", 9, "bold"), tags=("settings",))
        self.canvas.create_line(x0, 471, x1, 471, fill="#3d2525", tags=("settings", "settings_line_2"))

        self.draw_autostart_setting()
        self.draw_auto_update_setting()

        self.canvas.create_rectangle(x0, 603, x1, 647, fill="#080808", outline="#3d2525", width=1, tags=("settings", "settings_region_box"))
        self.canvas.create_text(x0 + 58, 625, text="Регион  •  PRO", anchor="w", fill=YELLOW, font=("Segoe UI", 12, "bold"), tags=("settings",))
        self.settings_region_menu = tk.OptionMenu(self.canvas, self.region_var, *REGIONS, command=self.set_region)
        self.settings_region_menu.config(bg="#00c319", fg="white", activebackground="#009b14", activeforeground="white", relief="flat", font=("Segoe UI", 9, "bold"), highlightthickness=0, cursor="hand2")
        self.settings_region_menu["menu"].config(bg=PANEL_2, fg=TEXT, activebackground="#333333", activeforeground=TEXT)
        self.settings_windows_by_name["region_menu"] = self.canvas.create_window(w / 2 + 365, 625, window=self.settings_region_menu, anchor="center", width=84, height=30, tags=("settings_window",))

        self.settings_window_items = list(self.settings_windows_by_name.values())
        self.position_settings_widgets()

    def open_faq_window(self):
        import webbrowser

        win = tk.Toplevel(self)
        win.title("FAQ — PHG LIVE")
        win.configure(bg=BG)
        win.geometry("760x560")
        win.resizable(False, False)
        win.transient(self)

        try:
            if hasattr(self, "_icon_ref"):
                win.iconphoto(True, self._icon_ref)
        except Exception:
            pass

        tk.Label(
            win,
            text="FAQ / ИНФОРМАЦИЯ",
            bg=BG,
            fg=BRIGHT_RED,
            font=("Segoe UI", 20, "bold"),
        ).pack(pady=(18, 10))

        text = (
            "DBD-UNLOCK — Это программа-гибрид сделаная на основе модернизированого Zapret "
            "(PHG LIVE) и некоторых функций VPN чтоб менять регион.\n\n"
            "Создатель/команда: сторонняя команда PHG (MCPLEH - Эмси Плех).\n\n"
            "Поддерживаемые сервисы:\n"
            "Программа специально сделана под игру Dead by Daylight, но так же открывает доступ "
            "для других игровых серверов, а так же Discord, Instagram, TikTok, YouTube, Twitter/X, Telegram.\n\n"
            "Приобрести ключ тут TG ЛС: https://t.me/mcpleh\n"
            "Discord: https://discord.gg/YCUTMsNxff\n"
            "Telegram: https://t.me/playhangames666\n"
            "Поддержка проекта / реквизиты:\n"
            "Номер карты: 2204 1202 0195 2187 или СБП 89517408874 Банк Юмани\n\n"
            "Благодаря вашей поддержке программа будет обновлятся и будут добавляться новые функции!\n\n"
            + DISCLAIMER_TEXT
        )

        box = tk.Text(
            win,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Segoe UI", 11),
            padx=18,
            pady=14,
        )
        box.pack(fill="both", expand=True, padx=28, pady=(0, 14))
        box.insert("1.0", text)

        def make_links_clickable(widget):
            url_pattern = r"https?://[^\s]+"
            content = widget.get("1.0", "end")

            for i, match in enumerate(re.finditer(url_pattern, content)):
                tag = f"link_{i}"
                url = match.group(0).rstrip(".,);]")
                start = f"1.0+{match.start()}c"
                end = f"1.0+{match.start() + len(url)}c"

                widget.tag_add(tag, start, end)
                widget.tag_config(tag, foreground="#4da6ff", underline=1)

                widget.tag_bind(tag, "<Button-1>", lambda _e, link=url: webbrowser.open(link))
                widget.tag_bind(tag, "<Enter>", lambda _e: widget.config(cursor="hand2"))
                widget.tag_bind(tag, "<Leave>", lambda _e: widget.config(cursor=""))

        make_links_clickable(box)
        box.config(state="disabled")

        GhostButton(win, "ЗАКРЫТЬ", win.destroy, 160, 48, 10).pack(pady=(0, 16))

    def run_tests_script(self):
        script = asset_path(self.root_dir, self.asset_dir, TEST_SCRIPT_FILE)
        if not script.exists():
            messagebox.showerror(APP_TITLE, f"Файл тестов не найден:\n{script}")
            return
        try:
            if is_windows():
                subprocess.Popen([
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-NoExit",
                    "-Command",
                    f"Set-Location -LiteralPath '{script.parent}'; & '{script}'"
                ], cwd=str(script.parent))
            else:
                messagebox.showerror(APP_TITLE, "Тесты доступны только в Windows.")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Не удалось запустить тесты:\n{e}")

    def _version_tuple(self, value: str):
        parts = re.findall(r"\d+", str(value or "0"))
        return tuple(int(p) for p in parts[:4]) or (0,)

    def _is_newer_version(self, remote_version: str) -> bool:
        return self._version_tuple(remote_version) > self._version_tuple(CURRENT_VERSION)

    def auto_check_updates_on_start(self):
        """Автопроверка доступна только PRO и только если включена в настройках."""
        if bool(self.config.get("auto_update", False)) and self.is_pro():
            self.check_for_updates(manual=False)

    def _format_update_sources(self, info: dict, download_url: str = "") -> str:
        """Возвращает список источников для ручного скачивания из version.json."""
        sources = []

        raw_sources = info.get("sources") or info.get("manual_sources") or []
        if isinstance(raw_sources, dict):
            raw_sources = [raw_sources]

        if isinstance(raw_sources, list):
            for item in raw_sources:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("title") or "Источник").strip()
                    url = str(item.get("url") or item.get("link") or "").strip()
                    if url:
                        sources.append(f"{name}: {url}")
                elif isinstance(item, str) and item.strip():
                    sources.append(item.strip())

        for key, label in (
            ("github_url", "GitHub"),
            ("telegram_url", "Telegram"),
            ("site_url", "Сайт"),
            ("manual_url", "Скачать вручную"),
        ):
            url = str(info.get(key, "")).strip()
            if url:
                sources.append(f"{label}: {url}")

        # Если отдельные источники не указаны, показываем download_url как ссылку для ручного скачивания.
        if not sources and download_url:
            sources.append(f"Скачать: {download_url}")

        # Убираем дубли, сохраняя порядок.
        unique = []
        seen = set()
        for source in sources:
            if source not in seen:
                seen.add(source)
                unique.append(source)

        return "\n".join(unique)

    def show_manual_update_info(self, remote_version: str, notes: str, info: dict, download_url: str):
        """Бесплатная проверка: только показывает наличие обновления и ссылки."""
        sources_text = self._format_update_sources(info, download_url)
        msg = f"Доступна новая версия: {remote_version}\nТекущая версия: {CURRENT_VERSION}"
        if notes:
            msg += f"\n\nЧто нового:\n{notes}"
        if sources_text:
            msg += f"\n\nСкачать вручную:\n{sources_text}"
        else:
            msg += "\n\nИсточник скачивания не указан в version.json."
        messagebox.showinfo(APP_TITLE, msg)

    def check_for_updates(self, manual: bool = True):
        """Проверяет version.json.

        manual=True: доступно всем, только показывает наличие новой версии и источники скачивания.
        manual=False: используется PRO-автообновлением, предлагает скачать и заменить exe.
        """
        def worker():
            try:
                with urllib.request.urlopen(UPDATE_INFO_URL, timeout=12) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                info = json.loads(raw)
                remote_version = str(info.get("version", "")).strip()
                download_url = str(info.get("download_url", "")).strip()
                notes = str(info.get("notes", "")).strip()

                if not remote_version:
                    raise ValueError("version.json должен содержать поле version")

                if self._is_newer_version(remote_version):
                    if manual:
                        self.after(0, lambda: self.show_manual_update_info(remote_version, notes, info, download_url))
                    else:
                        if not download_url:
                            return
                        self.after(0, lambda: self.prompt_update(remote_version, download_url, notes))
                elif manual:
                    self.after(0, lambda: messagebox.showinfo(APP_TITLE, f"У вас актуальная версия: {CURRENT_VERSION}"))
            except Exception as e:
                if manual:
                    self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, f"Не удалось проверить обновление:\n{err}"))

        threading.Thread(target=worker, daemon=True).start()

    def prompt_update(self, remote_version: str, download_url: str, notes: str = ""):
        """PRO-автообновление: спрашивает разрешение скачать и заменить exe."""
        msg = f"Доступна новая версия: {remote_version}\nТекущая версия: {CURRENT_VERSION}"
        if notes:
            msg += f"\n\nЧто нового:\n{notes}"
        msg += "\n\nСкачать и обновить?"
        if messagebox.askyesno(APP_TITLE, msg):
            self.download_and_install_update(remote_version, download_url)

    def download_and_install_update(self, remote_version: str, download_url: str):
        if not self.is_pro():
            self.open_key_window()
            return
        if not getattr(sys, "frozen", False):
            messagebox.showwarning(APP_TITLE, "Автообновление с заменой файла работает только в собранном .exe.")
            return

        progress = tk.Toplevel(self)
        progress.title("Обновление")
        progress.configure(bg=BG)
        progress.geometry("430x150")
        progress.resizable(False, False)
        progress.transient(self)
        tk.Label(progress, text=f"Скачивание обновления {remote_version}...", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(pady=(28, 10))
        status_label = tk.Label(progress, text="Подождите, файл загружается.", bg=BG, fg=DIM, font=("Segoe UI", 10))
        status_label.pack()
        progress.update_idletasks()

        def worker():
            try:
                current_exe = Path(sys.executable).resolve()
                temp_new_exe = Path(tempfile.gettempdir()) / f"{current_exe.stem}_update_{remote_version}.exe"
                urllib.request.urlretrieve(download_url, temp_new_exe)
                if not temp_new_exe.exists() or temp_new_exe.stat().st_size < 1024:
                    raise ValueError("Скачанный файл повреждён или слишком маленький")
                self.after(0, lambda: self.run_external_updater(temp_new_exe, current_exe))
            except Exception as e:
                self.after(0, lambda err=e: (progress.destroy(), messagebox.showerror(APP_TITLE, f"Не удалось скачать обновление:\n{err}")))

        threading.Thread(target=worker, daemon=True).start()

    def run_external_updater(self, new_exe: Path, current_exe: Path):
        updater_bat = Path(tempfile.gettempdir()) / "phg_live_updater.bat"
        pid = os.getpid()
        bat = f"""@echo off
chcp 65001 >nul
set "NEW_EXE={new_exe}"
set "OLD_EXE={current_exe}"
set "OLD_PID={pid}"

timeout /t 2 /nobreak >nul
:waitloop
tasklist /FI "PID eq %OLD_PID%" | find "%OLD_PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
copy /Y "%NEW_EXE%" "%OLD_EXE%" >nul
if errorlevel 1 (
    echo Failed to replace exe.
    pause
    exit /b 1
)
start "" "%OLD_EXE%"
del "%NEW_EXE%" >nul 2>&1
del "%~f0" >nul 2>&1
"""
        updater_bat.write_text(bat, encoding="utf-8")
        subprocess.Popen(["cmd.exe", "/c", str(updater_bat)], creationflags=subprocess.CREATE_NO_WINDOW if is_windows() else 0)
        self.destroy()

    def open_settings(self):
        self.show_settings_page()

    def section_title(self, master, title: str, pro: bool = False, top: int = 0):
        frame = tk.Frame(master, bg=BG)
        frame.pack(fill="x", pady=(top, 6))
        text = f"{title}  •  PRO" if pro else title
        color = YELLOW if pro else BRIGHT_RED
        tk.Label(frame, text=text, bg=BG, fg=color, font=("Segoe UI", 12, "bold")).pack(side="left")
        if pro:
            tk.Label(frame, text="доступно только после активации ключа", bg=BG, fg=DIM, font=("Segoe UI", 9, "bold")).pack(side="left", padx=12)
        tk.Frame(master, bg="#3d2525" if pro else BORDER, height=1).pack(fill="x", pady=(0, 4))

    def build_method_list(self, master):
        self.methods = self.find_methods()
        listbox = tk.Listbox(master, height=4, bg=BG, fg=TEXT, selectbackground="#343840", selectforeground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER, font=("Segoe UI", 11), activestyle="none")
        listbox.pack(fill="x")
        for p in self.methods:
            listbox.insert("end", method_title(p.name))
        current = self.method_var.get()
        for i, p in enumerate(self.methods):
            if p.name == current or method_title(p.name) == method_title(current):
                listbox.selection_set(i)
                listbox.see(i)
                break

        def apply(_event=None):
            sel = listbox.curselection()
            if sel:
                selected = self.methods[sel[0]].name
                self.method_var.set(selected)
                self.config["method"] = selected
                self.ping_var.set(self.estimate_ping_text(selected))
                if not self.connected:
                    self.status_var.set("Метод выбран")
                self.save_config()
                self.draw_status_panel()
        listbox.bind("<<ListboxSelect>>", apply)
        listbox.bind("<Double-Button-1>", apply)

    def open_key_window(self):
        if self.key_overlay and self.key_overlay.winfo_exists():
            self.key_overlay.lift()
            return
        overlay = tk.Frame(self, bg="#070707", highlightbackground=BORDER, highlightthickness=1)
        self.key_overlay = overlay
        overlay.place(relx=0.5, rely=0.16, anchor="n", width=430, height=230)
        overlay.lift()

        tk.Label(overlay, text="ВВЕДИТЕ PRO KEY", bg="#070707", fg=TEXT, font=("Segoe UI", 16, "bold")).pack(pady=(18, 12))
        entry = tk.Entry(overlay, bg=BG, fg=TEXT, insertbackground=TEXT, relief="flat", justify="center", font=("Segoe UI", 15, "bold"))
        entry.pack(fill="x", padx=34, ipady=8)
        entry.focus_set()

        def paste(_event=None):
            try:
                text = overlay.clipboard_get()
            except Exception:
                try:
                    text = entry.selection_get(selection="CLIPBOARD")
                except Exception:
                    text = ""
            if text:
                # Полностью заменяем выделенный текст, иначе вставляем в позицию курсора.
                try:
                    if entry.selection_present():
                        entry.delete("sel.first", "sel.last")
                except Exception:
                    pass
                entry.insert("insert", text.strip())
                entry.icursor("end")
            return "break"

        def select_all(_event=None):
            entry.select_range(0, "end")
            entry.icursor("end")
            return "break"

        # Надёжные бинды для разных раскладок/версий Tkinter.
        entry.bind("<Control-v>", paste)
        entry.bind("<Control-V>", paste)
        entry.bind("<Control-KeyPress-v>", paste)
        entry.bind("<Control-KeyPress-V>", paste)
        entry.bind("<<Paste>>", paste)
        entry.bind("<Control-a>", select_all)
        entry.bind("<Control-A>", select_all)
        entry.bind("<Button-3>", paste)  # правый клик тоже вставляет ключ

        paste_btn_frame = tk.Frame(overlay, bg="#070707")
        paste_btn_frame.pack(pady=(8, 0))
        tk.Button(
            paste_btn_frame,
            text="ВСТАВИТЬ",
            command=paste,
            bg="#222222",
            fg=TEXT,
            activebackground="#333333",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=3,
        ).pack()

        btns = tk.Frame(overlay, bg="#070707")
        btns.pack(pady=(10, 0))

        def close():
            overlay.destroy()
            self.key_overlay = None

        def apply():
            if self.activate_key(entry.get()):
                close()

        GhostButton(btns, "ЗАКРЫТЬ", close, 130, 52, 11).pack(side="left", padx=8)
        GhostButton(btns, "АКТИВИРОВАТЬ", apply, 170, 52, 11).pack(side="left", padx=8)
        entry.bind("<Return>", lambda _e: apply())

    def toggle_service(self, row: SwitchRow):
        if not self.require_pro():
            row.draw()
            return
        row.set_value(not row.value)
        self.config.setdefault("services", {})[row.title] = row.value
        self.save_config()

    def set_region(self, value):
        if not self.require_pro():
            self.region_var.set(self.config.get("region", REGIONS[0]))
            return
        self.config["region"] = value
        self.ping_var.set(self.estimate_ping_text())
        self.save_config()
        self.draw_status_panel()

    def toggle_autostart(self, row: SwitchRow):
        if not self.require_pro():
            row.draw()
            return
        new_value = not row.value
        if self.set_windows_autostart(new_value):
            row.set_value(new_value)
            self.config["autostart"] = new_value
            self.save_config()

    def set_windows_autostart(self, enable: bool) -> bool:
        if not is_windows():
            return False
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    target = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
                    winreg.SetValueEx(key, APP_TITLE, 0, winreg.REG_SZ, target)
                else:
                    try:
                        winreg.DeleteValue(key, APP_TITLE)
                    except FileNotFoundError:
                        pass
            return True
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Не удалось изменить автозапуск:\n{e}")
            return False

    def selected_method_path(self) -> Path | None:
        name = self.method_var.get().strip()
        for p in self.methods:
            if p.name == name or method_title(p.name) == method_title(name):
                return p
        return None

    def toggle_connect(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        method = self.selected_method_path()
        if not method:
            messagebox.showerror(APP_TITLE, "Выберите метод в настройках.")
            return
        try:
            self.disconnect(silent=True)
            hidden_bat = make_hidden_method_bat(method, self.root_dir)
            flags = 0
            if is_windows():
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            self.method_process = subprocess.Popen(["cmd.exe", "/d", "/k", str(hidden_bat)], cwd=str(self.root_dir), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, startupinfo=_create_hidden_startupinfo())
            self.current_method = method
            self.connected = True
            self.uptime_started_at = time.time()
            self.uptime_var.set("00:00:00")
            self.status_var.set("Подключено")
            self.connection_var.set("Активно")
            self.ping_var.set(self.estimate_ping_text(method.name))
            self.connect_btn.title = "ОТКЛЮЧИТЬ"
            self.connect_btn.draw()
            self.draw_status_panel()
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Не удалось подключить метод:\n{e}")

    def disconnect(self, silent: bool = False):
        try:
            if self.method_process and self.method_process.poll() is None:
                try:
                    self.method_process.terminate()
                except Exception:
                    pass
            self.method_process = None
            flags = subprocess.CREATE_NO_WINDOW if is_windows() else 0
            commands = [["taskkill", "/IM", "winws.exe", "/F"], ["net", "stop", "WinDivert"], ["sc", "delete", "WinDivert"], ["net", "stop", "WinDivert14"], ["sc", "delete", "WinDivert14"], ["net", "stop", "zapret"], ["sc", "delete", "zapret"]]
            for cmd in commands:
                subprocess.run(cmd, cwd=str(self.root_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, startupinfo=_create_hidden_startupinfo())
            self.connected = False
            self.current_method = None
            self.uptime_started_at = None
            self.uptime_var.set("00:00:00")
            self.status_var.set("Отключено")
            self.connection_var.set("-")
            self.ping_var.set(self.estimate_ping_text())
            self.connect_btn.title = "ПОДКЛЮЧИТЬ"
            self.connect_btn.draw()
            self.draw_status_panel()
        except Exception as e:
            if not silent:
                messagebox.showerror(APP_TITLE, f"Ошибка отключения:\n{e}")

    def _tray_image(self):
        if Image:
            logo_path = asset_path(self.root_dir, self.asset_dir, LOGO_FILE)
            try:
                if logo_path.exists():
                    return Image.open(logo_path).convert("RGBA").resize((64, 64))
                return Image.new("RGBA", (64, 64), (0, 0, 0, 255))
            except Exception:
                return Image.new("RGBA", (64, 64), (0, 0, 0, 255))
        return None

    def minimize_to_tray(self):
        if pystray is None or Image is None:
            messagebox.showerror(APP_TITLE, "Для трея установите зависимости:\n\npip install pystray pillow")
            return
        self.withdraw()
        if self.tray_icon:
            return
        def show_window(_icon=None, _item=None):
            self.after(0, self._restore_from_tray)
        def quit_app(_icon=None, _item=None):
            self.after(0, self._quit_from_tray)
        self.tray_icon = pystray.Icon(APP_TITLE, self._tray_image(), APP_TITLE, menu=pystray.Menu(pystray.MenuItem("Открыть", show_window), pystray.MenuItem("Закрыть полностью", quit_app)))
        self._tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self._tray_thread.start()

    def _restore_from_tray(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_from_tray(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        if self.connected:
            self.disconnect(silent=True)
        self.destroy()

    def on_close(self):
        win = tk.Toplevel(self)
        win.title(APP_TITLE)
        win.configure(bg=BG)
        win.geometry("470x190")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        try:
            if hasattr(self, "_icon_ref"):
                win.iconphoto(True, self._icon_ref)
        except Exception:
            pass
        tk.Label(win, text="Что сделать с программой?", bg=BG, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(pady=(22, 14))
        def to_tray():
            win.destroy(); self.minimize_to_tray()
        def full_exit():
            win.destroy()
            if self.connected:
                self.disconnect(silent=True)
            self.destroy()
        def cancel():
            win.destroy()
        btns = tk.Frame(win, bg=BG)
        btns.pack(pady=(4, 0))
        GhostButton(btns, "СВЕРНУТЬ В ТРЕЙ", to_tray, 170, 52, 11).pack(side="left", padx=6)
        GhostButton(btns, "ЗАКРЫТЬ", full_exit, 120, 52, 11).pack(side="left", padx=6)
        GhostButton(btns, "ОТМЕНА", cancel, 120, 52, 11).pack(side="left", padx=6)


def main():
    if not is_windows():
        print("Эта программа предназначена для Windows.")
        return
    relaunch_as_admin()
    app = PHGGui()
    app.mainloop()


if __name__ == "__main__":
    main()
