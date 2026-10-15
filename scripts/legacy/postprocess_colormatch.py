# -*- coding: utf-8 -*-
"""背景层后处理：LAB 颜色迁移(向原图掩膜外统计对齐) + 羽化合成
用法: python postprocess_colormatch.py <raw_gen.png> <mask.png> <orig.png> <out.png> [sigma]
"""
import sys
import numpy as np
from PIL import Image

def srgb_to_lab(img):
    c = img / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)

def lab_to_srgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    def finv(f):
        return np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787)
    xyz = np.stack([finv(fx), finv(fy), finv(fz)], axis=-1) * np.array([0.95047, 1.0, 1.08883])
    Mi = np.linalg.inv(np.array([[0.4124564, 0.3575761, 0.1804375],
                                 [0.2126729, 0.7151522, 0.0721750],
                                 [0.0193339, 0.1191920, 0.9503041]]))
    c = xyz @ Mi.T
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)
    return np.clip(c * 255, 0, 255)

def blur2d(m, sigma):
    k = int(sigma * 3) * 2 + 1
    ax = np.arange(k) - k // 2
    g = np.exp(-ax ** 2 / (2 * sigma ** 2)); g /= g.sum()
    mm = np.apply_along_axis(lambda v: np.convolve(v, g, mode='same'), 0, m)
    mm = np.apply_along_axis(lambda v: np.convolve(v, g, mode='same'), 1, m)
    return mm

def main():
    raw_p, mask_p, orig_p, out_p = sys.argv[1:5]
    sigma = float(sys.argv[5]) if len(sys.argv) > 5 else 3.0
    raw = np.asarray(Image.open(raw_p).convert("RGB"), dtype=np.float32)
    mask = np.asarray(Image.open(mask_p).convert("L"), dtype=np.float32) / 255.0
    orig = np.asarray(Image.open(orig_p).convert("RGB").resize((raw.shape[1], raw.shape[0])), dtype=np.float32)
    if mask.shape[:2] != raw.shape[:2]:
        mask = np.asarray(Image.open(mask_p).convert("L").resize((raw.shape[1], raw.shape[0])), dtype=np.float32) / 255.0

    lab = srgb_to_lab(raw)
    lab_t = srgb_to_lab(orig)
    outside = mask < 0.1
    for c in range(3):
        s, d = lab[..., c], lab_t[..., c]
        lab[..., c] = (s - s[outside].mean()) * (d[outside].std() + 1e-6) / (s[outside].std() + 1e-6) + d[outside].mean()
    matched = lab_to_srgb(lab)

    m = blur2d(np.stack([mask] * 3, -1), sigma)
    final = matched * m + orig * (1 - m)
    Image.fromarray(final.astype(np.uint8)).save(out_p)
    print("saved:", out_p)

if __name__ == "__main__":
    main()
