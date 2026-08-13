# -*- coding: utf-8 -*-
"""
clip_bridge.py — 剪贴板图片桥接

功能: 检测剪贴板中"纯位图且无文件引用"的图片（如系统截图 Win+Shift+S），
      自动落盘为 PNG 到 temp，并把剪贴板重写为「位图 + 文件引用(CF_HDROP)」——
      与 QQ 复制图片后的剪贴板格式一致，让 cc 终端能直接 Ctrl+V 识别为图片附件，
      同时微信/QQ 粘贴时仍读到原始位图，不受影响。

触发: 由 text2img.ahk 的 OnClipboardChange 监听自动调用（一次性脚本，不常驻）。
      剪贴板已有文件引用（QQ 复制/文件复制）或非位图时直接退出，防止死循环。

依赖: pip install pillow pywin32
"""

import io
import os
import struct
import sys
import time
from pathlib import Path

# 控制台按 UTF-8 输出（隐藏窗口运行时无控制台，print 无害）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import win32clipboard  # pywin32：读写系统剪贴板
from PIL import Image

# 桥接图片落盘目录（temp 下，自动创建）
CACHE_DIR = Path(os.environ.get("TEMP", r"C:\Temp")) / "cc_clipboard"


def has_format(fmt):
    """剪贴板是否包含指定格式"""
    win32clipboard.OpenClipboard()
    try:
        return win32clipboard.IsClipboardFormatAvailable(fmt)
    finally:
        win32clipboard.CloseClipboard()


def make_hdrop(paths):
    """构造 CF_HDROP 数据（DROPFILES 结构 + UTF-16 文件路径列表，双 null 结尾）"""
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)  # pFiles, pt.x, pt.y, fNC, fWide
    data = header
    for p in paths:
        data += str(p).encode("utf-16-le") + b"\x00\x00"
    return data + b"\x00\x00"  # 文件列表双 null 结尾


def main():
    # 1. 无位图（纯文本/其他）或已有文件引用（QQ 复制、文件复制）→ 无需转换
    if not has_format(win32clipboard.CF_DIB):
        return
    if has_format(win32clipboard.CF_HDROP):
        return  # 已有文件引用：跳过，避免与自身转换形成死循环

    # 2. 读取位图数据（BITMAPINFOHEADER + 像素）
    win32clipboard.OpenClipboard()
    try:
        dib = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
    except Exception:
        return
    finally:
        win32clipboard.CloseClipboard()
    if not dib:
        return

    # 3. CF_DIB → PIL 图像（补 BMP 文件头），存 PNG 到 temp
    # 像素偏移 = 14(文件头) + BITMAPINFOHEADER 大小(读 dib 前 4 字节)；
    # 写错偏移会把 infoheader 当像素解析，导致通道错乱（R/B 互换）
    bi_size = struct.unpack("<I", dib[0:4])[0]
    bmp = (
        b"BM"
        + (14 + len(dib)).to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + (14 + bi_size).to_bytes(4, "little")
        + dib
    )
    try:
        img = Image.open(io.BytesIO(bmp))
        img.load()  # 触发解码，验证数据可用
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = CACHE_DIR / f"{int(time.time() * 1000)}.png"
        img.save(out, "PNG")
    except Exception:
        return  # 位图数据异常（如 RLE 压缩等），放弃转换

    # 4. 重写剪贴板：位图(原数据) + 文件引用 —— QQ 同款双格式
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
        win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, make_hdrop([out]))
    finally:
        win32clipboard.CloseClipboard()
    print(f"桥接完成: {out}")


if __name__ == "__main__":
    main()
