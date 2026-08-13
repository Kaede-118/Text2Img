# -*- coding: utf-8 -*-
"""
text2img.py — 将剪贴板文本一键渲染为卡片式长图并写回剪贴板

用法:
    python text2img.py          # 读剪贴板 → 渲染长图 → 写回剪贴板（Ctrl+V 直接粘贴）
    python text2img.py --save   # 同时保存 PNG 到本目录（调试/留档用）

流程:
    读剪贴板文本 → 清理不可见字符 → Pillow 渲染卡片长图 → 写回剪贴板 → 提示音

特性:
    - 字体回退渲染：主字体缺字形（emoji/特殊符号）时自动用 Segoe UI Emoji/Symbol 补绘
    - 单词级换行：英文单词整体换行不拆开；单个单词超宽才逐字符硬断

配置:
    首次运行自动生成 config.json，可调整样式（宽度/配色/字号/行距等）

依赖:
    pip install pillow pywin32 fonttools
"""

import ctypes
import io
import json
import re
import sys
import traceback
import winsound
from pathlib import Path

# 控制台按 UTF-8 输出，避免中文在 GBK 代码页下乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import freetype  # FreeType：COLRv1 彩色 emoji 渲染
import win32clipboard  # pywin32：读写系统剪贴板
from fontTools.ttLib import TTFont  # fontTools：读取字体字形表，判断字符是否有字形
from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"

# 默认样式配置：首次运行写入 config.json 模板，用户可自行调整
DEFAULT_CONFIG = {
    "width": 860,                          # 图片宽度 px
    "padding": 48,                         # 卡片内边距 px
    "corner_radius": 24,                   # 卡片圆角半径 px
    "bg_color": "#FFFFFF",                 # 卡片背景色
    "outline_color": "#E5E7EB",            # 卡片描边色
    "title_color": "#111827",              # 首行标题颜色
    "text_color": "#374151",               # 正文颜色
    "title_scale": 1.4,                    # 标题字号 = 正文字号 × 此倍数
    "font_size": 30,                       # 正文字号 px
    "line_spacing": 1.7,                   # 行距倍数
    "font_path": r"C:\Windows\Fonts\msyh.ttc",  # 主字体：微软雅黑
    # 回退字体：主字体缺字形的字符按顺序尝试补绘（Pillow 只能渲染 outline 字形）
    "fallback_fonts": [
        r"C:\Windows\Fonts\seguiemj.ttf",  # Segoe UI Emoji：单色线稿兜底
        r"C:\Windows\Fonts\seguisym.ttf",  # Segoe UI Symbol：杂项符号
    ],
    # 彩色 emoji 字体：经 PowerShell + WPF(DirectWrite) 渲染成 PNG 缓存，
    # 与 Windows 终端/微信显示完全一致的微软风格彩色 emoji
    "emoji_font_path": r"C:\Windows\Fonts\seguiemj.ttf",
}


