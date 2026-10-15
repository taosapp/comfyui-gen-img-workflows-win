# -*- coding: utf-8 -*-
"""给 workflows/图片风格转换.json 补一个说明便签（幂等：重复运行只保留最新一份）。

用法:
    python patch_style_workflow.py [--sec 90]

--sec 是把实测耗时写进便签用（秒）；不传就沿用上次写的值/占位符。
"""
import argparse
import json
import os

WF = os.path.join("workflows", "图片风格转换.json")
STAMP = "<!-- 由 scripts/legacy/patch_style_workflow.py 生成 -->"

NOTE = STAMP + """

## 图片风格转换（Qwen-Image-2.1 GGUF）

**参考照片 + 提示词 → 新图**。画布尺寸 = 参考图按 ⑤ 的 `resolution` 缩放后的尺寸
（1.jpg 是 332×187 → 画布 1024×576），**换照片不用手改宽高**。

### 两个档位（只差一个节点 + 两个参数）

| | 极速档（**默认**） | 质量档 |
|---|---|---|
| ⑯ Turbo LoRA | 开启 | **选中 ⑯ 按 Ctrl+B 绕过** |
| ⑥ 步数 / cfg | 8 步 / 1.0 | 12 步 / 3.5 |
| 单张耗时（1024×576） | 约 __SEC__ 秒 | 约 70 秒 |
| 负向提示词 | **不参与计算** | 生效 |

> ⚠️ **极速档的代价 = 负向提示词失效**（cfg 1.0 时负向在数值上被忽略）。
> 靠负向压制内容的风格会变弱：`02-简笔画` 靠负向的 `photorealistic, 3d render` 压向涂鸦、
> `03-hd_img` 靠 `changed face, changed identity` 防止改脸。
> **用这两个风格时建议切回质量档**（Ctrl+B 绕过 ⑯，⑥ 改回 12 步 / cfg 3.5）。
> 补救办法：把关键负向词改写进风格文件的**正向**里（如 `Avoid photorealistic results`），
> 极速档也能带上。`01-水彩画` 这类负向只写「别发暗发灰」的风格，极速档基本够用。
> ⑯ 用的 Turbo LoRA 许可为 Qwen Research License（**非商用**）。

### 提示词从哪来 → ⑬「风格提示词」下拉框

| 下拉选什么 | 送进模型的提示词怎么组成 |
|---|---|
| **自定义（只用下面两个框）** | **完全手写**：`describe` 框 = 正向提示词，`avoid` 框 = 负向提示词，**前面不加任何内容** |
| 水彩画 / 简笔画 / hd_img | `ComfyUI\\styles\\*.txt` 里的通用规则（`---负向---` 前 = 正向，后 = 负向）+ 两个框里的个体信息 |

### 自定义模式怎么用（三步）

1. ⑬ 下拉选 **自定义（只用下面两个框）**
2. 上面框写正向提示词（**留空 = 模型自由发挥，一般不是你要的**）；下面框写负向，可留空
3. ④ 号 LoadImage 换参考照片 → `Queued` 运行

> 「自定义」这一项由 `custom_nodes/comfyui-style-prompt` 提供，**凡是用到该节点的工作流都能选**；
> 想把下拉里显示的文字改掉，改 `nodes.py` 顶部的 `CUSTOM_STYLE` 即可（改完要重启 ComfyUI）。

### 加 / 改风格（都不用动工作流）

- **加风格**：`ComfyUI\\styles\\` 里放一个 `04-xxx.txt`，文件名即风格名，重启后出现在下拉框
- **正负向分隔**：文件里单独一行写 `---负向---`，其后的内容作为该风格的负向提示词
- **注释**：`#` 或 `//` 开头的整行、`/* ... */` 块注释，读取时自动剔除
- **改完直接重跑**：节点按风格库文件的时间戳判断变化，不会被上次的执行缓存骗过去

### 采样与调参（⑥ KSampler）

极速档默认 **8 步 / cfg 1.0** + ⑯ Turbo 蒸馏 LoRA（`latent_image` 接 ⑤ 编码节点的 `latent`，
尺寸 = 参考图比例算出的空 latent，所以换照片不用手改宽高）。

| 想要的 | 怎么改 |
|---|---|
| 就用现在的快档 | 什么都不用动（8 步 / cfg 1.0 / ⑯ 开启） |
| 负向提示词生效、更细腻 | 选中 ⑯ 按 Ctrl+B 绕过；⑥ 改 12 步（或 20 步）、cfg 3.5 |
| 更贴参考图的结构/构图 | 质量档下 cfg 3.5 → 3.0 |
| 只想轻度风格化（更像原照片） | ⑥ 的 `latent_image` 从 ⑤ 的 `latent` 换成经 VAEEncode 的参考图，`denoise` 调 0.6~0.8 |

本机 RTX 3060 12GB + `--lowvram`：1024×576 / 8 步 + Turbo LoRA 约 __SEC__ 秒一张；
**服务重启后第一张会慢一些**（LoRA 加载/模型修补是一次性开销，之后一直快）。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=str, default=None)
    args = ap.parse_args()

    text = NOTE
    if args.sec:
        text = text.replace("__SEC__", args.sec)
    elif "__SEC__" in text:
        # 没给实测值：保留上一次文件里已经填过的数字，避免把好数据冲掉
        try:
            with open(WF, encoding="utf-8") as fh:
                old = json.load(fh)
            for n in old["nodes"]:
                if n.get("type") == "MarkdownNote":
                    old_text = n["widgets_values"][0]
                    i = old_text.find("Turbo LoRA 约 ")
                    if i >= 0:
                        seg = old_text[i + len("Turbo LoRA 约 "):]
                        text = text.replace("__SEC__", seg.split("秒")[0])
                        break
        except (OSError, ValueError, KeyError, IndexError):
            pass

    with open(WF, encoding="utf-8") as fh:
        wf = json.load(fh)

    wf["nodes"] = [n for n in wf["nodes"]
                   if not (n.get("type") == "MarkdownNote"
                           and str(n.get("widgets_values", [""])[0]).startswith(STAMP))]

    nid = max([n["id"] for n in wf["nodes"]] + [wf.get("last_node_id", 0)]) + 1
    wf["last_node_id"] = nid
    wf["nodes"].append({
        "id": nid, "type": "MarkdownNote", "pos": [380, 580], "size": [470, 720],
        "flags": {}, "order": len(wf["nodes"]), "mode": 0,
        "inputs": [], "outputs": [], "properties": {"Node name for S&R": "MarkdownNote"},
        "widgets_values": [text],
    })

    with open(WF, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=2)
    print("已写入便签，节点 id =", nid, "| 节点总数 =", len(wf["nodes"]))
    print("占位符是否已填：", "是" if "__SEC__" not in text else "否（仍是 __SEC__）")


if __name__ == "__main__":
    main()
