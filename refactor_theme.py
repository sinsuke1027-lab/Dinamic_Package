import re
import ast

THEME_REPLACEMENTS = [
    (r"#1e293b", "text_main"),
    (r"#0f172a", "text_dark"),
    (r"#334155", "text_sec"),
    (r"#64748b", "text_muted"),
    (r"#cbd5e1", "border_dark"),
    (r"#e2e8f0", "border_light"),
    (r"#f8fafc", "bg_main"),
    (r"#ffffff", "white"),
    (r"#fff(?![a-fA-F0-9])", "white"),
    (r"#f1f5f9", "bg_hover"),
    (r"#6366f1", "primary"),
    (r"#4f46e5", "primary_hover"),
    (r"#10b981", "success"),
    (r"#f87171", "danger"),
    (r"#4ade80", "success_light"),
    (r"#f59e0b", "warning"),
    (r"#0284c7", "info"),
    (r"#a78bfa", "chart_accent"),
    (r"#38bdf8", "info_light"),
    (r"linear-gradient\(135deg,#e0f2fe 0%,#bae6fd 100%\)", "grad_info"),
    (r"rgba\(2,132,199,0\.3\)", "border_info_alpha"),
    (r"rgba\(2,132,199,0\.1\)", "shadow_info_alpha"),
    (r"linear-gradient\(135deg,#f3e8ff 0%,#e9d5ff 100%\)", "grad_ai"),
    (r"rgba\(139,92,246,0\.3\)", "border_ai_alpha"),
    (r"rgba\(139,92,246,0\.1\)", "shadow_ai_alpha"),
    (r"rgba\(16,185,129,0\.1\)", "bg_success_alpha"),
    (r"rgba\(16,185,129,0\.3\)", "border_success_alpha"),
    (r"rgba\(167,139,250,0\.18\)", "chart_fill_alpha"),
    (r"rgba\(167,139,250,0\.1\)", "chart_fill_alpha2"),
    (r"rgba\(56,189,248,0\.2\)", "bg_info_light_alpha"),
    (r"#dcfce7", "badge_green_bg"),
    (r"#166534", "badge_green_text"),
    (r"#fee2e2", "badge_red_bg"),
    (r"#991b1b", "badge_red_text"),
    (r"#fef3c7", "alert_warning_bg"),
    (r"#fde68a", "alert_warning_border"),
    (r"#92400e", "alert_warning_text"),
    (r"#c7d2fe", "alert_info_border"),
    (r"#3730a3", "alert_info_text"),
    (r"#e0e7ff", "alert_info_bg"),
]

def refactor(filename):
    with open(filename, "r") as f:
        content = f.read()

    # Step 1: Add import
    if "from dashboard.theme import Theme" not in content:
        if "from dashboard.utils import" in content:
            content = content.replace("from dashboard.utils import", "from dashboard.theme import Theme\nfrom dashboard.utils import", 1)
        else:
            content = "from dashboard.theme import Theme\n" + content
        
    # Replacements
    for hex_code, prop in THEME_REPLACEMENTS:
        # replace in Plotly/Kwargs
        content = re.sub(rf'"{hex_code}"', f'Theme.{prop}', content)
        content = re.sub(rf"'{hex_code}'", f'Theme.{prop}', content)
        
        # replace in HTML/CSS
        content = re.sub(rf'{hex_code}', f'{{Theme.{prop}}}', content)

    # st.markdown fallback to f-string
    content = re.sub(r'st\.markdown\(\s*\'(<[^>]+>.*?)\'\s*(,|\))', r"st.markdown(f'\1'\2", content, flags=re.DOTALL)
    content = re.sub(r'st\.markdown\(\s*"(<[^>]+>.*?)"\s*(,|\))', r'st.markdown(f"\1"\2', content, flags=re.DOTALL)
    
    # st.markdown with single quotes
    content = re.sub(r"st\.markdown\(\s*'<div(.*?)'\s*(,|\))", r"st.markdown(f'<div\1'\2", content)
    content = re.sub(r"st\.markdown\(\s*'<p(.*?)'\s*(,|\))", r"st.markdown(f'<p\1'\2", content)

    with open(filename, "w") as f:
        f.write(content)
        
    # Validate syntax
    with open(filename, "r") as f:
        ast.parse(f.read())
        print(f"✅ {filename} Syntax OK")

refactor("backend/dashboard/app.py")
refactor("backend/dashboard/utils.py")
