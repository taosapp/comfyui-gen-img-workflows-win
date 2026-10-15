# -*- coding: utf-8 -*-
"""提交 **API 格式**（扁平 dict）的 ComfyUI prompt 并等待完成。

与 run_workflow_json.py 的区别：那个吃前端画布工作流 JSON（nodes/links，需要转换），
这个直接吃 API 格式，适合做单变量实验（改一个参数跑一次）。

用法:
    python submit_api.py <api_prompt.json> [--timeout 1800]

API 格式示例:
    {"3": {"class_type": "KSampler", "inputs": {"seed": 42, ...}}}
需要 ComfyUI 已在 127.0.0.1:8188 运行。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(k, None)

BASE = "http://127.0.0.1:8188"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(path, payload=None, timeout=120):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_json")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    with open(args.prompt_json, "r", encoding="utf-8") as f:
        prompt = json.load(f)

    label = args.label or os.path.basename(args.prompt_json)
    print("提交: %s  (%d 个节点)" % (label, len(prompt)))

    res = http_json("/prompt", {"prompt": prompt, "client_id": "submit_api"})
    pid = res.get("prompt_id")
    if not pid:
        print("!! 提交失败:", json.dumps(res, ensure_ascii=False)[:2000])
        return 1
    print("prompt_id =", pid)

    t0 = time.time()
    while time.time() - t0 < args.timeout:
        time.sleep(3)
        hist = http_json("/history/" + pid)
        if pid in hist:
            h = hist[pid]
            status = h.get("status", {})
            if status.get("status_str") == "error" or not status.get("completed", True):
                msgs = status.get("messages", [])
                print("!! 执行报错，耗时 %.0fs" % (time.time() - t0))
                for m in msgs[-4:]:
                    print("   ", json.dumps(m, ensure_ascii=False)[:1200])
                return 2
            print("完成，耗时 %.1fs" % (time.time() - t0))
            for nid, out in h.get("outputs", {}).items():
                for key in ("images", "gifs", "videos"):
                    for item in out.get(key, []) or []:
                        print("  产物: %s/%s" % (item.get("subfolder", ""), item.get("filename")))
            return 0
    print("!! 超时 %ds" % args.timeout)
    return 3


if __name__ == "__main__":
    sys.exit(main())
