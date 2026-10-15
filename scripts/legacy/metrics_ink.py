# -*- coding: utf-8 -*-
"""彩墨画保真度指标（与 A~O 轮次同一套口径，便于横向比较）。

用法: python metrics_ink.py <结果图.png> [更多图.png ...]
对照基准固定为 input/5.jpg。

指标:
  结构保真  = 64×64 灰度皮尔逊相关（整体构图/轮廓）
  上半部色距 = 上半部平均 RGB 欧氏距离（山体固有色保持）
  纹理走向  = 上半部梯度方向直方图峰值角（0~180 无向；丹霞彩条 ~45° 为对）
  饱和度/明度 = 上半部 HSV 均值（对照平台成品 0.210/0.790、原照 0.377/0.798）
  纹理密度  = 上半部梯度均值（原照 0.067、平台成品 0.075）
"""
import sys
import numpy as np
from PIL import Image

ORIG = r"D:\ai\comfyui-img2img-workflows-nvidia-windows\input\5.jpg"


def gray64(path):
    return np.asarray(
        Image.open(path).convert("L").resize((64, 64), Image.LANCZOS), dtype=np.float64)


def upper(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    return np.asarray(im.crop((0, 0, w, h // 2)), dtype=np.float64)


def sat_val(a):
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return float(sat.mean()), float(mx.mean() / 255.0)


def orient_peak(a):
    g = a.mean(axis=2)
    gx = np.gradient(g, axis=1)
    gy = np.gradient(g, axis=0)
    ang = np.degrees(np.arctan2(gy, gx)) % 180.0
    mag = np.hypot(gx, gy)
    hist, _ = np.histogram(ang, bins=36, range=(0.0, 180.0), weights=mag)
    k = int(hist.argmax())
    return k * 5.0 + 2.5, float(np.hypot(gx, gy).mean())


def main():
    g0 = gray64(ORIG)
    g0c = g0 - g0.mean()
    u0 = upper(ORIG)
    c0 = u0.mean(axis=(0, 1))
    s0, v0 = sat_val(u0)
    o0, d0 = orient_peak(u0)
    print("原照 5.jpg: 饱和=%.3f 明度=%.3f 走向=%.0f° 纹理密度=%.3f" % (s0, v0, o0, d0))
    for path in sys.argv[1:]:
        g1 = gray64(path)
        g1c = g1 - g1.mean()
        corr = float((g0c * g1c).sum() /
                     np.sqrt((g0c ** 2).sum() * (g1c ** 2).sum()))
        u1 = upper(path)
        dist = float(np.sqrt(((c0 - u1.mean(axis=(0, 1))) ** 2).sum()))
        s1, v1 = sat_val(u1)
        o1, d1 = orient_peak(u1)
        name = path.replace("\\", "/").split("/")[-1]
        print("%-42s 结构=%.3f 色距=%5.1f 走向=%3.0f° 饱和=%.3f 明度=%.3f 纹理密度=%.3f"
              % (name, corr, dist, o1, s1, v1, d1))


if __name__ == "__main__":
    main()
