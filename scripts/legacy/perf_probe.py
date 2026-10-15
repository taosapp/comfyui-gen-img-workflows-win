"""一次性性能探针：把 图片风格转换 工作流转成 API 格式提交，测量各阶段耗时。
不写入项目文件，只读；产物写到 _perf/。
"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8188"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
)

PROMPT = ("Transform this image into a soft muted watercolor painting style with rich "
          "midtones and deep shadows, keeping the main subject and composition")
NEG = "overexposed, blown out highlights, washed out, faded, high key lighting, low contrast"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def build(variant, steps=20, use_cache=False, resolution=1024, image="1.jpg"):
    g = {
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "qwen-image-2.1-Q5_K_M.gguf"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors",
                         "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image}},
        "5": {"class_type": "TextEncodeQwenImage21",
              "inputs": {"clip": ["2", 0], "prompt": PROMPT, "negative_prompt": NEG,
                         "vae": ["3", 0], "resolution": resolution,
                         "images.image_1": ["4", 0]}},
    }
    model_src = ["1", 0]
    if use_cache:
        g["9"] = {"class_type": "QwenImage21Cache",
                  "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}}
        model_src = ["9", 0]

    if variant == "te":
        # 只跑到文本编码，量化文本编码器+VAE 编码的耗时
        g["90"] = {"class_type": "PreviewAny", "inputs": {"source": ["5", 0]}}
        return g

    g["6"] = {"class_type": "KSampler",
              "inputs": {"model": model_src, "positive": ["5", 0], "negative": ["5", 1],
                         "latent_image": ["5", 2], "seed": 42, "steps": steps, "cfg": 3.5,
                         "sampler_name": "euler", "scheduler": "beta", "denoise": 1.0}}
    g["7"] = {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}}
    g["8"] = {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": "perfprobe_" + variant}}
    return g


def run(variant, steps=20, use_cache=False, resolution=1024, image="1.jpg", label=None):
    g = build(variant, steps=steps, use_cache=use_cache, resolution=resolution, image=image)
    t0 = time.perf_counter()
    res = post("/prompt", {"prompt": g, "client_id": "perfprobe"})
    pid = res["prompt_id"]
    t_submit = time.perf_counter() - t0
    while True:
        h = get("/history/" + pid)
        if pid in h:
            break
        time.sleep(1.0)
    total = time.perf_counter() - t0
    entry = h[pid]
    st = entry.get("status", {})
    name = label or variant
    print(f"{name:14s} submit={t_submit:5.1f}s  total={total:7.1f}s  status={st.get('status_str')}")
    for m in st.get("messages", []):
        if m[0] in ("execution_error",):
            print("   ERROR:", json.dumps(m[1])[:400])
    return total


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    BUST = os.environ.get("BUST", "")      # 改动提示词以绕过节点结果缓存
    RES = int(os.environ.get("RES", "1024"))
    globals()["PROMPT"] = PROMPT + BUST
    if which in ("all", "te"):
        run("te", label="TE-only", resolution=RES)
    if which in ("all", "full"):
        run("full", steps=20, label="full-20step", resolution=RES)
    if which in ("all", "cache"):
        run("full", steps=20, use_cache=True, label="full-20+cache", resolution=RES)
    if which in ("all", "steps2"):
        run("full", steps=2, label="full-2step", resolution=RES)
    if which in ("all", "steps10"):
        run("full", steps=10, label="full-10step", resolution=RES)
