# -*- coding: utf-8 -*-
"""
Smart Connect Manager — Kivy App
====================================
مدير اتصالات ذكي يفحص latency لسيرفرات متعددة ويختار الأسرع.
ملاحظة: هذا مدير اتصال، وليس VPN حقيقي (راجع التوثيق).
متوافق مع: Python 3.9 + Kivy 2.2.1
"""

import threading
import socket
import time
import json
import os
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Ellipse
from kivy.utils import platform, get_color_from_hex
from kivy.metrics import dp, sp

# ============================================================
# إعدادات عامة
# ============================================================
APP_TITLE = "Smart Connect"
STATE_FILE = "smart_connect_state.json"
LATENCY_TIMEOUT = 1.5  # ثواني
HEALTH_CHECK_INTERVAL = 30  # ثواني بين كل فحص دوري

# ألوان عصرية
COLOR_PRIMARY = get_color_from_hex("#1E88E5")     # أزرق
COLOR_SUCCESS = get_color_from_hex("#43A047")     # أخضر
COLOR_ERROR = get_color_from_hex("#E53935")       # أحمر
COLOR_BG = get_color_from_hex("#0F1419")          # خلفية داكنة
COLOR_CARD = get_color_from_hex("#1A2230")        # كرت
COLOR_TEXT = get_color_from_hex("#FFFFFF")
COLOR_TEXT_DIM = get_color_from_hex("#8B98A5")

# ============================================================
# قائمة السيرفرات (أمثلة حقيقية للاختبار)
# ============================================================
SERVERS = [
    {"name": "Cloudflare DNS",     "host": "1.1.1.1",         "port": 53},
    {"name": "Google DNS",         "host": "8.8.8.8",         "port": 53},
    {"name": "Quad9 DNS",          "host": "9.9.9.9",         "port": 53},
    {"name": "OpenDNS",            "host": "208.67.222.222",  "port": 53},
    {"name": "AdGuard DNS",        "host": "94.140.14.14",    "port": 53},
    {"name": "Cloudflare WARP",    "host": "engage.cloudflareclient.com", "port": 2408},
    {"name": "DNS.SB",             "host": "185.222.222.222", "port": 53},
    {"name": "CleanBrowsing",      "host": "185.228.168.9",   "port": 53},
]


