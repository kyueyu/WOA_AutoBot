# -*- coding: utf-8 -*-
"""
macOS 原生控制后端：以 AdbController 相同的接口驱动原生 WOA 窗口
（屏幕截图 + 合成鼠标），让 WoaBot 无改动复用。坐标契约与 AdbController 一致：
WoaBot 在 1600×900 logical 空间出坐标，本类负责 logical→窗口像素→全局屏幕点的换算。
"""

import json
import os
import random
import time

import cv2

from core import get_app_data_dir, read_image_safe
from vision import VisionMixin
import mac_window
import mac_input

CALIBRATION_FILE = "mac_calibration.json"
_ICON_SEG = os.sep + "icon" + os.sep
_ICON_MAC_SEG = os.sep + "icon_mac" + os.sep


class MacNativeController(VisionMixin):
    LOGICAL_WIDTH = 1600
    LOGICAL_HEIGHT = 900

    def __init__(self, target_window=None, instance_id=1, **_ignored):
        self.instance_id = instance_id
        self.screenshot_method = "mac_native"
        self.control_method = "mac_native"
        self._desired_screenshot_method = "mac_native"
        self._desired_control_method = "mac_native"
        self._window = target_window
        self._scale = 1.0
        self._raw_screen_w = self.LOGICAL_WIDTH
        self._raw_screen_h = self.LOGICAL_HEIGHT
        self.default_click_jitter = 0.0
        self._think_min = 0.0
        self._think_max = 0.0
        self._content_rect = None  # (x, y, w, h)，截图像素空间内的游戏内容区
        self._screenshot_cache = None
        self._screenshot_cache_ts = 0.0
        self._load_calibration()

    # ─── 校准档案 ───────────────────────────────────────
    def _calibration_path(self):
        return os.path.join(get_app_data_dir(), CALIBRATION_FILE)

    def _load_calibration(self):
        path = self._calibration_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        rect = data.get("content_rect")
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            self._content_rect = tuple(int(v) for v in rect)

    # ─── 思考 / 抖动（与 AdbController 对齐）──────────────
    def set_thinking_strategy(self, min_s, max_s):
        self._think_min = max(0.0, float(min_s))
        self._think_max = max(self._think_min, float(max_s))

    def _do_think(self):
        if self._think_max <= 0:
            return
        time.sleep(random.uniform(self._think_min, self._think_max))

    def _read_image_safe(self, path):
        # Mac 覆盖层：若 icon_mac/ 下存在同名模板（文字类需重拍），优先使用；否则复用 icon/。
        if _ICON_SEG in path:
            override = path.replace(_ICON_SEG, _ICON_MAC_SEG)
            if os.path.exists(override):
                return read_image_safe(override)
        return read_image_safe(path)

    def _apply_coordinate_jitter(self, x, y, jitter):
        if jitter <= 0:
            return x, y
        return x + random.uniform(-jitter, jitter), y + random.uniform(-jitter, jitter)

    # ─── ADB 兼容空实现 ─────────────────────────────────
    def set_control_method(self, method, _is_fallback=False):
        pass

    def set_screenshot_method(self, method, _is_fallback=False):
        pass

    def set_mumu_path(self, path):
        pass

    def set_nemu_folder_callback(self, cb):
        pass

    def _start_persistent_shell(self):
        return True

    def run_all_method_tests(self):
        return {"mac_native": self.ensure_methods_usable()}

    # ─── 生命周期 ───────────────────────────────────────
    def connect(self):
        if self._window is None:
            self._window = mac_window.find_woa_window()
        if self._window is None:
            return False
        mac_window.activate_window(self._window)
        return True

    def ensure_methods_usable(self):
        usable = True
        if not mac_window.has_screen_recording_permission():
            usable = False
        elif self._window is None and not self.connect():
            usable = False
        elif mac_window.capture_window(self._window)[0] is None:
            usable = False
        return {"usable": usable, "repaired": False}

    def close(self):
        try:
            self._template_cache.clear()
        except Exception:
            pass
        self._window = None

    # ─── 分辨率换算（与 AdbController 对齐）──────────────
    def _normalize_to_logical_resolution(self, img):
        # 等比缩放到宽 1600（保持 4:3，不拉伸），使现有模板在原始尺度匹配。
        if img is None:
            return None
        h, w = img.shape[:2]
        self._raw_screen_w = int(w)
        self._raw_screen_h = int(h)
        if w == self.LOGICAL_WIDTH:
            self.LOGICAL_HEIGHT = int(h)
            return img
        scale = self.LOGICAL_WIDTH / float(w)
        target_h = int(round(h * scale))
        self.LOGICAL_HEIGHT = target_h
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        return cv2.resize(img, (self.LOGICAL_WIDTH, target_h), interpolation=interp)

    def _logical_to_device_point(self, x, y):
        rw = max(1, int(self._raw_screen_w))
        rh = max(1, int(self._raw_screen_h))
        dx = int(round(float(x) * rw / self.LOGICAL_WIDTH))
        dy = int(round(float(y) * rh / self.LOGICAL_HEIGHT))
        dx = max(0, min(rw - 1, dx))
        dy = max(0, min(rh - 1, dy))
        return dx, dy

    def get_resolution_info(self):
        return {
            "logical": (self.LOGICAL_WIDTH, self.LOGICAL_HEIGHT),
            "raw": (int(self._raw_screen_w), int(self._raw_screen_h)),
        }

    # ─── 截图 ───────────────────────────────────────────
    def _refresh_window(self):
        if self._window is None:
            return self.connect()
        latest = mac_window.get_window_by_id(self._window["id"])
        if latest is None:
            self._window = mac_window.find_woa_window()
            return self._window is not None
        self._window = latest
        return True

    def get_screenshot(self, force_method=None):
        if not self._refresh_window():
            return None
        img, scale = mac_window.capture_window(self._window)
        if img is None:
            return None
        self._scale = scale if scale > 0 else 1.0
        if self._content_rect is not None:
            x, y, w, h = self._content_rect
            img = img[y:y + h, x:x + w]
            if img.size == 0:
                return None
        return self._normalize_to_logical_resolution(img)

    def get_screenshot_cached(self, max_age_ms=50):
        now = time.time()
        if self._screenshot_cache is not None and (now - self._screenshot_cache_ts) * 1000 < max_age_ms:
            return self._screenshot_cache
        img = self.get_screenshot()
        if img is not None:
            self._screenshot_cache = img
            self._screenshot_cache_ts = now
        return img

    def invalidate_screenshot_cache(self):
        self._screenshot_cache = None
        self._screenshot_cache_ts = 0.0

    def get_pixel_color(self, x, y):
        screen = self.get_screenshot()
        if screen is None:
            return None
        try:
            b, g, r = screen[y, x]
            return int(b), int(g), int(r)
        except (IndexError, ValueError):
            return None

    # ─── 坐标映射：设备/截图像素 → 全局屏幕点（左上原点、点单位）──
    def _device_to_global(self, dev_x, dev_y):
        bounds = self._window["bounds"]
        ox, oy = (self._content_rect[0], self._content_rect[1]) if self._content_rect else (0, 0)
        gx = bounds["x"] + (ox + dev_x) / self._scale
        gy = bounds["y"] + (oy + dev_y) / self._scale
        return gx, gy

    # ─── 输入 ───────────────────────────────────────────
    def _ensure_on_top(self, gx, gy):
        # 合成点击会落在该点最上层的窗口上：与其它窗口(Claude/GUI/终端)共屏被盖住时，先激活 WOA；仍被盖住则放弃本次输入
        pid = self._window.get("pid")
        if mac_window.owner_pid_at(gx, gy) == pid:
            return True
        mac_window.activate_window(self._window)
        deadline = time.time() + 1.5
        while time.time() < deadline:
            time.sleep(0.05)
            if mac_window.owner_pid_at(gx, gy) == pid:
                return True
        print(f">>> [Mac] WOA 窗口在 ({gx:.0f},{gy:.0f}) 被其它窗口遮挡，已跳过本次点击")
        return False

    def click(self, x, y, random_offset=5):
        self._do_think()
        jitter = max(float(random_offset), float(self.default_click_jitter))
        x, y = self._apply_coordinate_jitter(x, y, jitter)
        dev_x, dev_y = self._logical_to_device_point(int(round(x)), int(round(y)))
        self._adb_click_fallback(dev_x, dev_y)

    def _adb_click_fallback(self, dev_x, dev_y):
        if self._window is None:
            return
        gx, gy = self._device_to_global(dev_x, dev_y)
        if not self._ensure_on_top(gx, gy):
            return
        mac_input.click(gx, gy)
        self.invalidate_screenshot_cache()

    def double_click(self, x, y, random_offset=20):
        if self._window is None:
            return
        x, y = self._apply_coordinate_jitter(x, y, float(random_offset))
        dev_x, dev_y = self._logical_to_device_point(int(round(x)), int(round(y)))
        gx, gy = self._device_to_global(dev_x, dev_y)
        if not self._ensure_on_top(gx, gy):
            return
        mac_input.double_click(gx, gy)
        self.invalidate_screenshot_cache()

    def swipe(self, x1, y1, x2, y2, duration_ms=1000):
        self._do_think()
        if self._window is None:
            return
        g1 = self._device_to_global(*self._logical_to_device_point(x1, y1))
        g2 = self._device_to_global(*self._logical_to_device_point(x2, y2))
        if not (self._ensure_on_top(*g1) and self._ensure_on_top(*g2)):
            return
        mac_input.drag(g1[0], g1[1], g2[0], g2[1], duration_ms=duration_ms)
        self.invalidate_screenshot_cache()

    @staticmethod
    def scan_windows():
        return mac_window.list_windows(name_filter=True)
