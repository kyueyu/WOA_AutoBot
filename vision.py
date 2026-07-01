# -*- coding: utf-8 -*-
"""
OpenCV 模板匹配混入：被 AdbController 与 MacNativeController 共享，
与具体的截图/触控后端解耦（只依赖 self.get_screenshot() 提供的 BGR 截图）。
"""

import cv2
import numpy as np

from core import read_image_safe


class VisionMixin:
    """模板缓存 + 模板匹配。宿主类需提供 get_screenshot()。"""

    _template_cache = {}
    _template_cache_max = 60  # 上限防止多开时内存无限制增长

    def _read_image_safe(self, path):
        return read_image_safe(path)

    def _cache_template(self, template_path, template):
        if len(self._template_cache) >= self._template_cache_max:
            oldest_key = next(iter(self._template_cache))
            del self._template_cache[oldest_key]
        self._template_cache[template_path] = template

    def _get_template(self, template_path):
        template = self._template_cache.get(template_path)
        if template is not None:
            return template
        template = self._read_image_safe(template_path)
        if template is None:
            return None
        self._cache_template(template_path, template)
        return template

    def locate_image(self, template_path, confidence=0.8, screen_image=None):
        screen = screen_image if screen_image is not None else self.get_screenshot()
        if screen is None:
            return None
        template = self._get_template(template_path)
        if template is None:
            return None
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < confidence:
            return None
        h, w = template.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2, (max_loc[0], max_loc[1], w, h))

    def locate_all_images(self, template_path, confidence=0.8, screen_image=None):
        screen = screen_image if screen_image is not None else self.get_screenshot()
        if screen is None:
            return []
        template = self._get_template(template_path)
        if template is None:
            return []
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        h, w = template.shape[:2]
        loc = np.where(result >= confidence)
        found_items = []
        for pt in zip(*loc[::-1]):
            score = result[pt[1], pt[0]]
            if self._merge_duplicate(found_items, pt, score, w, h):
                continue
            found_items.append({
                'box': (pt[0], pt[1], w, h),
                'top': pt[1],
                'center': (pt[0] + w // 2, pt[1] + h // 2),
                'score': score,
            })
        return found_items

    @staticmethod
    def _merge_duplicate(found_items, pt, score, w, h):
        for item in found_items:
            if abs(pt[0] - item['box'][0]) < 10 and abs(pt[1] - item['box'][1]) < 10:
                if score > item['score']:
                    item['score'] = score
                    item['box'] = (pt[0], pt[1], w, h)
                    item['top'] = pt[1]
                    item['center'] = (pt[0] + w // 2, pt[1] + h // 2)
                return True
        return False
