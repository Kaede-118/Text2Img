; text2img.ahk — 一键文字转长图（AutoHotkey v2 语法）
; 全局热键: Ctrl+Shift+C → 运行 text2img.py（读剪贴板 → 渲染长图 → 写回剪贴板）
;           （与 Ditto 的 Ctrl+Shift+V 打开剪贴板对应成对）
; 用法: 双击本脚本常驻托盘，或复制到「启动」文件夹开机自启
; 改热键: 修改下方 ^+c 部分（^=Ctrl !=Alt +=Shift #=Win）

#Requires AutoHotkey v2.0

; Hide 选项：python 控制台窗口不可见，不打扰操作
^+c::Run('python "C:\Desktop\Text2Img\text2img.py"', , 'Hide')
