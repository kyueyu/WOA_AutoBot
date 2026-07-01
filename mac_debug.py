# -*- coding: utf-8 -*-
"""
Mac 原生后端冒烟测试（WS0 验收门）。
用法:
  python mac_debug.py                 # 检查权限 + 发现窗口 + 截图存盘
  python mac_debug.py --center        # 截图后向窗口中心投递一次点击（观察 WOA 是否响应）
  python mac_debug.py --click 800 450 # 向内容坐标(px)投递一次点击
  python mac_debug.py --match icon/setting.png  # 在截图中做一次模板匹配往返
"""

import argparse
import os
import sys
import time

import cv2

import mac_window
import mac_input


def _content_to_global(window, scale, cx, cy):
    bx = window["bounds"]["x"]
    by = window["bounds"]["y"]
    return bx + cx / scale, by + cy / scale


def _check_permissions():
    sr = mac_window.has_screen_recording_permission()
    ax = mac_window.has_accessibility_permission()
    print(f"屏幕录制权限: {'✅' if sr else '❌'}    辅助功能权限: {'✅' if ax else '❌'}")
    if not sr:
        print("→ 触发屏幕录制授权弹窗，请在系统设置中勾选后重新运行。")
        mac_window.request_screen_recording_permission()
    if not ax:
        print("→ 触发辅助功能授权弹窗，请在系统设置中勾选后重新运行。")
        mac_window.request_accessibility_permission()
    return sr, ax


def _run_controller_check(args, sr, ax):
    from mac_native_controller import MacNativeController
    controller = MacNativeController()
    if not controller.connect():
        print("❌ MacNativeController.connect() 未找到 WOA 窗口"); return 2
    b = controller._window["bounds"]
    print(f"已连接窗口 id={controller._window['id']} owner='{controller._window['owner']}' "
          f"bounds=({int(b['x'])},{int(b['y'])} {int(b['w'])}x{int(b['h'])})")
    if not sr:
        print("缺少屏幕录制权限，授权后重试。"); return 3

    screen = controller.get_screenshot()
    if screen is None:
        print("❌ controller.get_screenshot() 返回 None"); return 4
    print(f"✅ get_screenshot 归一化 size={screen.shape[1]}x{screen.shape[0]} "
          f"(应为 1600x900) raw={controller.get_resolution_info()['raw']} scale={controller._scale:.2f}")
    cv2.imwrite(args.out, screen)
    print(f"   已保存: {os.path.abspath(args.out)}")

    if args.click_logical:
        if not ax:
            print("缺少辅助功能权限，授权后重试。"); return 5
        lx, ly = args.click_logical
        print(f"3 秒后通过 controller.click 点击 logical=({lx:.0f},{ly:.0f})，确保 WOA 最前 ...")
        mac_window.activate_window(controller._window)
        time.sleep(3.0)
        controller.click(lx, ly, random_offset=0)
        print("✅ 已通过 MacNativeController.click 投递点击，观察 WOA 响应。")
    return 0


def main():
    if sys.platform != "darwin":
        print("仅支持 macOS"); return 1

    parser = argparse.ArgumentParser()
    parser.add_argument("--center", action="store_true", help="点击窗口中心")
    parser.add_argument("--click", nargs=2, type=float, metavar=("X", "Y"), help="点击内容坐标(px)")
    parser.add_argument("--match", metavar="TEMPLATE", help="对截图做一次模板匹配")
    parser.add_argument("--out", default="mac_debug_capture.png", help="截图输出路径")
    parser.add_argument("--controller", action="store_true",
                        help="用 MacNativeController 跑端到端（WoaBot 实际路径）")
    parser.add_argument("--click-logical", nargs=2, type=float, metavar=("X", "Y"),
                        help="配合 --controller：以 logical(1600×900) 坐标点击")
    args = parser.parse_args()

    sr, ax = _check_permissions()

    if args.controller:
        return _run_controller_check(args, sr, ax)

    windows = mac_window.list_windows(name_filter=True)
    if not windows:
        print("⚠️ 未发现 WOA 窗口（按名称匹配）。下面列出全部窗口供识别：")
        for w in mac_window.list_windows(name_filter=False):
            b = w["bounds"]
            print(f"  id={w['id']:<7} layer={w['layer']:<3} {w['owner'][:22]:<22} "
                  f"{int(b['w'])}x{int(b['h'])}  '{w['name'][:30]}'")
        return 2

    window = mac_window.find_woa_window() or windows[0]
    b = window["bounds"]
    print(f"目标窗口: id={window['id']} owner='{window['owner']}' "
          f"bounds=({int(b['x'])},{int(b['y'])} {int(b['w'])}x{int(b['h'])})")

    if not sr:
        print("缺少屏幕录制权限，无法截图，授权后重试。"); return 3

    img, scale = mac_window.capture_window(window)
    if img is None:
        print("❌ 截图失败：CGWindowListCreateImage 返回空（可能需改用 ScreenCaptureKit）。"); return 4
    print(f"✅ 截图成功 size={img.shape[1]}x{img.shape[0]} scale={scale:.2f}")
    cv2.imwrite(args.out, img)
    print(f"   已保存: {os.path.abspath(args.out)}")

    if args.match:
        tpl = cv2.imread(args.match, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"⚠️ 模板读取失败: {args.match}")
        else:
            res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            print(f"模板匹配 '{args.match}': 置信度={max_val:.3f} 位置={max_loc}")

    target = None
    if args.center:
        target = (b["w"] * scale / 2.0, b["h"] * scale / 2.0)
    elif args.click:
        target = (args.click[0], args.click[1])

    if target is not None:
        if not ax:
            print("缺少辅助功能权限，无法投递点击，授权后重试。"); return 5
        gx, gy = _content_to_global(window, scale, target[0], target[1])
        print(f"3 秒后点击 内容px=({target[0]:.0f},{target[1]:.0f}) -> 屏幕点=({gx:.0f},{gy:.0f})")
        print("请确保 WOA 窗口可见且最前 ...")
        mac_window.activate_window(window)
        time.sleep(3.0)
        mac_input.click(gx, gy)
        print("✅ 已投递点击，观察 WOA 是否响应。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
