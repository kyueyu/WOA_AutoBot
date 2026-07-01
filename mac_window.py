# -*- coding: utf-8 -*-
"""
macOS 原生窗口层：发现 WOA 窗口、截图、激活、权限预检。
仅依赖 PyObjC (Quartz/AppKit) + numpy/cv2，供 MacNativeController 与校准工具复用。
"""

import sys

import numpy as np
import cv2

import Quartz
import AppKit
from ApplicationServices import AXIsProcessTrusted

WOA_NAME_HINTS = ("world of airports", "worldofairports")


class MacWindowError(RuntimeError):
    pass


def _require_mac():
    if sys.platform != "darwin":
        raise MacWindowError("mac_window 仅支持 macOS")


def has_screen_recording_permission():
    """无副作用地检查屏幕录制权限。"""
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def request_screen_recording_permission():
    """触发系统屏幕录制授权弹窗（首次调用会提示用户）。"""
    return bool(Quartz.CGRequestScreenCaptureAccess())


def has_accessibility_permission():
    """检查辅助功能权限（合成鼠标事件需要）。"""
    return bool(AXIsProcessTrusted())


def request_accessibility_permission():
    """触发辅助功能授权弹窗。"""
    from HIServices import AXIsProcessTrustedWithOptions
    options = {"AXTrustedCheckOptionPrompt": True}
    return bool(AXIsProcessTrustedWithOptions(options))


def _window_matches(info):
    owner = (info.get(Quartz.kCGWindowOwnerName) or "").lower()
    name = (info.get(Quartz.kCGWindowName) or "").lower()
    haystack = f"{owner} {name}"
    return any(hint in haystack for hint in WOA_NAME_HINTS)


def _bounds_dict_to_rect(bounds):
    return {
        "x": float(bounds.get("X", 0.0)),
        "y": float(bounds.get("Y", 0.0)),
        "w": float(bounds.get("Width", 0.0)),
        "h": float(bounds.get("Height", 0.0)),
    }


def list_windows(name_filter=True):
    """返回当前屏上窗口列表，每项 dict: id, owner, name, pid, layer, bounds(x,y,w,h)。"""
    _require_mac()
    options = (Quartz.kCGWindowListOptionOnScreenOnly
               | Quartz.kCGWindowListExcludeDesktopElements)
    raw = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    windows = []
    for info in raw:
        if name_filter and not _window_matches(info):
            continue
        bounds = info.get(Quartz.kCGWindowBounds) or {}
        windows.append({
            "id": int(info.get(Quartz.kCGWindowNumber, 0)),
            "owner": info.get(Quartz.kCGWindowOwnerName) or "",
            "name": info.get(Quartz.kCGWindowName) or "",
            "pid": int(info.get(Quartz.kCGWindowOwnerPID, 0)),
            "layer": int(info.get(Quartz.kCGWindowLayer, 0)),
            "bounds": _bounds_dict_to_rect(bounds),
        })
    return windows


def find_woa_window():
    """返回最可能的 WOA 窗口（面积最大、layer 0），找不到返回 None。"""
    candidates = [w for w in list_windows(name_filter=True) if w["layer"] == 0]
    if not candidates:
        return None
    return max(candidates, key=lambda w: w["bounds"]["w"] * w["bounds"]["h"])


def get_window_by_id(window_id):
    """按窗口 id 重新查询（用于刷新窗口位置/尺寸），找不到返回 None。"""
    for window in list_windows(name_filter=False):
        if window["id"] == window_id:
            return window
    return None


def activate_window(window):
    """将目标 app 置于最前（合成输入要求 App Store iOS 应用为最前窗口）。"""
    pid = window.get("pid", 0)
    if not pid:
        return False
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        return False
    return bool(app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps))


def _cgimage_to_bgr(cgimage):
    """CGImage -> OpenCV BGR ndarray，经 NSBitmapImageRep 走 PNG 编解码以规避步幅/格式问题。"""
    if cgimage is None:
        return None
    rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(cgimage)
    if rep is None:
        return None
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    if png is None:
        return None
    arr = np.frombuffer(bytes(png), dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def capture_window(window):
    """
    截取指定窗口当前画面，返回 (img_bgr, scale)。
    scale = 像素宽 / 点宽（Retina 通常为 2.0），供输入坐标换算。
    失败返回 (None, 1.0)。
    """
    _require_mac()
    window_id = window["id"]
    cgimage = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution,
    )
    img = _cgimage_to_bgr(cgimage)
    if img is None:
        return None, 1.0
    bounds_w = max(1.0, window["bounds"]["w"])
    scale = img.shape[1] / bounds_w
    return img, scale
