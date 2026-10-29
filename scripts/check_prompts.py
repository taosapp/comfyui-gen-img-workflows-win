# -*- coding: utf-8 -*-
"""体检本项目自己的提示词，规则取自 Qwen-Image-2.1 官方提示词规范。

官方规范明确禁止在提示词里写空泛画质词（masterpiece / 8K / highly detailed /
award-winning 之类），要求用可观察的视觉描述代替；也不允许把分辨率、画幅比例
写进描述正文。本项目 3 个风格文件 + 各工作流的编码框正好是这类词的高发区，
所以做成脚本定期扫，避免手改时又加回去。

用法:
    python scripts/check_prompts.py            # 扫描全部
    python scripts/check_prompts.py -v         # 同时列出每段提示词的来源
"""
import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 官方 validate_prompt.py 里的禁用表 + 规范正文点名的几个
FORBIDDEN_BOOSTERS = [
    "8k", "4k", "masterpiece", "award-winning",
    "highly detailed", "best quality", "ultra-detailed", "high resolution",
]

# 描述正文里不该出现分辨率/比例/像素
RESOLUTION_PATTERNS = [
    (re.compile(r"\b\d{3,4}\s*[x×]\s*\d{3,4}\b"), "像素尺寸"),
    (re.compile(r"\b\d+\s*:\s*\d+\b"), "画幅比例"),
    (re.compile(r"\b\d+\s*[kK]\b"), "分辨率档位"),
]

NEG_SEPARATORS = ("---负向---", "---NEGATIVE---")


def strip_comments(text):
    """去掉行首 # / // 注释与 /* */ 块注释；行中 # 保留（护色值）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("#") or s.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def split_style(body):
    """风格文件 -> (正向, 负向)。没有分隔符时负向为空。"""
    for sep in NEG_SEPARATORS:
        if sep in body:
            pos, neg = body.split(sep, 1)
            return pos, neg
    return body, ""


def check_text(text, where, problems, verbose):
    if not text.strip():
        return

    low = text.lower()
    for word in FORBIDDEN_BOOSTERS:
        if re.search(r"\b" + re.escape(word) + r"\b", low):
            problems.append((where, f"空泛画质词「{word}」（官方规范禁止，用可观察描述代替）"))

    for pattern, label in RESOLUTION_PATTERNS:
        m = pattern.search(text)
        if m:
            problems.append((where, f"描述里出现{label}「{m.group(0)}」（比例/分辨率应交给画布参数）"))

    if text.count('"') % 2:
        problems.append((where, "双引号不配对（图上文字必须成对加直双引号）"))


def check_styles(problems, verbose):
    files = sorted(glob.glob(os.path.join(ROOT, "styles", "*.txt")))
    for path in files:
        name = os.path.basename(path)
        if name.startswith(("_", ".")):
            continue
        body = strip_comments(open(path, encoding="utf-8").read())
        pos, neg = split_style(body)
        check_text(pos, f"styles/{name} 正向", problems, verbose)
        # 负向里写画质词是合理的（"low quality" 之类），只查比例/分辨率
        for pattern, label in RESOLUTION_PATTERNS:
            m = pattern.search(neg)
            if m:
                problems.append((f"styles/{name} 负向",
                                 f"出现{label}「{m.group(0)}」"))
        if verbose:
            print(f"    扫描 styles/{name}: 正向 {len(pos)} / 负向 {len(neg)} 字符")


def check_workflows(problems, verbose):
    for path in sorted(glob.glob(os.path.join(ROOT, "workflows", "*.json"))):
        name = os.path.basename(path)
        try:
            wf = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            problems.append((f"workflows/{name}", f"无法解析: {e}"))
            continue
        for node in wf.get("nodes", []):
            if node.get("type") != "TextEncodeQwenImage21":
                continue
            vals = node.get("widgets_values") or []
            if not vals:
                continue
            check_text(str(vals[0]), f"workflows/{name} 节点{node['id']} 正向", problems, verbose)
            if verbose:
                print(f"    扫描 workflows/{name} 节点{node['id']}: {len(str(vals[0]))} 字符")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    problems = []
    if args.verbose:
        print("扫描中 ...")
    check_styles(problems, args.verbose)
    check_workflows(problems, args.verbose)

    print()
    if not problems:
        print("OK 提示词符合 Qwen-Image-2.1 规范，无空泛画质词与比例残留。")
        return 0

    # 同一个词既算空泛画质词又算分辨率档位时只报一次（8k / 4k 会命中两条规则）
    seen = set()
    unique = []
    for where, msg in problems:
        m = re.search(r"「(.+?)」", msg)
        key = (where, m.group(1).lower() if m else msg)
        if key in seen:
            continue
        seen.add(key)
        unique.append((where, msg))

    print(f"发现 {len(unique)} 处问题：")
    for where, msg in unique:
        print(f"  [{where}] {msg}")
    print("\n说明：这些规则来自阿里官方 Qwen-Image-2.1 提示词改写规范，")
    print("      空泛画质词不提供可执行的视觉信息，反而会把风格拉偏。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
