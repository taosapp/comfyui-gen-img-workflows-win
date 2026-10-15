# -*- coding: utf-8 -*-
"""把 workflows/图片风格转换.json 升级为「双档位」（幂等，可重复运行）：

  极速档（默认）：UnetLoaderGGUF → LoraLoaderBypassModelOnly → QwenImage21Cache → KSampler
                  KSampler 8 步 / cfg 1.0
  质量档（一键切）：选中 LoRA 节点按 Ctrl+B 绕过，⑥ 步数 12 / cfg 3.5

只动三处：① 插入 LoRA 节点（id 16）并改链接；② KSampler 参数；③ 挪一下缓存节点位置。
便签由 patch_style_workflow.py 单独负责。

⚠️ 连线号（link id）必须动态取最大值 +1：原文件的 `last_link_id` 曾与实际不符（22 vs 23），
   硬编码新号会与「⑬→⑤ negative」那条撞车，导致 ⑤ 的 negative_prompt 接到 LoRA 的输出上
   （POST /prompt 直接 400）。

用法:  python upgrade_style_turbo.py [--revert]
       --revert  回到原始单档（删 LoRA 节点并还原 KSampler 12 步 / cfg 3.5）
"""
import argparse
import json
import os
from collections import Counter

WF = os.path.join("workflows", "图片风格转换.json")
LORA = "qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors"
LORA_ID = 16
UNET_ID, CACHE_ID, KS_ID = 1, 14, 6
TURBO_WV = [42, "randomize", 8, 1.0, "euler", "beta", 1.0]
BASE_WV = [42, "randomize", 12, 3.5, "euler", "beta", 1.0]


def next_link_id(wf):
    return max([l[0] for l in wf["links"]] + [wf.get("last_link_id", 0)]) + 1


def link_between(wf, src, dst):
    for l in wf["links"]:
        if l[1] == src and l[3] == dst:
            return l
    return None


def check(wf, label):
    errs = 0
    b = {n["id"]: n for n in wf["nodes"]}
    ids = [l[0] for l in wf["links"]]
    if len(ids) != len(set(ids)):
        errs += 1
        print("连线号重复:", [k for k, c in Counter(ids).items() if c > 1])
    for lid, src, ss, dst, ds, typ in wf["links"]:
        so, di = b[src]["outputs"][ss], b[dst]["inputs"][ds]
        if so["type"] != typ or di["type"] != typ:
            errs += 1; print("类型错", lid)
        if lid not in so["links"]:
            errs += 1; print("出端缺 link", lid)
        if di.get("link") != lid:
            errs += 1; print("入端 link 不匹配", lid, "->", dst, ds, di.get("link"))
    used = {l for n in wf["nodes"] for o in (n.get("outputs") or [])
            for l in (o.get("links") or [])}
    if used != set(ids):
        errs += 1; print("links 表与节点 outputs 不一致", used ^ set(ids))
    dup = [k for k, c in Counter((l[3], l[4]) for l in wf["links"]).items() if c > 1]
    if dup:
        errs += 1; print("重复入线", dup)
    # 关键语义：⑤ 的 negative_prompt 必须来自 ⑬ 的 negative 口，不能接到 LoRA
    neg = next(i.get("link") for i in b[5]["inputs"] if i["name"] == "negative_prompt")
    src_link = next(l for l in wf["links"] if l[0] == neg)
    if (src_link[1], src_link[2]) != (13, 1):
        errs += 1; print("⑤ negative_prompt 来源错:", src_link)
    print(label, "自检错误数:", errs, "| 节点:", len(wf["nodes"]), "| 连线:", len(wf["links"]))
    return errs


def main(args):
    with open(WF, encoding="utf-8") as fh:
        wf = json.load(fh)
    b = {n["id"]: n for n in wf["nodes"]}
    ks, cache, unet = b[KS_ID], b[CACHE_ID], b[UNET_ID]

    if args.revert:
        if LORA_ID not in b:
            print("没有 LoRA 节点，无需还原"); return 0
        wf["nodes"] = [n for n in wf["nodes"] if n["id"] != LORA_ID]
        wf["links"] = [l for l in wf["links"] if l[1] != LORA_ID and l[3] != LORA_ID]
        direct = link_between(wf, UNET_ID, CACHE_ID)
        if direct is None:
            nid = next_link_id(wf)
            wf["links"].append([nid, UNET_ID, 0, CACHE_ID, 0, "MODEL"])
            unet["outputs"][0]["links"] = [nid]
            cache["inputs"][0]["link"] = nid
        ks["widgets_values"] = list(BASE_WV)
        cache["pos"] = [380, 340]
    elif LORA_ID in b:
        # 已升级：只校正接线与参数（连线号一律沿用现有 id）
        lin = link_between(wf, UNET_ID, LORA_ID)
        lout = link_between(wf, LORA_ID, CACHE_ID)
        if lin is None or lout is None:
            print("接线不完整，请先 --revert 再重跑"); return 1
        unet["outputs"][0]["links"] = [lin[0]]
        b[LORA_ID]["inputs"][0]["link"] = lin[0]
        b[LORA_ID]["outputs"][0]["links"] = [lout[0]]
        cache["inputs"][0]["link"] = lout[0]
        cache["pos"] = [380, 440]
        ks["widgets_values"] = list(TURBO_WV)
        print("已升级过：接线 / 参数已校正（连线号 %d → %d）" % (lin[0], lout[0]))
    else:
        # 1) 把「① → ⑭」直连改成「① → ⑯」
        direct = link_between(wf, UNET_ID, CACHE_ID)
        nid = next_link_id(wf)                       # 动态取号，避免撞车
        if direct is None:
            wf["links"].append([nid, UNET_ID, 0, LORA_ID, 0, "MODEL"])
            lin_id = nid
        else:
            direct[3], direct[4] = LORA_ID, 0         # 复用原连线号，只改终点
            lin_id = direct[0]
        wf["links"].append([nid, LORA_ID, 0, CACHE_ID, 0, "MODEL"])
        # 2) 插入 LoRA 节点
        wf["nodes"].append({
            "id": LORA_ID, "type": "LoraLoaderBypassModelOnly",
            "pos": [380, 340], "size": [460, 82], "flags": {}, "order": 5, "mode": 0,
            "inputs": [{"name": "model", "type": "MODEL", "link": lin_id}],
            "outputs": [{"name": "MODEL", "type": "MODEL", "links": [nid], "slot_index": 0}],
            "properties": {"Node name for S&R": "LoraLoaderBypassModelOnly"},
            "widgets_values": [LORA, 1.0],
            "title": "⑯ 极速档 Turbo LoRA（Ctrl+B 绕过 = 回到质量档）",
        })
        unet["outputs"][0]["links"] = [lin_id]
        cache["inputs"][0]["link"] = nid
        cache["pos"] = [380, 440]
        wf["last_node_id"] = max(wf["last_node_id"], LORA_ID)
        wf["last_link_id"] = max(nid, lin_id)
        # 3) KSampler → 8 步 / cfg 1.0
        ks["widgets_values"] = list(TURBO_WV)
        print("已插入 LoRA 节点 id=%d（连线 %d → %d），KSampler = %s"
              % (LORA_ID, lin_id, nid, TURBO_WV[2:4]))

    errs = check(wf, "图片风格转换")
    with open(WF, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=2)
    print("已写入", WF)
    return errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true", help="还原成原始单档工作流")
    raise SystemExit(0 if main(ap.parse_args()) == 0 else 1)
