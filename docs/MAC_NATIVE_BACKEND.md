# macOS 原生后端 / macOS Native Backend

> 面向贡献者的技术说明 · Contributor-facing technical guide
> 让 WOA AutoBot 直接操控 **Mac 原生版《World of Airports》**（App Store「Designed for iPad」应用），无需安卓模拟器与 ADB。

---

## 1. 概览 / Overview

WOA AutoBot 最初只支持在**安卓模拟器**里、通过 **ADB** 操控游戏。本后端新增了一条并行的 **macOS 原生**通路：

- **截图**：直接抓取 Mac 上 WOA 窗口的画面（Quartz `CGWindowListCreateImage`）。
- **输入**：用 `CGEvent` 合成鼠标事件（App Store 的 iOS 应用会把鼠标动作翻译成触摸）。
- **复用**：`WoaBot` 大脑、OpenCV 模板匹配、`SimpleOCR`、ttkbootstrap GUI **原样复用**，无需改动业务逻辑。

平台自动判定：macOS 上默认走原生后端，Windows 仍走 ADB。

---

## 2. 核心思想：可替换控制器 / Core idea: drop-in controller

`WoaBot`（`main_adb.py`）与「设备」之间只通过一个**很窄的接口**交互：

```
get_screenshot / click / swipe / double_click / get_pixel_color /
get_resolution_info / locate_image / set_thinking_strategy /
close / connect / ensure_methods_usable  (+ 若干 ADB 专用空实现)
```

OpenCV 模板/OCR 层本身与设备无关（只吃一张 BGR 截图 + 模板文件）。因此 Mac 支持 = **换一个控制器**：新增 `MacNativeController`，实现与 `AdbController` **完全相同的接口**，但底层改用 macOS 原生 I/O。大脑不变。

```
gui_launcher.py  (GUI，几乎复用)
   └─ 按平台选择后端 → 构造 WoaBot
        └─ WoaBot (main_adb.py，业务逻辑不变)
             └─ self.adb.*  ← 相同接口
                  ├─ AdbController         (Windows / 模拟器)
                  └─ MacNativeController    (macOS 原生)   ← 新增
```

后端在 `WoaBot` 内由 `set_backend()` 选择，控制器由 `_create_controller()` 构造（`main_adb.py:1304 / 1348`）。

---

## 3. 新增模块 / New modules

| 文件 File | 作用 Role |
|---|---|
| `mac_window.py` | WOA 窗口发现（`CGWindowListCopyWindowInfo`）、截图（`CGWindowListCreateImage` → BGR ndarray，经 `NSBitmapImageRep` 转 PNG 再 `cv2.imdecode`）、窗口置前、**TCC 权限**预检/申请（屏幕录制 + 辅助功能） |
| `mac_input.py` | 用 `CGEventCreateMouseEvent` + `CGEventPost` 在**全局屏幕坐标**投递 click / double-click / drag |
| `mac_native_controller.py` | `MacNativeController`——`AdbController` 的替身：截图归一化、坐标换算、输入、以及 `icon_mac/` 文字模板覆盖层 |
| `vision.py` | `VisionMixin`——从 `AdbController` 抽出的 OpenCV 模板匹配方法（`locate_image` / `locate_all_images` / 模板缓存），两个控制器共享，消除重复 |
| `mac_debug.py` | 独立**冒烟测试**：权限、窗口发现、截图、点击、控制器端到端 |
| `mac_calibrate.py` | **校准工具**：标定内容区 / 重拍模板到 `icon_mac/` / 点选坐标 |

---

## 4. 改动的文件 / Modified files

- **`main_adb.py`**（`WoaBot`）
  - `backend` 标志 + `set_backend()` + `_create_controller()`（后端选择接缝）
  - `_apply_mac_layout()`：Mac 布局下的坐标 / `REGION_*` 覆盖
  - `_build_icon_rois()`：从 `__init__` 抽出，`_apply_mac_layout` 后**重建** `ICON_ROIS`（否则仍是旧值——见 §5.4）
  - `_stand_action_mac()`：Mac 版地勤分配流程
  - `_mac_ground_service_hits()`：Mac 版「Doing」金色服务图标检测
  - `_load_task_templates()`：抽出任务模板加载
- **`gui_launcher.py`**：`Application.backend` 在 macOS 上为 `mac_native`；扫描列出 WOA 窗口而非 ADB 设备（`_list_woa_window_labels`）；`start_bot` 跳过 ADB 专有步骤、检查权限（`_ensure_mac_permissions`）、调用 `set_backend`
- **`adb_controller.py`**：`class AdbController(VisionMixin)`——模板方法上移至 `vision.py`
- **`simple_ocr.py`**：斜杠 `/` 单独放宽匹配阈值（见 §6 OCR）
- **`requirements.txt`**：pyobjc 三件套（带 `sys_platform == "darwin"` 标记）
- **`.gitignore`**：忽略 `mac_debug_capture.png`、`mac_calibration.json`

