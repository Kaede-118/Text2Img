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
    pip install pillow pywin32 fonttools freetype-py
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
    "title_bg": "#F2F4F7",                 # 标题底色（与表头底纹一致）
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
    # 彩色 emoji 字体：FreeType COLRv1 渲染（seguiemj 微软风格，与终端一致）
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
        字体按实际字形宽（tab 展开为 4 空格）"""
        if unit[0] == "emoji":
            return sum(self.emoji.get(c).width for c in seg)
        return unit[1].getlength(seg.replace("\t", "    "))

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
                seg_disp = seg.replace("\t", "    ")  # tab 展开为 4 空格宽再绘制
                draw.text((x, y), seg_disp, font=unit[1], fill=fill)
                x += unit[1].getlength(seg_disp)
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
            # 制表符统一转为 4 空格：表格自绘后不再依赖 tab 对齐输入，
            # 避免 tab 残留进单元格/文本（列表行首 tab 由前导空白逻辑处理）
            out.append("    ")
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
    cleaned = "".join(out)
    # 行首（允许前导空格）的 ❯ 提示符（cc 终端复制时带入的输入提示）及其后空白删除
    return re.sub(r"^\s*❯\s*", "", cleaned, flags=re.M)


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


def is_table_row(line):
    """表格行：markdown 竖线（|）或 box drawing 字符（┌─┬─┐│ 等，cc 终端
    渲染 markdown 表格时的形态）→ 整体不换行，避免列结构被拆断"""
    if "|" in line:
        return True
    return any(0x2500 <= ord(c) <= 0x257F for c in line)


def is_ascii_table_row(line):
    """ASCII markdown 表格行（| 分隔且无 box 字符）：源码列宽常不齐，需规范化"""
    return "|" in line and not any(0x2500 <= ord(c) <= 0x257F for c in line)


def is_sep_cells(cells):
    """分隔线行：ASCII 分隔线（- :）或 box 表格的顶/中/底线行
    （┌─┬─┐ 等，不含 │ 分隔符，split 后整行是一个单元格）"""
    if all(not c or set(c) <= set("-:") for c in cells):
        return True
    joined = "".join(cells)
    return bool(joined) and set(joined) <= set("┌┬┐├┼┤└┴┘─")


def disp_w(s):
    """显示宽度：CJK 全角字符计 2，其余计 1（等宽渲染按半角单位对齐）"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in s)


# markdown 标题标记（# 开头，容忍前导空白；# 后须有空白避免误判 #话题）
HEADING_RE = re.compile(r"^\s*#{1,6}\s+")


def is_heading(row):
    """是否 markdown 标题行（所有 # 标题统一加底色）"""
    return HEADING_RE.match(row) is not None


def parse_table_row(line):
    """解析表格行为单元格列表（兼容 ASCII | 和 box │ 两种分隔）。
    单元格内制表符清掉（终端复制表格常带 tab 对齐符，自绘表格不需要）"""
    line = line.strip()
    if "│" in line:  # box 表格
        cells = [c.strip().replace("\t", "") for c in line.strip("│").split("│")]
    elif "|" in line:  # markdown 表格
        cells = [c.strip().replace("\t", "") for c in line.strip("|").split("|")]
    else:
        cells = [line.replace("\t", "")]
    return cells


def parse_box_rows(rows):
    """解析 box 表格（│ 分隔）：取「过半行共有的 │ 列位置」为分隔符，
    单元格内容里出现的 │（位置不齐）自动排除——按对齐结构清洗，
    不依赖单行 split（内容含 │ 时不会被误拆）"""
    from collections import Counter

    stripped = [r.strip() for r in rows]
    counts = Counter()
    for line in stripped:
        for i, ch in enumerate(line):
            if ch == "│":
                counts[i] += 1
    # 分隔符位置 = 频率达到最高频的位置（所有数据行对齐的 │）；
    # 顶/中/底线行（┌─┬─┐）不含 │ 不影响；内容里的 │ 频率低自动排除
    max_c = max(counts.values()) if counts else 0
    seps = sorted(i for i, c in counts.items() if c >= max_c)

    if len(seps) < 2:
        # 列宽不齐的手写表格：回退简单 split（按 │ 拆），保证基本可用
        result = []
        for line in stripped:
            if "│" in line:
                cells = [c.strip() for c in line.strip("│").split("│")]
            else:
                cells = [line]
            result.append((cells, is_sep_cells(cells)))
        return result

    result = []
    for line in stripped:
        cells = []
        prev = 0
        for p in seps:
            cells.append(line[prev:p].strip())
            prev = p + 1
        cells.append(line[prev:].strip())
        # 首尾的 │ 是表格边框，去掉产生的空单元格
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        result.append((cells, is_sep_cells(cells)))
    return result


