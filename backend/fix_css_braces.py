import re
import ast

def fix_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    # Find apply_custom_css function
    match = re.search(r'(def apply_custom_css\(\):.*?st\.markdown\(f"""\n.*?)(<style>.*?</style>)(.*?)(""", unsafe_allow_html=True\))', content, re.DOTALL)
    if match:
        pre = match.group(1)
        css_part = match.group(2)
        post = match.group(3)
        end = match.group(4)
        
        # Escape braces
        css_part = css_part.replace("{", "{{").replace("}", "}}")
        # Unescape Theme variables
        css_part = re.sub(r'\{\{Theme\.([a-zA-Z0-9_]+)\}\}', r'{Theme.\1}', css_part)
        
        content = content[:match.start()] + pre + css_part + post + end + content[match.end():]

    # Also check other st.markdown f-strings in app.py that might have CSS
    # Actually, app.py uses inline styles `<div style="...">` which don't use braces {}.
    # Wait, what if app.py has `<style>` blocks? Let's check.
    
    with open(filepath, "w") as f:
        f.write(content)
        
    try:
        ast.parse(content)
        print(f"✅ {filepath} Syntax OK")
    except Exception as e:
        print(f"❌ {filepath} Syntax Error: {e}")

fix_file("backend/dashboard/utils.py")

# Check app.py syntax just in case
try:
    with open("backend/dashboard/app.py", "r") as f:
        ast.parse(f.read())
        print(f"✅ backend/dashboard/app.py Syntax OK")
except Exception as e:
    print(f"❌ backend/dashboard/app.py Syntax Error: {e}")

