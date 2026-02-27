import re

with open("backend/dashboard/app.py", "r", encoding="utf-8") as f:
    code = f.read()

# タブ定義の置換
tab_def_old = """tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "�� Executive Summary",
    "🎯 Today's Action",
    "🔍 Analysis & Tracking",
    "📦 Strategy Map",
    "🧪 Custom Simulator"
])"""

tab_def_new = """tabs = [
    "📈 Executive Summary",
    "🎯 Today's Action",
    "🔍 Analysis & Tracking",
    "📦 Strategy Map",
    "🧪 Custom Simulator"
]
selected_tab = st.radio("ナビゲーション", tabs, horizontal=True, label_visibility="collapsed", key="main_nav_tab")"""

code = code.replace(tab_def_old, tab_def_new)

# with tabX: の置換
code = code.replace("with tab1:", 'if selected_tab == "📈 Executive Summary":\n    with st.container():')
code = code.replace("with tab2:", 'if selected_tab == "🎯 Today\'s Action":\n    with st.container():')
code = code.replace("with tab3:", 'if selected_tab == "🔍 Analysis & Tracking":\n    with st.container():')
code = code.replace("with tab4:", 'if selected_tab == "📦 Strategy Map":\n    with st.container():')
code = code.replace("with tab5:", 'if selected_tab == "🧪 Custom Simulator":\n    with st.container():')

with open("backend/dashboard/app.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Done replacing tabs")
