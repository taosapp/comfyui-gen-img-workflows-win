# -*- coding: utf-8 -*-
"""生成 workflows/中国彩墨图生图.json（UI 格式 0.4）并自检。

单档配方：Qwen-Image-2.1 GGUF + Viggle Turbo 蒸馏 LoRA，8 步 / cfg 1.0，
RTX 3060 12GB 实测约 47 秒/张（首次约 225 秒，含 LoRA 加载与模型补丁的一次性开销）。
文生图 / 照片转彩墨画两用：⑥ 接参考图就是照片转彩墨，断开就是纯文生图。

⚠️ Turbo LoRA 是 Qwen Research License，**仅限非商用**。本项目只提供这一档。

历史：
  2026-10-12 由「彩墨画文生图」更名并通用化：提示词去掉绑定具体照片的内容，
             负向去掉现实物体黑名单（换题材会误伤）。
  2026-10-14 同种子复测证实负向提示词在本链路是负资产（真 cfg + 负向结构 0.534，
             不参与计算 0.826），此后日常出图走 Turbo 8 步档。
  2026-10-29 只保留这一档（原 26 步质量档已删除，需要时从 git 历史取回）；
             提示词按阿里官方 Qwen-Image-2.1 规范整改：删空泛画质词、
             保真条款压成总括句、补光照句。
"""
import io, json, sys

PROMPT = (
    "中国江南山水，远山层叠、云雾留白，山下公路蜿蜒、一叶扁舟。\n"
    "以水墨为主、设色含蓄：用焦墨勾勒物象轮廓，线条劲挺清晰；山石用皴法皴擦出纹理，笔锋苍劲带飞白；\n"
    "色彩只以赭石、花青为主，局部点染少量朱砂，饱和度适中，不要大面积高饱和色块；\n"
    "墨色浓淡层次丰富，黑白灰层次分明；宣纸纤维纹理清晰可见，大面积留白营造意境。\n"
    "画面明暗由墨色浓淡表现：受光处留白、背光处积墨。\n"
    "整幅构图重心偏下，上方留白开阔，意境清远。"
)

# 接参考图（照片 → 彩墨画）时的通用模板：任何照片开箱即用，不需要按照片改写。
# 铁律（前三条是踩坑换来的，后三条来自阿里官方 Qwen-Image-2.1 提示词规范）：
#   ① 负向不列现实物体——换个题材（真有人物/房子）就会误伤；
#   ② 不写「原图没有什么」——写了「不要长树」反而可能长出树，只描述「原图有什么」；
#   ③ 「保留清单」只写原图确实有的东西——曾把粉色路面误读成「红色护栏」，连续四版都凭空长护栏；
#   ④ 保真条款**一句总括**，只点名位置/角色，**不描述外观**：官方规范指出，
#      「你越具体描述打算保留的东西，模型越容易重画它」——逐项描述=给它发了一遍生成指令；
#   ⑤ 不写空泛画质词（masterpiece / best quality / 8K / 4K / highly detailed）：
#      它们不提供可执行的视觉信息，还会把风格往插画/动漫域拉；
#   ⑥ 光照单独一句（光源、方向、明暗分配），不靠「层次丰富」这种词暗示。
PROMPT_REF = (
    "把这张照片转换成中国彩墨山水国画，大师水墨写生风格，宣纸质感。"
    "写意用笔：以焦墨简练勾勒景物外轮廓，线条近粗远细；山石用皴擦表现原有质地，墨色浓淡层次丰富。"
    "原照的构图、各景物的位置关系与外形轮廓保持不变，只更换绘画媒介，不增删原照中没有的物体。"
    "设色以原照固有色为准，清雅含蓄。"
    "画面明暗由墨色浓淡表现：受光处留白、背光处积墨，光源方向与原照一致，不引入新的光源。"
    "天空与云朵只用淡墨晕染、不勾轮廓线，天空与地面之间留白。"
    "宣纸纤维纸纹清晰可见。"
)
# ↑ 三条禁令（都实测过，别加回来）：
#   加「取原照占比最大的颜色大面积铺陈」→ 变暗，结构 0.805→0.699；
#   加「亮部/中间调橙色块点染」→ 结构 0.503、纹理密度 11.9→9.1，原照山体纹理被抹平；
#   把保真条款拆成逐项外观描述 → 等于让模型把要保留的东西重新生成一遍。

