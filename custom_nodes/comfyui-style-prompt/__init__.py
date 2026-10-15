# -*- coding: utf-8 -*-
"""风格提示词节点（Style Prompt）。

给「图片风格转换」这类工作流提供统一的提示词入口：
    - 通用规则写在 ComfyUI 根目录 styles/ 的 .txt 风格库里（一条风格 = 一个文件）
    - 单张图片的个体信息写在节点界面的「describe」文本框里
节点输出两路 STRING（正向 / 负向），直接接进编码器；负向口恒为空串
（极速档 cfg 1.0 下负向不参与计算，2026-10-15 移除负向输入框）。
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