---

## 5. 工作原理 / How it works

### 5.1 截图与坐标模型 / Capture & coordinate model

`MacNativeController.get_screenshot()` 流程：

1. 定位 WOA 窗口 → `CGWindowListCreateImage` 抓原生画面。
2. 按 `mac_calibration.json` 里的 `content_rect` **裁掉 macOS 标题栏**（默认 `[0,30,1051,790]`）。
3. **归一化**（关键）。

> **⚠️ 关键坑：Mac 是 4:3，安卓参考是 16:9。**
> Mac（iPad）UI 是 **4:3**（窗口约 1051×790），而 `WoaBot` 的坐标是按安卓 **1600×900（16:9）** 写的。
> 最初把 4:3 **拉伸**到 1600×900 → 图标被水平拉扁 → 模板匹配只有 ~0.6，全线失配。
> 正确做法：**等比缩放到宽 1600**（→ 约 **1600×1203**），**不拉伸**。此时同一套游戏美术在**原始尺度**匹配（≈0.66× 只是窗口/参考的尺寸比）。

由此得到的坐标规律（贯穿整个 Mac 适配）：

- **x 坐标对齐**——两种布局宽度都是 1600，横向刻度一致。
- **y 坐标不同**——4:3 帧更高（1203 vs 900），元素纵向位置不同；顶栏锚定的坐标≈可用，底部/居中锚定的要下移。

所以 Mac 适配 = **复用模板** + 一组**有界的 y 坐标 / `REGION_*` 覆盖**（集中在 `_apply_mac_layout`），而非重写业务逻辑。

**输入换算**：`click(logical)` → `logical → 窗口像素 → 全局屏幕点`（考虑 Retina backing scale）→ `CGEvent`。`_device_to_global()` 负责最后一步。

### 5.2 模板策略（最重要的洞察）/ Template strategy (key insight)

- 游戏语言设为**简体中文**（这也是 bot 本来的要求）。
- 现有 **`icon/` 90 个模板可直接复用**：美术完全相同，只是 0.66× 尺度——**等比归一化后即可匹配**（0.85–0.96）。**无需大规模重拍。**
- 唯一例外：**文字类模板**（状态标题、按钮文案）在 Mac 上渲染略不同、个别文案也不同（如确认按钮 Android 是「确认」，Mac 是「选择停机位」），匹配分只有 ~0.5。
- 解决：**覆盖层**。`MacNativeController._read_image_safe()`（`mac_native_controller.py:72`）在读 `icon/<name>` 时，**若存在 `icon_mac/<name>` 则优先用它**，否则回退 `icon/`。重拍的**静态文字**模板匹配 ~1.0。

> 一句话：**图标复用 `icon/`，文字覆盖到 `icon_mac/`。**

### 5.3 权限 / Permissions

需要两项 TCC 授权（`mac_window.py` 预检/申请，GUI 启动前校验）：

- **屏幕录制 Screen Recording**（截图）
- **辅助功能 Accessibility**（合成鼠标事件）

限制：**仅前台**——App Store 的 iOS 应用要求 WOA 为最前窗口才能接收合成输入。

### 5.4 一个隐蔽的坑：ICON_ROIS 重建 / A subtle bug: rebuilding ICON_ROIS

`ICON_ROIS` 原本在 `__init__` 里用**安卓 `REGION_*` 的值**构造（值拷贝）。`_apply_mac_layout` 之后更新了 `REGION_BOTTOM_ROI` 等，但 `ICON_ROIS` 仍是旧值 → 所有走 `wait_and_click` 的底部按钮（起飞/后推/滑行/领奖/开始地勤…）都在**错误区域**里搜。
修复：抽出 `_build_icon_rois()`，在 `__init__` **和** `_apply_mac_layout` 末尾各调一次（用 Mac 区域重建）。

### 5.5 逐流程校准配方 / Per-flow calibration recipe

给贡献者补齐剩余流程的标准套路：

1. 让游戏进入该任务类型的界面（打开一架该类飞机）。
2. 抓一帧归一化截图，用**安卓模板的尺寸**、以其**弱匹配中心**为中心裁出对应区域：
   `crop = frame[cy-h//2 : cy-h//2+h, cx-w//2 : cx-w//2+w]`（`h,w = icon/<name> 尺寸`）。
