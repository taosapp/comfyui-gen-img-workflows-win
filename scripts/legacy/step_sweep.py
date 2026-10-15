# -*- coding: utf-8 -*-
"""步数扫描：同一张图、同一提示词、同一种子，只改 KSampler 的 steps，量化质量与耗时。

用途：判断「减少采样步数」这个零成本杠杆能省多少、掉多少质量。
质量用与参考步数输出的像素差 + 结构差衡量，并拼一张对照图供人眼复核。

用法: python step_sweep.py [workflow.json] [--steps 20,15,12,10,8]
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "legacy"))
import run_workflow_json as R  # noqa: E402

LOG = os.path.join(ROOT, "_verify", "console.log")
OUT = os.path.join(ROOT, "output")


def log_size():
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def tail_new(start):
    with open(LOG, "rb") as f:
        f.seek(start)
        return f.read().decode("utf-8", "replace")


def sampler_wall(text):
    ms = re.findall(r"(\d+)/\1 \[(\d+):(\d+)<", text)
    if not ms:
        return None
    _, mm, ss = ms[-1]
    return int(mm) * 60 + int(ss)


def run_once(base, steps, seed, image, prefix):
    p = json.loads(json.dumps(base))
    p["6"]["inputs"]["steps"] = steps
    p["6"]["inputs"]["seed"] = seed
    p["4"]["inputs"]["image"] = image
    p["8"]["inputs"]["filename_prefix"] = prefix
    off = log_size()
    t0 = time.perf_counter()
    res = R.http_json("/prompt", {"prompt": p, "client_id": "sweep"})
    if "prompt_id" not in res:
        print(f"  提交失败: {json.dumps(res, ensure_ascii=False)[:400]}")
        return None
    pid = res["prompt_id"]
    while True:
        h = R.http_json(f"/history/{pid}")
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                if st.get("status_str") == "error":
                    print(f"  执行报错: {json.dumps(st, ensure_ascii=False)[:400]}")
                    return None
                break
        time.sleep(2)
    wall = time.perf_counter() - t0
    time.sleep(1.5)
    new = tail_new(off)
    sw = sampler_wall(new)
    files = []
    for nid, o in h[pid].get("outputs", {}).items():
        for im in o.get("images", []):
            files.append(os.path.join(OUT, im.get("subfolder", ""), im["filename"]))
    print(f"  steps={steps:<3} 总耗时={wall:6.1f}s  采样={str(sw)+'s':>7}  {str(round(sw / max(steps - 1, 1), 2) if sw else '-'):>7}s/it")
    return wall, sw, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", nargs="?", default=os.path.join(ROOT, "workflows", "图片风格转换.json"))
    ap.add_argument("--steps", default="20,15,12,10,8")
    ap.add_argument("--seed", type=int, default=424242)
    ap.add_argument("--image", default="style_test_scene.png")
    args = ap.parse_args()

    from PIL import Image
    import numpy as np

    src = os.path.join(ROOT, "input", args.image)
    with Image.open(src) as im:
        print(f"素材: {args.image}  {im.size[0]}x{im.size[1]}")

    wf = json.load(open(args.workflow, encoding="utf-8"))
    obj = R.http_json("/object_info", timeout=300)
    base, warns = R.to_api(wf, obj)
    print("转换警告:", [w for w in warns if "隐藏控件" not in w] or "无")

    steps_list = [int(s) for s in args.steps.split(",")]
    results = []
    print("开始扫描 ...")
    for s in steps_list:
        r = run_once(base, s, args.seed, args.image, f"stepsweep_{s:02d}")
        if r:
            results.append((s, r[0], r[1], r[2]))

    if len(results) < 2:
        print("有效数据不足")
        return 1

    # 取步数最多的那次作参考
    ref_steps, _, _, ref_files = max(results, key=lambda z: z[0])
    ref = np.asarray(Image.open(ref_files[0]).convert("RGB")).astype(np.int16)
    print()
    print("=" * 74)
    print(f"参考 = steps {ref_steps}（{ref.shape[1]}x{ref.shape[0]}）")
    print(f"{'步数':<6}{'总耗时':>9}{'采样':>8}{'相对参考耗时':>13}{'平均像素差':>12}{'差>8占比':>10}")
    thumbs = []
    for s, wall, sw, files in results:
        img = np.asarray(Image.open(files[0]).convert("RGB")).astype(np.int16)
        if img.shape != ref.shape:
            print(f"{s:<6} 尺寸不一致，跳过比较")
            continue
        d = np.abs(img - ref).max(axis=2)
        slow = [r for r in results if r[0] == ref_steps][0]
        ratio = wall / slow[1] if slow[1] else 0
        print(f"{s:<6}{wall:>8.1f}s{str(sw)+'s':>8}{ratio*100:>12.0f}%{d.mean():>12.2f}{100*(d>8).mean():>9.2f}%")
        thumbs.append((s, files[0]))

    # 拼对照图
    sheet = []
    for s, f in thumbs:
        im = Image.open(f).convert("RGB")
        im.thumbnail((520, 520))
        sheet.append((s, im))
    if sheet:
        w = sum(im.size[0] for _, im in sheet)
        h = max(im.size[1] for _, im in sheet) + 26
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        x = 0
        try:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
        except Exception:
            draw = None
        for s, im in sheet:
            canvas.paste(im, (x, 26))
            if draw:
                draw.text((x + 6, 6), f"steps={s}", fill=(0, 0, 0))
            x += im.size[0]
        path = os.path.join(OUT, "stepsweep_compare.png")
        canvas.save(path)
        print(f"\n对照图: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
