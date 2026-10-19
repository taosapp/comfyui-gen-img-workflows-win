# ComfyUI 图生图工作流集（NVIDIA / Windows）

一套在 **NVIDIA 消费级显卡（8-12GB 显存）+ Windows** 上实测可用的 ComfyUI 图片工作流，
围绕 **Qwen-Image-2.1（GGUF 量化）图生图** 构建，包含：

| 工作流 | 用途 | 速度（RTX 3060 12GB 实测） |
|---|---|---|
| `workflows/图片风格转换.json` | 通用图生图风格转换，下拉框切换风格库（水彩/简笔画/高清增强等），也可选「自定义」手写完整正/负向提示词。**纯极速版**（8 步 + Turbo LoRA / cfg 1.0） | 约 36~60 秒/张 |
| `workflows/抠图.json` | 透明底抠图（BiRefNet 专用分割模型，不改像素） | 约 3 秒/张 |
| `workflows/文生图.json` | Qwen-Image-2.1 文生图（GGUF + KV 缓存加速，质量档 20 步 / cfg 3.5） | 约 205 秒/张（720 档实测） |
| `workflows/文生图-极速.json` | 同上挂 Turbo 蒸馏 LoRA（8 步 / cfg 1.0）；**参考图接线 = 图生图，静音 = 纯文生图** | 约 22 秒/张（720 纯文生图），接参考图约 80 秒 |
| `workflows/分层文生图.json` | Qwen-Image-Layered 一次生成分层图（文字直接生成多层，LatentCut 切层输出） | 待实测 |
| `workflows/中国彩墨图生图.json` | 中国彩墨画，文生图 / 照片转彩墨画两用（默认画布 864×1152 / 3:4，通用提示词不绑定具体照片），质量档（26 步 / cfg 3.2） | 约 4-5 分钟/张（864 级竖幅实测） |
| `workflows/中国彩墨图生图-极速.json` | 同上，挂 Turbo 蒸馏 LoRA（8 步 / cfg 1.0），**日常出图首选**（更快且更贴原照） | 约 47 秒/张（首次约 4 分钟，含 LoRA 加载） |

配套一个自建小节点包 `custom_nodes/comfyui-style-prompt/`（风格库下拉选择器 + 存回节点 + 背景填充节点），
以及一份 ComfyUI-GGUF 补丁（见 `patches/`）。

> 全部内容在 RTX 3060 12GB + 32GB 内存、Windows、`--lowvram` 启动下实测通过；
> 8GB 显存 / 16GB 内存的机器也能跑图片工作流（见下方「硬件要求」）。

## 工作流简介

### 图片风格转换
`LoadImage → 风格选择器(下拉) → TextEncodeQwenImage21 → KSampler → VAEDecode → SaveImage`，
中间串了一个 `QwenImage21Cache`（KV 缓存，同样提示词连续出图时可省 40% 时间，勿删）。

**纯极速版**（2026-10-15 精简）：链路里串了 Turbo 蒸馏 LoRA（⑯），8 步 / cfg 1.0，
实测 36~60 秒/张。工作流内不再保留质量档；确需负向提示词生效的场合，
用 `中国彩墨图生图.json`（质量版，26 步 / cfg 3.2）的链路。

> ⚠️ cfg 1.0 下**负向提示词不参与计算**（`comfy/samplers.py:610`：cfg=1.0 时负向
> 条件被直接置 None，UNet 只算正向——这也是速度快的原因）。想约束画面（"别上色"、
> "别改脸"）**必须写进正向**：`02-简笔画` 即范例，黑白线稿约束全写在正向，
> 实测 36 秒出标准线稿；长指令反而压不住颜色，风格文件请保持极简。
> `03-hd_img` 的防改脸负向在本工作流里保护力弱。Turbo LoRA 许可为 Qwen Research
> License（非商用）。

风格 = `styles/` 目录下一个 `.txt` 文件，文件名（去掉序号）就是下拉框里的名字。
**新增风格只要丢一个 txt 进去、浏览器 F5 即可**；改内容直接重新 Queue。
风格文件支持 `#` 注释（详见 `styles/_说明.txt`）。

下拉框第一项是 **「自定义（只用下面两个框）」**：不读风格库，`describe` 框 = 完整正向提示词、
`avoid` 框 = 完整负向提示词，原样送进模型（前面不加任何库内容）。适合手写一次性提示词，
不用为了跑一次而新建风格文件。

> ⚠️ 工作流里的 `QwenImage21Cache` **`dtype` 必须保持 `default`**：改成实验性的 `int8`
> 在本机会在采样第一步抛 `aimdo memory compile error`（KV 缓存量化与动态显存不兼容）。

### 抠图
核心节点 `LoadBackgroundRemovalModel + RemoveBackground`（BiRefNet，Swin-L 版），
输出与输入同尺寸的透明 PNG。注意链路中必须过一次 `InvertMask`
（`JoinImageWithAlpha` 内部做 `alpha = 1 - mask`），`GrowMask` 放在反相前用于去白边。

