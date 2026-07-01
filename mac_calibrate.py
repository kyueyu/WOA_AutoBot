# -*- coding: utf-8 -*-
"""
WOA Mac UI 校准工具（独立运行，配合 mac_native_controller）。

  python mac_calibrate.py content   # 标定游戏内容区 content_rect（排除标题栏）
  python mac_calibrate.py snip      # 重拍 Mac 模板到 icon_mac/
  python mac_calibrate.py point     # 点选查看 logical 坐标与像素（推导 ROI/坐标）
  python mac_calibrate.py list      # 列出现有 icon/ 模板（重拍清单）

content_rect 写入 app-data 的 mac_calibration.json，被 MacNativeController 读取。
"""

import argparse
import json
import os
import sys

import cv2

from core import get_app_data_dir, get_resource_path
import mac_window
from mac_native_controller import MacNativeController, CALIBRATION_FILE

MAC_ICON_DIR = "icon_mac"


def _calibration_path():
    return os.path.join(get_app_data_dir(), CALIBRATION_FILE)


def _load_calibration():
    path = _calibration_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_calibration(data):
    path = _calibration_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已写入 {path}")


def _capture_raw():
    window = mac_window.find_woa_window()
    if window is None:
        print("❌ 未找到 WOA 窗口"); return None, None
    mac_window.activate_window(window)
    img, _scale = mac_window.capture_window(window)
    if img is None:
        print("❌ 截图失败"); return None, None
    return img, window


def _normalized_frame():
    """返回 MacNativeController 实际喂给 WoaBot 的归一化 1600×900 帧。"""
    controller = MacNativeController()
    if not controller.connect():
        print("❌ 未找到 WOA 窗口"); return None
    if controller._content_rect is None:
        print("⚠️ 尚未标定 content_rect，将使用整窗(含标题栏)。建议先运行 content。")
    return controller.get_screenshot()


def _select_roi_scaled(title, img, max_w=1280, max_h=760):
    """缩放显示以适配屏幕后框选，返回原图分辨率下的 (x, y, w, h)。"""
    h, w = img.shape[:2]
    scale = min(1.0, max_w / w, max_h / h)
    disp = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img
    roi = cv2.selectROI(title, disp, showCrosshair=False)
    cv2.destroyAllWindows()
    x, y, rw, rh = (int(v) for v in roi)
    if 0 < scale < 1.0:
        x, y, rw, rh = int(x / scale), int(y / scale), int(rw / scale), int(rh / scale)
    return x, y, rw, rh


def mark_content_rect():
    img, window = _capture_raw()
    if img is None:
        return
    print("拖拽框选『游戏内容区』(排除顶部 macOS 标题栏)，回车确认，ESC 取消")
    x, y, w, h = _select_roi_scaled("content_rect (回车确认)", img)
    if w == 0 or h == 0:
        print("已取消"); return
    data = _load_calibration()
    data["content_rect"] = [x, y, w, h]
    data["window_bounds_at_calib"] = window["bounds"]
    _save_calibration(data)
    print(f"content_rect = {[x, y, w, h]} (raw px)")


def list_templates():
    icon_dir = get_resource_path("icon")
    names = []
    for root, _dirs, files in os.walk(icon_dir):
        for f in files:
            if f.lower().endswith(".png"):
                names.append(os.path.relpath(os.path.join(root, f), icon_dir))
    for n in sorted(names):
        print(" ", n)
    print(f"共 {len(names)} 个模板 (icon/)")
    return names


def _save_template(name, frame):
    if not name.lower().endswith(".png"):
        name += ".png"
    x, y, w, h = _select_roi_scaled(f"框选 {name} (回车保存)", frame)
    if w == 0 or h == 0:
        print("  跳过(空选)"); return
    out = os.path.join(MAC_ICON_DIR, name)
    subdir = os.path.dirname(out)
    if subdir:
        os.makedirs(subdir, exist_ok=True)
    cv2.imwrite(out, frame[y:y + h, x:x + w])
    print(f"  已保存 {out} ({w}x{h}) @ logical({x},{y})")


def snip_templates():
    os.makedirs(MAC_ICON_DIR, exist_ok=True)
    print("模板重拍：输入模板名(如 setting.png 或 digits/global/5.png)，空行结束")
    while True:
        name = input("模板名> ").strip()
        if not name:
            break
        frame = _normalized_frame()
        if frame is None:
            break
        _save_template(name, frame)


def pick_points():
    frame = _normalized_frame()
    if frame is None:
        return
    h, w = frame.shape[:2]
    scale = min(1.0, 1280 / w, 760 / h)
    disp = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame

    def on_mouse(event, mx, my, _flags, _param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        lx, ly = int(mx / scale), int(my / scale)
        b, g, r = frame[ly, lx]
        print(f"  logical=({lx},{ly})  BGR=({b},{g},{r})")

    title = "点选坐标 (q 退出)"
    cv2.namedWindow(title)
    cv2.setMouseCallback(title, on_mouse)
    print("点击查看 logical 坐标与像素；按 q 退出")
    while True:
        cv2.imshow(title, disp)
        if cv2.waitKey(20) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


def main():
    if sys.platform != "darwin":
        print("仅支持 macOS"); return 1
    parser = argparse.ArgumentParser(description="WOA Mac UI 校准工具")
    parser.add_argument("mode", nargs="?", default="content",
                        choices=["content", "snip", "point", "list"])
    args = parser.parse_args()
    {"content": mark_content_rect, "snip": snip_templates,
     "point": pick_points, "list": list_templates}[args.mode]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
