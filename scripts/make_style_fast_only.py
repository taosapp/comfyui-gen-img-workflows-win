# -*- coding: utf-8 -*-
"""把 workflows/图片风格转换.json 精简为纯极速版（2026-10-15）。

改动：
  1. ⑬ StylePromptSelector 保持默认「水彩画」不变；
  2. ④ LoadImage 默认照片换成 6.png（当前在用的参考图）；
  3. ⑱ 便签整体重写：删除双档位/Ctrl+B/质量档内容，只保留极速版说明，
     并写明 cfg 1.0 下负向不生效、约束必须写进正向。

幂等：重复运行结果一致。不改动任何节点/连线（极速版 11 个节点本来就是一个整体）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, "workflows", "图片风格转换.json")

NOTE = """<!-- 由 scripts/make_style_fast_only.py 生成（2026-10-15 精简为纯极速版） -->

## 图片风格转换（极速版 · Qwen-Image-2.1 GGUF + Turbo LoRA）

**参考照片 + 风格提示词 → 新图**。画布尺寸 = 参考图按 ⑤ 的 `resolution`
缩放后的尺寸（换照片不用手改宽高）。
12GB 显存级别显卡：**约 36~60 秒一张**（服务重启后第一张慢，
LoRA 加载/模型修补是一次性开销，之后一直快）。

### 提示词从哪来 → ⑬「风格提示词」下拉框

| 下拉选什么 | 送进模型的提示词怎么组成 |
|---|---|
| **自定义（只用下面这个框）** | **完全手写**：`describe` 框 = 完整正向提示词，**前面不加任何内容** |
| 水彩画 / 简笔画 / hd_img | `styles\\*.txt` 里的通用规则 + `describe` 框里的个体信息 |

### 自定义模式怎么用（三步）

1. ⑬ 下拉选 **自定义（只用下面这个框）**
2. 在框里写正向提示词（**留空 = 模型自由发挥，一般不是你要的**）
3. ④ 号 LoadImage 换参考照片 → `Queued` 运行

### ⚠️ 本工作流 cfg = 1.0：负向提示词不生效（2026-10-15 已删除负向框）

`comfy/samplers.py:610`：cfg = 1.0 时负向条件被直接置 None，UNet 只算正向
（8 步 = 8 次前向，这正是快的原因）。实测同种子下「负向=帽子」与「负向=空」
输出**逐像素完全相同**。

因此⑬ 节点上的**负向框已移除**，`styles\\*.txt` 的 `---负向---` 段也不再送出：

- **想约束画面必须写进 `describe`**——要去掉什么就写「去掉 X」。
  `02-简笔画` 就是范例：「黑白线稿 / 无填充 / 无阴影」全部写在正向；
- 长指令反而压不住，保持极简；
- 确需负向生效请用 `中国彩墨图生图.json`（质量版，26 步 / cfg 3.2）的链路。

### 加 / 改风格（都不用动工作流）

- **加风格**：`styles\\` 里放一个 `04-xxx.txt`，文件名即风格名，重启后出现在下拉框
- **注释**：`#` 或 `//` 开头的整行、`/* ... */` 块注释，读取时自动剔除
- **改完直接重跑**：节点按风格库文件时间戳判断变化，不会被执行缓存骗过去

### 采样与调参（⑥ KSampler）

默认 **8 步 / cfg 1.0** + ⑯ Turbo 蒸馏 LoRA（强度 1.0）+ ⑭ KV 缓存（`dtype` 保持
`default`，改 int8 会报 `aimdo memory compile error`）。

| 想要的 | 怎么改 |
|---|---|
| 更贴参考图的结构 | ⑤ 的 `resolution` 调大（768 → 1024，耗时增加） |
| 只想轻度风格化（更像原照片） | ⑥ 的 `latent_image` 从 ⑤ 的 `latent` 换成经 VAEEncode 的参考图，`denoise` 调 0.6~0.8 |
| 风格更稳 | ⑥ 步数 8 → 10~12（每 +2 步约 +5 秒） |

⑯ 用的 Turbo LoRA 许可为 Qwen Research License（**非商用**）。"""


def main():
    with open(WF, encoding="utf-8") as fh:
        wf = json.load(fh)

    hit = {"load": False, "style": False, "note": False}
    for n in wf["nodes"]:
        if n["type"] == "LoadImage":
            n["widgets_values"] = ["6.png", "image"]
            hit["load"] = True
        elif n["type"] == "StylePromptSelector":
            n["widgets_values"][0] = "水彩画"
            hit["style"] = True
        elif n["type"] == "MarkdownNote":
            n["widgets_values"] = [NOTE]
            hit["note"] = True

    if not all(hit.values()):
        print("缺少节点:", {k: v for k, v in hit.items() if not v})
        return 1

    with open(WF, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=1)
    print("已精简: LoadImage→6.png / 便签→纯极速版 / 节点与连线未动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