### 文生图（质量版 / 极速版）
`UnetLoaderGGUF →（仅极速档）Turbo LoRA → QwenImage21Cache → TextEncodeQwenImage21 → KSampler → SaveImage`，
分辨率走 512 / 720 / 1024 下拉档。

- **极速版**（8 步 / cfg 1.0）720 档实测 **22 秒/张**，且实测光影更自然；「参考图（可选）」节点
  **线上接着就是图生图**（出图比例跟随参考图，约 80 秒），选中按 `M` 静音就回到纯文生图，不用改连线。
  接参考图时必须保留「VAELoader → 编码器.vae」这根线，否则图生图失效。
- **质量版**（20 步 / cfg 3.5）实测约 **205 秒/张**，留作对照与正式交付（Turbo LoRA 是
  Qwen Research License **非商用**）。

> ⚠️ 极速档同样是 cfg 1.0，**负向提示词不参与计算**，要约束的内容全部写进正向（同「图片风格转换」）。

### 中国彩墨图生图（质量版 / 极速版）
同一套「空 latent + 参考图条件」链路的两个档位，提示词模板通用、不绑定具体照片
（换参考照片记得把画布改成同比例，如 9:16 → 864×1536）：

- **极速版**挂 Qwen-Image-2.1 Viggle Turbo 蒸馏 LoRA（8 步 / cfg 1.0），约 47 秒/张，
  且实测结构保真/纹理密度更好（结构 0.831~0.887 vs 0.534，纹理密度 13.0 vs 11.1），
  **日常出图首选**。首次运行慢约 3 分钟（LoRA 加载/修补一次性开销），服务不重启就一直快。
- **质量版**（26 步 / cfg 3.2）保留作对照、以及需要用负向提示词控制画风的场合。

> ⚠️ 本链路中负向提示词是「负资产」：负向里的「照片/摄影/写实」会把画面推离参考图结构
> （同种子实测结构保真 0.826 → 0.534）。cfg 1.0 时负向不参与计算，反而更贴原照。
> Turbo LoRA 许可为 Qwen Research License（**非商用**）。

### MiniMax-H3 图生视频（2026-10-15 已移除）
该工作流与配套的约 27GB 视频模型（unet 主模型 / 32B 文本编码器 / turbo LoRA / 音视频 VAE）
已从本仓库与本机一并移除，`scripts/prepare.py` 里的下载条目与 `--with-video` 参数同步删除。
需要时从 git 历史取回工作流 JSON，并按 `README` 旧版清单自行下载模型。

## 快速开始（新电脑）

本仓库 clone 下来后**只含策划资产**（工作流/风格库/自建节点/补丁/启动器），
运行时、依赖、模型都不在仓库里。用任意 Python 3.9+ 跑一次准备脚本即可补齐：

```bash
git clone https://github.com/taosapp/comfyui-gen-img-workflows-win.git
cd comfyui-gen-img-workflows-win
python scripts/prepare.py                # 全自动：环境 + 运行时 + 依赖 + 节点补丁 + 模型下载
python scripts/prepare.py --check        # 或先只做检查，缺什么会列出来
```

准备脚本会依次：找/建 conda 环境 `comfyui`（无 conda 则退建项目内 `.venv`）→
浅克隆官方 ComfyUI 补齐运行时 → 安装 pytorch cu126 与依赖 →
克隆 ComfyUI-GGUF 并打上本仓库的补丁 → 按 `scripts/prepare.py` 内置清单
从 hf-mirror 下载缺失模型（支持断点续传，中断重跑即可续）。
装完双击 `start_comfyui.bat`（Windows）或 `bash start_comfyui_mac.sh`（macOS）启动。
少数模型没有自动下载地址（脚本会打印获取指引），按提示手动放置即可。

## 安装