# 负向只留「画风 + 画质」词。不要写「硬边缘/高对比度/描边/平涂/粗重线条」——
# 这几个词会把「焦墨勾勒 + 浓墨重彩」压掉（2026-10-12 实测）；不要列现实物体。
# 注意：本档 cfg = 1.0，负向不参与采样计算（comfy/samplers.py:610 把 uncond_ 置 None），
# 这个框留着只是备查——要去掉什么必须写进正向。
NEGATIVE = (
    "印章，题字，文字，签名，水印，画面发灰，浑浊，模糊，低分辨率，像素噪点，压缩瑕疵，过曝，荧光色，"
    "边框，畸形，杂乱构图，重复元素，照片，摄影，写实照片，3D 渲染，CG，油画，动漫，二次元，卡通，水彩，"
    "粉笔画，涂抹，photograph, photorealistic, 3d render, cgi, anime, cartoon, watercolor, blurry, "
    "lowres, neon colors, cluttered composition"
)

TURBO_LORA = "qwen_image_2.1_viggle_turbo_v0.2.1_r128_comfy.safetensors"

note_text = (
    "## 中国彩墨图生图（Qwen-Image-2.1 GGUF + Turbo）\n\n"
    "**8 步 / cfg 1.0，实测约 47 秒一张 · 通用模板不绑定任何照片 · 文生图 / 照片转彩墨画两用**\n\n"
    "### 两种模式\n"
    "| 模式 | 怎么做 |\n|---|---|\n"
    "| **照片转彩墨画** | `⑥` 选好照片，**把 ⑦ 画布宽高改成原图比例**"
    "（3:4 → 864×1152；9:16 → 864×1536；1:1 → 1024×1024；总像素控制在 1.1MP 内）；"
    "`⑤ 正向` 用下面的通用模板，**不需要按照片改写**|\n"
    "| **纯文生图** | `⑥` 不接（`⑤` 的 images 输入留空），`⑤ 正向` 写题材，画布按需要设比例 |\n\n"
    "参考图模式下 **③ VAE 要接到 ⑤**（已接好）：VAE 把参考图编码成 latent 拼进条件序列，"
    "这是「构图与纹理不变」的关键；不接只剩视觉塔，构图会漂。\n\n"
    "### 通用提示词模板（照片转彩墨画，任何照片直接可用）\n\n"
    "```\n" + PROMPT_REF + "\n```\n\n"
    "负向（cfg 1.0 下**不参与计算**，仅备用）：\n\n"
    "```\n" + NEGATIVE + "\n```\n\n"
    "### 三条铁律（都是踩坑换来的）\n"
    "1. **负向词里不列现实物体**。以前为了「防止画蛇添足」，把「护栏/房屋/人物/栈道/船只/路灯/电线杆」"
    "写进负向——但换个题材（照片里真有人物、房子）就会误伤。负向只放画风词和画质词。\n"
    "2. **不写「原图没有什么」**。原图没树，就什么都不写；写「不要长树 / 保持裸露岩石」"
    "反而可能把树画出来。正向只描述「原图有什么」和「要变成什么风格」。\n"
    "3. **「保留清单」只写原图确实存在的东西**。曾把照片里的粉色路面误读成「红色护栏」写进保留清单，"
    "结果连续四版都凭空长出护栏——提示词写什么，模型就画什么。\n\n"
    "### 另外三条（来自阿里官方提示词规范）\n"
    "4. **保真只点名位置和角色，不描述外观**。官方原话：「你越具体描述打算保留的东西，"
    "模型越容易重画它」——逐项描述等于把要保留的内容重新生成一遍。所以模板里保真只写一句总括。\n"
    "5. **不写空泛画质词**（masterpiece / best quality / 8K / 4K / highly detailed）："
    "不提供可执行信息，还会把水墨往插画/动漫域拉。想要清晰就写纸纹、墨色层次这些可观察的东西。\n"
    "6. **光照单独一句**：光源、方向、明暗分配要说出来，别指望「层次丰富」这种词暗示。\n\n"
    "### 想让某个特征更突出（可选）\n"
    "在正向里点名它，例如「山体的横向彩条层理是主要特征，务必保留」。"
    "点名**存在**的东西有效；点名**不存在**的东西会把它们画出来。一次只加一句，改完再对比。\n\n"
    "### 实测指标（同一照片 5.jpg / 864×1152）\n"
    "| 结构保真 | 上半部色距 | 饱和度 | 明度 | 纹理密度（原照 12.9） | 耗时 |\n"
    "|---|---|---|---|---|---|\n"
    "| **0.831~0.887** | 20.4~28.9 | 0.147 | 0.742 | **13.0** | **约 47 秒** |\n\n"
    "> **负向提示词在本链路是负资产**：负向里的「照片/摄影/写实」会把画面推离原照结构。"
    "cfg 1.0 时负向根本不参与计算，反而更贴原照——别为了「压住」某样东西去改负向框，写进正向。\n"
    "> **加色块 = 拿纹理换颜色**：「主色大面积铺陈」整体压暗（明度 0.726→0.621、结构 0.805→0.699）；"
    "「亮部/中间调橙色块点染」更狠（结构 0.503、纹理密度 11.9→9.1，原照山体纹理被色块盖平）。"
    "默认**不写任何加色块指令**。\n"
    "> **提示词越「指令化」越容易失真**：旧版 6 段式逐条约束结构保真只有 0.363；简短通用描述更好。\n"
    "> **「显得暗淡」多半是明度/中间调问题**：写「宣纸洁白、明度略高、淡墨清透」，别笼统写「更鲜艳」。\n\n"
    "### 调参\n"
    "| 症状 | 怎么调 |\n|---|---|\n"
    "| 颜色偏淡、不够浓 | **先别加色块**（会抹平原照纹理）。优先调墨：「焦墨勾勒、墨色浓一分」，"
    "或小幅提饱和「设色略浓、不要偏灰」（代价：整体略变暗）|\n"
    "| 山体/岩石纹理被抹平 | 正向里是不是有「橙色块点染 / 大面积色块铺陈 / 色块渲染 / 晕染过渡」这类**加色块**词？"
    "删掉即回到默认的完整纹理（实测纹理密度 9.1 → 11.9）|\n"
    "| 山体被重画 / 地貌走样 | cfg 已是 1.0 最低，不能再降；改提示词（保真条款压成一句），或换一张参考图 |\n"
    "| 凭空多出东西 | 是不是被写进正向「保留清单」了？删掉那个词 |\n"
    "| 细节丢失（带参考图） | 把 ⑤ 的 `resolution` 调到 1280~1536（与画布接近）|\n"
    "| 整体发灰发暗 | 正向加「宣纸洁白、明度略高、淡墨清透」；别用「加色块」提亮 |\n"
    "| 想更快 | ⑦ 改 720×960；或降 ⑤ 的 `resolution` |\n"
    "| 要更大尺寸 | ⑦ 等比放大，12GB 显存建议 ≤1.5MP |\n\n"
    "### 内存 / 性能\n"
    "`resolution` 调到 1536 以上时，本机偶尔触发 comfy-aimdo 原生报错（`aimdo memory compile error`，"
    "会带崩服务）。1280 是安全值；真要更大，可给启动器加 `--disable-dynamic-vram`。\n"
    "RTX 3060 12GB + `--lowvram`：864×1152 / 8 步约 47 秒一张，首次约 225 秒。\n\n"
    "### 注意\n"
    "- **首次运行慢约 3 分钟**：LoRA 加载与模型补丁是一次性开销，服务不重启就一直快。\n"
    "- LoRA 有 96/585 个张量未加载（`img_mlp.gate_up` 融合键与 GGUF 权重名不匹配），约 84% 生效，"
    "实测效果已足够好；想 100% 生效需换 bf16/int8 版 DiT（多下 7.3~14.2GB）。\n"
    "- **LoRA 许可为 Qwen Research License（非商用）**，本项目只提供这一档。\n"
    "- 节点 ①½ 在 ComfyUI 里归类为调试加载器（model/loaders），实测工作正常。\n"
    "- **同一工作流 + 同种子重复提交会命中缓存（3 秒假完成）**，换图记得换种子或改参数。\n\n"
    "### 换题材（纯文生图时改 `⑤ 正向` 第一句）\n"
    "`一枝斜出的梅花，雪意朦胧，背景留白` / `远山瀑布，飞瀑直下，山间云气` / "
    "`荷塘一角，荷叶田田，一支半开的荷花`\n\n"
    "### 提示词写法（彩墨画）\n"
    "- **写意**：淡雅晕染 + 毛笔宣纸质感 + 淡彩 + 留白；**工笔**写「工笔重彩、勾勒填色」\n"
    "- 颜料词（花青/赭石/藤黄/胭脂/石青）比「蓝的、黄的」有效得多\n"
    "- 真正的分辨率靠 ⑦ 的宽高，别在提示词里写「4K」指望模型自己加分辨率\n"
    "- 想客观比较两版提示词：缩到 64×64 灰度算相关系数（结构保真），比上半部平均色与原照的色距"
    "（固有色保持），再看饱和度/明度/纹理梯度（脚本 `scripts/legacy/metrics_ink.py`）\n"
    "- 写新提示词可参考 `styles/_槽位模板.txt` 的填槽骨架\n\n"
    "### 纯文生图模板（`⑥ 参考照片` 断开时用）\n\n"
    "```\n" + PROMPT + "\n```\n"
)


