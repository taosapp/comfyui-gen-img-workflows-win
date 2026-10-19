# ComfyUI + Qwen-Image-2.1 (GGUF) 图生图配置指南

> 历史快照（2026-09-22）：当时 ComfyUI 还装在独立的旧目录，现在**仓库根目录本身就是运行环境**，
> 文中的绝对路径已统一换成当前目录。
> 日常配置请看 `README.md` 与 `docs/移植与开源说明.md`，本文仅作早期搭建记录。

## 系统要求
- GPU: NVIDIA RTX 3060 12GB
- 内存: 32GB
- Python: 3.12 (已通过 conda 安装)
- CUDA: 12.4+

## 已完成的配置

### 1. 环境设置
- Conda 环境: `comfyui` (Python 3.12)
- ComfyUI 安装位置: `D:\ai\comfyui-gen-img-workflows-win`
- PyTorch: 2.6.0+cu124
- ComfyUI-GGUF 自定义节点: 已安装

### 2. 模型文件
下载完成后，文件位置：
- **GGUF 模型**: `D:\ai\comfyui-gen-img-workflows-win\models\diffusion_models\qwen-image-2.1-Q5_K_M.gguf` (约 5GB)
- **文本编码器**: `D:\ai\comfyui-gen-img-workflows-win\models\text_encoders\qwen3vl_8b_int8_convrot.safetensors` (约 8.9GB)
- **VAE**: `D:\ai\comfyui-gen-img-workflows-win\models\vae\qwen_image_2.1_vae_bf16.safetensors` (645MB)

### 3. 启动方式
双击运行: `D:\ai\comfyui-gen-img-workflows-win\start_comfyui.bat`

启动后访问: http://127.0.0.1:8188

## 图生图工作流使用

### 加载工作流
1. 启动 ComfyUI
2. 点击菜单 → Load → 选 `workflows/` 下的现有工作流（当时的 `qwen_image21_img2img.json` 已拆成
   `图片风格转换.json` / `中国彩墨图生图*.json`，清单以 README 为准）
3. 或者直接将 JSON 文件拖拽到 ComfyUI 界面

### 工作流节点说明
```
UnetLoaderGGUF → 加载 Q5_K_M.gguf 模型
     ↓
CLIPLoader → 加载 int8 文本编码器
     ↓
TextEncodeQwenImage21 → 编码图像和提示词（核心节点）
     ↓
KSampler → 采样生成（CFG: 4.0, Steps: 20）
     ↓
VAEDecode → 解码为图像
     ↓
SaveImage → 保存输出
```

### 使用步骤

> ⚠️ 下面这组参数是 2026-09-22 的状态，**现在已不同**：风格转换与极速档是 8 步 / cfg 1.0
> （Turbo LoRA），彩墨质量档 26 步 / cfg 3.2，文生图质量档 20 步 / cfg 3.5。当前值以工作流
> JSON 和 `README.md` 为准；cfg 1.0 下负向提示词不参与计算。

1. **加载输入图像**: 在 `LoadImage` 节点点击选择要编辑的图片
2. **编写提示词**: 在 `TextEncodeQwenImage21` 节点的 `prompt` 字段描述想要的效果
   - 示例: "Transform this image into a watercolor painting style"
   - 示例: "Add a sunset background while keeping the main subject"
   - 示例: "Convert to anime style, maintain composition"
3. **调整参数**:
   - `resolution`: 1024（参考图像会被缩放到此分辨率）
   - `steps`: 20（质量与速度的平衡）
   - `cfg`: 4.0（提示词引导强度）
   - `seed`: 随机或固定值
4. **点击 Queue Prompt** 开始生成

### 提示词技巧
- 描述你想要的**风格变化**或**编辑效果**
- 保持简洁，避免过长描述
- 可以指定保持某些元素："keeping the main subject"
- 支持中文提示词，但英文效果更稳定

