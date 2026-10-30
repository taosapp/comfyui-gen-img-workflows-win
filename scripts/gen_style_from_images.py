# -*- coding: utf-8 -*-
"""从风格参考图反推提示词，生成 styles/ 下的风格文件。

用 ComfyUI 内置的 `TextGenerate` 节点 + 本项目已有的 Qwen3-VL-8B 文本编码器
（`comfy/text_encoders/qwen3vl.py` 里就有 `generate()`），不需要装任何插件、
不需要额外下载模型。

用法：
    1. 先启动 ComfyUI（start_comfyui.bat）
    2. 把参考图放进 input/style_refs/：
         - 子文件夹模式：input/style_refs/水墨/1.png、2.png  → 文件夹名即风格名
         - 平铺模式：    input/style_refs/水彩.png          → 文件名即风格名
    3. python scripts/gen_style_from_images.py            # 预览，不写文件
       python scripts/gen_style_from_images.py --write    # 真正写入 styles/

写入后浏览器 F5 就能在风格下拉框里看到。

设计取舍：
  - 一个风格只取**一张**参考图（子文件夹里按文件名排序取第一张）。多张图不做自动
    合并——合并要么再调一次模型、要么机械取交集，两条路都容易引入不属于该风格的词。
    需要更准就换一张更有代表性的图重跑。
  - 生成的是**草稿**：反推只看得见这张图，看不见项目约定（cfg 1.0、保真条款写法等），
    所以每个文件末尾都留了注释提示人工过一遍。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFS_DIR = os.path.join(ROOT, "input", "style_refs")
STYLES_DIR = os.path.join(ROOT, "styles")
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
# 项目现用的文本编码器，它的 generate() 就能当 LLM 用
ENCODER = "qwen3vl_8b_int8_convrot.safetensors"

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
for _k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_k, None)
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 让模型严格分三段输出，脚本按段解析：英文 tags / 英文转换指令 / 中文要点
INSTRUCTION = (
    "这是一张画作或照片。请只分析它的**绘画风格**，忽略画面内容。\n"
    "严格按下面三段输出，不要加任何标题、编号或多余解释：\n"
    "第 1 段：**只能英文**，10~15 个逗号分隔的风格关键词，描述媒介、笔触、颜料、"
    "纸张或画布质感、用色倾向、明暗处理。不许出现任何具体景物或人物。\n"
    "第 2 段：**只能英文**，一句话的转换指令，以 Transform this photo into 开头，"
    "说明把照片转成什么媒介，并要求保住原照构图、景物位置与外形轮廓。\n"
    "第 3 段：中文，两三句说明这种风格最要紧的特征，供人阅读，不会写进提示词。\n"
    "三段之间用空行分隔。"
)


def http_json(port, path, payload=None, timeout=120):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers=headers, method="POST" if data else "GET")
    with _opener.open(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except Exception:
        return body


def collect_styles():
    """返回 [(风格名, 参考图路径)]。子文件夹优先，其次平铺图片。"""
    if not os.path.isdir(REFS_DIR):
        return []
    found = []
    for entry in sorted(os.listdir(REFS_DIR)):
        full = os.path.join(REFS_DIR, entry)
        if os.path.isdir(full):
            imgs = sorted(f for f in os.listdir(full) if f.lower().endswith(IMG_EXTS))
            if imgs:
                found.append((entry, os.path.join(full, imgs[0])))
            else:
                print(f"  跳过空文件夹: {entry}")
        elif entry.lower().endswith(IMG_EXTS):
            found.append((os.path.splitext(entry)[0], full))
    return found


def upload_image(port, path):
    """把本地图传进 ComfyUI 的 input 目录，返回它认得的文件名。"""
    with open(path, "rb") as f:
        raw = f.read()
    boundary = "----stylegen"
    name = os.path.basename(path)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + raw + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with _opener.open(req, timeout=120) as r:
        return json.loads(r.read().decode())["name"]


def run_generate(port, image_name, max_len):
    prompt = {
        "1": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": ENCODER,
                         "type": "qwen_image", "device": "default"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "TextGenerate",
              "inputs": {"clip": ["1", 0], "prompt": INSTRUCTION, "image": ["2", 0],
                         "max_length": max_len, "sampling_mode": "off",
                         "thinking": False, "use_default_template": True, "mtp": "auto"}},
        "4": {"class_type": "SaveText",
              "inputs": {"text": ["3", 0], "filename_prefix": "_stylegen/out",
                         "format": "txt"}},
    }
    pid = http_json(port, "/prompt", {"prompt": prompt})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 1800:
        h = http_json(port, f"/history/{pid}")
        if pid in h:
            status = h[pid].get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False)[:600])
            if status.get("completed"):
                val = h[pid].get("outputs", {}).get("4", {}).get("text")
                if not val:
                    raise RuntimeError("TextGenerate 没有产出文本")
                if isinstance(val, list):
                    val = val[0]
                # SaveText 的 text 输出是正文本身；个别版本会给文件名，兼容一下
                if isinstance(val, dict):
                    rel = os.path.join(val.get("subfolder", ""), val["filename"])
                    with open(os.path.join(ROOT, "output", rel), encoding="utf-8") as f:
                        return f.read()
                if isinstance(val, str) and "\n" not in val and val.lower().endswith(
                        (".txt", ".md", ".json")):
                    with open(os.path.join(ROOT, "output", val), encoding="utf-8") as f:
                        return f.read()
                return str(val)
        time.sleep(2)
    raise RuntimeError("等待超时")


def parse(out):
    """按空行切三段。第一段英文 tags，第二段英文指令，第三段中文要点。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", out.strip()) if b.strip()]
    tags = blocks[0] if blocks else ""
    tags = tags.splitlines()[0].strip() if tags else ""
    tags = re.sub(r"^[\-\*\d\.\s]+", "", tags).rstrip("。.")
    instr = ""
    for b in blocks[1:]:
        if b.lower().startswith(("transform", "convert")):
            instr = " ".join(b.split())
            break
    notes = blocks[-1] if len(blocks) > 1 else ""
    return tags, instr, notes


