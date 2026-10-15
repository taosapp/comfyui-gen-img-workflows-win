# -*- coding: utf-8 -*-
"""生成 workflows/文生图-极速.json（2026-10-15）。

以现有 `文生图.json` 为基准改造：
  1. 模型链插 `LoraLoaderBypassModelOnly`（viggle turbo），接 KV 缓存；
  2. KSampler 改 8 步 / cfg 1.0（极速档）；
  3. 加 `LoadImage`（可选参考图）→ 编码器 images.image_1；
  4. 编码器补接 VAE（有参考图时要做 vae.encode）。

可选参考图的原理（comfy_extras/nodes_qwen.py:TextEncodeQwenImage21.execute）：
    images = images or {}; for ...: if image is None: continue
    keep_vision = len(ref_latents) == 0
即编码器天生兼容「不接图」——不接 = 纯文生图（keep_vision=True，latent 走 resolution 正方形）；
接了 = 图生图，latent 自动按参考图比例算。所以「可选」不需要额外节点，
画布上把 ④LoadImage 那根线拔掉即可切回纯文生图。

幂等：每次运行结果一致。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "workflows", "文生图.json")
DST = os.path.join(ROOT, "workflows", "文生图-极速.json")

NOTE = """## 文生图 · 极速版（Turbo LoRA，2026-10-15 新增）

**8 步 / cfg 1.0，实测 720 档约 22 秒一张**（质量档 `文生图.json` 约 205 秒，快 9 倍以上）。

实测两档光影风格差别明显：**极速档的光影更自然、有电影感**（用户 2026-10-15 目视选定这档）。
质量档更"工整规整"，但用户偏好极速档的质感——按审美偏好选，不按参数优劣选。

| 模式 | 实测耗时 | 实测出图尺寸 |
|---|---|---|
| 纯文生图（不接参考图） | **22.2 秒** | 720×720 |
| 图生图（接参考图 1024×576） | **80.5 秒** | **960×544**（跟随参考图比例） |

> 接参考图会慢 3 倍多：多了一次 `vae.encode` + 视觉塔要过整张图。
> 草稿试词建议不接图，确定构图后再接。

### ⭐ 参考图：接不接都行（同一个工作流两种模式）

**这是本工作流的核心：④ 号参考图的连线，决定它是文生图还是图生图。**

| ④ 参考图 | 出图尺寸（resolution=720 时） | 效果 |
|---|---|---|
| **线接着**（默认，有图） | **960×544**（跟随参考图比例） | 图生图：参考图参与构图与光影 |
| **选中 ④ 按 `M` 静音该节点** | **720×720** 正方形 | 纯文生图：只有文字提示词 |

> 💡 切换方法：点一下 ④ 号节点让它变成**红色/虚线**（或选中按 `M`），
> 这根线就断了 → 纯文生图。再点一下恢复 → 图生图。**不用删线、不用重搭。**

原理在源码 `comfy_extras/nodes_qwen.py:TextEncodeQwenImage21.execute`：
```python
images = images or {}
for name in sorted(images, ...):
    if image is None: continue          # 没接图直接跳过
keep_vision = len(ref_latents) == 0     # 决定是否保留视觉 token
```
**「可不上传」是编码器的原生能力**，所以不需要任何额外节点或开关——
这也是为什么这个工作流不像别的要拖一个 BooleanSelector。

### 接线说明

```
① UnetLoaderGGUF → ⑯ Turbo LoRA → ⑭ KV 缓存 → ⑥ KSampler.model
② CLIPLoader ─┐
④ 参考图 ──────┼→ ⑦ 编码器 → ⑥ KSampler.positive / .negative / .latent_image
③ VAELoader ──┘（有参考图时必须要，编码器用它做 vae.encode）
④ 分辨率下拉 → ⑤ 转 INT → ⑦ 编码器.resolution
```

**注意**：本工作流多接了 `③ VAELoader → 编码器.vae`。文生图那版没接（纯文生图不需要），
但一旦接了参考图就必须接——否则参考图只进视觉塔、不进潜空间，图生图会失效。

### ⚠️ 本档 cfg = 1.0：负向提示词不参与计算

`comfy/samplers.py:610`：cfg = 1.0 时负向条件被置 None，UNet 只算正向。
**要去掉什么、想强调什么，全部写进正向 prompt。**（已在 ⑦ 编码器的负向口保留输入，
但填了也不生效，只是留着方便切回质量档时用。）

### 采样参数（⑥ KSampler）

| 项 | 值 | 说明 |
|---|---|---|
| steps | **8** | Turbo 蒸馏档，不要改高（改高反而可能劣化） |
| cfg | **1.0** | 见上，改高会失去极速且未必更准 |
| sampler / scheduler | euler / beta | 与质量档一致 |
| denoise | 1.0 | 参考图模式下也别调，改了会偏离原图结构 |

### 许可

⑯ 用的 Turbo LoRA 是 **Qwen Research License，仅限非商业用途**。
要商用/正式交付请用 `文生图.json`（质量档）或 `中国彩墨图生图.json`。

