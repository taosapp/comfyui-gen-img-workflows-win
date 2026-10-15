# -*- coding: utf-8 -*-
"""把 ComfyUI 前端工作流 JSON 转成 API prompt 并提交执行，用于无头验证工作流是否真能跑通。

用法:
    python run_workflow_json.py <workflow.json> [--timeout 3600] [--keep]

说明:
    - 纯验证工具。项目日常使用仍走 start_comfyui.bat + 浏览器画布。
    - 需要 ComfyUI 已在 127.0.0.1:8188 运行。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(k, None)

BASE = "http://127.0.0.1:8188"
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COMFY_DYNAMICCOMBO_V3"}
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(path, payload=None, method=None, timeout=120):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    with _opener.open(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except Exception:
        return body


def is_widget(tp):
    """tp 为 object_info 里的 [类型, 选项] 结构。链接型输入的类型是字符串名，控件是 STRING/INT/... 或选项列表。"""
    first = tp[0] if isinstance(tp, list) and tp else tp
    if isinstance(first, list):
        return True                       # COMBO：选项直接以列表给出
    return isinstance(first, str) and first in WIDGET_TYPES


def type_name(tp):
    first = tp[0] if isinstance(tp, list) and tp else tp
    if isinstance(first, list):
        return "COMBO"
    return str(first)


def options_of(tp):
    first = tp[0] if isinstance(tp, list) and tp else tp
    return first if isinstance(first, list) else None


def to_api(wf, obj):
    """前端 JSON -> API prompt。返回 (prompt, 警告列表)。"""
    warns = []
    linkmap = {}
    for L in wf.get("links", []):
        lid, src, sslot, dst, dslot, ltype = L
        linkmap[lid] = (src, sslot)

    out = {}
    for n in wf["nodes"]:
        nid, ntype = n["id"], n["type"]
        if n.get("mode") in (2, 4):       # 2=muted, 4=bypass
            warns.append(f"节点 {nid}({ntype}) 处于静音/绕过状态，仍按原样转换")
        info = obj.get(ntype)
        if info is None:
            warns.append(f"节点 {nid} 类型 {ntype} 在当前实例中不存在（缺自定义节点？）")
            continue

        spec = info.get("input", {})
        ordered = list((spec.get("required") or {}).items()) + list((spec.get("optional") or {}).items())

        inputs = {}
        # 1) 连线输入：前端 node.inputs 里 link 非空的项
        linked_names = set()
        for i in n.get("inputs", []):
            lid = i.get("link")
            if lid is None:
                continue
            name = i.get("name")
            if lid not in linkmap:
                warns.append(f"节点 {nid}({ntype}) 输入 {name} 指向不存在的链接 {lid}")
                continue
            src, sslot = linkmap[lid]
            inputs[name] = [str(src), sslot]
            linked_names.add(name)

        # 2) 控件值：按 object_info 顺序分配 widgets_values，跳过 control_after_generate 占位
        wv = list(n.get("widgets_values") or [])
        cur = 0
        for name, tp in ordered:
            if not is_widget(tp):
                continue
            if name in linked_names:
                # 控件被转换成了输入（如 prompt 接了风格选择器）：前端仍会把它的值存在 widgets_values 里，
                # 只是运行时由连线覆盖。所以这里必须照样推进游标，否则后面所有控件都会整体串位。
                cur += 1
                continue
            if cur >= len(wv):
                opts = tp[1] if isinstance(tp, list) and len(tp) > 1 and isinstance(tp[1], dict) else {}
                if "default" in opts:
                    inputs[name] = opts["default"]
                    warns.append(f"节点 {nid}({ntype}) 控件 {name} 缺少值，使用 default={opts['default']!r}")
                    continue
                warns.append(f"节点 {nid}({ntype}) 控件 {name} 缺少值且无 default")
                continue
            val = wv[cur]
            cur += 1
            if name == "seed" or name.endswith("_seed"):
                opts = tp[1] if isinstance(tp, list) and len(tp) > 1 and isinstance(tp[1], dict) else {}
                if opts.get("control_after_generate") and cur < len(wv):
                    cur += 1              # 跳过前端插入的 control_after_generate 值
            inputs[name] = val

        if cur < len(wv):
            warns.append(f"节点 {nid}({ntype}) 有 {len(wv) - cur} 个多余的 widgets_values 未使用"
                         f"（前端的隐藏控件，通常可忽略）: {wv[cur:]}")

        # 3) 校验必填项齐全（自动增长型输入 images 在 API 里展开成 images.image_1 这类键）
        for name, tp in (spec.get("required") or {}).items():
            ok = name in inputs or any(k.startswith(name + ".") for k in inputs)
            if not ok:
                warns.append(f"节点 {nid}({ntype}) 缺少必填输入 {name}({type_name(tp)})")

        out[str(nid)] = {"class_type": ntype, "inputs": inputs}
    return out, warns


def run(prompt, timeout=3600, poll=3.0):
    t0 = time.perf_counter()
    res = http_json("/prompt", {"prompt": prompt, "client_id": "wfcheck"})
    if isinstance(res, str) or "prompt_id" not in res:
        return None, None, res
    pid = res["prompt_id"]
    while True:
        if time.perf_counter() - t0 > timeout:
            return pid, None, "超时"
        try:
            h = http_json(f"/history/{pid}")
        except urllib.error.URLError as e:
            h = None
            last = f"轮询异常 {e}"
        if h and pid in h:
            entry = h[pid]
            status = entry.get("status", {})
            if status.get("completed") or status.get("status_str") in ("success", "error"):
                elapsed = time.perf_counter() - t0
                if status.get("status_str") == "error" or not status.get("completed"):
                    return pid, elapsed, status
                return pid, elapsed, entry
        time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("--timeout", type=float, default=3600)
    ap.add_argument("--dump", action="store_true", help="打印转换后的 API prompt")
    args = ap.parse_args()

    wf = json.load(open(args.workflow, encoding="utf-8"))
    obj = http_json("/object_info", timeout=300)
    prompt, warns = to_api(wf, obj)

    print(f"工作流: {args.workflow}")
    print(f"节点数: {len(wf['nodes'])}  转换后: {len(prompt)}")
    print("关键链路:")
    for nid, node in sorted(prompt.items(), key=lambda z: int(z[0])):
        ins = {k: v for k, v in node["inputs"].items() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)}
        print(f"  {nid:>3} {node['class_type']:<24} 连线入={ins}")
    if warns:
        print("警告:")
        for w in warns:
            print("  [!!] " + w)
    else:
        print("警告: 无")
    if args.dump:
        print(json.dumps(prompt, ensure_ascii=False, indent=1))

    print("提交执行 ...")
    pid, elapsed, res = run(prompt, timeout=args.timeout)
    if elapsed is None and pid:
        print(f"失败: {res}")
        return 2
    if isinstance(res, str):
        print(f"提交被拒绝: {res[:800]}")
        return 2
    if pid and isinstance(res, dict) and "status" in res:
        st = res.get("status") or {}
        # 成功返回的 history 条目同样带 "status" 键，必须看内容而不是只看键是否存在
        if st.get("status_str") == "error" or not st.get("completed"):
            print(f"执行报错, 耗时 {elapsed:.1f}s")
            print(json.dumps(res, ensure_ascii=False, indent=1)[:2000])
            return 3
    print(f"完成，耗时 {elapsed:.1f}s")
    outs = res.get("outputs", {})
    for nid, o in outs.items():
        if o.get("images"):
            for im in o["images"]:
                print(f"  产物: {im.get('subfolder')}/{im.get('filename')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
