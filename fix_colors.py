import re

with open('backend/dashboard/app.py', 'r') as f:
    content = f.read()

# Replace colors
content = content.replace("color:#e2e8f0", "color:#334155")
content = content.replace("color:#cbd5e1", "color:#64748b")
content = content.replace("background:rgba(15,23,42,0.8)", "background:#ffffff")
content = content.replace("border:1px solid #1e293b", "border:1px solid #e2e8f0")
content = content.replace("background:#1e293b; border-radius:4px; height:6px", "background:#e2e8f0; border-radius:4px; height:6px")
content = content.replace("color:#bae6fd", "color:#0284c7")
content = content.replace("color:#38bdf8", "color:#0284c7")
content = content.replace("background:rgba(56,189,248,0.2)", "background:#e0f2fe")
content = content.replace("color:#ffffff", "color:#0f172a")

# Fix button or badge where white is needed
content = content.replace("background:#10b981; color:#0f172a", "background:#10b981; color:#ffffff")
content = content.replace("color:#fff", "color:#ffffff")

with open('backend/dashboard/app.py', 'w') as f:
    f.write(content)

print("Color replacements done.")
