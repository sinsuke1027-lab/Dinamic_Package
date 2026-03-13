
import re

with open('/Users/shinsukeimanaka/.gemini/antigravity/applicaiton_develop/Dinamic_Priceing/backend/dashboard/utils.py', 'r') as f:
    content = f.read()

# find apply_custom_css function
start_match = re.search(r'def apply_custom_css\(\):', content)
if start_match:
    start_pos = start_match.start()
    # find the st.markdown(f""" block
    markdown_match = re.search(r'st\.markdown\(f"""(.*?)"""', content[start_pos:], re.DOTALL)
    if markdown_match:
        css_content = markdown_match.group(1)
        # Check for single braces that are not followed by Theme.
        # This is a bit naive but good for a quick check.
        # Valid: {Theme.xxx}, {{, }}
        # Invalid: { (without Theme), } (without Theme)
        
        # Replace all {{ and }} with something else to ignore them
        dummy = css_content.replace('{{', 'DOUBLE_OPEN').replace('}}', 'DOUBLE_CLOSE')
        
        # Find all single { and check if they are followed by Theme.
        single_opens = re.findall(r'(?<!{){(?=Theme\.)', dummy)
        all_opens = re.findall(r'(?<!{){', dummy)
        
        bad_opens = [o for o in all_opens if not re.match(r'{Theme\.', o + dummy[dummy.find(o)+1:dummy.find(o)+10])]
        
        print(f"Total single opens: {len(all_opens)}")
        print(f"Valid single opens (Theme.): {len(single_opens)}")
        
        # More robust check: find all { and }
        import string
        class SafeDict(dict):
            def __missing__(self, key):
                return '{' + key + '}'

        try:
            # We can't easily mock Theme here, but we can see if it throws a ValueError for unbalanced braces
            # instead, we'll just search for them.
            pass
        except Exception as e:
            print(f"Format error: {e}")

        # Let's count unescaped braces
        for i, char in enumerate(css_content):
            if char == '{':
                if i+1 < len(css_content) and css_content[i+1] == '{':
                    continue # escaped
                if i > 0 and css_content[i-1] == '{':
                    continue # escaped
                # check if it's a variable
                if not css_content[i:i+7] == '{Theme.':
                    print(f"Potential bad open brace at index {i}: {css_content[i:i+20]}...")
            if char == '}':
                if i+1 < len(css_content) and css_content[i+1] == '}':
                    continue # escaped
                if i > 0 and css_content[i-1] == '}':
                    continue # escaped
                # check if it closes a Theme variable
                # (this is harder, but simplified)
                prev_content = css_content[max(0, i-30):i]
                if '{Theme.' not in prev_content:
                    print(f"Potential bad close brace at index {i}: ...{css_content[i-20:i+1]}")