class EmojiBitmaps:
    """从 emoji 字体渲染彩色位图（FreeType COLRv1，与 Windows 终端同款微软风格）。
    seguiemj 是 COLRv1 彩色字形，Pillow 只能渲染出单色线稿；
    FreeType 2.13+ 支持 FT_LOAD_COLOR 直接渲染彩色层"""

    def __init__(self, path, size):
        self.size = size  # 目标渲染尺寸 px（按高度缩放）
        self.face = freetype.Face(path)
        self.face.set_pixel_sizes(0, size * 2)  # 2x 超采样渲染，缩放更平滑
        self.cache = {}  # {码点: 裁剪缩放后的 RGBA 图像}

    @staticmethod
    def _is_emoji(cp):
        """常见 emoji 的 Unicode 区块（字体覆盖 ASCII/标点等非 emoji，需过滤）"""
        return (
            0x1F000 <= cp <= 0x1FAFF  # 补充平面：表情/动物/食物/活动/旗子等
            or 0x2600 <= cp <= 0x27BF  # 杂项符号 + 装饰符号（☀ ❤ ✨ 等）
            or 0x2B00 <= cp <= 0x2BFF  # 杂项符号和箭头（⭐ 等）
            or 0x2300 <= cp <= 0x23FF  # 杂项技术（⏰ ⌚ 等）
            or cp in (0x00A9, 0x00AE, 0x2122)  # © ® ™
        )

    def has(self, ch):
        """该字符是否应作为彩色 emoji 渲染（Unicode 区块 + 字体有字形）"""
        cp = ord(ch)
        return self._is_emoji(cp) and self.face.get_char_index(ch) != 0

    def prepare(self, text):
        """兼容接口：FreeType 渲染无需预准备，仅预热缓存（可选）"""
        for ch in text:
            if self.has(ch):
                self.get(ch)

    def get(self, ch):
        """渲染该 emoji 的 RGBA 图像（按像素格式分支 + 裁剪缩放 + 缓存）"""
        cp = ord(ch)
        if cp not in self.cache:
            face = self.face
            face.load_char(ch, freetype.FT_LOAD_COLOR | freetype.FT_LOAD_RENDER)
            bmp = face.glyph.bitmap
            buf = bmp.buffer
            w, h = bmp.width, bmp.rows
            if w < 1 or h < 1:
                return Image.new("RGBA", (1, 1), (0, 0, 0, 0))  # 兜底：空图
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            px = img.load()
            if bmp.pixel_mode == freetype.FT_PIXEL_MODE_BGRA:
                # COLRv1 彩色字形：BGRA 预乘 alpha，反预乘后转 RGBA
                for y in range(h):
                    row = y * bmp.pitch
                    for x in range(w):
                        i = row + x * 4
                        b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
                        if a and a < 255:
                            r, g, b = r * 255 // a, g * 255 // a, b * 255 // a
                        px[x, y] = (r, g, b, a)
            elif bmp.pixel_mode == freetype.FT_PIXEL_MODE_GRAY:
                # 单色字形（如 ✻ 等无 COLR 层）：灰度作 alpha，黑色填充（与终端单色显示一致）
                for y in range(h):
                    row = y * bmp.pitch
                    for x in range(w):
                        a = buf[row + x]
                        px[x, y] = (0, 0, 0, a)
            else:
                return Image.new("RGBA", (1, 1), (0, 0, 0, 0))  # 其他格式：空图
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)  # 裁掉字形外透明区域
            if img.height != self.size:
                scale = self.size / img.height  # 按高度缩放，保持比例
                img = img.resize((max(1, int(img.width * scale)), self.size), Image.LANCZOS)
            self.cache[cp] = img
        return self.cache[cp]


