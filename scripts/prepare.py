#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键准备脚本：新电脑 git clone 本仓库后，用任意 Python 3.9+ 跑一次即可。

    python scripts/prepare.py            # 完整准备（缺什么补什么，大模型下载前会询问）
    python scripts/prepare.py --check    # 只检查不安装/不下载
    python scripts/prepare.py --yes      # 下载模型不再逐个询问

它做五件事：
  1. 运行环境：优先找/建 conda 环境 comfyui（python 3.12），没有 conda 就退而建项目内 .venv；
  2. 上游运行时：本仓库只跟踪策划资产，若 main.py 缺失则浅克隆官方 ComfyUI 补齐；
  3. 依赖：安装 pytorch（NVIDIA 为 cu126 版）与 ComfyUI requirements.txt；
  4. 自定义节点：克隆 ComfyUI-GGUF 并打上 patches/ 里的 Qwen-Image 架构补丁；
  5. 模型：按下方清单检查 models/，缺失的可自动从 hf-mirror 下载（支持断点续传）。

只用标准库，不要求预先装任何包。国内网络默认走 hf-mirror.com，可用环境变量 HF_MIRROR 覆盖。
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF_MIRROR = os.environ.get("HF_MIRROR", "https://hf-mirror.com").rstrip("/")
CONDA_ENV = "comfyui"
GGUF_URL = "https://github.com/city96/ComfyUI-GGUF"
UPSTREAM = "https://github.com/comfyanonymous/ComfyUI"

# ---- 模型清单（文件名必须与工作流加载器里的一致，一字不差）-----------------
# 只列图片工作流需要的模型；视频（MiniMax-H3）相关已于 2026-10-15 从本仓库移除。
# url=None 的条目无法自动下载，脚本会给出获取指引。
MODELS = [
    # -- Qwen-Image-2.1 文生图 / 图片风格转换 --
    dict(path="models/diffusion_models/qwen-image-2.1-Q5_K_M.gguf", size="4.9G",
         url=HF_MIRROR + "/unsloth/Qwen-Image-2.1-GGUF/resolve/main/qwen-image-2.1-Q5_K_M.gguf"),
    dict(path="models/text_encoders/qwen3vl_8b_int8_convrot.safetensors", size="8.8G",
         url=HF_MIRROR + "/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors"),
    dict(path="models/vae/qwen_image_2.1_vae_bf16.safetensors", size="0.7G",
         url=HF_MIRROR + "/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors"),
    # -- Qwen-Image-Layered 分层文生图 --
    dict(path="models/diffusion_models/qwen-image-layered-Q4_K_S.gguf", size="12G",
         url=HF_MIRROR + "/unsloth/Qwen-Image-Layered-GGUF/resolve/main/qwen-image-layered-Q4_K_S.gguf"),
    dict(path="models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", size="8.8G",
         url=None,
         note="Comfy-Org 社区重打包版；在 HF 搜索 qwen_2.5_vl_7b_fp8_scaled 获取，"
              "或下载官方 Qwen2.5-VL-7B-Instruct-FP8 后按 ComfyUI 文档改名"),
    dict(path="models/vae/qwen_image_layered_vae.safetensors", size="0.3G",
         url=HF_MIRROR + "/Comfy-Org/Qwen-Image-Layered_ComfyUI/resolve/main/split_files/vae/qwen_image_layered_vae.safetensors"),
    # -- BiRefNet 抠图 --
    dict(path="models/background_removal/birefnet.safetensors", size="0.5G",
         url=HF_MIRROR + "/Comfy-Org/BiRefNet/resolve/main/background_removal/birefnet.safetensors"),
    # -- Turbo 蒸馏 LoRA：彩墨极速版 / 图片风格转换极速版**必需**（缺它这两个工作流跑不了）--
    # 上游 Viggle/Qwen-Image-2.1-viggle-turbo（Qwen Research License，非商用）；
    # 本机已核对 SHA256 = 2bbf5b6c91d19ecb568a63d61ac490aa679a6a7bef14a68291abd386c0d4f77f
    dict(path="models/loras/qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors", size="0.9G",
         url=HF_MIRROR + "/t8star/Zen-Image-Edit-Comfy/resolve/main/viggle-v0.2.1/"
                         "qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors"),
]