class MdTable:
    """解析后的表格：行列表（单元格, 是否分隔线），列宽按显示宽度自计算。
    box 表格（│）按对齐位置解析，内容里的 │ 不误拆"""

    def __init__(self, rows):
        if any("│" in r for r in rows):
            self.rows = parse_box_rows(rows)  # box 表格：对齐结构清洗
        else:
            self.rows = []
            for row in rows:
                cells = parse_table_row(row)
                self.rows.append((cells, is_sep_cells(cells)))
        self.ncols = max(len(c) for c, _ in self.rows)

    def cell_widths(self):
        """每列显示宽度（内容最大显示宽 + 2 内边距）"""
        widths = []
        for j in range(self.ncols):
            w = max((disp_w(c[j]) for c, sep in self.rows if not sep and j < len(c)), default=2)
            widths.append(w + 2)
        return widths

    def is_header(self):
        """是否有表头（存在非分隔线行；box 表格首行是顶线需跳过）"""
        return any(not sep for _c, sep in self.rows)


def draw_table(img, draw, x, y, table, group, font_size, line_height, cfg):
    """自绘表格：列宽自计算、边框自绘制、单元格用普通字体渲染。
    返回 (表格宽, 表格高)"""
    ncols = table.ncols
    # 列宽：半角单位 × 半角像素宽（中文全角=2 半角，字号为全角像素）
    widths = [w * font_size // 2 for w in table.cell_widths()]
    border = 2  # 单元格边框宽度
    row_h = line_height
    total_w = sum(widths) + (ncols + 1) * border
    # 行布局：分隔线行只占边框高度，数据行占完整行高
    row_heights = [border if sep else row_h for _c, sep in table.rows]
    total_h = sum(row_heights) + border  # 含底部边框
    line_color = cfg.get("table_border_color", "#C8CCD4")
    header_bg = cfg.get("table_header_bg", "#F2F4F7")

    # 表头底纹：第一个非分隔线行（box 表格首行是顶线，需跳过其 2px 高度）
    first_data = next((i for i, (_c, s) in enumerate(table.rows) if not s), None)
    if first_data is not None:
        y_cursor = y
        for _i in range(first_data):
            y_cursor += row_heights[_i]
        draw.rectangle([x, y_cursor, x + total_w, y_cursor + row_h], fill=header_bg)

    # 横向边框线（每行边界）
    y_cursor = y
    for r, (_c, _sep) in enumerate(table.rows):
        draw.line([(x, y_cursor), (x + total_w - 1, y_cursor)], fill=line_color, width=1)
        y_cursor += row_heights[r]
    draw.line([(x, y_cursor), (x + total_w - 1, y_cursor)], fill=line_color, width=1)
    # 纵向边框线
    for c in range(ncols + 1):
        xx = x + c * border + sum(widths[:c])
        draw.line([(xx, y), (xx, y + total_h - 1)], fill=line_color, width=1)

    # 单元格文字（左对齐，垂直居中；分隔线行跳过）
    y_cursor = y
    for r, (cells, is_sep) in enumerate(table.rows):
        if not is_sep:
            yy = y_cursor + border
            for c in range(ncols):
                cell = cells[c] if c < len(cells) else ""
                if not cell:
                    continue
                xx = x + c * border + sum(widths[:c]) + border
                pad = font_size // 2
                color = cfg["title_color"] if (r == first_data and table.is_header()) else cfg["text_color"]
                group.draw(
                    img, draw, (xx + pad, yy + (row_h - font_size) // 2),
                    cell, color, row_h,
                )
        y_cursor += row_heights[r]

    return total_w, total_h


def wrap_line(group, line, max_width):
    """单行文本按宽度自动换行：按空白块分词，单词整体换行不拆开；
    仅当单个无空白块本身超宽（如超长中文段落）时才逐字符硬断。
    表格行（含 |）整体不换行。返回 [(行文本, 行缩进px), ...]：
    首行缩进 = 原始前导（列表标记/空白），续行悬挂缩进与首行内容对齐"""
    if not line:
        return [("", 0)]
    if is_table_row(line):
        return [(line, 0)]  # 表格行不换行（render_card 会按宽度缩放字号）
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

    parts = re.split(r"( +)", rest)  # 仅按普通空格分词：tab 不参与断行，避免拆断列表/表格
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
    """渲染卡片式长图：文本行逐行布局，表格块解析后自绘（列宽自计算、
    边框自绘制），不再依赖输入文本的对齐；表格字号优先正文 100%，
    画布加宽兜底（上限 2x），超限才缩字号（下限 50% 取偶）"""
    font_size = cfg["font_size"]
    title_size = int(font_size * cfg["title_scale"])
    line_height = int(font_size * cfg["line_spacing"])
    title_line_height = int(title_size * cfg["line_spacing"])
    # 表格字号下限 = 正文 50%（取偶避免半像素错位）
    min_table_size = max(10, int(font_size * 0.5) - (int(font_size * 0.5) % 2))

    fallback = cfg.get("fallback_fonts", [])
    emoji_font = cfg.get("emoji_font_path")
    group = FontGroup(cfg["font_path"], font_size, fallback, emoji_font)
    title_group = FontGroup(cfg["font_path"], title_size, fallback, emoji_font)
    if group.emoji:
        group.emoji.prepare(text)  # 批量渲染文本中未缓存的彩色 emoji

    padding = cfg["padding"]
    rows_text = text.split("\n")

    def table_px_width(table, size):
        """表格像素总宽：列宽(半角单位) × 半角像素 + 边框"""
        return sum(w * size // 2 for w in table.cell_widths()) + (table.ncols + 1) * 2

    # ---- 第一步：扫描文本，切分表格块/文本行，确定表格字号与画布宽度 ----
    max_canvas_w = cfg["width"] * 2
    items = []  # ('table', MdTable) 或 ('text', 原始行)
    i = 0
    while i < len(rows_text):
        if is_table_row(rows_text[i]):
            block = []
            while i < len(rows_text) and is_table_row(rows_text[i]):
                block.append(rows_text[i])
                i += 1
            items.append(("table", MdTable(block)))
        else:
            items.append(("text", rows_text[i]))
            i += 1

    canvas_w = cfg["width"]
    table_size = {}
    for kind, obj in items:
        if kind == "table":
            table = obj
            size = font_size
            w100 = table_px_width(table, font_size)
            if w100 > max_canvas_w - padding * 2 - 10:
                size = max(min_table_size, int(font_size * (max_canvas_w - padding * 2 - 10) / w100))
                size = size - (size % 2)
            table_size[id(table)] = size
            canvas_w = max(canvas_w, table_px_width(table, size) + padding * 2)
    avail = canvas_w - padding * 2

    # ---- 第二步：布局所有条目（文本行 + 表格块），统计总高度 ----
    layout = []  # ('text', wl, indent, lh, is_title, group) 或 ('table', table, group, size, lh, w, h)
    total_h = padding
    for kind, obj in items:
        if kind == "table":
            table = obj
            size = table_size[id(table)]
            g = FontGroup(cfg["font_path"], size, fallback, emoji_font)
            lh = int(size * cfg["line_spacing"])
            w = table_px_width(table, size)
            # 高度：数据行占行高，分隔线行只占边框，含底部边框
            n_sep = sum(1 for _c, s in table.rows if s)
            h = (len(table.rows) - n_sep) * lh + (len(table.rows) + 1) * 2
            layout.append(("table", table, g, size, lh, w, h))
            total_h += h
        else:
            raw = obj
            # 标题 = markdown 标题标记行（# 开头，非表格行），所有标题统一底色
            is_title = is_heading(raw) and not is_table_row(raw)
            g = title_group if is_title else group
            lh = title_line_height if is_title else line_height
            for wl, indent_w in wrap_line(g, raw, avail):
                layout.append(("text", wl, indent_w, lh, is_title, g))
                total_h += lh if wl else lh // 2
            if is_title:
                layout.append(("text", "", 0, 2 * line_height, False, None))
                total_h += line_height
    img_h = total_h + padding

    img = Image.new("RGB", (canvas_w, img_h), cfg["bg_color"])
    draw = ImageDraw.Draw(img)

    # 圆角描边卡片
    draw.rounded_rectangle(
        [1, 1, canvas_w - 2, img_h - 2],
        radius=cfg["corner_radius"],
        outline=cfg["outline_color"],
        width=2,
    )

    y = padding
    for item in layout:
        if item[0] == "table":
            _k, table, g, size, lh, w, h = item
            draw_table(img, draw, padding, y, table, g, size, lh, cfg)
            y += h
        else:
            _k, wl, indent_w, lh, is_title, g2 = item
            if wl:
                if is_title:
                    # 标题底纹（与表头底色一致，整行浅色背景）
                    draw.rectangle(
                        [padding, y, canvas_w - padding, y + lh],
                        fill=cfg.get("title_bg", "#F2F4F7"),
                    )
                color = cfg["title_color"] if is_title else cfg["text_color"]
                g = g2 if g2 is not None else (title_group if is_title else group)
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
        winsound.MessageBeep(winsound.MB_ICONHAND)