class FontGroup:
    """文本渲染单元组：逐字符选择渲染方式。
    优先级：emoji 彩色位图（CBDT）> 主字体 > 回退字体。
    渲染单元分两类：('font', PIL字体) 普通字形；('emoji', 码点) 彩色位图"""

    def __init__(self, primary_path, size, fallback_paths, emoji_font_path=None):
        self.size = size
        # 普通字体列表：(PIL 字体对象, 字形码点集合)
        self.fonts = []
        self.fonts.append((ImageFont.truetype(primary_path, size), self._cmap(primary_path)))
        for fp in fallback_paths:
            p = Path(fp)
            if not p.exists():
                continue
            try:
                self.fonts.append((ImageFont.truetype(str(p), size), self._cmap(str(p))))
            except OSError:
                pass  # 位图字体等 Pillow 无法加载的字体跳过
        # 彩色 emoji 位图源（Pillow 加载不了 CBDT，由 fontTools 提取数据自行渲染）
        self.emoji = None
        if emoji_font_path:
            p = Path(emoji_font_path)
            if p.exists():
                try:
                    self.emoji = EmojiBitmaps(str(p), size)
                except Exception:
                    self.emoji = None  # 字体损坏/格式不符时静默降级

    @staticmethod
    def _cmap(path):
        """读取字体字符映射表（fontTools），用于判断字符是否有字形；
        .ttc 为字体集合文件，需指定 fontNumber=0 取第一个字体"""
        return set(TTFont(path, fontNumber=0).getBestCmap().keys())

    def unit_for(self, ch):
        """返回字符的渲染单元：('emoji', 码点) 或 ('font', PIL字体)"""
        if self.emoji and self.emoji.has(ch):
            return ("emoji", ord(ch))
        cp = ord(ch)
        for font, cmap in self.fonts:
            if cp in cmap:
                return ("font", font)
        return ("font", self.fonts[0][0])  # 兜底主字体

    def getlength(self, text):
        """按渲染单元分组计算文本总宽度（与 draw 分组逻辑一致）"""
        if not text:
            return 0
        total = 0
        seg = text[0]
        prev = self.unit_for(text[0])
        for ch in text[1:]:
            u = self.unit_for(ch)
            if u != prev:
                total += self._unit_width(prev, seg)
                seg = ch
                prev = u
            else:
                seg += ch
        total += self._unit_width(prev, seg)
        return total

    def _unit_width(self, unit, seg):
        """单个渲染单元内一段文本的宽度：
        emoji 用实际渲染宽度（与 draw 一致，避免宽字形与后续文字重叠）；
        字体按实际字形宽"""
        if unit[0] == "emoji":
            return sum(self.emoji.get(c).width for c in seg)
        return unit[1].getlength(seg)

    def draw(self, img, draw, xy, text, fill, line_height):
        """按渲染单元分组绘制：相邻同单元的文本段合并绘制，减少调用次数。
        emoji 位图按行高垂直居中贴到画布上"""
        x, y = xy
        if not text:
            return
        units = [self.unit_for(ch) for ch in text]
        i = 0
        while i < len(text):
            unit = units[i]
            j = i + 1
            while j < len(text) and units[j] == unit:
                j += 1
            seg = text[i:j]
            if unit[0] == "font":
                draw.text((x, y), seg, font=unit[1], fill=fill)
                x += unit[1].getlength(seg)
            else:
                emoji_img = self.emoji.get(seg[0])
                # 垂直居中于行高内，避免位图偏高或偏低；
                # RGB 画布用源图 alpha 通道作 mask 合成（alpha_composite 要求双 RGBA）
                y_off = y + max(0, (line_height - emoji_img.height) // 2)
                img.paste(emoji_img, (int(x), y_off), emoji_img)
                x += emoji_img.width  # 按实际宽度前进，宽字形不重叠
            i = j


def clean_text(text):
    """清理文本：归一化换行、删除不可见控制字符，避免渲染成方框（豆腐块）"""
    out = []
    for ch in text:
        o = ord(ch)
        if ch == "\r":
            continue  # CR 归一到 \n（复制终端文本常带 CRLF）
        if ch == "\t":
            out.append("    ")  # 制表符展开为 4 空格（制表符无字形会成方框）
            continue
        if ch == "\n":
            out.append("\n")
            continue
        if o < 0x20 or 0x7F <= o < 0xA0:
            continue  # C0/C1 控制字符（除 \n \t 已处理）
        if 0x200B <= o <= 0x200D or o in (0x2060, 0xFEFF, 0x00AD):
            continue  # 零宽空格/零宽连接符/BOM/软连字符
        if o in (0x2028, 0x2029):
            out.append("\n")  # 行/段分隔符 → 换行
            continue
        if 0xFE00 <= o <= 0xFE0F:
            continue  # 变体选择符（如 ❤️ 的 U+FE0F）
        out.append(ch)
    return "".join(out)


def load_config():
    """读取 config.json；不存在时生成默认模板。
    用默认配置兜底合并：旧版 config 缺少新字段（如 fallback_fonts）时自动补全"""
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        print(f"已生成样式模板: {CONFIG_FILE}")
        print("如需自定义样式，修改后重新运行")
        print()
    user_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {**DEFAULT_CONFIG, **user_cfg}  # 默认值打底，用户配置覆盖


def read_clipboard_text():
    """读取剪贴板纯文本；剪贴板无文本时返回 None"""
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(
                win32clipboard.CF_UNICODETEXT
            ):
                return win32clipboard.GetClipboardData(
                    win32clipboard.CF_UNICODETEXT
                )
            return None
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        print(f"读取剪贴板失败: {e}")
        return None


def write_clipboard_image(img):
    """将 PIL 图像以 CF_DIB 格式写入剪贴板（微信/QQ/文档均可直接粘贴）"""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="BMP")
    # 跳过 BMP 文件头(14字节)：CF_DIB 需要 BITMAPINFOHEADER 起的原始数据
    data = buf.getvalue()[14:]
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()


# 列表标记：- * + 1. 1) • 等，后续空白作为内容缩进基准
LIST_MARK_RE = re.compile(r"^(\s*)([-*+•·▪]|\d{1,2}[.)])(\s+)")