ok = lambda s: print("  [OK]", s)
warn = lambda s: print("  [!!]", s)
do = lambda s: print("  [..]", s)


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kw)


# ---------------------------------------------------------------- 环境 ----
def conda_base():
    cands = []
    if os.environ.get("CONDA_EXE"):
        cands.append(Path(os.environ["CONDA_EXE"]).parent.parent)
    home = Path.home()
    for d in (home / "miniconda3", home / "anaconda3", Path("C:/miniconda3"),
              Path("C:/ProgramData/miniconda3"), home / "miniforge3"):
        cands.append(d)
    for d in cands:
        if (d / "condabin").exists() or (d / "Scripts" / "conda.exe").exists() or (d / "bin" / "conda").exists():
            return d
    return None


def env_python(conda):
    """返回现成环境的 python 路径；找不到返回 None。"""
    py = "python.exe" if os.name == "nt" else "python"
    cands = []
    if conda:
        cands.append(conda / "envs" / CONDA_ENV / py)
    venv = ROOT / ".venv"
    cands.append(venv / ("Scripts" if os.name == "nt" else "bin") / py)
    for p in cands:
        if p.exists():
            return p
    return None


def setup_env():
    conda = conda_base()
    if env_python(conda):
        ok("运行环境已存在: %s" % env_python(conda))
        return env_python(conda)
    if conda:
        do("创建 conda 环境 %s (python 3.12)" % CONDA_ENV)
        conda_exe = str(conda / ("Scripts" / "conda.exe" if os.name == "nt" else "bin" / "conda"))
        if run([conda_exe, "create", "-y", "-n", CONDA_ENV, "python=3.12"]).returncode != 0:
            warn("conda 建环境失败，改用项目内 .venv")
        else:
            return env_python(conda)
    do("未找到 conda，使用当前 Python 建项目内 .venv")
    run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    return env_python(conda)


def pip_install(env_py, *args):
    return run([env_py, "-m", "pip", "install", *args]).returncode == 0


def setup_deps(env_py):
    if platform.system() == "Darwin":
        do("安装 pytorch（macOS 用官方源）")
        pip_install(env_py, "torch", "torchvision", "torchaudio")
    else:
        do("安装 pytorch cu126（NVIDIA 显卡）")
        if not pip_install(env_py, "torch", "torchvision", "torchaudio",
                           "--index-url", "https://download.pytorch.org/whl/cu126"):
            warn("cu126 安装失败，请检查显卡/驱动后重试")
    req = ROOT / "requirements.txt"
    if req.exists():
        do("安装 ComfyUI requirements.txt")
        pip_install(env_py, "-r", str(req))
    else:
        warn("requirements.txt 不存在（先完成上游运行时步骤）")


# ---------------------------------------------------------- 上游运行时 ----
def setup_upstream():
    if (ROOT / "main.py").exists():
        ok("上游 ComfyUI 运行时已就位")
        return
    do("本仓库只含策划资产，开始浅克隆官方 ComfyUI 补齐运行时")
    tmp = ROOT / "_upstream_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    if run(["git", "clone", "--depth", "1", UPSTREAM, str(tmp)]).returncode != 0:
        warn("克隆失败，请检查网络后重试")
        return
    for item in tmp.iterdir():
        if item.name == ".git":
            continue  # 上游 .git 不需要；将来更新可重跑本步
        shutil.move(str(item), str(ROOT / item.name))
    shutil.rmtree(tmp, ignore_errors=True)
    ok("上游运行时已就位")