# ============================================================
# محرك الفحص (يعمل في thread منفصل)
# ============================================================
class ServerScanner:
    """
    يفحص latency لكل السيرفرات بشكل متوازٍ.
    لا يلمس الواجهة مباشرة — يُبلّغ عبر callbacks.
    """

    def __init__(self, servers):
        self.servers = servers
        self.results = {}
        self._lock = threading.Lock()

    def scan_one(self, server):
        """قياس latency لسيرفر واحد عبر TCP."""
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(LATENCY_TIMEOUT)
            sock.connect((server["host"], server["port"]))
            sock.close()
            latency_ms = int((time.time() - start) * 1000)
            return latency_ms
        except Exception:
            return None

    def scan_all(self, on_progress=None, on_complete=None):
        """فحص كل السيرفرات بالتوازي."""
        threads = []
        results = {}

        def worker(srv):
            latency = self.scan_one(srv)
            with self._lock:
                results[srv["name"]] = latency
            if on_progress:
                on_progress(srv["name"], latency)

        for server in self.servers:
            t = threading.Thread(target=worker, args=(server,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=LATENCY_TIMEOUT + 0.5)

        self.results = results

        # أفضل سيرفر = الأقل latency
        valid = {k: v for k, v in results.items() if v is not None}
        best = min(valid, key=valid.get) if valid else None

        if on_complete:
            on_complete(results, best, valid.get(best) if best else None)

        return results, best


# ============================================================
# عناصر الواجهة
# ============================================================
class RoundedButton(ButtonBehavior, Label):
    """زر دائري عصري."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.font_size = sp(20)
        self.color = COLOR_TEXT
        self.bold = True
        self._state = "idle"
        self._pulse = 0
        with self.canvas.before:
            self._bg_color = Color(*COLOR_PRIMARY)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(80)])
        self.bind(pos=self._update_canvas, size=self._update_canvas)

    def _update_canvas(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def set_state(self, state):
        """idle | scanning | connected | error"""
        self._state = state
        color_map = {
            "idle": COLOR_PRIMARY,
            "scanning": get_color_from_hex("#FB8C00"),
            "connected": COLOR_SUCCESS,
            "error": COLOR_ERROR,
        }
        text_map = {
            "idle": "اضغط للاتصال",
            "scanning": "جاري الفحص...",
            "connected": "متصل ✓",
            "error": "فشل الاتصال",
        }
        self._bg_color.rgba = color_map.get(state, COLOR_PRIMARY)
        self.text = text_map.get(state, "")


class StatusCard(BoxLayout):
    """كرت عرض معلومات الحالة."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(20), spacing=dp(8), **kwargs)
        with self.canvas.before:
            Color(*COLOR_CARD)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(20)])
        self.bind(pos=self._update_canvas, size=self._update_canvas)

        self.title_label = Label(
            text="غير متصل",
            font_size=sp(22),
            bold=True,
            color=COLOR_TEXT,
            size_hint_y=0.4,
        )
        self.info_label = Label(
            text="اضغط الزر لبدء الفحص الذكي",
            font_size=sp(14),
            color=COLOR_TEXT_DIM,
            size_hint_y=0.3,
        )
        self.stats_label = Label(
            text="",
            font_size=sp(12),
            color=COLOR_TEXT_DIM,
            size_hint_y=0.3,
        )
        self.add_widget(self.title_label)
        self.add_widget(self.info_label)
        self.add_widget(self.stats_label)

    def _update_canvas(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def update_status(self, title, info, stats=""):
        self.title_label.text = title
        self.info_label.text = info
        self.stats_label.text = stats


# ============================================================
# الشاشة الرئيسية
# ============================================================
class MainScreen(FloatLayout):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.clearcolor = COLOR_BG

        self.scanner = ServerScanner(SERVERS)
        self.is_scanning = False
        self.best_server = None
        self.best_latency = None
        self.last_scan_time = None
        self.servers_count = len(SERVERS)

        self._build_ui()
        self._schedule_health_check()

    def _build_ui(self):
        # ----- عنوان التطبيق -----
        title = Label(
            text=APP_TITLE,
            font_size=sp(28),
            bold=True,
            color=COLOR_TEXT,
            size_hint=(1, None),
            height=dp(60),
            pos_hint={"center_x": 0.5, "top": 0.96},
        )
        self.add_widget(title)

        # ----- كرت الحالة -----
        self.status_card = StatusCard(
            size_hint=(0.9, 0.35),
            pos_hint={"center_x": 0.5, "center_y": 0.62},
        )
        self.add_widget(self.status_card)

        # ----- الزر الرئيسي -----
        self.main_button = RoundedButton(
            text="اضغط للاتصال",
            size_hint=(None, None),
            size=(dp(200), dp(200)),
            pos_hint={"center_x": 0.5, "center_y": 0.32},
        )
        self.main_button.bind(on_release=self.on_button_press)
        self.add_widget(self.main_button)

        # ----- تذييل -----
        footer = Label(
            text=f"{self.servers_count} سيرفرات • فحص ذكي • اختيار تلقائي",
            font_size=sp(11),
            color=COLOR_TEXT_DIM,
            size_hint=(1, None),
            height=dp(30),
            pos_hint={"center_x": 0.5, "y": 0.05},
        )
        self.add_widget(footer)

    # ========================================================
    # التفاعل مع الزر
    # ========================================================
    def on_button_press(self, *args):
        if self.is_scanning:
            return  # تجاهل النقرات أثناء الفحص
        self.start_scan()

    def start_scan(self):
        self.is_scanning = True
        self.main_button.set_state("scanning")
        self.status_card.update_status(
            title="جاري الفحص الذكي...",
            info=f"فحص {self.servers_count} سيرفر بالتوازي",
            stats="",
        )

        # تشغيل الفحص في thread منفصل
        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()

    def _scan_worker(self):
        """يعمل في thread منفصل — يُبلّغ main thread بالنتائج."""
        results, best, latency = self.scanner.scan_all()

        # العودة إلى main thread لتحديث الواجهة
        Clock.schedule_once(
            lambda dt: self._on_scan_complete(results, best, latency), 0
        )

    @mainthread
    def _on_scan_complete(self, results, best, latency):
        """يُستدعى في main thread — تحديث آمن للواجهة."""
        self.is_scanning = False
        self.best_server = best
        self.best_latency = latency
        self.last_scan_time = datetime.now()

        if best:
            self.main_button.set_state("connected")
            self.status_card.update_status(
                title=f"متصل بـ {best}",
                info=f"زمن الاستجابة: {latency} ms",
                stats=f"آخر فحص: {self.last_scan_time.strftime('%H:%M:%S')}",
            )
            self._save_state(best, latency)
        else:
            self.main_button.set_state("error")
            self.status_card.update_status(
                title="فشل الاتصال",
                info="لا يوجد سيرفر يستجيب حالياً",
                stats="تحقق من اتصالك بالإنترنت",
            )

    # ========================================================
    # الفحص الدوري (Health Check)
    # ========================================================
    def _schedule_health_check(self):
        Clock.schedule_interval(self._health_check, HEALTH_CHECK_INTERVAL)

    def _health_check(self, dt):
        """فحص دوري صامت — لا يُزعج المستخدم."""
        if self.is_scanning or not self.best_server:
            return
        thread = threading.Thread(target=self._silent_recheck, daemon=True)
        thread.start()

    def _silent_recheck(self):
        latency = self.scanner.scan_one(
            next((s for s in SERVERS if s["name"] == self.best_server), SERVERS[0])
        )
        if latency is None:
            Clock.schedule_once(lambda dt: self._auto_switch(), 0)

    @mainthread
    def _auto_switch(self):
        """تبديل صامت — بدون إزعاج المستخدم."""
        if not self.is_scanning:
            self.start_scan()

    # ========================================================
    # حفظ/استرجاع الحالة
    # ========================================================
    def _save_state(self, server, latency):
        try:
            state = {
                "best_server": server,
                "latency": latency,
                "timestamp": datetime.now().isoformat(),
            }
            with open(STATE_FILE, "w") as f:
                json.dump(state, f)
        except Exception:
            pass

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return None


# ============================================================
# نقطة الدخول
# ============================================================
class SmartConnectApp(App):

    def build(self):
        self.title = APP_TITLE
        return MainScreen()

    def on_pause(self):
        return True

    def on_resume(self):
        pass


if __name__ == "__main__":
    SmartConnectApp().run()
