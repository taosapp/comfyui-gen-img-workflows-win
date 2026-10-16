# -*- coding: utf-8 -*-
"""实测 图片风格转换 工作流在 2:3 竖幅下各档resolution 能否跑通。

背景：用户想出 1080x1600（1.73MP）。源码算法
    width  = round(sqrt(res^2 * ratio) / 32) * 32
    height = round(sqrt(res^2 / ratio) / 32) * 32
ratio = 参考图宽/高。本机已有实测红线：resolution 1536 触发
`aimdo memory compile error` 直接崩服务，故按档位逐级试探，崩了就停。

用法：python scripts/legacy/probe_resolution.py [--start 1248]
不带参数则从 1024 逐级往上试，每档跑完检查服务是否还活着。
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

HOST = "http://127.0.0.1:8188"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PROMPT = ("把这张照片转换成水彩画风格，明亮通透的湿画法，"
          "白纸透出，笔触自然，保留原图构图与人物特征")

REF = "ref_test_scene.png"          # input/ 下，1024x576 横图；竖幅另指定
LORA = "qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors"
UNET = "qwen-image-2.1-Q5_K_M.gguf"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"


def alive():
    try:
        OP.open(HOST + "/system_stats", timeout=5).read()
        return True
    except Exception:
        return False


def graph(res, ref, tag):
    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "16": {"class_type": "LoraLoaderBypassModelOnly",
               "inputs": {"model": ["1", 0], "lora_name": LORA, "strength_model": 1.0}},
        "14": {"class_type": "QwenImage21Cache",
               "inputs": {"model": ["16", 0], "device": "auto", "dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": ref}},
        "5": {"class_type": "TextEncodeQwenImage21",
              "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": PROMPT,
                         "negative_prompt": "", "resolution": res,
                         "images.image_1": ["4", 0]}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["14", 0], "seed": 20261016, "steps": 8, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "beta", "denoise": 1.0,
                         "positive": ["5", 0], "negative": ["5", 1], "latent_image": ["5", 2]}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": "probe_res/" + tag}},
    }
    return g


def run(res, ref):
    from PIL import Image
    w, h = Image.open(os.path.join(ROOT, "input", ref)).size
    ratio = w / h
    ew = round(math.sqrt(res * res * ratio) / 32) * 32
    eh = round(math.sqrt(res * res / ratio) / 32) * 32

    tag = "res%d_%dx%d" % (res, ew, eh)
    print("→ resolution=%d  预期出图 %dx%d (%.2f MP)"
          % (res, ew, eh, ew * eh / 1e6), flush=True)

    t0 = time.time()
    try:
        req = urllib.request.Request(
            HOST + "/prompt",
            data=json.dumps({"prompt": graph(res, ref, tag)}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        pid = json.loads(OP.open(req, timeout=60).read().decode())["prompt_id"]
    except urllib.error.HTTPError as e:
        return res, ew, eh, "提交失败 HTTP %d" % e.code, 0.0, True

    while True:
        # 只有服务真的连不上才算崩溃；一次读不到 history 不能判定为死。
        if not alive():
            time.sleep(5)          # 给崩溃栈一点落地时间再复查
            if not alive():
                return res, ew, eh, "★ 服务已崩溃（aimdo memory compile error）", \
                    time.time() - t0, True
            continue
        try:
            h = json.loads(OP.open(HOST + "/history/" + pid, timeout=10).read().decode())
        except Exception:
            time.sleep(3)
            continue
        if pid in h:
            break
        time.sleep(3)

    el = time.time() - t0
    # 注意：必须先看 status_str 再取产物。节点 id 硬编码为 "8" 在
    # 缓存命中或执行中断时可能取不到 images 键，会被误判成"服务崩溃"。
    st = h[pid].get("status", {})
    status_str = st.get("status_str")
    if status_str != "success":
        return res, ew, eh, "执行状态=%s（服务仍在）" % status_str, el, False
    try:
        img = h[pid]["outputs"]["8"]["images"][0]
        return res, img["width"], img["height"], img["filename"], el, False
    except Exception as e:
        return res, ew, eh, "success 但取产物失败: %s" % e, el, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1024)
    ap.add_argument("--upto", type=int, default=1344)
    ap.add_argument("--step", type=int, default=64)
    ap.add_argument("--ref", default=REF)
    a = ap.parse_args()

    if not alive():
        print("ComfyUI 未启动，请先双击 start_comfyui.bat")
        sys.exit(1)

    print("服务在线，开始逐级试探（崩了就停并报告）\n")
    res = a.start
    while res <= a.upto:
        r, ew, eh, note, el, dead = run(res, a.ref)
        status = "失败" if dead else "OK"
        print("   %-6s %dx%d  %6.1fs  %s  [%s]\n" % (r, ew, eh, el, note, status), flush=True)
        if dead:
            print("★ 在 resolution=%d 处中断。上一个成功的档位就是本机上限。" % r)
            print("  要突破需给启动器加 --disable-dynamic-vram 关掉 aimdo 内存编译器。")
            break
        res += a.step
    else:
        print("全部档位跑通。")


if __name__ == "__main__":
    main()