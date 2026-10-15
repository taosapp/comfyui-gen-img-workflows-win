"""重新生成仓库根目录的 start_comfyui.bat（GBK / CRLF）。

维护流程：
  1. 编辑 scripts/launcher/start_comfyui.src.txt（UTF-8，中文不会乱码）
  2. 在项目根目录运行 python scripts/launcher/rebuild.py
  3. 运行 start_comfyui.bat 验证

为什么需要转码：cmd.exe 在中文 Windows 下按 GBK(936) 解释 .bat 文件，
若把含中文的脚本存成 UTF-8，双击后提示信息就会是乱码。
"""

import shutil
from pathlib import Path

launcher = Path(__file__).resolve().parent
root = launcher.parents[1]
src_file = launcher / "start_comfyui.src.txt"
target = root / "start_comfyui.bat"
bak_dir = launcher / "backup"

src = src_file.read_text(encoding="utf-8")

# 只在首次生成时保留一份旧脚本备份
bak_dir.mkdir(exist_ok=True)
if target.exists() and not (bak_dir / "start_comfyui.bat.old").exists():
    shutil.copy2(target, bak_dir / "start_comfyui.bat.old")

# 编码成 GBK；出现无法表示的字符会在这里报错，属于预期保护
target.write_bytes(src.replace("\n", "\r\n").encode("gbk"))

back = target.read_bytes().decode("gbk")
print("written      :", target.name)
print("bytes        :", target.stat().st_size)
print("CRLF         :", b"\r\n" in target.read_bytes())
print("lines        :", len(back.splitlines()))
print("conda default:", "CONDA_ENV=comfyui" in back)
print("no hardcoded :", "D:\\ai\\ComfyUI" not in back and "miniconda3\\Scripts\\activate" not in back)

# 坑点自检：块内 echo 若含半角括号，会提前闭合 if 的括号块，整段脚本语法崩溃
bad = [l.strip() for l in back.splitlines()
       if l.strip().lower().startswith("echo") and ("(" in l or ")" in l)]
print("paren check  :", "OK" if not bad else "SUSPECT -> %r" % (bad,))