def I(name, typ, link=None):
    d = {"name": name, "type": typ}
    if link is not None:
        d["link"] = link
    return d


def O(name, typ, links, slot=0):
    return {"name": name, "type": typ, "links": links, "slot_index": slot}


def N(nid, typ, pos, size, order, inputs, outputs, wv, title=None):
    d = {"id": nid, "type": typ, "pos": pos, "size": size, "flags": {}, "order": order,
         "mode": 0, "inputs": inputs, "outputs": outputs,
         "properties": {"Node name for S&R": typ}, "widgets_values": wv}
    if title:
        d["title"] = title
    return d


nodes = [
    N(1, "UnetLoaderGGUF", [40, 60], [330, 58], 0, [], [O("MODEL", "MODEL", [1])],
      ["qwen-image-2.1-Q5_K_M.gguf"], "① 主模型（Qwen-Image-2.1 GGUF）"),
    N(15, "LoraLoaderBypassModelOnly", [430, 60], [400, 80], 1, [I("model", "MODEL", 1)],
      [O("MODEL", "MODEL", [13])], [TURBO_LORA, 1.0], "①½ Turbo 蒸馏 LoRA（提速关键，勿删）"),
    N(4, "QwenImage21Cache", [900, 60], [360, 90], 2, [I("model", "MODEL", 13)],
      [O("MODEL", "MODEL", [2])], ["auto", "default"], "④ KV 缓存加速（勿删）"),
    N(2, "CLIPLoader", [40, 170], [330, 78], 3, [], [O("CLIP", "CLIP", [3])],
      ["qwen3vl_8b_int8_convrot.safetensors", "qwen_image", "default"], "② 文本编码器"),
    N(3, "VAELoader", [40, 300], [330, 58], 4, [], [O("VAE", "VAE", [4, 10])],
      ["qwen_image_2.1_vae_bf16.safetensors"], "③ VAE"),
    N(5, "TextEncodeQwenImage21", [900, 210], [420, 300], 5,
      [I("clip", "CLIP", 3), I("vae", "VAE", 10), I("images.image_1", "IMAGE", 11)],
      [O("positive", "CONDITIONING", [5], 0), O("negative", "CONDITIONING", [6], 1),
       O("latent", "LATENT", None, 2)],
      [PROMPT_REF, NEGATIVE, 1280], "⑤ 提示词（正向 / 负向）——只改这两个框"),
    N(14, "LoadImage", [40, 420], [330, 320], 6, [],
      [O("IMAGE", "IMAGE", [11], 0), O("MASK", "MASK", None, 1)],
      ["5.jpg", "image"], "⑥ 参考照片（接上=照片转彩墨画；不接=纯文生图）"),
    N(6, "EmptySD3LatentImage", [900, 580], [330, 110], 7, [],
      [O("LATENT", "LATENT", [7], 0)], [864, 1152, 1], "⑦ 画布 864×1152（3:4，与照片同比例）"),
    N(7, "KSampler", [1330, 60], [320, 270], 8,
      [I("model", "MODEL", 2), I("positive", "CONDITIONING", 5), I("negative", "CONDITIONING", 6),
       I("latent_image", "LATENT", 7)], [O("LATENT", "LATENT", [8], 0)],
      [42, "randomize", 8, 1.0, "euler", "beta", 1.0], "⑧ 采样（8 步 / cfg 1.0，Turbo 专属配方）"),
    N(8, "VAEDecode", [1720, 60], [300, 60], 9, [I("samples", "LATENT", 8), I("vae", "VAE", 4)],
      [O("IMAGE", "IMAGE", [9], 0)], [], "⑨ 解码"),
    N(9, "SaveImage", [2090, 60], [340, 400], 10, [I("images", "IMAGE", 9)], [],
      ["彩墨画/彩墨画"], "⑩ 出图"),
    {"id": 90, "type": "MarkdownNote", "pos": [40, 760], "size": [420, 640], "flags": {},
     "order": 11, "mode": 0, "inputs": [], "outputs": [], "properties": {},
     "widgets_values": [note_text]},
]

