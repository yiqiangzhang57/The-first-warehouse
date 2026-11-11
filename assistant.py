from __future__ import annotations

import ast
import ctypes
import io
import json
import math
import operator
import os
import random
import shutil
import struct
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageGrab, ImageTk


DEFAULT_APP_NAME = "浮浮助手"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_ICON = RESOURCE_DIR / "assets" / "assistant.ico"
APP_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "FloatingAssistant"
DATA_FILE = APP_DIR / "data.json"
SCREENSHOT_DIR = Path.home() / "Pictures" / "浮浮助手截图"
AVATAR_DIR = APP_DIR / "avatars"

COLORS = {
    "bg": "#F4F5FA",
    "card": "#FFFFFF",
    "ink": "#202335",
    "muted": "#71768A",
    "brand": "#7065F4",
    "brand_dark": "#574BDB",
    "brand_soft": "#ECEAFF",
    "nav": "#24273A",
    "nav_active": "#7065F4",
    "line": "#E8E9F1",
    "success": "#2FA572",
    "danger": "#E45B69",
    "float": "#7567F8",
}


DEFAULT_DATA = {
    "app_name": DEFAULT_APP_NAME,
    "clipboard": [],
    "notes": "",
    "todos": [],
    "reminders": [],
    "avatar": {"type": "emoji", "value": "🐳"},
    "position": None,
    "auto_hide_fullscreen": True,
    "clipboard_enabled": True,
    "pomodoro_minutes": 25,
    "random_options": "火锅\n烧烤\n米饭\n面条",
    "random_mode": "转盘",
    "transfers": [],
    "satellite_count": 5,
    "satellite_layout": "自动",
    "satellite_distance": 92,
    "satellite_functions": [
        "region_capture",
        "clipboard",
        "transfer",
        "notes",
        "pomodoro",
        "calculator",
    ],
}


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


class DataStore:
    def __init__(self) -> None:
        ensure_dirs()
        self.lock = threading.RLock()
        self.data = dict(DEFAULT_DATA)
        if DATA_FILE.exists():
            try:
                loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                self.data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass

    def save(self) -> None:
        with self.lock:
            tmp = DATA_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(DATA_FILE)


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip = None
        self.job = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def schedule(self, _event=None) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
        self.job = self.widget.after(550, self.show)

    def show(self) -> None:
        self.job = None
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 7
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(
            self.tip,
            text=self.text,
            bg="#202433",
            fg="white",
            padx=9,
            pady=5,
            font=("Microsoft YaHei UI", 9),
        ).pack()
        self.tip.geometry(f"+{x}+{y}")

    def hide(self, _event=None) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class SelectionScreenshot:
    def __init__(self, app: "FloatingAssistant") -> None:
        self.app = app
        self.x0 = self.y0 = 0
        self.rect = None
        self.image = None
        self.photo = None
        self.virtual_x = ctypes.windll.user32.GetSystemMetrics(76)
        self.virtual_y = ctypes.windll.user32.GetSystemMetrics(77)
        self.virtual_w = ctypes.windll.user32.GetSystemMetrics(78)
        self.virtual_h = ctypes.windll.user32.GetSystemMetrics(79)
        self.capture()

    def capture(self) -> None:
        try:
            self.image = ImageGrab.grab(all_screens=True)
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
            self.app.restore_after_capture()
            return

        self.win = tk.Toplevel(self.app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(
            f"{self.virtual_w}x{self.virtual_h}{self.virtual_x:+d}{self.virtual_y:+d}"
        )
        self.canvas = tk.Canvas(self.win, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        shade = Image.new("RGBA", self.image.size, (25, 30, 45, 95))
        shown = Image.alpha_composite(self.image.convert("RGBA"), shade)
        self.photo = ImageTk.PhotoImage(shown)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_text(
            24,
            22,
            anchor="nw",
            text="拖动选择截图区域  ·  Esc 取消",
            fill="white",
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self.start)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.finish)
        self.win.bind("<Escape>", self.cancel)
        self.win.focus_force()

    def start(self, event) -> None:
        self.x0, self.y0 = event.x, event.y
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.x0,
            self.y0,
            self.x0,
            self.y0,
            outline="#8C7BFF",
            width=3,
            fill="",
        )

    def drag(self, event) -> None:
        if self.rect:
            self.canvas.coords(self.rect, self.x0, self.y0, event.x, event.y)

    def finish(self, event) -> None:
        x1, x2 = sorted((self.x0, event.x))
        y1, y2 = sorted((self.y0, event.y))
        if x2 - x1 < 8 or y2 - y1 < 8:
            self.cancel()
            return
        crop = self.image.crop((x1, y1, x2, y2))
        self.win.destroy()
        path = self.app.save_screenshot(crop)
        self.app.copy_image_to_clipboard(crop)
        self.app.restore_after_capture()
        self.app.toast(f"截图已保存并复制\n{path.name}")

    def cancel(self, _event=None) -> None:
        if hasattr(self, "win") and self.win.winfo_exists():
            self.win.destroy()
        self.app.restore_after_capture()


