; text2img.ahk — 文字转长图 + 剪贴板图片桥接（AutoHotkey v2 语法）
;
; 功能 1: 全局热键 Ctrl+Shift+C → text2img.py（读剪贴板文本 → 渲染长图 → 写回剪贴板）
; 功能 2: 剪贴板出现"纯位图无文件引用"的图片（如系统截图）→ 自动调用
;         clip_bridge.py 落盘并补文件引用，cc 终端可直接 Ctrl+V 粘贴图片
;
; 用法: 双击本脚本常驻托盘，或复制到「启动」文件夹开机自启
; 改热键: 修改下方 ^+c 部分（^=Ctrl !=Alt +=Shift #=Win）

#Requires AutoHotkey v2.0

; ---------- 功能 1: Ctrl+Shift+C 文字转长图 ----------
; Hide 选项：python 控制台窗口不可见，不打扰操作
^+c::Run('python "C:\Desktop\Text2Img\text2img.py"', , 'Hide')

; ---------- 功能 2: 剪贴板图片桥接 ----------
; 监听剪贴板变化：Type=2 表示含图片或文件
; 延迟 50ms 再触发，避免在剪贴板锁占用期间启动 python
OnClipboardChange(ClipChanged)

ClipChanged(Type) {
    if Type == 2
        SetTimer(DoBridge, -50)
}

DoBridge() {
    Run('python "C:\Desktop\Text2Img\clip_bridge.py"', , 'Hide')
}