links = [
    [1, 1, 0, 15, 0, "MODEL"], [13, 15, 0, 4, 0, "MODEL"], [2, 4, 0, 7, 0, "MODEL"],
    [3, 2, 0, 5, 0, "CLIP"], [4, 3, 0, 8, 1, "VAE"], [5, 5, 0, 7, 1, "CONDITIONING"],
    [6, 5, 1, 7, 2, "CONDITIONING"], [7, 6, 0, 7, 3, "LATENT"], [8, 7, 0, 8, 0, "LATENT"],
    [9, 8, 0, 9, 0, "IMAGE"], [10, 3, 0, 5, 1, "VAE"], [11, 14, 0, 5, 2, "IMAGE"],
]

wf = {"last_node_id": 90, "last_link_id": 13, "nodes": nodes, "links": links,
      "config": {}, "extra": {}, "version": 0.4}


def check(nodes_, links_, label):
    """连线自检：类型、双向一致、无重复入线。返回错误数。"""
    byid_ = {n["id"]: n for n in nodes_}
    errs = 0
    for lid, src, ss, dst, ds, typ in links_:
        so, di = byid_[src]["outputs"][ss], byid_[dst]["inputs"][ds]
        if so["type"] != typ or di["type"] != typ:
            errs += 1; print("类型错", label, lid, so["type"], di["type"])
        if lid not in so["links"]:
            errs += 1; print("出端缺 link", label, lid)
        if di.get("link") != lid:
            errs += 1; print("入端 link 不匹配", label, lid, di.get("link"))
    used = {l for n in nodes_ for o in n["outputs"] for l in (o["links"] or [])}
    if used != {l[0] for l in links_}:
        errs += 1; print("links 表与节点 outputs 不一致", label, used ^ {l[0] for l in links_})
    from collections import Counter
    dup = [k for k, c in Counter((l[3], l[4]) for l in links_).items() if c > 1]
    if dup:
        errs += 1; print("重复入线", label, dup)
    print(label, "自检错误数:", errs, "| nodes:", len(nodes_), "| links:", len(links_))
    return errs


total_errs = check(nodes, links, "彩墨")

with io.open("workflows/中国彩墨图生图.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(wf, f, ensure_ascii=False, indent=1)
print("已写入 workflows/中国彩墨图生图.json")

sys.exit(0 if total_errs == 0 else 1)
