# -*- coding: utf-8 -*-
"""把照片转成几何点阵图（半调网点），形状/密度/高光全部可控。

为什么不靠提示词：实测「every dot is a perfect circle」和「square block」两句指令
在同一 seed 下相关系数 0.9845、平均像素差仅 2.51%，模型等于没听。原因是扩散模型
画的是笔尖墨点（每点 2~4 像素），圆和方在这个尺度上不存在，也无法执行几何约束。
要真正的正圆/方块/菱形，得走图像处理——形状是画出来的，不是"求"出来的。

用法：
    python scripts/make_dot_matrix.py 输入图 输出图 --shape circle
    python scripts/make_dot_matrix.py in.jpg out.png --shape diamond --cell 10
    python scripts/make_dot_matrix.py in.jpg out.png --shape circle --white-at 200

形状：circle / square / diamond / triangle / hexagon / cross
"""
import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw


def load_gray(path, size=None):
    im = Image.open(path).convert("L")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def cell_gray(gray, cell):
    """把图像切成 cell×cell 的格子，返回每格平均灰度（0~255）。"""
    h, w = gray.shape
    gh, gw = h // cell, w // cell
    cropped = gray[:gh * cell, :gw * cell]
    return cropped.reshape(gh, cell, gw, cell).mean(axis=(1, 3))


def shape_radius(value, max_r, white_at, black_at):
    """格子灰度 -> 形状外接半径。越暗越大；超过 white_at 直接不画，低于 black_at 画满。"""
    if value >= white_at:
        return 0.0
    if value <= black_at:
        return max_r
    # 面积与暗度成正比（标准半调），暗度在 [0,1] 归一化
    t = (white_at - value) / max(white_at - black_at, 1e-6)
    return max_r * math.sqrt(min(max(t, 0.0), 1.0))


def draw_shape(draw, cx, cy, r, shape, angle):
    if r <= 0.2:
        return
    box = [cx - r, cy - r, cx + r, cy + r]
    if shape == "circle":
        draw.ellipse(box, fill=0)
    elif shape == "square":
        a = math.radians(angle)
        pts = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            px, py = sx * r, sy * r
            pts.append((cx + px * math.cos(a) - py * math.sin(a),
                        cy + px * math.sin(a) + py * math.cos(a)))
        draw.polygon(pts, fill=0)
    elif shape == "diamond":
        draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=0)
    elif shape == "triangle":
        draw.polygon([(cx, cy - r), (cx + r * 0.866, cy + r * 0.5),
                      (cx - r * 0.866, cy + r * 0.5)], fill=0)
    elif shape == "hexagon":
        pts = [(cx + r * math.cos(math.radians(60 * i - 30)),
                cy + r * math.sin(math.radians(60 * i - 30))) for i in range(6)]
        draw.polygon(pts, fill=0)
    elif shape == "cross":
        arm = r * 0.38
        draw.rectangle([cx - arm, cy - r, cx + arm, cy + r], fill=0)
        draw.rectangle([cx - r, cy - arm, cx + r, cy + arm], fill=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--shape", default="circle",
                    choices=["circle", "square", "diamond", "triangle", "hexagon", "cross"])
    ap.add_argument("--cell", type=int, default=9, help="网格边长（像素），越小越密")
    ap.add_argument("--max-ratio", type=float, default=0.96,
                    help="最深处的形状直径 / 网格边长，1.0 = 点挨在一起")
    ap.add_argument("--angle", type=float, default=0.0, help="方格/网格旋转角（度）")
    ap.add_argument("--white-at", type=float, default=235.0,
                    help="灰度高于此值的格子完全不画点（纯白）。调小 = 高光面积变大")
    ap.add_argument("--black-at", type=float, default=25.0,
                    help="灰度低于此值的格子画满（实黑）。调大 = 暗部更快成实块")
    ap.add_argument("--invert", action="store_true", help="深底白点")
    args = ap.parse_args()

    gray = load_gray(args.src)
    if args.invert:
        gray = 255.0 - gray
    cells = cell_gray(gray, args.cell)
    gh, gw = cells.shape

    out = Image.new("L", (gw * args.cell, gh * args.cell), 255)
    draw = ImageDraw.Draw(out)
    max_r = args.cell * args.max_ratio / 2.0
    pad = 2

    for gy in range(gh):
        for gx in range(gw):
            r = shape_radius(cells[gy, gx], max_r, args.white_at, args.black_at)
            if r > 0.2:
                # 留 pad 是为了旋转后的方格不被裁掉
                draw_shape(draw, gx * args.cell + args.cell / 2.0,
                           gy * args.cell + args.cell / 2.0,
                           min(r, max_r + pad), args.shape, args.angle)

    out = out.convert("1").convert("L")
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    out.save(args.dst)
    dark = (np.asarray(out) < 128).mean() * 100
    print(f"{args.shape:8s} cell={args.cell:2d} -> {args.dst}  "
          f"尺寸 {out.width}x{out.height}  墨点覆盖 {dark:.1f}%")


if __name__ == "__main__":
    main()
