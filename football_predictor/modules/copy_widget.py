"""自定义复制组件  100% 可用，不依赖 Streamlit 内置组件"""
import streamlit.components.v1 as components


def copy_block(text: str, label: str = "📋 一键复制",
               height: int = 320, key: str = ""):
    """
    可复制的文本框 + 一键复制按钮
    - 纯 HTML/JS，绕过 Streamlit 的 download/code 组件
    - 兼容深色主题
    - 支持 Ctrl+A / 手动选中兜底
    """
    safe_text = (text
                 .replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <textarea id="txt_{key}" readonly
        style="width:100%; height:{height - 70}px; box-sizing:border-box;
               font-family:'Consolas','Monaco',monospace; font-size:12px;
               background:#0E1117; color:#FAFAFA;
               border:1px solid #2a2a2a; border-radius:6px;
               padding:10px; resize:vertical; line-height:1.5;"
        >{safe_text}</textarea>
      <button id="btn_{key}" onclick="copy_{key}()"
        style="width:100%; margin-top:6px; padding:8px 12px;
               background:#FF4B4B; color:white; border:none;
               border-radius:6px; cursor:pointer; font-size:13px;
               font-weight:600;">
        {label}
      </button>
    </div>
    <script>
    function copy_{key}() {{
        const ta = document.getElementById('txt_{key}');
        const btn = document.getElementById('btn_{key}');
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, ta.value.length);

        let done = false;
        try {{
            if (navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(ta.value).then(() => {{
                    btn.textContent = '✅ 已复制到剪贴板';
                    setTimeout(() => btn.textContent = '{label}', 1500);
                }});
                done = true;
            }}
        }} catch(e) {{}}

        if (!done) {{
            try {{
                const ok = document.execCommand('copy');
                btn.textContent = ok ? '✅ 已复制' : '⚠️ 请手动 Ctrl+C';
                setTimeout(() => btn.textContent = '{label}', 1500);
            }} catch(e) {{
                btn.textContent = '⚠️ 请手动 Ctrl+C';
            }}
        }}
    }}
    </script>
    """
    components.html(html, height=height, scrolling=False)