# ------------------------------------------------------------ GGUF 节点 ----
def setup_gguf():
    dst = ROOT / "custom_nodes" / "ComfyUI-GGUF"
    if not dst.exists():
        do("克隆 ComfyUI-GGUF")
        if run(["git", "clone", GGUF_URL, str(dst)]).returncode != 0:
            warn("克隆失败，跳过补丁步骤")
            return
    patch = ROOT / "patches" / "comfyui-gguf-add-qwen-image-arch.patch"
    chk = run(["git", "-C", str(dst), "apply", "--check", str(patch)], capture_output=True)
    if chk.returncode == 0:
        run(["git", "-C", str(dst), "apply", str(patch)], check=True)
        ok("已打上 Qwen-Image 架构补丁")
    else:
        rev = run(["git", "-C", str(dst), "apply", "--check", "-R", str(patch)], capture_output=True)
        ok("补丁已打过" if rev.returncode == 0 else "补丁不适用（上游代码变动？见 patches/README.md）")
    req = dst / "requirements.txt"
    if req.exists():
        do("安装 ComfyUI-GGUF requirements.txt")
        pip_install(env_python(conda_base()), "-r", str(req))


# ---------------------------------------------------------------- 模型 ----
def human(n):
    return "%.1fGB" % (n / 1024**3)


def check_models():
    missing = []
    for m in MODELS:
        p = ROOT / m["path"]
        if p.exists() and p.stat().st_size > 1024 * 1024:
            ok("%s (%s)" % (m["path"], human(p.stat().st_size)))
        else:
            missing.append(m)
            warn("缺失 %s (约 %s)" % (m["path"], m["size"]))
    return missing


def download(m, always_yes):
    p = ROOT / m["path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    if not m.get("url"):
        warn("无自动下载地址：%s\n      %s" % (m["path"], m.get("note", "")))
        return False
    if not always_yes:
        try:
            if input("      下载 %s (约 %s)? [y/N] " % (m["path"], m["size"])).strip().lower() != "y":
                warn("跳过 %s" % m["path"])
                return False
        except EOFError:
            return False
    do("curl 下载（支持断点续传，中断后重跑本脚本可续）")
    cmd = ["curl", "-L", "-C", "-", "--retry", "3", "--retry-delay", "2", "-o", str(p), m["url"]]
    if not os.environ.get("PROXY"):
        cmd += ["--noproxy", "*"]
    return run(cmd).returncode == 0 and p.exists()


# ---------------------------------------------------------------- 主流程 ----
def main():
    ap = argparse.ArgumentParser(description="ComfyUI 工作流仓库一键准备")
    ap.add_argument("--check", action="store_true", help="只检查，不安装不下载")
    ap.add_argument("--yes", action="store_true", help="下载模型不询问")
    ap.add_argument("--skip-models", action="store_true", help="跳过模型检查/下载")
    args = ap.parse_args()

    print("== 项目准备（根目录 %s）==" % ROOT)
    print("== 1/5 运行环境 ==")
    env_py = setup_env()
    if env_py is None:
        warn("没有可用的 Python 环境，后续步骤无法继续")
        return 1

    print("== 2/5 上游运行时 ==")
    setup_upstream()

    print("== 3/5 依赖 ==")
    if not args.check:
        setup_deps(env_py)
    else:
        ok("（--check 跳过安装）")

    print("== 4/5 ComfyUI-GGUF 节点与补丁 ==")
    if args.check:
        ok("已就位" if (ROOT / "custom_nodes/ComfyUI-GGUF").exists() else "缺失（--check 跳过安装）")
    else:
        setup_gguf()

    print("== 5/5 模型 ==")
    missing = check_models()
    if missing and not args.check and not args.skip_models:
        for m in missing:
            download(m, args.yes)
        missing = check_models()

    print("== 完成 ==")
    if platform.system() == "Windows":
        print("启动：双击 start_comfyui.bat，或命令行运行它（首次会自动探测 conda/venv）")
    else:
        print("启动：bash start_comfyui_mac.sh（macOS；注意 int8_convrot 量化在 MPS 的兼容性未知，"
              "若加载失败请在工作流里换 bf16 权重）")
    if missing:
        print("仍缺 %d 个模型文件，见上方 [!!] 清单。" % len(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
