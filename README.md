# Text2Img — 剪贴板文字一键变长图

复制文字 → 按热键 → 卡片式长图进剪贴板 → 随处 Ctrl+V 粘贴。

## 文件

| 文件 | 说明 |
|------|------|
| `text2img.py` | 核心脚本：读剪贴板 → 渲染 → 写回剪贴板 |
| `text2img.ahk` | AHK 热键脚本（v2 语法），全局热键 `Ctrl+Shift+C` |
| `config.json` | 样式配置（首次运行自动生成） |

## 使用

1. 安装依赖（一次性）：

   ```bash
   pip install pillow pywin32
   ```

2. 复制任意文字
3. 按 `Ctrl+Shift+C`（需先运行 `text2img.ahk` 常驻托盘；与 Ditto 的 `Ctrl+Shift+V` 打开剪贴板对应成对）
4. 到微信 / QQ / 文档里 Ctrl+V 粘贴即可

调试可用：`python text2img.py --save`（同时保存 out.png 到本目录）

## 样式配置（config.json）

| 字段 | 含义 |
|------|------|
| `width` | 图片宽度 px |
| `padding` | 卡片内边距 px |
| `corner_radius` | 卡片圆角 px |
| `bg_color` / `outline_color` | 背景色 / 描边色 |
| `title_color` / `text_color` | 标题色 / 正文色 |
| `title_scale` | 标题字号倍数（相对正文） |
| `font_size` | 正文字号 px |
| `line_spacing` | 行距倍数 |
| `font_path` | 字体文件（默认微软雅黑） |

## 改热键

编辑 `text2img.ahk` 里的 `^+c`（`^`=Ctrl，`!`=Alt，`+`=Shift，`#`=Win），改完重新加载脚本（托盘右键 → Reload）。

> 注意：若你用的是 AutoHotkey v1，请告诉我，我把脚本改成 v1 语法。
