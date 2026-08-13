# Text2Img — 剪贴板文字一键变长图

复制文字 → 按热键 → 卡片式长图进剪贴板 → 随处 Ctrl+V 粘贴。

## 文件

| 文件 | 说明 |
|------|------|
| `text2img.py` | 核心脚本：读剪贴板 → 渲染 → 写回剪贴板 |
| `text2img.ahk` | AHK 热键脚本（v2 语法），全局热键 `Ctrl+Shift+C` |
| `config.json` | 样式配置（首次运行自动生成） |

## 依赖

- **Python 3** + pip：

  ```bash
  pip install pillow pywin32 fonttools freetype-py
  ```

- **AutoHotkey v2**（运行 `text2img.ahk` 需要，安装后双击 .ahk 即常驻托盘）：

  ```bash
  winget install AutoHotkey.AutoHotkey
  ```

## 使用

1. 按上面的依赖安装好
2. 双击 `text2img.ahk` 常驻托盘（复制到「启动」文件夹可开机自启）
3. 复制任意文字
4. 按 `Ctrl+Shift+C`（与 Ditto 的 `Ctrl+Shift+V` 打开剪贴板对应成对）
5. 到微信 / QQ / 文档里 Ctrl+V 粘贴即可

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
| `font_path` | 主字体文件（默认微软雅黑） |
| `fallback_fonts` | 回退字体列表（主字体缺字形时按序补绘） |
| `emoji_font_path` | 彩色 emoji 字体（默认 Segoe UI Emoji，FreeType COLR 渲染） |

## 改热键

编辑 `text2img.ahk` 里的 `^+c`（`^`=Ctrl，`!`=Alt，`+`=Shift，`#`=Win），改完重新加载脚本（托盘右键 → Reload）。
