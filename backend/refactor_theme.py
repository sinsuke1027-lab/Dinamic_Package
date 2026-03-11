import re
import ast
import traceback

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
    (r"#4ade80", "success_light"),
    (r"#f87171", "danger"),
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

    # Some st.markdown strings might not be f-strings after introducing {}
    # Make sure st.markdown('<div', or st.markdown("<style", etc are f-strings if they contain {Theme
    # Instead of complex regex, let's target specific patterns we know exist.
    
    # st.markdown('<p ...') -> st.markdown(f'<p ...') if it has {Theme
    def make_fstring(m):
        full_match = m.group(0)
        inner_quote = m.group(1) # ' or "
        inner_content = m.group(2)
        if "{Theme." in inner_content:
            return f'st.markdown(f{inner_quote}{inner_content}{inner_quote}'
        return full_match

    content = re.sub(r'st\.markdown\((\'\'\'|"""|\'|")([\s\S]*?)\1', make_fstring, content)

    with open(filename, "w") as f:
        f.write(content)
        
    # Validate syntax
    try:
        with open(filename, "r") as f:
            ast.parse(f.read())
            print(f"✅ {filename} Syntax OK")
    except SyntaxError as e:
        print(f"❌ Syntax Error in {filename}: {e}")
        traceback.print_exc()

refactor("dashboard/app.py")
refactor("dashboard/utils.py")
