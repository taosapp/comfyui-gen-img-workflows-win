# -*- coding: utf-8 -*-
"""风格库读写 + 风格提示词选择器节点。

风格库位置：ComfyUI 根目录下的 styles/ 文件夹（可用环境变量 COMFYUI_STYLE_DIR 覆盖）
    文件名（去掉「01-」这类序号前缀）= 下拉框里显示的风格名
    文件内容                          = 该风格的提示词
例如： styles/01-水彩画.txt 、 styles/02-简笔画.txt

数字前缀只用来排序，不会出现在选择框里；文件名以 _ 或 . 开头的文件会被忽略
（所以可以放 _说明.txt）。

风格文件内容支持注释，读取时自动剔除（2026-09-28 新增）：
    行首（允许空白）的 # 或 // 整行忽略；/* ... */ 块注释跨行剔除。
    行中间的 # 不算注释（避免误伤 #ff0000 这类色值）。
    想临时停用某段提示词：把它单独放一行，行首加 # 即可。

风格文件支持负向提示词段（2026-09-29 新增）：
    文件里写一行 ---负向--- （或 ---NEGATIVE---），其后的内容作为该风格的
    负向提示词，从节点第二个输出送出；之前的所有内容仍是正向提示词。
    没写分隔符的文件，负向输出为空串。

分工（2026-09-29 定稿，2026-10-15 负向框已删除）：
    风格库 .txt = 这类需求的**通用规则**（怎么写、修到什么程度、不许改什么）；
    节点上的「describe」文本框 = **这一张照片的个体信息**（人物、人数、
    年龄、年代、服饰……），追加到库正向之后。改通用规则改文件，
    改单张照片的信息改界面，两边都不用动另一处。

    负向已移除（2026-10-15）：极速档 cfg 1.0 下负向不参与采样计算
    （comfy/samplers.py:610 把 uncond_ 置 None），留着控件只会让人以为
    「写进去就能去掉东西」。要去掉什么，直接写进 describe。
    风格文件里的 ---负向--- 段不再送出（保留解析，避免历史文件报错）。

自定义模式（2026-10-12 新增）：
    下拉里的第一项「自定义（只用下面这个框）」不读风格库，describe 框的内容
    原样作为最终正向提示词送出（前面不加任何库内容、不做任何拼接）。
    适合「这一次就是要手写完整提示词」的场合——不用为了跑一次而去建一个风格文件。
"""

import logging
import os
import re

LOG = logging.getLogger("style-prompt")


def _comfy_root():
    # <root>/custom_nodes/comfyui-style-prompt/nodes.py  ->  <root>
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


STYLE_DIR = os.environ.get("COMFYUI_STYLE_DIR") or os.path.join(_comfy_root(), "styles")
STYLE_EXTS = (".txt", ".md", ".prompt")
# 下拉里的第一项：不读风格库，两个文本框原样当正/负向提示词用。
# 名字会出现在下拉框里，改这里即可（不要与风格库文件名重名）。
CUSTOM_STYLE = "自定义（只用下面这个框）"
_ORDER_PREFIX = re.compile(r"^\s*\d+\s*[-_.、)）．\s]*\s*")
_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def display_name(stem):
    """文件名去掉序号前缀 = 风格名。"""
    return _ORDER_PREFIX.sub("", stem).strip() or stem


def library_files():
    """返回风格库里的文件名（已排序、已过滤）。"""
    try:
        names = sorted(os.listdir(STYLE_DIR))
    except OSError:
        return []
    out = []
    for fn in names:
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in STYLE_EXTS or fn.startswith((".", "_")):
            continue
        out.append(fn)
    return out