### 三档分辨率

沿用质量档的下拉：512（草稿）/ **720（默认）**/ 1024（最慢）。
**接了参考图时 `resolution` 仍然生效**，但出图比例跟随参考图（不是正方形）。
"""


def main():
    with open(SRC, encoding="utf-8") as f:
        wf = json.load(f)

    nodes = {n["id"]: n for n in wf["nodes"]}
    links = wf["links"]

    def link(lid, oid, oslot, tid, tslot, typ):
        links.append([lid, oid, oslot, tid, tslot, typ])

    # --- 1. 模型链插 LoRA ---
    # 原：1(UnetGGUF) → 6(Cache) → 8(KSampler.model)
    # 新：1 → 16(LoRA) → 6(Cache) → 8
    # 先摘掉 Unet 直连 Cache 那条，再重建，避免留重复连线。
    wf["links"] = [l for l in links if not (l[1] == 1 and l[3] == 6)]
    links = wf["links"]
    cache_in = next(i for i in nodes[6]["inputs"] if i["name"] == "model")
    cache_in["link"] = 21          # 改由 LoRA 驱动

    lora = {
        "id": 16,
        "type": "LoraLoaderBypassModelOnly",
        "pos": [40, -320],
        "size": [340, 130],
        "flags": {},
        "order": 4,
        "mode": 0,
        "inputs": [
            {"name": "model", "type": "MODEL", "link": 20},
            {"name": "lora_name", "type": "COMBO",
             "widget": {"name": "lora_name"},
             "link": None},
            {"name": "strength_model", "type": "FLOAT", "widget": {"name": "strength_model"},
             "input": {"name": "strength_model"}, "link": None},
        ],
        "outputs": [
            {"name": "MODEL", "type": "MODEL", "links": [21], "slot_index": 0},
        ],
        "properties": {"cnr_id": "comfyui-lora-loader", "ver": "1.0.0"},
        "widgets_values": [
            "qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors",
            1.0,
        ],
        "title": "⑯ 极速档 Turbo LoRA（Ctrl+B 绕过 = 回到质量档）",
    }
    wf["nodes"].append(lora)
    link(20, 1, 0, 16, 0, "MODEL")   # Unet → LoRA
    link(21, 16, 0, 6, 0, "MODEL")   # LoRA → Cache

    # --- 2. KSampler 改 8 步 / cfg 1.0 ---
    nodes[8]["widgets_values"] = [42, "randomize", 8, 1.0, "euler", "beta", 1.0]
    nodes[10]["widgets_values"] = ["文生图/极速"]

    # --- 3. 编码器补接 VAE ---
    enc = nodes[7]
    vae_in = {"name": "vae", "type": "VAE", "link": 22}
    # 插到 clip 之后、resolution 之前
    enc["inputs"].insert(1, vae_in)
    link(22, 3, 0, 7, 1, "VAE")

    # 插了输入就要重排 target_slot：前端按 inputs 数组下标连线，
    # 原 resolution 那条 link 的 slot 1 得跟着抬到 2，否则 INT 会接到后面的图槽上。
    def sync_slots(node):
        for i, slot in enumerate(node["inputs"]):
            if slot.get("link") is None:
                continue
            for l in links:
                if l[0] == slot["link"]:
                    l[4] = i
    sync_slots(enc)

    # --- 4. 可选参考图 ---
    img = {
        "id": 17,
        "type": "LoadImage",
        "pos": [-260, 240],
        "size": [340, 320],
        "flags": {},
        "order": 5,
        "mode": 0,          # 0 = 常态；写成 4 会把节点置成 BYPASS，参考图直接不参与计算
        "inputs": [],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": [23], "slot_index": 0},
            {"name": "MASK", "type": "MASK", "links": None, "slot_index": 1},
        ],
        "properties": {"cnr_id": "comfyui", "ver": "0.3.4"},
        "widgets_values": ["ref_test_scene.png", "image"],
        "title": "④ 参考图（可选）·不接这根线 = 纯文生图 · 接线 = 图生图",
    }
    wf["nodes"].append(img)
    # images 是 Autogrow 输入，在 schema 里排在 resolution 之后，槽名形如 images.image_1。
    # 只往 links 表加连线而不在这里登记槽位，target_slot 会撞上 resolution。
    enc["inputs"].append({"name": "images.image_1", "type": "IMAGE", "link": 23})
    link(23, 17, 0, 7, 3, "IMAGE")   # 参考图 → 编码器 images.image_1
    sync_slots(enc)

    # --- 5. 便签 ---
    nodes[11]["widgets_values"] = [NOTE]
    nodes[11]["title"] = "ⓘ 用法速查（极速版 / 参考图可接可不接）"

    with open(DST, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)

    print("已生成 %s" % DST)
    print("  节点 %d 个，连线 %d 条" % (len(wf["nodes"]), len(wf["links"])))


if __name__ == "__main__":
    main()