### 显存优化（12GB 配置）
启动脚本已配置 `--lowvram` 参数，会自动：
- 分块加载模型到显存
- 文本编码器使用 int8 量化版本（节省约 8GB）
- 自动管理显存分配

如果仍然遇到显存不足：
1. 降低 `resolution` 到 768 或 512
2. 减少 `steps` 到 15
3. 关闭其他占用显存的程序

## 常见问题

### Q: 下载中断怎么办？
A: 重新运行下载命令，curl 会断点续传：
```bash
cd /d/ai/comfyui-gen-img-workflows-win/models/diffusion_models
curl -L -C - -o qwen-image-2.1-Q5_K_M.gguf "https://hf-mirror.com/abenzerps/Qwen-Image-2.1-GGUF/resolve/main/qwen-image-2.1-Q5_K_M.gguf"
```

### Q: 节点显示红色怎么办？
A: 先看是不是缺自定义节点（`custom_nodes/comfyui-style-prompt/`、`custom_nodes/ComfyUI-GGUF` + 补丁），
改过节点代码要**重启** ComfyUI。运行时文件不在仓库里，别在根目录 `git pull`（那拉的是资产仓库）。

### Q: 生成的图像质量不好？
A: 调整以下参数：
- 增加 `steps` 到 30-40
- 调整 `cfg` 在 3.5-5.0 之间
- 使用更详细的提示词
- 尝试不同的量化版本（Q4_K_M 或 Q6_K）

### Q: 可以使用其他量化版本吗？
A: 可以，修改 `UnetLoaderGGUF` 节点的模型名称：
- `qwen-image-2.1-Q4_K_M.gguf` (4.4GB) - 更快，质量略低
- `qwen-image-2.1-Q6_K.gguf` (5.6GB) - 更高质量，需要更多显存
- `qwen-image-2.1-Q8_0.gguf` (7.2GB) - 最高质量，12GB 显存可能不足

## 手动下载命令（如需重新下载）

```bash
# 设置镜像
export HF_ENDPOINT=https://hf-mirror.com

# 下载 GGUF 模型（Q5_K_M，推荐 12GB 显存）
cd /d/ai/comfyui-gen-img-workflows-win/models/diffusion_models
curl -L -o qwen-image-2.1-Q5_K_M.gguf "https://hf-mirror.com/abenzerps/Qwen-Image-2.1-GGUF/resolve/main/qwen-image-2.1-Q5_K_M.gguf"

# 下载文本编码器（int8 量化）
cd /d/ai/comfyui-gen-img-workflows-win/models/text_encoders
curl -L -o qwen3vl_8b_int8_convrot.safetensors "https://hf-mirror.com/abenzerps/Qwen-Image-2.1-GGUF/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors"

# VAE 已下载完成
# /d/ai/comfyui-gen-img-workflows-win/models/vae/qwen_image_2.1_vae_bf16.safetensors
```

## 更新与维护

### 更新 ComfyUI 运行时
运行时由 `scripts/prepare.py` 浅克隆到根目录且不带 `.git`，所以**不能在这里 `git pull`**。
要更新就删掉运行时文件（`main.py`、`comfy*/`、`nodes.py` 等）后重跑 `python scripts/prepare.py`。

### 更新自定义节点
```bash
cd /d/ai/comfyui-gen-img-workflows-win/custom_nodes/ComfyUI-GGUF
git pull
```

⚠️ 重新拉取 ComfyUI-GGUF 会**冲掉本仓库的架构补丁**，必须按 `patches/README.md` 重新打
（基线 city96/ComfyUI-GGUF @ `6ea2651e`），否则 Q5_K_M 权重会报 `Unknown model architecture!`。

## 参考资源
- ComfyUI 官方文档: https://docs.comfy.org
- Qwen-Image-2.1 模型: https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF
- ComfyUI-GGUF 节点: https://github.com/city96/ComfyUI-GGUF

---
**注意**: Qwen-Image-2.1 遵循 Qwen Research License，仅限研究和非商业用途。
