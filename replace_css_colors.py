import re

file_path = "backend/dashboard/utils.py"
with open(file_path, "r", encoding="utf-8") as f:
    code = f.read()

# Replace colors
code = code.replace("#94a3b8", "#e2e8f0")
code = code.replace("#64748b", "#cbd5e1")
code = code.replace("#475569", "#94a3b8")

# Add styles for radio buttons to make them act like bright tabs
radio_css = """
    /* ラジオボタン（疑似タブ）の文字色を明るくする */
    div[role="radiogroup"] label {
        color: #e2e8f0 !important;
        font-weight: 600;
    }
    
    /* 通知アラート */"""

code = code.replace("    /* 通知アラート */", radio_css)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(code)

print("CSS replacements done.")
