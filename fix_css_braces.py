import re
import ast

def fix_css_in_utils():
    with open("backend/dashboard/utils.py", "r") as f:
        content = f.read()
        
    # The start of apply_custom_css
    start_str = 'def apply_custom_css():\n    """カスタムCSSを適用する (ライトテーマ版)"""\n    st.markdown(f"""'
    end_str = '    """, unsafe_allow_html=True)'
    
    start_idx = content.find(start_str)
    if start_idx == -1:
        print("Could not find apply_custom_css start")
        return
        
    css_start_idx = start_idx + len(start_str)
    css_end_idx = content.find(end_str, css_start_idx)
    
    css_part = content[css_start_idx:css_end_idx]
    
    # In CSS part, replace all { with {{ and } with }}, EXCEPT if they surround Theme.
    # To do this safely, first let's mask {Theme.xyz}
    css_part = re.sub(r'\{Theme\.([a-zA-Z0-9_]+)\}', r'__THEME__\1__', css_part)
    
    # Now replace { and } with {{ and }}
    css_part = css_part.replace("{", "{{").replace("}", "}}")
    
    # Unmask Theme variables back to {Theme.xyz}
    css_part = re.sub(r'__THEME__([a-zA-Z0-9_]+)__', r'{Theme.\1}', css_part)
    
    new_content = content[:css_start_idx] + css_part + content[css_end_idx:]
    
    with open("backend/dashboard/utils.py", "w") as f:
        f.write(new_content)
        
    try:
        ast.parse(new_content)
        print("✅ utils.py Syntax OK")
    except Exception as e:
        print(f"❌ utils.py Syntax Error: {e}")

fix_css_in_utils()