def wrap_line(group, line, max_width):
    """单行文本按宽度自动换行：按空白块分词，单词整体换行不拆开；
    仅当单个无空白块本身超宽（如超长中文段落）时才逐字符硬断。
    返回 [(行文本, 行缩进px), ...]：首行缩进 = 原始前导（列表标记/空白），
    续行悬挂缩进与首行内容对齐（列表续行不乱）"""
    if not line:
        return [("", 0)]
    # 提取前导：列表标记（- * + 1. • 等）或纯空白
    m = LIST_MARK_RE.match(line)
    if m:
        lead = m.group(0)  # 标记+符号+空格，保留原始格式
    else:
        ws = re.match(r"^\s+", line)
        lead = ws.group(0) if ws else ""
    rest = line[len(lead):]
    if not rest.strip():
        return [(lead.strip(), 0)]  # 纯空白/只有标记的行
    lead_w = group.getlength(lead)
    avail = max_width - lead_w  # 首行与续行可用宽度一致（续行从缩进处开始）

    parts = re.split(r"(\s+)", rest)  # 按空白分词，保留空白块
    lines = []
    cur = ""
    for part in parts:
        candidate = part if not cur else cur + part
        if group.getlength(candidate) > avail:
            if cur:
                lines.append(cur)
                cur = ""
            # part 自身可能仍超宽（无空白的超长文本块）：逐字符硬断
            if group.getlength(part) > avail:
                for ch in part:
                    if group.getlength(cur + ch) > avail and cur:
                        lines.append(cur)
                        cur = ""
                    cur += ch
            else:
                cur = "" if not part.strip() else part
        else:
            cur = candidate
    lines.append(cur)
    if lead.strip():
        # 首行带列表标记（如 "- "）从行首绘制；续行悬挂缩进到标记后内容起点
        return [(lead + lines[0], 0)] + [(t, lead_w) for t in lines[1:]]
    # 纯空白缩进：首行与续行都从缩进处开始绘制
    return [(lines[0], lead_w)] + [(t, lead_w) for t in lines[1:]]


def render_card(text, cfg):
    """渲染卡片式长图：预计算显示行（统计/绘制共用同一列表，保证高度一致）"""
    font_size = cfg["font_size"]
    title_size = int(font_size * cfg["title_scale"])
    line_height = int(font_size * cfg["line_spacing"])
    title_line_height = int(title_size * cfg["line_spacing"])

    fallback = cfg.get("fallback_fonts", [])
    emoji_font = cfg.get("emoji_font_path")
    group = FontGroup(cfg["font_path"], font_size, fallback, emoji_font)
    title_group = FontGroup(cfg["font_path"], title_size, fallback, emoji_font)
    if group.emoji:
        group.emoji.prepare(text)  # 批量渲染文本中未缓存的彩色 emoji

    padding = cfg["padding"]
    max_width = cfg["width"] - padding * 2

    # 预计算所有显示行：(行文本, 行缩进px, 行高, 是否标题)
    display_lines = []
    title_done = False
    for raw in text.split("\n"):
        is_title = (not title_done) and bool(raw.strip())
        if is_title:
            title_done = True
        g = title_group if is_title else group
        lh = title_line_height if is_title else line_height
        for wl, indent_w in wrap_line(g, raw, max_width):
            display_lines.append((wl, indent_w, lh, is_title))
        if is_title:
            # 标题段落后追加一行正文高的间距（空行条目按半行距渲染），增强标题层级
            display_lines.append(("", 0, 2 * line_height, False))

    # 空行压缩为半行距，保持段落感
    total_h = sum(lh if wl else lh // 2 for wl, _indent, lh, _t in display_lines)
    img_h = padding * 2 + max(total_h, line_height)

    img = Image.new("RGB", (cfg["width"], img_h), cfg["bg_color"])
    draw = ImageDraw.Draw(img)

    # 圆角描边卡片
    draw.rounded_rectangle(
        [1, 1, cfg["width"] - 2, img_h - 2],
        radius=cfg["corner_radius"],
        outline=cfg["outline_color"],
        width=2,
    )

    y = padding
    for wl, indent_w, lh, is_title in display_lines:
        if wl:
            color = cfg["title_color"] if is_title else cfg["text_color"]
            g = title_group if is_title else group
            g.draw(img, draw, (padding + indent_w, y), wl, color, lh)
        y += lh if wl else lh // 2

    return img


def main():
    cfg = load_config()
    text = read_clipboard_text()
    if not text:
        print("剪贴板没有文本内容，请先复制文字再运行")
        sys.exit(1)

    text = clean_text(text)
    img = render_card(text, cfg)

    if "--save" in sys.argv:
        save_path = BASE_DIR / "out.png"
        img.save(save_path)
        print(f"已保存 PNG: {save_path}")

    write_clipboard_image(img)
    winsound.MessageBeep(winsound.MB_OK)  # 成功提示音
    print(f"已生成 {img.width}x{img.height} 长图并写入剪贴板，直接 Ctrl+V 粘贴")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 热键隐藏控制台窗口运行时，错误改为弹窗提示（否则用户看不到报错）
        msg = "Text2Img 出错:\n\n" + traceback.format_exc()
        ctypes.windll.user32.MessageBoxW(0, msg, "Text2Img 错误", 0x10)
        winsound.MessageBeep(winsound.MB_ICONERROR)
