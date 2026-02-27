import re

file_path = "backend/dashboard/app.py"
with open(file_path, "r", encoding="utf-8") as f:
    code = f.read()

# 置換ルール
# より暗いグレー (#475569) -> より明るいグレー (#94a3b8)
# 中間のグレー (#64748b) -> かなり明るいグレー (#cbd5e1)
# 明るめのグレー (#94a3b8) -> 更に明るい/白に近いグレー (#e2e8f0)

code = code.replace("#475569", "#94a3b8")
code = code.replace("#64748b", "#cbd5e1")
code = code.replace("#94a3b8", "#e2e8f0")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Color replacements done.")
