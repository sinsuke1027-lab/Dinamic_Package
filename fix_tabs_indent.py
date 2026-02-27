with open("backend/dashboard/app.py", "r", encoding="utf-8") as f:
    code = f.read()

# with st.container(): を消す（if文の直下は既に4スペースインデントされているため）
code = code.replace('if selected_tab == "📈 Executive Summary":\n    with st.container():', 'if selected_tab == "📈 Executive Summary":')
code = code.replace('if selected_tab == "🎯 Today\'s Action":\n    with st.container():', 'if selected_tab == "🎯 Today\'s Action":')
code = code.replace('if selected_tab == "🔍 Analysis & Tracking":\n    with st.container():', 'if selected_tab == "🔍 Analysis & Tracking":')
code = code.replace('if selected_tab == "📦 Strategy Map":\n    with st.container():', 'if selected_tab == "�� Strategy Map":')
code = code.replace('if selected_tab == "🧪 Custom Simulator":\n    with st.container():', 'if selected_tab == "🧪 Custom Simulator":')

with open("backend/dashboard/app.py", "w", encoding="utf-8") as f:
    f.write(code)
print("Done fixing indent")