def render(name, tags, instr, notes, src, date):
    lines = [tags, ""]
    if instr:
        lines += [instr, ""]
    lines.append(f"# ===== 由 scripts/gen_style_from_images.py 于 {date} 生成，是草稿 =====")
    lines.append(f"# 参考图：{src}")
    lines.append("#")
    lines.append("# 生成后请人工过一遍：反推只看得见这张图，不知道项目约定——")
    lines.append("#   1. 删掉与风格无关、或这张图特有的词（别把偶然元素当风格）；")
    lines.append("#   2. 补上你最在意的质感词（纸纹、颗粒、笔痕这些比形容词有用）；")
    lines.append("#   3. 不要加 masterpiece / best quality / 8K 这类空泛画质词，")
    lines.append("#      scripts/check_prompts.py 会报错，官方规范也禁止；")
    lines.append("#   4. 本项目 cfg = 1.0，负向不参与计算，本文件不写 ---负向--- 段；")
    lines.append("#      要去掉什么，写进节点的 describe 框（正向）。")
    if notes:
        lines.append("#")
        lines.append("# 模型的中文要点（仅供阅读，不送进模型）：")
        for ln in notes.splitlines():
            if ln.strip():
                lines.append("#   " + ln.strip())
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8188, help="ComfyUI 端口（默认 8188）")
    ap.add_argument("--write", action="store_true", help="真正写入 styles/，否则只预览")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的同名风格文件")
    ap.add_argument("--max-len", type=int, default=320, help="生成的最大 token 数")
    args = ap.parse_args()

    try:
        http_json(args.port, "/system_stats", timeout=8)
    except Exception:
        print(f"连不上 ComfyUI（127.0.0.1:{args.port}）。先双击 start_comfyui.bat 再跑本脚本。")
        return 2

    # 端口被别的 ComfyUI 占着（本机常见：ComfyUI Desktop 绑 127.0.0.1:8188，
    # 本仓库实例 --listen 0.0.0.0 也绑 8188，本地连接会被前者抢走），
    # 那套没有本项目的模型，直接跑会报一堆看不懂的缺模型错。先查一下。
    try:
        info = http_json(args.port, "/object_info/CLIPLoader", timeout=30)
        names = info["CLIPLoader"]["input"]["required"]["clip_name"][0]
        if ENCODER not in names:
            print(f"这个 ComfyUI（:{args.port}）里没有 {ENCODER}，多半连错了实例。")
            print("本机若同时开着 ComfyUI Desktop，它会抢走 127.0.0.1:8188。")
            print(f"改用本仓库实例的端口重试，例如：--port 8191")
            return 2
    except Exception as e:
        print(f"读取节点信息失败: {e}")
        return 2

    styles = collect_styles()
    if not styles:
        print(f"{REFS_DIR} 里没有参考图。")
        print("放法（任选一种）：")
        print("  子文件夹： input/style_refs/水墨/1.png     → 风格名「水墨」")
        print("  平铺：     input/style_refs/水彩.png       → 风格名「水彩」")
        return 2

    print(f"发现 {len(styles)} 个待反推风格：{', '.join(n for n, _ in styles)}\n")
    date = time.strftime("%Y-%m-%d")
    written = 0
    for name, path in styles:
        target = os.path.join(STYLES_DIR, f"{name}.txt")
        rel_src = os.path.relpath(path, ROOT).replace("\\", "/")
        if os.path.exists(target) and not args.force:
            print(f"[跳过] {name}：styles/{name}.txt 已存在（要覆盖加 --force）")
            continue
        print(f"[反推] {name} ← {rel_src}", flush=True)
        try:
            uploaded = upload_image(args.port, path)
            raw = run_generate(args.port, uploaded, args.max_len)
        except Exception as e:
            print(f"  失败: {e}")
            continue
        tags, instr, notes = parse(raw)
        if not tags:
            print("  模型没给出可用的关键词，跳过")
            continue
        text = render(name, tags, instr, notes, rel_src, date)
        print(f"  tags: {tags[:90]}{'…' if len(tags) > 90 else ''}")
        if args.write:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"  → 已写入 styles/{name}.txt")
            written += 1
        else:
            print("  （预览，未写入；确认无误后加 --write）")
        print()

    if not args.write:
        print("预览完成。确认后跑：python scripts/gen_style_from_images.py --write")
    else:
        print(f"完成，写入 {written} 个风格文件。浏览器 F5 刷新即可在风格下拉框看到。")
        print("记得跑一次 python scripts/check_prompts.py 体检。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
