# -*- coding: utf-8 -*-
"""老照片损伤掩膜生成器（配合「老照片轻修复」工作流使用）。

原理：用大窗口中值滤波估计"干净背景"，原图与背景的差异超过 k*标准差的像素
即划痕/污渍/斑点；再膨胀几像素盖住边缘光晕。输出白=损伤 的掩膜 PNG。

用法:
    python make_damage_mask.py <照片路径> [k=1.6] [膨胀=4]

输出:
    ComfyUI/input/<照片名>_damage_mask.png   （掩膜，直接在 LoadImageMask 里选它）
    同时打印推荐填入工作流 ImageScale 节点的宽 x 高（32 的倍数）。

依赖: numpy, scipy, Pillow（ComfyUI 环境自带）。
"""
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage


def round32(x):
    return max(32, int(round(x / 32)) * 32)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    k = float(sys.argv[2]) if len(sys.argv) > 2 else 1.6
    dilate = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    im = Image.open(src).convert("RGB")
    W, H = round32(im.width), round32(im.height)
    im = im.resize((W, H), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32)
    gray = arr @ np.array([0.299, 0.587, 0.114], np.float32)

    bg = ndimage.median_filter(gray, size=51)
    diff = gray - bg
    std = float(diff.std())
    mask = (diff > k * std) | (diff < -k * std)
    mask = ndimage.binary_dilation(mask, iterations=dilate)
    frac = mask.mean() * 100

    base = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "..", "..", "input", base + "_damage_mask.png")
    out = os.path.normpath(out)
    Image.fromarray((mask * 255).astype(np.uint8)).save(out)

    print("掩膜已保存: %s" % out)
    print("损伤覆盖率: %.1f%%   (k=%.1f, 膨胀=%d)" % (frac, k, dilate))
    print("请把工作流 ImageScale 节点填成: %d x %d" % (W, H))
    if frac > 45:
        print("提示: 覆盖率偏高（照片整体脏），把 k 调大到 1.8~2.0 可只保留最重的损伤。")
    elif frac < 8:
        print("提示: 覆盖率偏低，把 k 调小到 1.3~1.5 可多清一些污渍。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