def strip_comments(text):
    """去掉风格文件里的注释（读取风格库时统一执行）。

    支持：
      - 整行注释：行首（允许空白）的 # 或 //
      - 块注释：/* ... */（可跨行，与 ComfyUI 前端动态提示词的注释语法一致）
    注意：行中间的 # 不算注释（避免误伤 #ff0000 这类色值），
    想临时停用某段提示词，把它单独放在一行、行首加 # 即可。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    kept = [ln for ln in text.splitlines() if not re.match(r"^\s*(?:#|//)", ln)]
    return "\n".join(ln.strip() for ln in kept if ln.strip()).strip()


_NEG_SEP = re.compile(r"^\s*-{2,}\s*(?:负向|negative)\s*-{2,}\s*$", re.IGNORECASE)


def split_negative(text):
    """按 ---负向--- 分隔符把风格文本拆成 (正向, 负向)，各自剔除注释。"""
    pos, neg = [], []
    target = pos
    for ln in text.splitlines():
        if _NEG_SEP.match(ln):
            target = neg
            continue
        target.append(ln)
    return strip_comments("\n".join(pos)), strip_comments("\n".join(neg))


def load_styles():
    """读取整份风格库，返回 {风格名: (正向, 负向)}（顺序 = 文件名排序）。"""
    styles = {}
    for fn in library_files():
        path = os.path.join(STYLE_DIR, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            LOG.warning("[style-prompt] 读取失败 %s：%s", fn, exc)
            continue
        pos, neg = split_negative(text)
        if not pos and not neg:
            continue
        name = display_name(os.path.splitext(fn)[0])
        if name in styles:  # 重名时退回完整文件名，避免互相覆盖
            name = os.path.splitext(fn)[0]
        while name in styles:
            name += " "
        styles[name] = (pos, neg)
    return styles


def library_stamp():
    """风格库指纹：任何文件变动都会让 ComfyUI 重新执行节点（否则会命中缓存）。"""
    parts = []
    for fn in library_files():
        path = os.path.join(STYLE_DIR, fn)
        try:
            parts.append("%s:%d:%d" % (fn, os.path.getsize(path), int(os.path.getmtime(path))))
        except OSError:
            pass
    return "%d|%s" % (len(parts), ",".join(parts))


class StylePromptSelector:
    """下拉选风格（通用规则）+ 本图描述（个体信息）→ 输出正向提示词。

    负向口恒为空：极速档 cfg 1.0 下负向不参与采样计算（comfy/samplers.py:610），
    保留控件只会误导。所有约束写进 describe。
    """

    @classmethod
    def INPUT_TYPES(cls):
        names = [CUSTOM_STYLE] + (list(load_styles()) or ["(风格库为空)"])
        return {
            "required": {
                "style": (names, {"tooltip": "第一项「自定义」= 不用风格库，下面这个框就是完整的正向提示词；"
                                           "其余来自 ComfyUI\\styles 里的 *.txt，文件名即风格名"}),
                "describe": ("STRING", {
                    "multiline": True,
                    "dynamicPrompts": False,
                    "default": "",
                    "tooltip": "选「自定义」时：这里就是**完整的正向提示词**（前面不会再加任何内容）；"
                               "选风格库风格时：这一张照片的情况（人物、人数、年龄、年代、服饰……）追加在风格正向后。"
                               "要去掉什么也写在这里——负向不参与计算。",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "negative")
    FUNCTION = "select"
    CATEGORY = "style"

    def select(self, style, describe):
        extra_pos = (describe or "").strip()

        # 自定义模式：文本框就是最终提示词，不读库、不拼接。
        if style == CUSTOM_STYLE:
            LOG.info("[style-prompt] 自定义模式：正向 %d 字符（不读风格库）", len(extra_pos))
            if not extra_pos:
                LOG.warning("[style-prompt] 自定义模式下正向提示词为空，模型会自由发挥")
            return (extra_pos, "")

        styles = load_styles()
        lib_pos, lib_neg = styles.get(style, ("", ""))
        if not lib_pos and styles:
            fallback = next(iter(styles))
            LOG.warning("[style-prompt] 风格「%s」不在库里，改用「%s」", style, fallback)
            style = fallback
            lib_pos, lib_neg = styles[fallback]
        if not lib_pos:
            LOG.warning("[style-prompt] 风格库为空：%s", STYLE_DIR)

        pos = "\n".join(t for t in (lib_pos, extra_pos) if t)

        LOG.info("[style-prompt] 风格「%s」→ 正向 = 库 %d 字符 + 本图 %d 字符",
                 style, len(lib_pos), len(extra_pos))
        if not pos:
            LOG.warning("[style-prompt] 正向提示词为空（库与文本框都空）")
        return (pos, "")

    @classmethod
    def IS_CHANGED(cls, style, describe):
        return "%s|%s|%s" % (library_stamp(), style, describe)


class StylePromptSave:
    """把提示词写回风格库（默认不写，只透传；把 enabled 打开才落盘）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": False, "label_on": "写入风格库",
                                        "label_off": "只透传不写"}),
                "style_name": ("STRING", {"default": "", "tooltip": "写入/覆盖的风格名；库里已有同名文件就覆盖它"}),
                "prompt": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False}),
            },
            "optional": {
                "text": ("STRING", {"forceInput": True, "tooltip": "接了上游就用上游的文本（例如选择器的输出）"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "save"
    CATEGORY = "style"
    OUTPUT_NODE = True

    def save(self, enabled, style_name, prompt, text=None):
        value = text if text is not None else prompt
        value = value or ""
        if not enabled:
            LOG.info("[style-prompt] 存库节点未启用，透传（%d 字符）", len(value))
            return (value,)
        name = (style_name or "").strip()
        if not name:
            LOG.warning("[style-prompt] 未填风格名，跳过写入")
            return (value,)
        try:
            path = self._write(name, value)
            LOG.info("[style-prompt] 已写入风格库：%s", path)
        except OSError as exc:
            LOG.error("[style-prompt] 写入风格库失败：%s", exc)
        return (value,)

    @staticmethod
    def _write(name, text):
        os.makedirs(STYLE_DIR, exist_ok=True)
        target = None
        for fn in library_files():
            if display_name(os.path.splitext(fn)[0]) == name:
                target = os.path.join(STYLE_DIR, fn)
                break
        if target is None:
            prefix = 0
            for fn in library_files():
                m = re.match(r"^\s*(\d+)", fn)
                if m:
                    prefix = max(prefix, int(m.group(1)))
            target = os.path.join(STYLE_DIR, "%02d-%s.txt" % (prefix + 1, _ILLEGAL.sub("_", name)))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.strip() + "\n")
        return target


class BackgroundFillSmooth:
    """背景填充节点：把掩膜区（白色=1）用周边像素做结构延续填充。

    算法（三步，无扩散模型，确定性好、速度快）：
      1. 逐行水平插值 —— 每行洞内像素由左右最近有效像素（各取 6px 均值做锚点）
         线性过渡；掩膜顶到图像边界的悬空段用最近锚点颜色恒定延伸。
         对水平条带型背景（天空/地平线/水面/台面）能精确延续结构。
      2. 轻扩散统一质感 —— 高斯模糊（sigma 12/6/3）+ 已知区回贴，软化插值痕迹。
      3. 匹配噪点 —— 填充区加轻噪，避免与周边颗粒感脱节。

    典型用途：产品图层拆分里的「背景层」——被产品/文字挡住的区域补全，
    之后合成回去时中心区会被产品重新盖住，边界延续才是质量关键。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask": ("MASK",),
                "grain": ("FLOAT", {"default": 2.2, "min": 0.0, "max": 20.0, "step": 0.1}),
                "seed": ("INT", {"default": 7, "min": 0, "max": 2**31 - 1}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "fill"
    CATEGORY = "image/compositing"

    def fill(self, image, mask, grain, seed):
        import numpy as np
        import torch
        from PIL import Image as PILImage

        img = image[0].cpu().numpy().astype(np.float32) * 255.0     # H,W,C
        msk = mask[0].cpu().numpy().astype(np.float32)              # H,W（1=填充区）
        if msk.shape != img.shape[:2]:
            msk = np.asarray(
                PILImage.fromarray((msk * 255).astype(np.uint8)).resize((img.shape[1], img.shape[0]))
            , dtype=np.float32) / 255.0
        known = msk < 0.1
        H, W, _ = img.shape

        # 1) 逐行水平插值 + 边界悬空段恒定延伸
        fill = img.copy()
        K = 6
        for y in range(H):
            row = known[y]
            if row.all():
                continue
            xs = np.where(row)[0]
            if len(xs) == 0:
                continue
            if xs[0] > 0:                       # 左侧顶边：向左延伸右锚点
                fill[y, :xs[0]] = img[y, xs[:K]].mean(axis=0)
            if xs[-1] < W - 1:                  # 右侧顶边：向右延伸左锚点
                fill[y, xs[-1] + 1:] = img[y, xs[-K:]].mean(axis=0)
            for seg in range(len(xs) - 1):      # 中间跨度线性过渡
                x0, x1 = xs[seg], xs[seg + 1]
                if x1 - x0 <= 1:
                    continue
                lpx = xs[max(0, seg - K + 1):seg + 1]
                rpx = xs[seg + 1:seg + K]
                c0 = img[y, lpx].mean(axis=0)
                c1 = img[y, rpx].mean(axis=0) if len(rpx) else c0
                t = np.linspace(0.0, 1.0, x1 - x0 + 1)[:, None]
                fill[y, x0:x1 + 1] = c0 * (1 - t) + c1 * t

        # 2) 轻扩散（已知区永远回贴原图）
        work = fill
        try:
            from PIL import ImageFilter
            pil = PILImage.fromarray(np.clip(work, 0, 255).astype(np.uint8))
            for sigma in (12, 6, 3):
                b = np.asarray(pil.filter(ImageFilter.GaussianBlur(radius=sigma)), dtype=np.float32)
                work = np.where(known[..., None], img, b)
                pil = PILImage.fromarray(np.clip(work, 0, 255).astype(np.uint8))
        except ImportError:
            LOG.warning("[style-prompt] BackgroundFillSmooth: 无 PIL，跳过扩散步")

        # 3) 匹配噪点
        if grain > 0:
            rng = np.random.default_rng(seed)
            work = work + rng.normal(0.0, grain, work.shape) * (~known[..., None])
        work = np.clip(work, 0.0, 255.0) / 255.0
        return (torch.from_numpy(work).float().unsqueeze(0),)


NODE_CLASS_MAPPINGS = {
    "StylePromptSelector": StylePromptSelector,
    "StylePromptSave": StylePromptSave,
    "BackgroundFillSmooth": BackgroundFillSmooth,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "StylePromptSelector": "风格提示词（通用库 + 本图描述）",
    "StylePromptSave": "风格提示词存回库",
}


def _styles_route(request):
    from aiohttp import web
    styles = load_styles()
    return web.json_response({
        "styles": {k: v[0] for k, v in styles.items()},
        "negatives": {k: v[1] for k, v in styles.items()},
        "dir": STYLE_DIR,
    })


def _register_routes():
    """把风格库暴露给前端 js（拉取提示词用来自动填充文本框）。"""
    try:
        from server import PromptServer
        inst = getattr(PromptServer, "instance", None)
        if inst is None:
            return
        inst.routes.get("/style_prompt/styles")(_styles_route)
        LOG.info("[style-prompt] 风格库已就绪：%s（%d 条）", STYLE_DIR, len(library_files()))
    except Exception as exc:  # 单独 import 本模块做测试时不带 server 也能用
        LOG.debug("[style-prompt] 未注册 HTTP 路由：%s", exc)


_register_routes()