class FloatingAssistant:
    def __init__(self) -> None:
        self.store = DataStore()
        self.root = tk.Tk()
        self.root.title(self.app_name)
        if APP_ICON.exists():
            try:
                self.root.iconbitmap(str(APP_ICON))
            except tk.TclError:
                pass
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#010101")
        self.root.wm_attributes("-transparentcolor", "#010101")
        self.root.geometry(self.initial_geometry())

        self.drag_origin = None
        self.did_drag = False
        self.click_job = None
        self.panel = None
        self.toast_window = None
        self.avatar_photo = None
        self.last_clipboard = ""
        self.fullscreen_hidden = False
        self.panel_visible_before_capture = False
        self.pomodoro_remaining = 0
        self.pomodoro_running = False
        self.pomodoro_job = None
        self.satellites = []
        self.satellite_hide_job = None
        self.random_animation_job = None
        self.random_angle = 0

        self.configure_styles()
        self.build_float()
        self.build_context_menu()
        self.register_hotkey()

        self.root.after(800, self.poll_clipboard)
        self.root.after(1000, self.check_reminders)
        self.root.after(1500, self.check_fullscreen)
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    @property
    def app_name(self) -> str:
        value = str(self.store.data.get("app_name", DEFAULT_APP_NAME)).strip()
        return value[:12] or DEFAULT_APP_NAME

    def initial_geometry(self) -> str:
        pos = self.store.data.get("position")
        if isinstance(pos, list) and len(pos) == 2:
            return f"72x72+{int(pos[0])}+{int(pos[1])}"
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        return f"72x72+{sw - 92}+{max(80, sh // 3)}"

    def configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TNotebook",
            background=COLORS["bg"],
            borderwidth=0,
            tabmargins=(6, 8, 6, 0),
        )
        style.configure(
            "TNotebook.Tab",
            font=("Microsoft YaHei UI", 9),
            padding=(11, 8),
            background=COLORS["bg"],
            foreground=COLORS["muted"],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["card"])],
            foreground=[("selected", COLORS["brand"])],
        )
        style.configure(
            "Treeview",
            rowheight=30,
            font=("Microsoft YaHei UI", 9),
            background="white",
            fieldbackground="white",
            foreground=COLORS["ink"],
            bordercolor=COLORS["line"],
        )
        style.configure(
            "Treeview.Heading",
            font=("Microsoft YaHei UI", 9, "bold"),
            background="#F0F1F6",
            foreground=COLORS["ink"],
        )
        style.configure(
            "Accent.TButton",
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(10, 7),
            background=COLORS["brand"],
            foreground="white",
            borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", COLORS["brand_dark"])])
        style.configure(
            "Soft.TButton",
            font=("Microsoft YaHei UI", 9),
            padding=(9, 6),
            background="#EEF0F6",
            foreground=COLORS["ink"],
            borderwidth=0,
        )

    def build_float(self) -> None:
        self.float_canvas = tk.Canvas(
            self.root,
            width=72,
            height=72,
            highlightthickness=0,
            bg="#010101",
            cursor="hand2",
        )
        self.float_canvas.pack()
        self.redraw_avatar()
        self.float_canvas.bind("<ButtonPress-1>", self.on_press)
        self.float_canvas.bind("<B1-Motion>", self.on_drag)
        self.float_canvas.bind("<ButtonRelease-1>", self.on_release)
        self.float_canvas.bind("<Double-Button-1>", self.on_double_click)
        self.float_canvas.bind("<Button-3>", self.show_context_menu)
        self.float_canvas.bind("<Enter>", self.show_satellites, add="+")
        self.float_canvas.bind("<Leave>", self.schedule_hide_satellites, add="+")
        self.float_tooltip = ToolTip(
            self.float_canvas, f"{self.app_name} · 单击展开 · 右键菜单"
        )

    def redraw_avatar(self) -> None:
        self.float_canvas.delete("all")
        self.float_canvas.create_oval(
            5,
            7,
            67,
            69,
            fill="#282D40",
            outline="",
            tags="shadow",
        )
        self.float_canvas.create_oval(
            4,
            3,
            66,
            65,
            fill=COLORS["float"],
            outline="#AEA5FF",
            width=2,
        )
        avatar = self.store.data.get("avatar", DEFAULT_DATA["avatar"])
        if avatar.get("type") == "image" and Path(avatar.get("value", "")).exists():
            try:
                image = Image.open(avatar["value"]).convert("RGBA")
                image.thumbnail((48, 48), Image.Resampling.LANCZOS)
                canvas_image = Image.new("RGBA", (50, 50), (255, 255, 255, 0))
                canvas_image.alpha_composite(
                    image, ((50 - image.width) // 2, (50 - image.height) // 2)
                )
                self.avatar_photo = ImageTk.PhotoImage(canvas_image)
                self.float_canvas.create_image(35, 34, image=self.avatar_photo)
                return
            except Exception:
                pass
        self.float_canvas.create_text(
            35,
            34,
            text=avatar.get("value", "🐳"),
            font=("Segoe UI Emoji", 28),
            fill="white",
        )

    def build_context_menu(self) -> None:
        if hasattr(self, "context"):
            self.context.destroy()
        self.context = tk.Menu(self.root, tearoff=False, font=("Microsoft YaHei UI", 9))
        self.context.add_command(label=f"打开{self.app_name}", command=self.open_panel)
        self.context.add_command(label="区域截图", command=self.start_region_capture)
        self.context.add_command(label="快速便签", command=lambda: self.open_panel("便签待办"))
        self.context.add_command(label="文件中转", command=lambda: self.open_panel("文件中转"))
        self.context.add_command(label="开始番茄钟", command=lambda: self.open_panel("番茄"))
        self.context.add_separator()
        self.context.add_command(label="更换形象", command=lambda: self.open_panel("设置"))
        self.context.add_command(label="锁定电脑", command=self.lock_computer)
        self.context.add_separator()
        self.context.add_command(label=f"退出{self.app_name}", command=self.quit_app)

    def show_satellites(self, _event=None) -> None:
        if self.satellite_hide_job:
            self.root.after_cancel(self.satellite_hide_job)
            self.satellite_hide_job = None
        if self.satellites or self.did_drag:
            return
        self.root.update_idletasks()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        count = max(0, min(6, int(self.store.data.get("satellite_count", 5))))
        if count == 0:
            return
        catalog = self.satellite_catalog()
        configured = list(self.store.data.get("satellite_functions", []))
        defaults = DEFAULT_DATA["satellite_functions"]
        function_ids = [
            configured[index] if index < len(configured) else defaults[index]
            for index in range(count)
        ]
        actions = [catalog.get(item, catalog["home"]) for item in function_ids]
        targets = self.satellite_targets(x, y, count)
        for index, (icon, label, command, color) in enumerate(actions):
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#010101")
            win.wm_attributes("-transparentcolor", "#010101")
            win.geometry(f"44x44+{x}+{y}")
            canvas = tk.Canvas(
                win, width=44, height=44, bg="#010101", highlightthickness=0, cursor="hand2"
            )
            canvas.pack()
            canvas.create_oval(3, 4, 41, 42, fill="#232638", outline="")
            canvas.create_oval(2, 2, 40, 40, fill=color, outline="#FFFFFF", width=1)
            canvas.create_text(
                21, 21, text=icon, fill="white", font=("Microsoft YaHei UI", 14, "bold")
            )
            canvas.bind("<Button-1>", lambda _e, c=command: self.activate_satellite(c))
            canvas.bind("<Enter>", self.cancel_hide_satellites)
            canvas.bind("<Leave>", self.schedule_hide_satellites)
            ToolTip(canvas, label)
            self.satellites.append(win)
            target_x, target_y = targets[index]
            self.animate_satellite(win, x + 14, y + 14, target_x, target_y, 0)

    def satellite_catalog(self) -> dict:
        return {
            "home": ("⌂", "首页", lambda: self.open_panel("首页"), "#7567F8"),
            "region_capture": ("✂", "区域截图", self.start_region_capture, "#FF8A7A"),
            "full_capture": ("▣", "全屏截图", self.capture_fullscreen, "#EB6F92"),
            "clipboard": (
                "▤",
                "剪贴板",
                lambda: self.open_panel("剪贴板"),
                "#5EAEF2",
            ),
            "transfer": (
                "⇄",
                "文件中转",
                lambda: self.open_panel("文件中转"),
                "#4FC7A4",
            ),
            "notes": (
                "✓",
                "便签待办",
                lambda: self.open_panel("便签待办"),
                "#F6B84A",
            ),
            "pomodoro": (
                "◷",
                "番茄钟",
                lambda: self.open_panel("番茄"),
                "#A777E8",
            ),
            "calculator": (
                "＋",
                "计算器",
                lambda: self.open_panel("工具"),
                "#4DA8DA",
            ),
            "random": (
                "◇",
                "随机决定",
                lambda: self.open_panel("工具"),
                "#EA7FBA",
            ),
            "reminder": ("⏰", "添加提醒", self.quick_add_reminder, "#F0A04B"),
            "lock": ("▦", "锁定电脑", self.lock_computer, "#6D7894"),
        }

    def monitor_work_area(self) -> tuple[int, int, int, int]:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [POINT, ctypes.c_ulong]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MONITORINFO),
        ]
        center = POINT(
            self.root.winfo_x() + self.root.winfo_width() // 2,
            self.root.winfo_y() + self.root.winfo_height() // 2,
        )
        monitor = user32.MonitorFromPoint(center, 2)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcWork
            return rect.left, rect.top, rect.right, rect.bottom
        return (
            0,
            0,
            user32.GetSystemMetrics(0),
            user32.GetSystemMetrics(1),
        )

    def satellite_targets(self, root_x: int, root_y: int, count: int) -> list[tuple[int, int]]:
        left, top, right, bottom = self.monitor_work_area()
        center_x = root_x + 36
        center_y = root_y + 36
        spaces = {
            "左侧": center_x - left,
            "右侧": right - center_x,
            "上方": center_y - top,
            "下方": bottom - center_y,
        }
        layout = self.store.data.get("satellite_layout", "自动")
        if layout == "自动":
            layout = max(spaces, key=spaces.get)
        opposite = {"左侧": "右侧", "右侧": "左侧", "上方": "下方", "下方": "上方"}
        required = 104 if count >= 5 else 92
        if layout in opposite and spaces[layout] < required and spaces[opposite[layout]] > spaces[layout]:
            layout = opposite[layout]

        configured_distance = max(
            80, min(130, int(self.store.data.get("satellite_distance", 92)))
        )
        minimum_distance = 92 if count >= 6 else (84 if count >= 5 else 80)
        radius = max(configured_distance, minimum_distance)
        if layout == "环绕":
            angles = [-90 + index * (360 / count) for index in range(count)]
        else:
            centers = {"右侧": 0, "下方": 90, "左侧": 180, "上方": 270}
            center_angle = centers.get(layout, 180)
            span = 0 if count == 1 else min(150, 34 * (count - 1))
            angles = [
                center_angle - span / 2 + (span * index / max(1, count - 1))
                for index in range(count)
            ]

        targets = []
        for angle in angles:
            radians = math.radians(angle)
            target_x = round(center_x + math.cos(radians) * radius - 22)
            target_y = round(center_y + math.sin(radians) * radius - 22)
            targets.append([target_x, target_y])

        min_x = min(item[0] for item in targets)
        max_x = max(item[0] + 44 for item in targets)
        min_y = min(item[1] for item in targets)
        max_y = max(item[1] + 44 for item in targets)
        shift_x = max(0, left + 5 - min_x) + min(0, right - 5 - max_x)
        shift_y = max(0, top + 5 - min_y) + min(0, bottom - 5 - max_y)
        return [
            (
                max(left + 5, min(item[0] + shift_x, right - 49)),
                max(top + 5, min(item[1] + shift_y, bottom - 49)),
            )
            for item in targets
        ]

    def animate_satellite(
        self, win: tk.Toplevel, start_x: int, start_y: int, end_x: int, end_y: int, step: int
    ) -> None:
        if not win.winfo_exists():
            return
        progress = min(1.0, step / 7)
        eased = 1 - (1 - progress) ** 3
        x = round(start_x + (end_x - start_x) * eased)
        y = round(start_y + (end_y - start_y) * eased)
        win.geometry(f"+{x}+{y}")
        try:
            win.attributes("-alpha", max(0.15, progress))
        except tk.TclError:
            pass
        if step < 7:
            self.root.after(
                18,
                lambda: self.animate_satellite(
                    win, start_x, start_y, end_x, end_y, step + 1
                ),
            )

    def activate_satellite(self, command) -> None:
        self.hide_satellites()
        command()

    def cancel_hide_satellites(self, _event=None) -> None:
        if self.satellite_hide_job:
            self.root.after_cancel(self.satellite_hide_job)
            self.satellite_hide_job = None

    def schedule_hide_satellites(self, _event=None) -> None:
        self.cancel_hide_satellites()
        self.satellite_hide_job = self.root.after(380, self.hide_satellites_if_outside)

    def hide_satellites_if_outside(self) -> None:
        px, py = self.root.winfo_pointerxy()
        windows = [self.root] + [w for w in self.satellites if w.winfo_exists()]
        for win in windows:
            x, y = win.winfo_rootx(), win.winfo_rooty()
            if x <= px <= x + win.winfo_width() and y <= py <= y + win.winfo_height():
                return
        self.hide_satellites()

    def hide_satellites(self) -> None:
        self.satellite_hide_job = None
        for win in self.satellites:
            if win.winfo_exists():
                win.destroy()
        self.satellites.clear()

    def show_context_menu(self, event) -> None:
        self.context.tk_popup(event.x_root, event.y_root)

    def on_press(self, event) -> None:
        self.hide_satellites()
        self.drag_origin = (
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
        )
        self.did_drag = False

    def on_drag(self, event) -> None:
        if not self.drag_origin:
            return
        dx = event.x_root - self.drag_origin[0]
        dy = event.y_root - self.drag_origin[1]
        if abs(dx) + abs(dy) > 4:
            self.did_drag = True
        x = self.drag_origin[2] + dx
        y = self.drag_origin[3] + dy
        self.root.geometry(f"+{x}+{y}")
        if self.panel and self.panel.winfo_exists() and self.panel.state() == "normal":
            self.position_panel()

    def on_release(self, _event) -> None:
        if self.did_drag:
            self.snap_to_edge()
            self.did_drag = False
            return
        if self.click_job:
            self.root.after_cancel(self.click_job)
        self.click_job = self.root.after(230, self.toggle_panel)

    def on_double_click(self, _event) -> None:
        if self.click_job:
            self.root.after_cancel(self.click_job)
            self.click_job = None
        self.open_panel("首页")

    def snap_to_edge(self) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        target_x = 6 if x + w / 2 < sw / 2 else sw - w - 6
        target_y = max(8, min(y, sh - h - 48))
        self.root.geometry(f"+{target_x}+{target_y}")
        self.store.data["position"] = [target_x, target_y]
        self.store.save()
        if self.panel and self.panel.winfo_exists() and self.panel.state() == "normal":
            self.position_panel()

    def toggle_panel(self) -> None:
        self.click_job = None
        if self.panel and self.panel.winfo_exists() and self.panel.state() == "normal":
            self.panel.withdraw()
        else:
            self.open_panel()

    def open_panel(self, tab: str | None = None) -> None:
        self.hide_satellites()
        self.fullscreen_hidden = False
        self.root.deiconify()
        if not self.panel or not self.panel.winfo_exists():
            self.build_panel()
        self.refresh_all()
        self.show_tab(tab or getattr(self, "active_tab", "首页"))
        self.position_panel()
        self.panel.deiconify()
        self.panel.lift()
        self.panel.focus_force()

    def build_panel(self) -> None:
        self.panel = tk.Toplevel(self.root)
        self.panel.title(self.app_name)
        self.panel.transient(self.root)
        self.panel.overrideredirect(True)
        self.panel.geometry("620x760")
        self.panel.minsize(580, 700)
        self.panel.configure(bg=COLORS["bg"])
        self.panel.attributes("-topmost", True)
        if APP_ICON.exists():
            try:
                self.panel.iconbitmap(str(APP_ICON))
            except tk.TclError:
                pass
        self.panel.protocol("WM_DELETE_WINDOW", self.panel.withdraw)
        self.panel.bind("<Escape>", lambda _e: self.panel.withdraw())
        self.panel.after(30, lambda: self.round_window_corners(self.panel))

        header = tk.Frame(self.panel, bg=COLORS["nav"], height=74)
        header.pack(fill="x")
        header.pack_propagate(False)
        self.header_name_label = tk.Label(
            header,
            text=self.app_name,
            bg=COLORS["nav"],
            fg="white",
            font=("Microsoft YaHei UI", 19, "bold"),
        )
        self.header_name_label.pack(side="left", padx=22, pady=17)
        tk.Button(
            header,
            text="×",
            command=self.panel.withdraw,
            bg=COLORS["nav"],
            fg="#D7D9E7",
            activebackground="#35394E",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 17),
            width=3,
            cursor="hand2",
        ).pack(side="right", padx=(0, 10))
        tk.Label(
            header,
            text="轻量常驻  ·  Ctrl + Alt + A",
            bg=COLORS["nav"],
            fg="#BFC3D7",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=(8, 6))

        body = tk.Frame(self.panel, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(body, bg=COLORS["nav"], width=104)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(body, bg=COLORS["bg"])
        self.content.pack(side="left", fill="both", expand=True)
        self.tabs = {}
        self.tab_layers = {}
        self.nav_buttons = {}
        nav_items = [
            ("首页", "⌂"),
            ("剪贴板", "▤"),
            ("工具", "◇"),
            ("便签待办", "✓"),
            ("文件中转", "⇄"),
            ("番茄", "◷"),
            ("设置", "⚙"),
        ]
        for name, icon in nav_items:
            button = tk.Button(
                self.sidebar,
                text=f"{icon}\n{name}",
                command=lambda n=name: self.show_tab(n),
                bg=COLORS["nav"],
                fg="#BFC3D7",
                activebackground="#34384E",
                activeforeground="white",
                relief="flat",
                bd=0,
                height=3,
                font=("Microsoft YaHei UI", 9),
                cursor="hand2",
            )
            button.pack(fill="x", padx=8, pady=3)
            self.nav_buttons[name] = button
            layer = tk.Frame(self.content, bg=COLORS["bg"])
            layer.place(x=0, y=0, relwidth=1, relheight=1)
            self.tab_layers[name] = layer
            if name in ("工具", "便签待办", "设置"):
                canvas = tk.Canvas(
                    layer, bg=COLORS["bg"], highlightthickness=0, bd=0
                )
                scrollbar = ttk.Scrollbar(layer, orient="vertical", command=canvas.yview)
                canvas.configure(yscrollcommand=scrollbar.set)
                scrollbar.pack(side="right", fill="y")
                canvas.pack(side="left", fill="both", expand=True)
                frame = tk.Frame(canvas, bg=COLORS["bg"])
                window_id = canvas.create_window((0, 0), window=frame, anchor="nw")
                frame.bind(
                    "<Configure>",
                    lambda _e, c=canvas: c.configure(scrollregion=c.bbox("all")),
                )
                canvas.bind(
                    "<Configure>",
                    lambda e, c=canvas, wid=window_id: c.itemconfigure(wid, width=e.width),
                )
                canvas.bind(
                    "<MouseWheel>",
                    lambda e, c=canvas: c.yview_scroll(
                        -1 if e.delta > 0 else 1, "units"
                    ),
                )
                frame.bind(
                    "<MouseWheel>",
                    lambda e, c=canvas: c.yview_scroll(
                        -1 if e.delta > 0 else 1, "units"
                    ),
                )
                self.tabs[name] = frame
            else:
                self.tabs[name] = layer

        self.build_home_tab()
        self.build_clipboard_tab()
        self.build_tools_tab()
        self.build_notes_tab()
        self.build_transfer_tab()
        self.build_pomodoro_tab()
        self.build_settings_tab()
        self.show_tab("首页")

    @staticmethod
    def round_window_corners(window: tk.Toplevel) -> None:
        try:
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            preference = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference)
            )
        except Exception:
            pass

    def show_tab(self, name: str) -> None:
        if name not in getattr(self, "tabs", {}):
            name = "首页"
        self.active_tab = name
        self.tab_layers[name].tkraise()
        for tab_name, button in self.nav_buttons.items():
            active = tab_name == name
            button.configure(
                bg=COLORS["nav_active"] if active else COLORS["nav"],
                fg="white" if active else "#BFC3D7",
            )

    def position_panel(self) -> None:
        if not self.panel or not self.panel.winfo_exists():
            return
        self.root.update_idletasks()
        self.panel.update_idletasks()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        pw = max(self.panel.winfo_width(), 620)
        ph = max(self.panel.winfo_height(), 760)
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        if px < sw / 2:
            x = px + self.root.winfo_width() + 10
        else:
            x = px - pw - 10
        x = max(8, min(x, sw - pw - 8))
        y = max(8, min(py - 20, sh - ph - 48))
        self.panel.geometry(f"{pw}x{ph}+{x}+{y}")

    def section_title(self, parent, title: str, subtitle: str = "") -> tk.Frame:
        box = tk.Frame(parent, bg=COLORS["bg"])
        box.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(
            box,
            text=title,
            bg=COLORS["bg"],
            fg=COLORS["ink"],
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(anchor="w")
        if subtitle:
            tk.Label(
                box,
                text=subtitle,
                bg=COLORS["bg"],
                fg=COLORS["muted"],
                font=("Microsoft YaHei UI", 9),
            ).pack(anchor="w", pady=(3, 0))
        return box

    def card(self, parent) -> tk.Frame:
        frame = tk.Frame(
            parent,
            bg=COLORS["card"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        frame.pack(fill="x", padx=18, pady=7)
        return frame

    def build_home_tab(self) -> None:
        tab = self.tabs["首页"]
        self.section_title(tab, "今天想做点什么？", "常用功能一键直达")
        grid = tk.Frame(tab, bg=COLORS["bg"])
        grid.pack(fill="x", padx=12)
        actions = [
            ("✂", "区域截图", self.start_region_capture),
            ("▣", "全屏截图", self.capture_fullscreen),
            ("⌑", "计算器", lambda: self.open_panel("工具")),
            ("⇄", "文件中转", lambda: self.open_panel("文件中转")),
            ("✓", "添加待办", self.quick_add_todo),
            ("⏰", "添加提醒", self.quick_add_reminder),
            ("◷", "番茄钟", lambda: self.open_panel("番茄")),
            ("🎲", "随机决定", lambda: self.open_panel("工具")),
        ]
        for i, (icon, label, command) in enumerate(actions):
            button = tk.Button(
                grid,
                text=f"{icon}\n{label}",
                command=command,
                bg="white",
                fg=COLORS["ink"],
                activebackground="#EFEDFF",
                activeforeground=COLORS["brand"],
                relief="flat",
                font=("Microsoft YaHei UI", 10),
                width=10,
                height=3,
                cursor="hand2",
            )
            button.grid(row=i // 4, column=i % 4, padx=5, pady=5, sticky="nsew")
            grid.columnconfigure(i % 4, weight=1)

        card = self.card(tab)
        tk.Label(
            card,
            text="快捷操作",
            bg="white",
            fg=COLORS["ink"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 8))
        row = tk.Frame(card, bg="white")
        row.pack(fill="x", padx=12, pady=(0, 14))
        ttk.Button(row, text="锁定电脑", style="Soft.TButton", command=self.lock_computer).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(
            row,
            text="打开截图目录",
            style="Soft.TButton",
            command=lambda: os.startfile(SCREENSHOT_DIR),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            row,
            text="隐藏面板",
            style="Soft.TButton",
            command=lambda: self.panel.withdraw(),
        ).pack(side="left")

        status = self.card(tab)
        self.home_status = tk.Label(
            status,
            text="",
            justify="left",
            bg="white",
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 10),
            padx=14,
            pady=14,
        )
        self.home_status.pack(anchor="w")

    def build_clipboard_tab(self) -> None:
        tab = self.tabs["剪贴板"]
        self.section_title(tab, "剪贴板历史", "自动保存最近 100 条文字，双击即可复制")
        top = tk.Frame(tab, bg=COLORS["bg"])
        top.pack(fill="x", padx=18, pady=(0, 8))
        self.clip_search_var = tk.StringVar()
        search = tk.Entry(
            top,
            textvariable=self.clip_search_var,
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            bd=1,
        )
        search.pack(side="left", fill="x", expand=True, ipady=6)
        search.bind("<KeyRelease>", lambda _e: self.refresh_clipboard())
        ttk.Button(
            top, text="清空", style="Soft.TButton", command=self.clear_clipboard_history
        ).pack(side="left", padx=(8, 0))

        body = tk.Frame(tab, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self.clip_tree = ttk.Treeview(
            body, columns=("favorite", "text", "time"), show="headings", selectmode="browse"
        )
        self.clip_tree.heading("favorite", text="收藏")
        self.clip_tree.heading("text", text="内容")
        self.clip_tree.heading("time", text="时间")
        self.clip_tree.column("favorite", width=52, anchor="center", stretch=False)
        self.clip_tree.column("text", width=300)
        self.clip_tree.column("time", width=80, anchor="center", stretch=False)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.clip_tree.yview)
        self.clip_tree.configure(yscrollcommand=scrollbar.set)
        self.clip_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.clip_tree.bind("<Double-1>", lambda _e: self.copy_selected_clip())

        actions = tk.Frame(tab, bg=COLORS["bg"])
        actions.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(
            actions, text="复制选中", style="Accent.TButton", command=self.copy_selected_clip
        ).pack(side="left")
        ttk.Button(
            actions, text="收藏/取消", style="Soft.TButton", command=self.toggle_clip_favorite
        ).pack(side="left", padx=8)
        ttk.Button(
            actions, text="删除", style="Soft.TButton", command=self.delete_selected_clip
        ).pack(side="left")

    def build_tools_tab(self) -> None:
        tab = self.tabs["工具"]
        self.section_title(tab, "轻量计算器", "支持括号、幂、百分数和常用数学函数")
        calc_card = self.card(tab)
        self.calc_var = tk.StringVar()
        calc_entry = tk.Entry(
            calc_card,
            textvariable=self.calc_var,
            font=("Consolas", 14),
            relief="flat",
            bg="#F7F7FA",
        )
        calc_entry.pack(side="left", fill="x", expand=True, padx=12, pady=12, ipady=7)
        calc_entry.bind("<Return>", lambda _e: self.calculate())
        ttk.Button(
            calc_card, text="计算", style="Accent.TButton", command=self.calculate
        ).pack(side="right", padx=(0, 12))
        self.calc_result = tk.Label(
            tab,
            text="结果会显示在这里",
            bg=COLORS["bg"],
            fg=COLORS["brand"],
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        self.calc_result.pack(anchor="w", padx=20, pady=(0, 8))

        self.section_title(tab, "随机决定器", "转盘、抽签与抛硬币，各有不同的动态体验")
        random_card = self.card(tab)
        mode_row = tk.Frame(random_card, bg="white")
        mode_row.pack(fill="x", padx=12, pady=(12, 8))
        self.random_mode_var = tk.StringVar(
            value=self.store.data.get("random_mode", "转盘")
        )
        self.random_mode_buttons = {}
        for mode, icon in [("转盘", "◉"), ("抽签", "▥"), ("抛硬币", "●")]:
            button = tk.Button(
                mode_row,
                text=f"{icon} {mode}",
                command=lambda m=mode: self.set_random_mode(m),
                relief="flat",
                bd=0,
                padx=13,
                pady=7,
                font=("Microsoft YaHei UI", 9, "bold"),
                cursor="hand2",
            )
            button.pack(side="left", padx=(0, 7))
            self.random_mode_buttons[mode] = button
        self.random_input = tk.Text(
            random_card,
            height=3,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            bg="#F7F7FA",
        )
        self.random_input.pack(fill="x", padx=12, pady=(12, 8))
        self.random_input.insert("1.0", self.store.data.get("random_options", ""))
        self.random_canvas = tk.Canvas(
            random_card,
            height=210,
            bg="#F8F8FC",
            highlightthickness=0,
        )
        self.random_canvas.pack(fill="x", padx=12, pady=(0, 8))
        random_row = tk.Frame(random_card, bg="white")
        random_row.pack(fill="x", padx=12, pady=(0, 12))
        self.random_start_button = ttk.Button(
            random_row,
            text="开始",
            style="Accent.TButton",
            command=self.start_random_experience,
        )
        self.random_start_button.pack(side="left")
        self.random_result = tk.Label(
            random_row,
            text="准备好，把决定交给一点运气",
            bg="white",
            fg=COLORS["brand"],
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.random_result.pack(side="left", padx=16)
        self.set_random_mode(self.random_mode_var.get(), save=False)

    def build_notes_tab(self) -> None:
        tab = self.tabs["便签待办"]
        self.section_title(tab, "便签", "内容会自动保存在本机")
        note_card = self.card(tab)
        self.note_text = tk.Text(
            note_card,
            height=6,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            bg="#FFFDF2",
        )
        self.note_text.pack(fill="x", padx=10, pady=10)
        self.note_text.insert("1.0", self.store.data.get("notes", ""))
        self.note_text.bind("<KeyRelease>", self.schedule_note_save)
        self.note_save_job = None

        self.section_title(tab, "待办事项", "双击一项可切换完成状态")
        todo_add = tk.Frame(tab, bg=COLORS["bg"])
        todo_add.pack(fill="x", padx=18, pady=(0, 8))
        self.todo_var = tk.StringVar()
        todo_entry = tk.Entry(
            todo_add,
            textvariable=self.todo_var,
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            bd=1,
        )
        todo_entry.pack(side="left", fill="x", expand=True, ipady=6)
        todo_entry.bind("<Return>", lambda _e: self.add_todo())
        ttk.Button(todo_add, text="添加", style="Accent.TButton", command=self.add_todo).pack(
            side="left", padx=(8, 0)
        )
        self.todo_tree = ttk.Treeview(
            tab, columns=("state", "text"), show="headings", height=6
        )
        self.todo_tree.heading("state", text="状态")
        self.todo_tree.heading("text", text="事项")
        self.todo_tree.column("state", width=58, anchor="center", stretch=False)
        self.todo_tree.column("text", width=360)
        self.todo_tree.pack(fill="x", padx=18)
        self.todo_tree.bind("<Double-1>", lambda _e: self.toggle_todo())
        todo_actions = tk.Frame(tab, bg=COLORS["bg"])
        todo_actions.pack(fill="x", padx=18, pady=8)
        ttk.Button(
            todo_actions, text="完成/恢复", style="Soft.TButton", command=self.toggle_todo
        ).pack(side="left")
        ttk.Button(
            todo_actions, text="删除", style="Soft.TButton", command=self.delete_todo
        ).pack(side="left", padx=8)

        self.section_title(tab, "提醒", "时间格式：2026-07-23 18:30")
        reminder = tk.Frame(tab, bg=COLORS["bg"])
        reminder.pack(fill="x", padx=18, pady=(0, 8))
        self.reminder_text_var = tk.StringVar()
        self.reminder_time_var = tk.StringVar(
            value=(datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        )
        tk.Entry(
            reminder,
            textvariable=self.reminder_text_var,
            font=("Microsoft YaHei UI", 9),
            relief="solid",
            bd=1,
        ).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Entry(
            reminder,
            textvariable=self.reminder_time_var,
            font=("Consolas", 9),
            width=17,
            relief="solid",
            bd=1,
        ).pack(side="left", padx=6, ipady=5)
        ttk.Button(
            reminder, text="添加", style="Accent.TButton", command=self.add_reminder
        ).pack(side="left")
        self.reminder_list = tk.Listbox(
            tab,
            height=4,
            font=("Microsoft YaHei UI", 9),
            relief="solid",
            bd=1,
            selectbackground=COLORS["brand"],
        )
        self.reminder_list.pack(fill="x", padx=18)
        ttk.Button(
            tab, text="删除选中提醒", style="Soft.TButton", command=self.delete_reminder
        ).pack(anchor="w", padx=18, pady=8)

    def build_pomodoro_tab(self) -> None:
        tab = self.tabs["番茄"]
        self.section_title(tab, "番茄专注钟", "专注一小段时间，然后安心休息")
        card = self.card(tab)
        self.pomodoro_label = tk.Label(
            card,
            text="25:00",
            bg="white",
            fg=COLORS["brand"],
            font=("Consolas", 44, "bold"),
        )
        self.pomodoro_label.pack(pady=(34, 12))
        self.pomodoro_state = tk.Label(
            card,
            text="准备开始",
            bg="white",
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 11),
        )
        self.pomodoro_state.pack(pady=(0, 20))
        minutes_row = tk.Frame(card, bg="white")
        minutes_row.pack()
        tk.Label(
            minutes_row,
            text="专注时长",
            bg="white",
            fg=COLORS["ink"],
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left")
        self.pomodoro_minutes_var = tk.IntVar(
            value=int(self.store.data.get("pomodoro_minutes", 25))
        )
        ttk.Spinbox(
            minutes_row,
            from_=1,
            to=120,
            textvariable=self.pomodoro_minutes_var,
            width=6,
            justify="center",
        ).pack(side="left", padx=8)
        tk.Label(
            minutes_row,
            text="分钟",
            bg="white",
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left")
        action_row = tk.Frame(card, bg="white")
        action_row.pack(pady=(24, 34))
        ttk.Button(
            action_row, text="开始 / 暂停", style="Accent.TButton", command=self.toggle_pomodoro
        ).pack(side="left", padx=5)
        ttk.Button(
            action_row, text="重置", style="Soft.TButton", command=self.reset_pomodoro
        ).pack(side="left", padx=5)

        tip = self.card(tab)
        tk.Label(
            tip,
            text="小提示\n专注期间把手机放远一点，结束后站起来活动 5 分钟。",
            justify="left",
            bg="white",
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 10),
            padx=14,
            pady=14,
        ).pack(anchor="w")

    def build_transfer_tab(self) -> None:
        tab = self.tabs["文件中转"]
        self.section_title(
            tab,
            "文件中转站",
            "暂存文件位置，不复制文件本体；选择后可直接粘贴到资源管理器",
        )
        add_row = tk.Frame(tab, bg=COLORS["bg"])
        add_row.pack(fill="x", padx=18, pady=(2, 10))
        ttk.Button(
            add_row, text="＋ 添加文件", style="Accent.TButton", command=self.add_transfer_files
        ).pack(side="left")
        ttk.Button(
            add_row, text="添加文件夹", style="Soft.TButton", command=self.add_transfer_folder
        ).pack(side="left", padx=8)
        self.transfer_count_label = tk.Label(
            add_row,
            text="0 项",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        self.transfer_count_label.pack(side="right")

        body = tk.Frame(tab, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=18)
        self.transfer_tree = ttk.Treeview(
            body,
            columns=("name", "kind", "time", "state"),
            show="headings",
            selectmode="extended",
        )
        self.transfer_tree.heading("name", text="名称")
        self.transfer_tree.heading("kind", text="类型")
        self.transfer_tree.heading("time", text="加入时间")
        self.transfer_tree.heading("state", text="状态")
        self.transfer_tree.column("name", width=225)
        self.transfer_tree.column("kind", width=70, anchor="center", stretch=False)
        self.transfer_tree.column("time", width=88, anchor="center", stretch=False)
        self.transfer_tree.column("state", width=58, anchor="center", stretch=False)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.transfer_tree.yview)
        self.transfer_tree.configure(yscrollcommand=scrollbar.set)
        self.transfer_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.transfer_tree.bind("<Double-1>", lambda _e: self.open_transfer())

        actions = tk.Frame(tab, bg=COLORS["bg"])
        actions.pack(fill="x", padx=18, pady=10)
        ttk.Button(
            actions,
            text="复制文件（可粘贴）",
            style="Accent.TButton",
            command=self.copy_transfer_files,
        ).pack(side="left")
        ttk.Button(
            actions, text="打开", style="Soft.TButton", command=self.open_transfer
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions, text="定位", style="Soft.TButton", command=self.reveal_transfer
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions, text="移出中转站", style="Soft.TButton", command=self.remove_transfers
        ).pack(side="right")

        tip = self.card(tab)
        tk.Label(
            tip,
            text="使用方法  添加 → 多选 → 复制文件 → 在目标文件夹按 Ctrl + V\n"
            "中转站只保存路径，因此几乎不增加磁盘占用；移动原文件后会显示“失效”。",
            justify="left",
            bg="white",
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
            padx=14,
            pady=13,
        ).pack(anchor="w")
        ttk.Button(
            tip,
            text="清理失效项目",
            style="Soft.TButton",
            command=self.clean_missing_transfers,
        ).pack(anchor="w", padx=14, pady=(0, 13))

    def build_settings_tab(self) -> None:
        tab = self.tabs["设置"]
        self.section_title(tab, "助手名称", "修改后，窗口、菜单和提醒会立即同步")
        name_card = self.card(tab)
        name_row = tk.Frame(name_card, bg="white")
        name_row.pack(fill="x", padx=12, pady=12)
        self.app_name_var = tk.StringVar(value=self.app_name)
        name_entry = tk.Entry(
            name_row,
            textvariable=self.app_name_var,
            font=("Microsoft YaHei UI", 11),
            relief="flat",
            bg="#F4F4F9",
        )
        name_entry.pack(side="left", fill="x", expand=True, ipady=7)
        name_entry.bind("<Return>", lambda _e: self.change_app_name())
        ttk.Button(
            name_row,
            text="应用名称",
            style="Accent.TButton",
            command=self.change_app_name,
        ).pack(side="left", padx=(9, 0))

        self.section_title(tab, "小助手形象", "选择表情形象，或使用自己的图片")
        avatar_card = self.card(tab)
        row = tk.Frame(avatar_card, bg="white")
        row.pack(fill="x", padx=12, pady=14)
        for emoji in ["🐳", "🐱", "🤖", "🦊", "🐼", "🌙", "⭐"]:
            tk.Button(
                row,
                text=emoji,
                font=("Segoe UI Emoji", 20),
                bg="#F5F4FF",
                activebackground="#E7E3FF",
                relief="flat",
                width=2,
                cursor="hand2",
                command=lambda e=emoji: self.set_emoji_avatar(e),
            ).pack(side="left", padx=3)
        ttk.Button(
            avatar_card, text="选择本地图片", style="Soft.TButton", command=self.choose_avatar_image
        ).pack(anchor="w", padx=14, pady=(0, 14))

        self.section_title(
            tab,
            "快捷小卫星",
            "可设置数量、展开方向以及每一颗小球负责的功能",
        )
        satellite_card = self.card(tab)
        satellite_top = tk.Frame(satellite_card, bg="white")
        satellite_top.pack(fill="x", padx=14, pady=(14, 10))
        tk.Label(
            satellite_top,
            text="数量",
            bg="white",
            fg=COLORS["ink"],
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        self.satellite_count_var = tk.IntVar(
            value=max(0, min(6, int(self.store.data.get("satellite_count", 5))))
        )
        ttk.Spinbox(
            satellite_top,
            from_=0,
            to=6,
            textvariable=self.satellite_count_var,
            width=5,
            justify="center",
        ).pack(side="left", padx=(7, 18))
        tk.Label(
            satellite_top,
            text="展开方向",
            bg="white",
            fg=COLORS["ink"],
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        self.satellite_layout_var = tk.StringVar(
            value=self.store.data.get("satellite_layout", "自动")
        )
        ttk.Combobox(
            satellite_top,
            textvariable=self.satellite_layout_var,
            values=["自动", "左侧", "右侧", "上方", "下方", "环绕"],
            state="readonly",
            width=9,
        ).pack(side="left", padx=7)
        tk.Label(
            satellite_top,
            text="距离",
            bg="white",
            fg=COLORS["ink"],
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(10, 0))
        self.satellite_distance_var = tk.IntVar(
            value=max(80, min(130, int(self.store.data.get("satellite_distance", 92))))
        )
        ttk.Spinbox(
            satellite_top,
            from_=80,
            to=130,
            increment=5,
            textvariable=self.satellite_distance_var,
            width=5,
            justify="center",
        ).pack(side="left", padx=7)

        function_grid = tk.Frame(satellite_card, bg="white")
        function_grid.pack(fill="x", padx=10, pady=(0, 10))
        catalog = self.satellite_catalog()
        self.satellite_label_to_id = {value[1]: key for key, value in catalog.items()}
        function_labels = list(self.satellite_label_to_id)
        configured = list(self.store.data.get("satellite_functions", []))
        defaults = DEFAULT_DATA["satellite_functions"]
        self.satellite_function_vars = []
        for index in range(6):
            cell = tk.Frame(function_grid, bg="white")
            cell.grid(row=index // 2, column=index % 2, sticky="ew", padx=4, pady=4)
            function_grid.columnconfigure(index % 2, weight=1)
            tk.Label(
                cell,
                text=f"第 {index + 1} 颗",
                bg="white",
                fg=COLORS["muted"],
                font=("Microsoft YaHei UI", 8),
            ).pack(side="left", padx=(0, 5))
            function_id = configured[index] if index < len(configured) else defaults[index]
            label = catalog.get(function_id, catalog["home"])[1]
            variable = tk.StringVar(value=label)
            self.satellite_function_vars.append(variable)
            ttk.Combobox(
                cell,
                textvariable=variable,
                values=function_labels,
                state="readonly",
                width=12,
            ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            satellite_card,
            text="应用小卫星设置",
            style="Accent.TButton",
            command=self.save_satellite_settings,
        ).pack(anchor="w", padx=14, pady=(0, 14))

        self.section_title(tab, "行为设置")
        settings_card = self.card(tab)
        self.clip_enabled_var = tk.BooleanVar(
            value=bool(self.store.data.get("clipboard_enabled", True))
        )
        tk.Checkbutton(
            settings_card,
            text="记录文字剪贴板历史",
            variable=self.clip_enabled_var,
            command=self.save_settings,
            bg="white",
            activebackground="white",
            fg=COLORS["ink"],
            selectcolor="white",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=14, pady=(14, 7))
        self.auto_hide_var = tk.BooleanVar(
            value=bool(self.store.data.get("auto_hide_fullscreen", True))
        )
        tk.Checkbutton(
            settings_card,
            text="全屏应用时自动隐藏（快捷键可立即唤回）",
            variable=self.auto_hide_var,
            command=self.save_settings,
            bg="white",
            activebackground="white",
            fg=COLORS["ink"],
            selectcolor="white",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=14, pady=(0, 14))

        self.section_title(tab, "数据与说明")
        data_card = self.card(tab)
        ttk.Button(
            data_card,
            text="打开数据目录",
            style="Soft.TButton",
            command=lambda: os.startfile(APP_DIR),
        ).pack(anchor="w", padx=14, pady=(14, 7))
        tk.Label(
            data_card,
            text=f"本地数据：{DATA_FILE}\n无后台联网服务；主要功能均可离线使用。",
            justify="left",
            wraplength=420,
            bg="white",
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=14, pady=(0, 14))

    def change_app_name(self) -> None:
        value = self.app_name_var.get().strip()
        if not value:
            messagebox.showinfo("名称不能为空", "请输入 1—12 个字符。", parent=self.panel)
            return
        if len(value) > 12:
            messagebox.showinfo("名称过长", "助手名称最多 12 个字符。", parent=self.panel)
            return
        self.store.data["app_name"] = value
        self.store.save()
        self.refresh_branding()
        self.toast(f"以后就叫我“{value}”吧")

    def refresh_branding(self) -> None:
        name = self.app_name
        self.root.title(name)
        if self.panel and self.panel.winfo_exists():
            self.panel.title(name)
            self.header_name_label.configure(text=name)
        self.float_tooltip.text = f"{name} · 单击展开 · 右键菜单"
        self.build_context_menu()

    def refresh_all(self) -> None:
        if not self.panel or not self.panel.winfo_exists():
            return
        self.refresh_clipboard()
        self.refresh_todos()
        self.refresh_reminders()
        self.refresh_transfers()
        pending = len([t for t in self.store.data["todos"] if not t.get("done")])
        reminders = len([r for r in self.store.data["reminders"] if not r.get("notified")])
        self.home_status.configure(
            text=f"当前状态\n{pending} 项待办 · {reminders} 个未触发提醒 · "
            f"{len(self.store.data['clipboard'])} 条剪贴板记录 · "
            f"{len(self.store.data.get('transfers', []))} 个中转项目"
        )

    def add_transfer_files(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.panel, title="添加到文件中转站")
        self.add_transfer_paths(paths)

    def add_transfer_folder(self) -> None:
        path = filedialog.askdirectory(parent=self.panel, title="添加文件夹到中转站")
        if path:
            self.add_transfer_paths([path])

    def add_transfer_paths(self, paths) -> None:
        existing = {
            os.path.normcase(os.path.abspath(item.get("path", "")))
            for item in self.store.data.get("transfers", [])
        }
        added = 0
        for raw in paths:
            path = os.path.abspath(str(raw))
            normalized = os.path.normcase(path)
            if normalized in existing or not os.path.exists(path):
                continue
            self.store.data.setdefault("transfers", []).insert(
                0,
                {
                    "path": path,
                    "added": datetime.now().strftime("%m-%d %H:%M"),
                },
            )
            existing.add(normalized)
            added += 1
        self.store.data["transfers"] = self.store.data.get("transfers", [])[:100]
        self.store.save()
        self.refresh_transfers()
        if added:
            self.toast(f"已加入中转站：{added} 项")

    def refresh_transfers(self) -> None:
        if not hasattr(self, "transfer_tree"):
            return
        self.transfer_tree.delete(*self.transfer_tree.get_children())
        transfers = self.store.data.get("transfers", [])
        for index, item in enumerate(transfers):
            path = Path(item.get("path", ""))
            exists = path.exists()
            kind = "文件夹" if exists and path.is_dir() else (path.suffix[1:].upper() or "文件")
            self.transfer_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    path.name or str(path),
                    kind,
                    item.get("added", ""),
                    "可用" if exists else "失效",
                ),
            )
        self.transfer_count_label.configure(text=f"{len(transfers)} 项")

    def selected_transfer_indices(self) -> list[int]:
        return sorted((int(item) for item in self.transfer_tree.selection()))

    def selected_transfer_paths(self) -> list[str]:
        transfers = self.store.data.get("transfers", [])
        return [
            transfers[index]["path"]
            for index in self.selected_transfer_indices()
            if 0 <= index < len(transfers) and Path(transfers[index]["path"]).exists()
        ]

    def open_transfer(self) -> None:
        paths = self.selected_transfer_paths()
        if paths:
            os.startfile(paths[0])

    def reveal_transfer(self) -> None:
        paths = self.selected_transfer_paths()
        if not paths:
            return
        path = Path(paths[0])
        if path.is_dir():
            os.startfile(path)
        else:
            subprocess.Popen(["explorer.exe", "/select,", str(path)])

    def remove_transfers(self) -> None:
        indices = self.selected_transfer_indices()
        if not indices:
            return
        transfers = self.store.data.get("transfers", [])
        for index in reversed(indices):
            if 0 <= index < len(transfers):
                transfers.pop(index)
        self.store.save()
        self.refresh_transfers()

    def clean_missing_transfers(self) -> None:
        before = len(self.store.data.get("transfers", []))
        self.store.data["transfers"] = [
            item
            for item in self.store.data.get("transfers", [])
            if Path(item.get("path", "")).exists()
        ]
        removed = before - len(self.store.data["transfers"])
        self.store.save()
        self.refresh_transfers()
        self.toast(f"已清理 {removed} 个失效项目")

    def copy_transfer_files(self) -> None:
        paths = self.selected_transfer_paths()
        if not paths:
            self.toast("请先选择可用文件或文件夹")
            return
        if self.copy_file_paths_to_clipboard(paths):
            self.toast(f"已复制 {len(paths)} 项，可在目标文件夹粘贴")
        else:
            self.toast("复制失败，请稍后重试")

    @staticmethod
    def copy_file_paths_to_clipboard(paths: list[str]) -> bool:
        CF_HDROP = 15
        GMEM_MOVEABLE = 0x0002
        GMEM_ZEROINIT = 0x0040
        encoded_paths = ("\0".join(paths) + "\0\0").encode("utf-16le")
        payload = struct.pack("IiiII", 20, 0, 0, 0, 1) + encoded_paths
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(payload))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return False
        ctypes.memmove(pointer, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        if not user32.OpenClipboard(None):
            return False
        user32.EmptyClipboard()
        result = bool(user32.SetClipboardData(CF_HDROP, handle))
        user32.CloseClipboard()
        return result

    def poll_clipboard(self) -> None:
        try:
            if self.store.data.get("clipboard_enabled", True):
                text = self.root.clipboard_get().strip()
                if text and text != self.last_clipboard:
                    self.last_clipboard = text
                    if not self.store.data["clipboard"] or self.store.data["clipboard"][0].get(
                        "text"
                    ) != text:
                        self.store.data["clipboard"].insert(
                            0,
                            {
                                "text": text,
                                "time": datetime.now().strftime("%H:%M"),
                                "favorite": False,
                            },
                        )
                        favorites = [
                            x for x in self.store.data["clipboard"] if x.get("favorite")
                        ]
                        others = [
                            x for x in self.store.data["clipboard"] if not x.get("favorite")
                        ][:100]
                        self.store.data["clipboard"] = favorites + others
                        self.store.save()
                        if self.panel and self.panel.winfo_exists():
                            self.refresh_clipboard()
        except tk.TclError:
            pass
        self.root.after(900, self.poll_clipboard)

    def refresh_clipboard(self) -> None:
        if not hasattr(self, "clip_tree"):
            return
        self.clip_tree.delete(*self.clip_tree.get_children())
        query = self.clip_search_var.get().strip().lower()
        for index, item in enumerate(self.store.data["clipboard"]):
            text = item.get("text", "")
            if query and query not in text.lower():
                continue
            display = " ".join(text.split())
            if len(display) > 70:
                display = display[:67] + "…"
            self.clip_tree.insert(
                "", "end", iid=str(index), values=("★" if item.get("favorite") else "", display, item.get("time", ""))
            )

    def selected_clip_index(self) -> int | None:
        selection = self.clip_tree.selection()
        return int(selection[0]) if selection else None

    def copy_selected_clip(self) -> None:
        index = self.selected_clip_index()
        if index is None:
            return
        text = self.store.data["clipboard"][index]["text"]
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.last_clipboard = text
        self.toast("已复制到剪贴板")

    def toggle_clip_favorite(self) -> None:
        index = self.selected_clip_index()
        if index is None:
            return
        item = self.store.data["clipboard"][index]
        item["favorite"] = not item.get("favorite", False)
        self.store.save()
        self.refresh_clipboard()

    def delete_selected_clip(self) -> None:
        index = self.selected_clip_index()
        if index is None:
            return
        self.store.data["clipboard"].pop(index)
        self.store.save()
        self.refresh_clipboard()

    def clear_clipboard_history(self) -> None:
        if messagebox.askyesno("清空剪贴板", "保留收藏项并清空其他记录？", parent=self.panel):
            self.store.data["clipboard"] = [
                x for x in self.store.data["clipboard"] if x.get("favorite")
            ]
            self.store.save()
            self.refresh_clipboard()

    def start_region_capture(self) -> None:
        self.prepare_capture()
        self.root.after(280, lambda: SelectionScreenshot(self))

    def capture_fullscreen(self) -> None:
        self.prepare_capture()

        def do_capture():
            try:
                image = ImageGrab.grab(all_screens=True)
                path = self.save_screenshot(image)
                self.copy_image_to_clipboard(image)
                self.restore_after_capture()
                self.toast(f"全屏截图已保存并复制\n{path.name}")
            except Exception as exc:
                self.restore_after_capture()
                messagebox.showerror("截图失败", str(exc))

        self.root.after(280, do_capture)

    def prepare_capture(self) -> None:
        self.hide_satellites()
        self.panel_visible_before_capture = bool(
            self.panel and self.panel.winfo_exists() and self.panel.state() == "normal"
        )
        if self.panel and self.panel.winfo_exists():
            self.panel.withdraw()
        self.root.withdraw()

    def restore_after_capture(self) -> None:
        self.root.deiconify()
        self.root.lift()
        if self.panel_visible_before_capture:
            self.open_panel()

    def save_screenshot(self, image: Image.Image) -> Path:
        ensure_dirs()
        path = SCREENSHOT_DIR / datetime.now().strftime("截图_%Y%m%d_%H%M%S.png")
        image.save(path, "PNG")
        return path

    @staticmethod
    def copy_image_to_clipboard(image: Image.Image) -> None:
        output = io.BytesIO()
        image.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]
        output.close()
        CF_DIB = 8
        GMEM_MOVEABLE = 0x0002
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if user32.OpenClipboard(None):
            user32.EmptyClipboard()
            user32.SetClipboardData(CF_DIB, handle)
            user32.CloseClipboard()

    def calculate(self) -> None:
        expression = self.calc_var.get().strip().replace("^", "**")
        expression = expression.replace("%", "/100")
        try:
            result = safe_eval(expression)
            self.calc_result.configure(text=f"= {result}")
        except Exception:
            self.calc_result.configure(text="表达式无法计算", fg=COLORS["danger"])
            self.root.after(
                1800, lambda: self.calc_result.configure(fg=COLORS["brand"])
            )

    def set_random_mode(self, mode: str, save: bool = True) -> None:
        if mode not in ("转盘", "抽签", "抛硬币"):
            mode = "转盘"
        self.random_mode_var.set(mode)
        for name, button in self.random_mode_buttons.items():
            active = name == mode
            button.configure(
                bg=COLORS["brand"] if active else COLORS["brand_soft"],
                fg="white" if active else COLORS["brand_dark"],
                activebackground=COLORS["brand_dark"] if active else "#DDD9FF",
                activeforeground="white" if active else COLORS["brand_dark"],
            )
        if mode == "抛硬币":
            self.random_input.configure(state="disabled", bg="#EEEEF4")
        else:
            self.random_input.configure(state="normal", bg="#F7F7FA")
        if save:
            self.store.data["random_mode"] = mode
            self.store.save()
        self.render_random_idle()

    def random_options(self) -> list[str]:
        raw = self.random_input.get("1.0", "end").strip()
        return [x.strip() for x in raw.replace("，", "\n").splitlines() if x.strip()]

    def render_random_idle(self) -> None:
        if not hasattr(self, "random_canvas"):
            return
        mode = self.random_mode_var.get()
        if mode == "转盘":
            self.draw_wheel(self.random_options() or ["选项 1", "选项 2", "选项 3"], 0)
        elif mode == "抽签":
            self.draw_lottery_box("等待抽签")
        else:
            self.draw_coin("?", 1.0)

    def start_random_experience(self) -> None:
        mode = self.random_mode_var.get()
        options = self.random_options()
        if mode != "抛硬币" and len(options) < 2:
            self.random_result.configure(text="至少填写两个选项")
            return
        raw = self.random_input.get("1.0", "end").strip()
        self.store.data["random_options"] = raw
        self.store.data["random_mode"] = mode
        self.store.save()
        self.random_start_button.configure(state="disabled")
        self.random_result.configure(text="命运正在认真思考…")
        if mode == "转盘":
            self.animate_wheel(options)
        elif mode == "抽签":
            self.animate_lottery(options)
        else:
            self.animate_coin()

    def finish_random(self, result: str) -> None:
        self.random_result.configure(text=f"结果：{result}")
        self.random_start_button.configure(state="normal")
        self.root.bell()

    def draw_wheel(self, options: list[str], angle: float) -> None:
        canvas = self.random_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 430)
        cx, cy, radius = width // 2, 104, 86
        palette = ["#7567F8", "#FF8A7A", "#4FC7A4", "#F4B84E", "#5EAEF2", "#A777E8"]
        extent = 360 / len(options)
        for index, option in enumerate(options):
            start = angle + index * extent
            color = palette[index % len(palette)]
            canvas.create_arc(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                start=start,
                extent=extent,
                fill=color,
                outline="white",
                width=2,
            )
            mid = math.radians(start + extent / 2)
            tx = cx + math.cos(mid) * radius * 0.62
            ty = cy - math.sin(mid) * radius * 0.62
            label = option if len(option) <= 6 else option[:5] + "…"
            canvas.create_text(
                tx,
                ty,
                text=label,
                fill="white",
                font=("Microsoft YaHei UI", 9, "bold"),
                angle=-(start + extent / 2) % 360,
            )
        canvas.create_oval(
            cx - 18, cy - 18, cx + 18, cy + 18, fill="#24273A", outline="white", width=2
        )
        canvas.create_polygon(
            cx + radius + 9,
            cy,
            cx + radius - 6,
            cy - 9,
            cx + radius - 6,
            cy + 9,
            fill="#24273A",
            outline="white",
        )

    def animate_wheel(self, options: list[str]) -> None:
        start_angle = self.random_angle
        distance = random.randint(5, 8) * 360 + random.randint(0, 359)
        frames = 52

        def frame(step: int) -> None:
            progress = step / frames
            eased = 1 - (1 - progress) ** 3
            angle = start_angle + distance * eased
            self.draw_wheel(options, angle)
            if step < frames:
                self.random_animation_job = self.root.after(28, lambda: frame(step + 1))
            else:
                self.random_angle = angle % 360
                extent = 360 / len(options)
                index = int(((-self.random_angle) % 360) / extent) % len(options)
                self.finish_random(options[index])

        frame(0)

    def draw_lottery_box(self, ticket_text: str, offset: int = 0) -> None:
        canvas = self.random_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 430)
        cx = width // 2
        canvas.create_rectangle(
            cx - 105,
            67 + offset,
            cx + 105,
            174 + offset,
            fill="#4A426F",
            outline="#7567F8",
            width=3,
        )
        canvas.create_polygon(
            cx - 115,
            68 + offset,
            cx,
            125 + offset,
            cx + 115,
            68 + offset,
            fill="#60578A",
            outline="#9187DE",
        )
        canvas.create_rectangle(
            cx - 86,
            26 - offset,
            cx + 86,
            88 - offset,
            fill="#FFF8DE",
            outline="#F4B84E",
            width=2,
        )
        canvas.create_text(
            cx,
            56 - offset,
            text=ticket_text[:18],
            fill="#4B425F",
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        canvas.create_text(
            cx, 196, text="轻轻摇一摇，抽出属于你的签", fill=COLORS["muted"], font=("Microsoft YaHei UI", 9)
        )

    def animate_lottery(self, options: list[str]) -> None:
        frames = 24

        def frame(step: int) -> None:
            preview = random.choice(options)
            offset = 4 if step % 2 else -4
            self.draw_lottery_box(preview, offset)
            if step < frames:
                self.random_animation_job = self.root.after(
                    55 + step * 3, lambda: frame(step + 1)
                )
            else:
                result = random.choice(options)
                self.draw_lottery_box(result, 0)
                self.finish_random(result)

        frame(0)

    def draw_coin(self, side: str, scale: float) -> None:
        canvas = self.random_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 430)
        cx, cy = width // 2, 102
        half_w = max(5, int(62 * scale))
        canvas.create_oval(
            cx - half_w + 5,
            cy - 58 + 8,
            cx + half_w + 5,
            cy + 58 + 8,
            fill="#C98A19",
            outline="",
        )
        canvas.create_oval(
            cx - half_w,
            cy - 58,
            cx + half_w,
            cy + 58,
            fill="#F6C759",
            outline="#FFF1A8",
            width=3,
        )
        canvas.create_text(
            cx,
            cy,
            text=side,
            fill="#7C5515",
            font=("Microsoft YaHei UI", 28, "bold"),
        )
        canvas.create_text(
            cx, 190, text="正面还是反面？让硬币替你回答", fill=COLORS["muted"], font=("Microsoft YaHei UI", 9)
        )

    def animate_coin(self) -> None:
        final = random.choice(["正面", "反面"])
        frames = 30

        def frame(step: int) -> None:
            side = "正" if step % 2 == 0 else "反"
            scale = max(0.08, abs(math.cos(step * math.pi / 4)))
            self.draw_coin(side, scale)
            if step < frames:
                self.random_animation_job = self.root.after(
                    45 + step * 2, lambda: frame(step + 1)
                )
            else:
                self.draw_coin(final[0], 1.0)
                self.finish_random(final)

        frame(0)

    def schedule_note_save(self, _event=None) -> None:
        if self.note_save_job:
            self.root.after_cancel(self.note_save_job)
        self.note_save_job = self.root.after(500, self.save_notes)

    def save_notes(self) -> None:
        self.store.data["notes"] = self.note_text.get("1.0", "end-1c")
        self.store.save()
        self.note_save_job = None

    def quick_add_todo(self) -> None:
        text = simpledialog.askstring("添加待办", "要做什么？", parent=self.panel)
        if text:
            self.store.data["todos"].append(
                {"text": text.strip(), "done": False, "created": datetime.now().isoformat()}
            )
            self.store.save()
            self.refresh_todos()
            self.refresh_all()

    def add_todo(self) -> None:
        text = self.todo_var.get().strip()
        if not text:
            return
        self.store.data["todos"].append(
            {"text": text, "done": False, "created": datetime.now().isoformat()}
        )
        self.todo_var.set("")
        self.store.save()
        self.refresh_todos()

    def refresh_todos(self) -> None:
        if not hasattr(self, "todo_tree"):
            return
        self.todo_tree.delete(*self.todo_tree.get_children())
        for index, todo in enumerate(self.store.data["todos"]):
            self.todo_tree.insert(
                "",
                "end",
                iid=str(index),
                values=("✓" if todo.get("done") else "○", todo.get("text", "")),
            )

    def selected_todo_index(self) -> int | None:
        selected = self.todo_tree.selection()
        return int(selected[0]) if selected else None

    def toggle_todo(self) -> None:
        index = self.selected_todo_index()
        if index is None:
            return
        todo = self.store.data["todos"][index]
        todo["done"] = not todo.get("done")
        self.store.save()
        self.refresh_todos()

    def delete_todo(self) -> None:
        index = self.selected_todo_index()
        if index is None:
            return
        self.store.data["todos"].pop(index)
        self.store.save()
        self.refresh_todos()

    def quick_add_reminder(self) -> None:
        self.open_panel("便签待办")
        self.reminder_text_var.set("")
        self.reminder_time_var.set(
            (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        )

    def add_reminder(self) -> None:
        text = self.reminder_text_var.get().strip()
        raw_time = self.reminder_time_var.get().strip()
        if not text:
            messagebox.showinfo("添加提醒", "请填写提醒内容。", parent=self.panel)
            return
        try:
            when = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
        except ValueError:
            messagebox.showerror(
                "时间格式不正确", "请按 2026-07-23 18:30 的格式填写。", parent=self.panel
            )
            return
        self.store.data["reminders"].append(
            {"text": text, "time": when.isoformat(timespec="minutes"), "notified": False}
        )
        self.store.data["reminders"].sort(key=lambda x: x["time"])
        self.reminder_text_var.set("")
        self.store.save()
        self.refresh_reminders()

    def refresh_reminders(self) -> None:
        if not hasattr(self, "reminder_list"):
            return
        self.reminder_list.delete(0, "end")
        for item in self.store.data["reminders"]:
            when = item.get("time", "").replace("T", " ")
            state = "（已提醒）" if item.get("notified") else ""
            self.reminder_list.insert("end", f"{when}  {item.get('text', '')}{state}")

    def delete_reminder(self) -> None:
        selected = self.reminder_list.curselection()
        if not selected:
            return
        self.store.data["reminders"].pop(selected[0])
        self.store.save()
        self.refresh_reminders()

    def check_reminders(self) -> None:
        now = datetime.now()
        changed = False
        due = []
        for item in self.store.data["reminders"]:
            if item.get("notified"):
                continue
            try:
                when = datetime.fromisoformat(item["time"])
            except (ValueError, KeyError):
                continue
            if when <= now:
                item["notified"] = True
                due.append(item.get("text", "提醒时间到了"))
                changed = True
        if changed:
            self.store.save()
            if hasattr(self, "reminder_list"):
                self.refresh_reminders()
        for text in due:
            self.show_reminder(text)
        self.root.after(5000, self.check_reminders)

    def show_reminder(self, text: str) -> None:
        self.fullscreen_hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.bell()
        messagebox.showinfo(f"⏰ {self.app_name}提醒", text, parent=self.root)

    def toggle_pomodoro(self) -> None:
        if self.pomodoro_remaining <= 0:
            minutes = max(1, int(self.pomodoro_minutes_var.get()))
            self.pomodoro_remaining = minutes * 60
            self.store.data["pomodoro_minutes"] = minutes
            self.store.save()
        self.pomodoro_running = not self.pomodoro_running
        self.pomodoro_state.configure(
            text="正在专注" if self.pomodoro_running else "已暂停"
        )
        if self.pomodoro_running:
            self.tick_pomodoro()

    def tick_pomodoro(self) -> None:
        if not self.pomodoro_running:
            return
        minutes, seconds = divmod(self.pomodoro_remaining, 60)
        self.pomodoro_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        if self.pomodoro_remaining <= 0:
            self.pomodoro_running = False
            self.pomodoro_state.configure(text="完成！休息一下吧")
            self.root.bell()
            self.toast("🍅 番茄钟完成，休息一下吧")
            return
        self.pomodoro_remaining -= 1
        self.pomodoro_job = self.root.after(1000, self.tick_pomodoro)

    def reset_pomodoro(self) -> None:
        self.pomodoro_running = False
        self.pomodoro_remaining = max(1, int(self.pomodoro_minutes_var.get())) * 60
        minutes, seconds = divmod(self.pomodoro_remaining, 60)
        self.pomodoro_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        self.pomodoro_state.configure(text="准备开始")

    def set_emoji_avatar(self, emoji: str) -> None:
        self.store.data["avatar"] = {"type": "emoji", "value": emoji}
        self.store.save()
        self.redraw_avatar()
        self.toast(f"新形象已启用 {emoji}")

    def choose_avatar_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.panel,
            title="选择小助手图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            source = Path(path)
            target = AVATAR_DIR / f"custom{source.suffix.lower()}"
            shutil.copy2(source, target)
            self.store.data["avatar"] = {"type": "image", "value": str(target)}
            self.store.save()
            self.redraw_avatar()
            self.toast("自定义形象已启用")
        except Exception as exc:
            messagebox.showerror("更换形象失败", str(exc), parent=self.panel)

    def save_satellite_settings(self) -> None:
        try:
            count = max(0, min(6, int(self.satellite_count_var.get())))
        except (TypeError, ValueError, tk.TclError):
            count = 5
        try:
            distance = max(80, min(130, int(self.satellite_distance_var.get())))
        except (TypeError, ValueError, tk.TclError):
            distance = 92
        layout = self.satellite_layout_var.get()
        if layout not in ("自动", "左侧", "右侧", "上方", "下方", "环绕"):
            layout = "自动"
        functions = [
            self.satellite_label_to_id.get(variable.get(), "home")
            for variable in self.satellite_function_vars
        ]
        self.store.data["satellite_count"] = count
        self.store.data["satellite_layout"] = layout
        self.store.data["satellite_distance"] = distance
        self.store.data["satellite_functions"] = functions
        self.store.save()
        self.hide_satellites()
        if count:
            self.toast(f"已应用：{count} 颗小卫星 · {layout}展开")
        else:
            self.toast("快捷小卫星已关闭")

    def save_settings(self) -> None:
        self.store.data["clipboard_enabled"] = bool(self.clip_enabled_var.get())
        self.store.data["auto_hide_fullscreen"] = bool(self.auto_hide_var.get())
        self.store.save()

    def lock_computer(self) -> None:
        if messagebox.askyesno("锁定电脑", "现在锁定 Windows？", parent=self.panel or self.root):
            ctypes.windll.user32.LockWorkStation()

    def toast(self, text: str) -> None:
        if self.toast_window and self.toast_window.winfo_exists():
            self.toast_window.destroy()
        win = tk.Toplevel(self.root)
        self.toast_window = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        tk.Label(
            win,
            text=text,
            justify="left",
            bg="#252A3A",
            fg="white",
            font=("Microsoft YaHei UI", 10),
            padx=16,
            pady=11,
        ).pack()
        win.update_idletasks()
        win.geometry(
            f"+{sw - win.winfo_width() - 24}+{sh - win.winfo_height() - 72}"
        )
        win.after(2400, win.destroy)

    def register_hotkey(self) -> None:
        def listener():
            user32 = ctypes.windll.user32
            HOTKEY_ID = 0xA551
            MOD_CONTROL = 0x0002
            MOD_ALT = 0x0001
            WM_HOTKEY = 0x0312
            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, ord("A")):
                return
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.root.after(0, self.hotkey_toggle)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        import ctypes.wintypes

        threading.Thread(target=listener, daemon=True).start()

    def hotkey_toggle(self) -> None:
        self.fullscreen_hidden = False
        self.root.deiconify()
        self.root.lift()
        self.toggle_panel()

    def check_fullscreen(self) -> None:
        if not self.store.data.get("auto_hide_fullscreen", True):
            if self.fullscreen_hidden:
                self.root.deiconify()
                self.fullscreen_hidden = False
            self.root.after(1800, self.check_fullscreen)
            return
        try:
            # Windows 会区分普通最大化窗口与真正的 D3D 全屏/演示模式。
            # 使用该状态可避免在浏览器、编辑器等最大化时误隐藏。
            notification_state = ctypes.c_int()
            result = ctypes.windll.shell32.SHQueryUserNotificationState(
                ctypes.byref(notification_state)
            )
            is_full = result == 0 and notification_state.value in (3, 4)
            if is_full and not self.fullscreen_hidden:
                self.hide_satellites()
                if self.panel and self.panel.winfo_exists():
                    self.panel.withdraw()
                self.root.withdraw()
                self.fullscreen_hidden = True
            elif not is_full and self.fullscreen_hidden:
                self.root.deiconify()
                self.root.lift()
                self.fullscreen_hidden = False
        except Exception:
            pass
        self.root.after(1800, self.check_fullscreen)

    def quit_app(self) -> None:
        try:
            self.hide_satellites()
            if hasattr(self, "note_text"):
                self.save_notes()
            self.store.data["position"] = [self.root.winfo_x(), self.root.winfo_y()]
            self.store.save()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
ALLOWED_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "abs": abs,
    "round": round,
}
ALLOWED_NAMES = {"pi": math.pi, "e": math.e}


def safe_eval(expression: str):
    if not expression or len(expression) > 200:
        raise ValueError("invalid expression")
    tree = ast.parse(expression, mode="eval")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINOPS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("power too large")
            return ALLOWED_BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY:
            return ALLOWED_UNARY[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.Name) and node.id in ALLOWED_NAMES:
            return ALLOWED_NAMES[node.id]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ALLOWED_FUNCS
            and not node.keywords
        ):
            return ALLOWED_FUNCS[node.func.id](*(evaluate(arg) for arg in node.args))
        raise ValueError("unsupported expression")

    value = evaluate(tree)
    if isinstance(value, float):
        return round(value, 12)
    return value


if __name__ == "__main__":
    try:
        FloatingAssistant().run()
    except Exception as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "小助手启动失败",
            f"{error}\n\n请使用“诊断启动.bat”查看详细信息。",
        )
        raise
