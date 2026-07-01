# -*- coding: utf-8 -*-
"""
macOS 合成鼠标输入：通过 Quartz CGEvent 在全局屏幕坐标（左上原点、点单位）投递点击/拖拽。
App Store iOS 应用会把鼠标事件翻译为触摸，需目标窗口为最前。
"""

import time

import Quartz

_LEFT = Quartz.kCGMouseButtonLeft


def _post(event_type, gx, gy, click_state=None):
    point = Quartz.CGPointMake(float(gx), float(gy))
    event = Quartz.CGEventCreateMouseEvent(None, event_type, point, _LEFT)
    if click_state is not None:
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, click_state)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def move(gx, gy):
    _post(Quartz.kCGEventMouseMoved, gx, gy)


def click(gx, gy, settle=0.02):
    _post(Quartz.kCGEventMouseMoved, gx, gy)
    _post(Quartz.kCGEventLeftMouseDown, gx, gy, click_state=1)
    time.sleep(settle)
    _post(Quartz.kCGEventLeftMouseUp, gx, gy, click_state=1)


def double_click(gx, gy, settle=0.02):
    _post(Quartz.kCGEventLeftMouseDown, gx, gy, click_state=1)
    time.sleep(settle)
    _post(Quartz.kCGEventLeftMouseUp, gx, gy, click_state=1)
    _post(Quartz.kCGEventLeftMouseDown, gx, gy, click_state=2)
    time.sleep(settle)
    _post(Quartz.kCGEventLeftMouseUp, gx, gy, click_state=2)


def drag(x1, y1, x2, y2, duration_ms=1000, steps=24):
    _post(Quartz.kCGEventLeftMouseDown, x1, y1, click_state=1)
    step_delay = max(0.0, (duration_ms / 1000.0) / max(1, steps))
    for i in range(1, steps + 1):
        t = i / steps
        gx = x1 + (x2 - x1) * t
        gy = y1 + (y2 - y1) * t
        _post(Quartz.kCGEventLeftMouseDragged, gx, gy)
        time.sleep(step_delay)
    _post(Quartz.kCGEventLeftMouseUp, x2, y2, click_state=1)