3. 存到 `icon_mac/<name>.png`（静态文字 → 匹配 ~1.0）。
4. 若该流程用到底部/居中锚定的固定坐标或 ROI，在 `_apply_mac_layout` 里加 Mac 值。
5. 也可直接用 `mac_calibrate.py snip` 手动框选（同样存入 `icon_mac/`）。

---

## 6. 已打通的流程 / Working flows

| 流程 Flow | 说明 |
|---|---|
| **进场 Approach** | 复用 `status_approach`（重拍到 `icon_mac/`）；分配机位改为点击**检测到的** `stand_vacant` 位置（Mac 分支），不再用固定 (490,770) |
| **离场 Departure** | 「直接起飞」态：`status_takeoff`(离港) + `takeoff`(直接起飞) 重拍；`REGION_BOTTOM_ROI` 下移到面板底部金色按钮 |
| **停机位/地勤 Stand** | 滑块在 **y≈873**（非 574）；派完crew后按钮文案变 `指派地勤人员`→**`启动地面保障`**（即 `start_ground_support`）；`_stand_action_mac` 跳过 16:9 版脆弱的像素颜色/图标校验，靠 `insufficient_ground_staff` + 按钮判定 |
| **地勤人数 OCR Staff OCR** | `REGION_GLOBAL_STAFF` 正确框住顶栏「X/24」；数字能读、**斜杠**匹配 0.598 略低于 0.65 阈值 → 单独给斜杠更低阈值（`simple_ocr.py:120`，不与数字混淆、对安卓安全）→ 读出「9/24」→ 可用 = 总数−已用 |
| **Doing（服务派遣）** | WoA 3.6.0 需**逐个点击金色高亮**的服务图标（非结束按钮）。`_mac_ground_service_hits` 在 (380,1000)-(**1300**,1160) 带内做 HSV 金色圆形检测；面板左固定、随服务数向右生长（>6 个也覆盖，且避开 x≳1320 的任务列表）|

---

## 7. 环境与运行 / Setup & running

本机用 **conda**（miniforge3），环境名 `woa`，Python 3.12：

```bash
# 依赖：opencv-python、numpy、pyobjc 三件套，以及 requirements.txt
conda create -y -n woa python=3.12
conda run -n woa pip install -r requirements.txt
```

- **运行**：`python gui_launcher.py`（macOS 自动进入原生模式）→ 首次授权屏幕录制+辅助功能 → 「扫描」列出 WOA 窗口 → 选中 → 启动。
- **冒烟测试**：`python mac_debug.py [--controller] [--click-logical X Y]`
- **校准**：`python mac_calibrate.py content | snip | point | list`
  - `content`：拖框标定游戏内容区（排除标题栏）→ 写入 `mac_calibration.json`
  - `snip`：重拍模板 → 存入 `icon_mac/`（自动被覆盖层使用）
  - `point`：点选查看 logical 坐标 + 像素（推导 ROI/坐标）

---

## 8. 已知限制与待办 / Constraints & remaining work

**限制 Constraints**
- **仅前台**：WOA 必须是最前窗口才能接收输入。
- **不要同时开 GUI 和诊断脚本**：两个进程同时抓同一窗口会把 `CGWindowListCreateImage` 卡死（wedge）。诊断前先 `pkill -f gui_launcher.py`。
- 完整可用需**逐流程校准**（有界、可迭代——见 §5.5）。

**待办 Remaining**
- Doing 全部完成时的 **`地勤保障完成`** 领取按钮（文字模板，需在该状态出现时重拍）。
- 离场其它状态：**后推 `push_back`**、**滑行 `taxi_to_runway`**（需推出的飞机）。
- 领奖弹窗 `get_award_1..4`（`REGION_REWARD_RECOVERY` 已给 Mac 值，待验证）。
- 除冰/维修/塔台流程、花费 OCR（task 数字）。
- 打包：`WOA_AutoBot_mac.spec` 需补 pyobjc hiddenimports + `icon_mac` datas + Info.plist `NSScreenCaptureUsageDescription`。

---

## 9. 快速索引 / Quick reference

| 关注点 | 位置 |
|---|---|
| 后端选择 | `main_adb.py` `set_backend` / `_create_controller`；`gui_launcher.py:573` |
| Mac 坐标/ROI 覆盖 | `main_adb.py` `_apply_mac_layout` / `_build_icon_rois` |
| 截图归一化（等比 1600 宽） | `mac_native_controller.py` `_normalize_to_logical_resolution` |
| 文字模板覆盖层 | `mac_native_controller.py` `_read_image_safe`（`icon_mac/` 优先） |
| 原生截图/输入/权限 | `mac_window.py` / `mac_input.py` |
| 共享 OpenCV 匹配 | `vision.py` `VisionMixin` |
| 校准 / 冒烟 | `mac_calibrate.py` / `mac_debug.py` |