1. 安装 [ComfyUI](https://github.com/comfyanonymous/ComfyUI)（本仓库工作流基于 0.37.0 实测）；
2. 安装第三方节点 [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)：
   ```bash
   git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
   pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt
   ```
3. **给 ComfyUI-GGUF 打补丁**（重要）：
   `qwen-image-2.1-Q5_K_M.gguf` 没有架构元数据，加载器只能从张量名反推架构，
   原版 ComfyUI-GGUF 不认识它、会报 `Unknown model architecture!`。
   打法见 `patches/README.md`（基线：city96/ComfyUI-GGUF @ `6ea2651e`）；
4. 把 `custom_nodes/comfyui-style-prompt/` 拷进你的 `custom_nodes/`，重启 ComfyUI；
5. 把 `workflows/`、`styles/` 放到 ComfyUI 根目录同名文件夹下；
6. 按下表下载模型（**模型不随仓库分发，请自行获取**）。

## 模型清单（图片工作流部分）

| 文件 | 大小 | 放置目录 | 来源 |
|---|---|---|---|
| `qwen-image-2.1-Q5_K_M.gguf` | 4.9 GB | `models/diffusion_models/` | [Qwen/Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) 官方权重的 GGUF 量化版（[Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)、unsloth 等社区仓库有量化版） |
| `qwen3vl_8b_int8_convrot.safetensors` | 8.7 GB | `models/text_encoders/` | 基于 [Qwen/Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) 的 int8 convrot 量化版（ComfyUI 社区量化）；也可用官方 BF16 |
| `qwen_image_2.1_vae_bf16.safetensors` | 0.63 GB | `models/vae/` | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) |
| `qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors`（**所有极速档必需**：图片风格转换 / 文生图-极速 / 彩墨极速） | 0.84 GB | `models/loras/` | Viggle Turbo v0.2.1 r128 蒸馏 LoRA（[Viggle/Qwen-Image-2.1-viggle-turbo](https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo)，Qwen Research License **非商用**；本仓库实测 SHA256 `2bbf5b6c…4f77f`） |
| `qwen-image-layered-Q4_K_S.gguf`（分层文生图用） | 12 GB | `models/diffusion_models/` | Qwen-Image-Layered 的 GGUF 量化版（unsloth 等社区仓库） |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors`（分层文生图用） | 8.7 GB | `models/text_encoders/` | Comfy-Org 社区重打包版（HF 搜 `qwen_2.5_vl_7b_fp8_scaled`） |
| `qwen_image_layered_vae.safetensors`（分层文生图用） | 0.24 GB | `models/vae/` | [Comfy-Org/Qwen-Image-Layered_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image-Layered_ComfyUI) |
| `birefnet.safetensors`（仅抠图用） | 0.42 GB | `models/background_removal/` | [Comfy-Org/BiRefNet](https://huggingface.co/Comfy-Org/BiRefNet)（MIT） |

- 合计约 **36 GB**（其中分层文生图三件 21 GB，只跑风格转换/彩墨/抠图约 15.5 GB）；
  国内网络可用 [hf-mirror.com](https://hf-mirror.com) 镜像下载；`scripts/prepare.py` 内置本清单可自动下载；
- **文件名必须一字不差**：工作流按文件名找模型；
- 各模型许可证不同（Qwen 系列为 Apache-2.0 / Qwen Research，请自行确认你的用途是否合规）。

## 硬件要求（实测）

| 配置 | 结论 |
|---|---|
| RTX 3060 12GB + 32GB 内存 | 全部工作流实测可用，启动参数 `--lowvram` |
| RTX 4060 8GB + 16GB 内存 | 图片工作流可跑：8GB 显存需更多内存换入换出（更慢），**16GB 内存必须把页面文件设到 24-32GB（SSD）**，预计比 12GB 卡慢 1.5-3 倍 |

启动示例（Windows）：

```bat
python main.py --lowvram --preview-method auto
```

## 目录结构

仓库只跟踪策划资产（根目录共 6 个文件 + 5 个目录），其余根目录文件属于 ComfyUI 运行时，见下一节：

```
├── workflows/                          # 7 个工作流（浏览器里直接拖进去打开）
├── styles/                             # 风格库：一个 txt = 一种风格，支持 # 注释
├── custom_nodes/comfyui-style-prompt/  # 自建节点：风格下拉选择器 + 存回节点 + 背景填充
├── patches/                            # ComfyUI-GGUF 的 Qwen-Image 架构补丁
├── scripts/
│   ├── prepare.py                      # 新机器一键准备（环境/运行时/依赖/节点补丁/模型）
│   └── launcher/                       # Windows 启动器维护件：UTF-8 源 + rebuild.py + selftest.py
├── start_comfyui.bat                   # Windows 启动器（自动探测 conda/venv）
└── start_comfyui_mac.sh                # mac / Linux 启动器
```

改启动脚本不要直接改 `.bat`（它是 GBK 编码，编辑器很容易把中文写坏）：改
`scripts/launcher/start_comfyui.src.txt`，再跑：

```bat
python scripts/launcher/rebuild.py
python scripts/launcher/selftest.py
```

前者重建根目录的 GBK/CRLF `.bat`（附带块内括号自检），后者把启动行换成 `echo` 干跑环境探测
与降级逻辑（9 项），**不会真的启动 ComfyUI**。两个脚本自己算路径，在哪个目录跑都行。

> 本机另在 `docs/` 放了移植打包说明、性能剖析、Qwen-Image 配置笔记（含机器专属路径），
> 这些不进仓库。

## 根目录为什么还有 main.py / nodes.py

这个目录**同时是本机的 ComfyUI 运行环境**：`scripts/prepare.py` 会把官方 ComfyUI 浅克隆到
当前目录，补齐 `main.py`、`nodes.py`、`execution.py`、`server.py`、`comfy/`、`comfy_extras/`
等运行时文件，模型放 `models/`，出图进 `output/`。这些文件的位置由上游决定，**不能删也不能挪**。

`.gitignore` 用白名单模式（`/*` + 逐项放行），所以 `git status` 不会变成几十 GB 模型的灾难，
clone 出去也只拿到上面那些策划资产。`python scripts/prepare.py --check` 会列出缺什么。

## 免责声明

本项目只包含工作流与代码，不含任何模型权重与图片素材。模型的使用请遵守各自许可证；
生成内容（尤其是人物风格化）请遵守当地法律法规，不要用于伪造他人身份等用途。
