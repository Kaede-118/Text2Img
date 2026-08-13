# Text2Img — 剪贴板文本转长图 + 图片桥接

复制文字 → 按热键 → 卡片式长图进剪贴板 → 随处 Ctrl+V 粘贴。
截图后 → cc 终端直接 Ctrl+V 粘贴图片（自动桥接，无需手动操作）。

## 文件

| 文件 | 说明 |
|------|------|
| `text2img.py` | 文字转长图：读剪贴板 → 渲染 → 写回剪贴板 |
| `clip_bridge.py` | 图片桥接：截图位图 → 落盘 temp → 剪贴板补文件引用 |
| `text2img.ahk` | AHK v2 常驻脚本：热键 `Ctrl+Shift+C` + 剪贴板变化监听 |
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
4. 按 `Ctrl+Shift+C`
5. 到微信 / QQ / 文档里 Ctrl+V 粘贴即可

调试可用：`python text2img.py --save`（同时保存 out.png 到本目录）

## 剪贴板图片桥接（cc 终端直接粘贴截图）

系统截图（Win+Shift+S）后剪贴板只有位图，cc 终端收不到。AHK 常驻监听检测到
「纯位图无文件引用」时，自动落盘 PNG 到 `%TEMP%\cc_clipboard\` 并重写剪贴板为
「位图 + 文件引用」——与 QQ 复制图片同款格式，cc 输入框 Ctrl+V 直接识别为图片附件；
微信/QQ 粘贴时仍读到原始位图，不受影响。

```text
截图 → 剪贴板位图 → AHK 监听 → clip_bridge.py 落盘+补文件引用 → cc Ctrl+V ✓
```

> 提示：截图后稍等 1~2 秒再粘贴（AHK 触发 + 转换需要时间）。落盘文件在系统 temp，
> 自动清理。已有文件引用的剪贴板（QQ 复制等）不会被重复转换。

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
