# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Text2Img — 把剪贴板文本一键渲染成卡片式长图并写回剪贴板（Ctrl+V 直接粘贴）。全局热键 `Ctrl+Shift+C`（AHK v2 脚本 `text2img.ahk` 常驻托盘触发）。样式（宽度/配色/字号/字体）由 `config.json` 控制。

## Commands

```bash
# 运行（读剪贴板 → 渲染 → 写回剪贴板；--save 额外保存 out.png 调试）
python text2img.py [--save]

# 依赖（全部为运行所需，无 dev 依赖）
pip install pillow pywin32 fonttools freetype-py
```

没有测试、lint、构建步骤。

## Architecture

单文件 `text2img.py`（~430 行），流程为：`main` → `read_clipboard_text` → `clean_text` → `render_card` → `write_clipboard_image`。

### 关键设计决策（踩坑总结）

- **彩色 emoji 用 FreeType 渲染，不是 Pillow**：`seguiemj.ttf`（Segoe UI Emoji）是 COLRv1 彩色字形，Pillow 只能渲染单色线稿；Pillow 也加载不了 CBDT 位图字体。`EmojiBitmaps` 用 `freetype-py` 的 `FT_LOAD_COLOR` 渲染，按 `pixel_mode` 分支处理（BGRA = 彩色字形反预乘；GRAY = 单色字形灰度作 alpha）。WPF 离屏渲染和 GDI+ 都只能出单色，已验证不可用。
- **`FontGroup` 是渲染单元分发器**：逐字符决定用 emoji 位图还是字体（雅黑 → seguiemj → seguisym 回退链），`unit_for` 判定 + 相邻同单元分段合并绘制。Unicode 区块（`_is_emoji`）过滤 ASCII/标点，避免空格等被当 emoji。
- **换行 `wrap_line` 支持列表悬挂缩进**：检测列表标记（`- * + 1. •`）或前导空白，首行带标记从行首绘制，续行缩进到标记后内容起点（返回 `(文本, 缩进px)` 元组列表）。英文按空白分词整体换行，超宽块才逐字符硬断。
- **`load_config` 用默认配置兜底 merge**（`{**DEFAULT_CONFIG, **user_cfg}`）：旧 config 缺新字段（如 `emoji_font_path`）时自动补全，不会静默失效。
- **`clean_text` 预处理**：归一化 CRLF、删零宽字符/变体选择符/控制字符、`\t` 展开为空格——否则这些字符渲染成豆腐块。
- **剪贴板写入用 CF_DIB**：PIL 存 BMP 后跳过 14 字节文件头，微信/QQ/文档可直接粘贴。

### 运行时行为

- 控制台输出经 `sys.stdout.reconfigure(encoding="utf-8")`，防 GBK 乱码。
- 顶层 `try/except` 捕获未处理异常并弹 `MessageBox` 提示——AHK 以 `Hide` 选项静默运行（无控制台窗口），必须弹窗否则错误不可见。
- `config.json`、`out.png` 已 gitignore（config 含本地绝对路径字体配置，脚本会自动生成默认模板）。

## Batch/脚本

- `text2img.ahk`：AHK **v2** 语法，热键 `^+c`（Ctrl+Shift+C），`Run(..., "Hide")` 静默运行。改热键后需重载脚本（托盘右键 Reload 或杀进程重启）。
