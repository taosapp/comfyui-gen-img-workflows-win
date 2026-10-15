"""start_comfyui.bat 自检脚本。

只验证「环境探测」与「降级」逻辑，不会真正启动 ComfyUI：
把启动行临时替换成打印，跑完即删。

用法：
    python scripts/launcher/selftest.py

覆盖两个场景：
  1. 默认环境（comfyui 存在）      -> 应精确定位到 envs\\comfyui\\python.exe
  2. 指定一个不存在的环境名        -> 应给出警告 + 明确报错，而不是拿别的 python 硬跑
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / "start_comfyui.bat"


def dry_run(args, tag):
    """生成一份「只探测不启动」的副本并执行，返回 (rc, 输出)。"""
    src = BAT.read_text(encoding="gbk")
    dry = src.replace(
        '"!PYEXE!" main.py %COMFY_ARGS%',
        'echo [DRYRUN] "!PYEXE!" main.py %COMFY_ARGS%',
    ).replace("\npause\n", "\n")
    tmp = ROOT / ("_selftest_%s.bat" % tag)
    tmp.write_bytes(dry.replace("\n", "\r\n").encode("gbk"))
    try:
        proc = subprocess.run(
            ["cmd", "/c", tmp.name] + args,
            cwd=str(ROOT), capture_output=True, timeout=600,
        )
        return proc.returncode, (proc.stdout + proc.stderr).decode("gbk", errors="replace")
    finally:
        tmp.unlink(missing_ok=True)


results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("   " + detail) if detail else ""))


print("[1] 默认环境")
rc, out = dry_run([], "ok")
check("退出码为 0", rc == 0, "rc=%s" % rc)
check("定位到 conda.bat", "conda.bat" in out)
check("解释器落在 envs\\comfyui", "envs\\comfyui\\python.exe" in out)
check("未出现错误/警告", "[错误]" not in out and "[警告]" not in out)
check("走到启动行（DRYRUN）", "[DRYRUN]" in out)
if "[错误]" in out or "[警告]" in out:
    print("  --- 输出 ---")
    print("\n".join("  | " + l for l in out.splitlines()))

print("[2] 指定不存在的环境名")
rc, out = dry_run(["no_such_env"], "bad")
check("退出码为 0（不崩）", rc == 0, "rc=%s" % rc)
check("有激活失败警告", "[警告]" in out)
check("有明确错误提示", "[错误]" in out)
check("没有误用其它 python 启动", "[DRYRUN]" not in out)

failed = [n for n, ok in results if not ok]
print()
if failed:
    print("FAILED: %d 项 -> %s" % (len(failed), failed))
    sys.exit(1)
print("ALL PASS (%d 项)" % len(results))
