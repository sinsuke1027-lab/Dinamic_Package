import re

with open('backend/dashboard/utils.py', 'r') as f:
    code = f.read()

# dataframe 用のより強力な上書き設定
# Streamlit >= 1.30 では Glide Data Grid が用いられているため、.dvn- コンポーネントへのスタイル追加も必要
css_df_old = """    /* dataframe */
    .stDataFrame, .stDataFrame * {
        color: """ + "{Theme.text_main}" + """ !important;
    }"""

css_df_new = """    /* dataframe overrides */
    [data-testid="stDataFrame"] {
        background-color: """ + "{Theme.white}" + """ !important;
    }
    
    [data-testid="stDataFrame"] > div:first-child,
    [data-testid="stDataFrame"] [data-testid="stTable"] {
        background-color: """ + "{Theme.white}" + """ !important;
    }
    
    /* For Streamlit's new Glide Data Grid */
    .glideDataEditor {
        background-color: """ + "{Theme.white}" + """ !important;
    }
    .dvn-scroller {
        background-color: """ + "{Theme.white}" + """ !important;
    }
    .dvn-cell {
        background-color: """ + "{Theme.white}" + """ !important;
        color: """ + "{Theme.text_main}" + """ !important;
    }
    .dvn-header-cell {
        background-color: """ + "{Theme.bg_hover}" + """ !important;
        color: """ + "{Theme.text_dark}" + """ !important;
        font-weight: bold !important;
    }
"""

if css_df_old in code:
    code = code.replace(css_df_old, css_df_new)
else:
    # 古い形式が見つからない場合、既存の div[data-testid="stDataFrame"]... の手前に挿入
    code = code.replace(
        'div[data-testid="stDataFrame"] > div,',
        css_df_new + '\n    div[data-testid="stDataFrame"] > div,'
    )

with open('backend/dashboard/utils.py', 'w') as f:
    f.write(code)
