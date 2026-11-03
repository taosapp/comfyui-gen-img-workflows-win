# patches —— 本机对第三方节点的改动存档

## comfyui-nodes_qwen-prompt-ratio.patch

**作用**：给 ComfyUI 本体的 `comfy_extras/nodes_qwen.py`（`TextEncodeQwenImage21`）加提示词比例解析：
**纯文生图**（不接参考图）时，如果提示词里写了明确的长宽比（如 `9:16`、`2:3`、`16:9`），
空 latent 按该比例生成，`resolution` 只当**长边**用（如 512 + 9:16 → 288×512）；
没写比例时维持原行为（resolution 正方形）。**接了参考图的工作流完全不受影响**（仍跟随参考图比例）。

**解析规则**：

- 正则 `(?<![\d.])(\d{1,2})[:：](\d{1,2})(?![\d.])`，取第一个能通过校验的匹配；
- 两个数都 ≤ 32，且比例不比 8:1 更极端（`10:30` 这类时间虽能过校验会误判成 1:3，
  控制台会打 `Prompt aspect ratio ...` 日志，提示词里写时刻请避开冒号）；
- 短边取 `round(长边×比例/16)*16`（9:16 在 512/1024 下是精确的 288/576；720 下 405→400）。

**适用版本**：ComfyUI 本体 commit `6ea2651`（同 `_upstream_commit.txt`，2026-01-12）。

**恢复方式**（`comfy_extras/` 不进 git，换机后需要重打）：

```bash
cd comfy_extras
patch -p1 < ../patches/comfyui-nodes_qwen-prompt-ratio.patch
```

**验证是否生效**：启动 ComfyUI 后跑一次纯文生图，提示词带 `9:16`、分辨率 512，
出图应为 288×512；控制台应有一行 `Prompt aspect ratio 9:16 -> 288x512`。

## comfyui-gguf-add-qwen-image-arch.patch

**作用**：给 `city96/ComfyUI-GGUF` 的 `tools/convert.py` 增加一个 `ModelQwenImage` 架构类，并把 `qwen_image` 加进 `arch_list`。

**为什么必须打**：

- `models/diffusion_models/qwen-image-2.1-Q5_K_M.gguf` 这个文件**没有任何元数据**（实测：297 个张量、0 个 KV，没有 `general.architecture`）。
- 加载器 `loader.py` 第 96–103 行的逻辑是：读不到 `general.architecture` 时，回落到
  `from .tools.convert import detect_arch` → `detect_arch(...).arch` 用**张量名**反推架构。
- 没有 `ModelQwenImage` 这个类，`detect_arch` 找不到匹配项 → 报 **`Unknown model architecture!`**，工作流跑不起来。

（MiniMax-H3 的两个 GGUF 不受影响：它们自带元数据，`general.architecture = wan` / `qwen3vl`，本来就在白名单里。）

**适用版本**：`city96/ComfyUI-GGUF` commit `6ea2651e7df66d7585f6ffee804b20e92fb38b8a`（2026-01-12）

**恢复方式（在新机器上）**：

```bash
cd custom_nodes/ComfyUI-GGUF
git apply ../../patches/comfyui-gguf-add-qwen-image-arch.patch
# 打不上（上游已变动）时用三方合并：
# git apply -3 ../../patches/comfyui-gguf-add-qwen-image-arch.patch
```

**验证是否生效**：

```bash
python -c "
import sys; sys.path.insert(0, '.')
from tools.convert import arch_list
print([c.arch for c in arch_list])   # 应该看到 'qwen_image'
"
```

**最省事的做法**：直接把本机 `custom_nodes/ComfyUI-GGUF/` 整目录拷过去（补丁已经在里面了），别在新机重新 clone。
