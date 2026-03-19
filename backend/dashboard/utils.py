from dashboard.theme import Theme
"""
dashboard/utils.py
Streamlit UI で使用するスタイル設定や共通データ変換関数を管理。
"""

import plotly.graph_objects as go
import streamlit as st
import sqlite3
import os
import pandas as pd
from datetime import datetime, timezone

def get_seasonal_target_rate(departure_date: str, conf: dict) -> float:
    """出発日の月に応じて、繁忙期/閑散期/中間期の目標販売率を返す"""
    if not departure_date:
        return conf.get("target_sell_rate", 1.0)
    try:
        # ISOやYYYY-MM-DDなど対応
        dt = pd.to_datetime(departure_date)
        month = dt.month
        if month in {5, 7, 8}:
            return conf.get("target_rate_peak", conf.get("target_sell_rate", 0.95))
        elif month in {2, 6, 11}:
            return conf.get("target_rate_offpeak", conf.get("target_sell_rate", 0.60))
        else:
            return conf.get("target_rate_normal", conf.get("target_sell_rate", 0.80))
    except Exception:
        return conf.get("target_sell_rate", 1.0)

def light_dataframe(df: "pd.DataFrame", **kwargs) -> None:
    """DataFrameをライトテーマのHTMLテーブルとして表示する。
    st.dataframe の Canvas レンダリングが黒背景になる問題を回避するため、
    HTML テーブルを st.markdown で描画する。
    kwargs は use_container_width, hide_index 等（無視して互換性を維持）。
    """
    # NaN を空文字に変換
    df = df.fillna("")
    
    # HTMLテーブル生成
    header_cells = "".join(
        f"<th style='background:#f1f5f9;color:#0f172a;font-weight:700;"
        f"padding:8px 12px;border-bottom:2px solid #e2e8f0;"
        f"border-right:1px solid #e2e8f0;text-align:left;font-size:0.85rem;'>"
        f"{col}</th>"
        for col in df.columns
    )
    header = f"<tr>{header_cells}</tr>"
    
    rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
        cells = "".join(
            f"<td style='background:{bg};color:#1e293b;padding:7px 12px;"
            f"border-bottom:1px solid #e2e8f0;border-right:1px solid #e2e8f0;"
            f"font-size:0.9rem;'>{val}</td>"
            for val in row
        )
        rows.append(f"<tr>{cells}</tr>")
    
    table_html = f"""
    <div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:1rem;">
      <table style="border-collapse:collapse;width:100%;font-family:'Inter',sans-serif;">
        <thead>{header}</thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def log_price_history(results: list[dict], db_path: str):
    """現在の動的価格を履歴テーブルに保存する（トレンド可視化用）"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    for r in results:
        # inv_ratio * 100 を整数として保存（旧仕様準拠）
        cursor.execute("""
            INSERT INTO price_history (inventory_id, recorded_at, remaining_stock, dynamic_price, lead_days)
            VALUES (?, ?, ?, ?, ?)
        """, (r["inventory_id"], now_str, int(r.get("inv_ratio", 0)*100), r["final_price"], r["lead_days"]))
    conn.commit()
    conn.close()

def hex_to_rgba(hex_color: str, opacity: float) -> str:
    """HexカラーをRGBA文字列に変換する"""
    hex_color = hex_color.lstrip('#')
    lv = len(hex_color)
    rgb = tuple(int(hex_color[i:i + lv // 3], 16) for i in range(0, lv, lv // 3))
    return f'rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {opacity})'

def light_layout(fig: go.Figure, title: str = "", secondary_y: bool = False, yaxis_title: str = "") -> go.Figure:
    """PlotlyのFigureにライトテーマ（SaaS風白基調）の共通レイアウトを適用する"""
    fig.update_layout(
        title=title,
        paper_bgcolor=Theme.bg_transparent,
        plot_bgcolor=Theme.bg_transparent,
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=40),
        font=dict(family="'Outfit', 'Inter', 'Segoe UI', 'Roboto', sans-serif", color=Theme.text_main, size=15),
        xaxis=dict(gridcolor=Theme.border_light, linecolor=Theme.border_dark),
        yaxis=dict(gridcolor=Theme.border_light, linecolor=Theme.border_dark, title=yaxis_title),
        legend=dict(bgcolor=Theme.bg_glass, bordercolor=Theme.border_dark)
    )
    if secondary_y:
        fig.update_layout(yaxis2=dict(gridcolor=Theme.border_light, linecolor=Theme.border_dark))
    return fig

def render_metric_card(label: str, value: str, subvalue: str = "", delta: str = "", delta_color: str = "normal", is_brake: bool = False):
    """モダンなメトリックカードを描画する（HTML/CSS）"""
    badge_class = "badge-up" if delta_color == "normal" and not delta.startswith("-") else "badge-down"
    brake_html = '<div class="badge-brake">🚔 AUTO BRAKE ACTIVE</div>' if is_brake else ""
    
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{value}</div>
      <div class="metric-sub">{subvalue}</div>
      {f'<div><span class="{badge_class}">{delta}</span></div>' if delta else ""}
      {brake_html}
    </div>""", unsafe_allow_html=True)

def apply_custom_css():
    """カスタムCSSを適用する (ライトテーマ版)"""
    # print("DEBUG: apply_custom_css() called") # Streamlit reload check
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;900&family=Inter:wght@400;600;700&display=swap');
    
    
    :root {{
        --st-background-color: {Theme.bg_main};
        --st-secondary-background-color: {Theme.bg_hover};
        --st-text-color: {Theme.text_main};
    }}
    body {{
        background-color: {Theme.white} !important;
    }}
    .stApp {{ 
        background: {Theme.bg_main}; 
        color: {Theme.text_main}; 
        font-family: 'Inter', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        text-rendering: optimizeLegibility;
    }}
    
    /* グラスモーフィズム・カード (ライト) */
    .metric-card {{
        background: {Theme.bg_glass};
        backdrop-filter: blur(12px);
        border: 1px solid rgba(226, 232, 240, 0.8);
        border-radius: {Theme.radius_lg};
        padding: {Theme.spacing_lg};
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: {Theme.shadow_sm};
        margin-bottom: {Theme.spacing_md};
    }}
    .metric-card:hover {{ 
        transform: translateY(-4px); 
        background: {Theme.white}; 
        border-color: rgba(99, 102, 241, 0.3);
        box-shadow: {Theme.shadow_lg};
    }}
    
    .metric-label {{ font-size: {Theme.font_size_metric_label}; color: {Theme.text_muted}; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; font-family: 'Inter', sans-serif; }}
    .metric-value {{ font-size: {Theme.font_size_metric}; font-weight: 900; color: {Theme.text_dark}; margin: {Theme.spacing_xs} 0; font-family: 'Outfit', 'Segoe UI', sans-serif; }}
    .metric-sub {{ font-size: {Theme.size_md}; color: {Theme.text_muted}; font-weight: 500; font-family: 'Inter', sans-serif; }}
    
    .badge-up {{ background: rgba(34, 197, 94, 0.15); color: {Theme.badge_green_text}; padding: {Theme.spacing_xs} 10px; border-radius: 999px; font-size: {Theme.size_sm}; font-weight: 700; border: 1px solid rgba(34, 197, 94, 0.3); }}
    .badge-down {{ background: rgba(239, 68, 68, 0.15); color: {Theme.badge_red_text}; padding: {Theme.spacing_xs} 10px; border-radius: 999px; font-size: {Theme.size_sm}; font-weight: 700; border: 1px solid rgba(239, 68, 68, 0.3); }}
    .badge-brake {{ background: rgba(245, 158, 11, 0.15); color: #b45309; padding: {Theme.spacing_xs} 10px; border-radius: 999px; font-size: {Theme.size_xs}; font-weight: 800; border: 1px solid rgba(245, 158, 11, 0.3); margin-top: 10px; display: inline-block; }}
    
    /* タブ・サイドバーの装飾 (ライト) */
    .stTabs [data-baseweb="tab-list"] {{ gap: 10px; background: {Theme.bg_tab_list}; padding: 5px; border-radius: {Theme.radius_md}; }}
    .stTabs [data-baseweb="tab"] {{ height: 45px; border-radius: {Theme.radius_sm}; color: {Theme.text_sec}; transition: all 0.2s; border: none; font-weight: 600; }}
    .stTabs [aria-selected="true"] {{ background: {Theme.white}; color: {Theme.text_dark}; font-weight: 800; box-shadow: {Theme.shadow_sm}; }}
    
    /* ナビゲーション用のラジオボタン（疑似タブ）をモダンなボタン・タブ風に整形 */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"] > div:first-child {{
        display: none !important;
    }}

    div[data-testid="stRadio"] div[aria-label="MainNavigation"] div[role="radiogroup"] {{
        display: flex;
        justify-content: center;
        gap: 6px;
        background: #e2e8f0; /* 少し濃いグレー背景でエリア全体を明確に */
        padding: 6px;
        border-radius: 12px;
        width: 100%;
        box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.05);
    }}
    
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"] {{
        padding: 10px 20px !important;
        border-radius: 8px !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        cursor: pointer !important;
        border: 1px solid rgba(255, 255, 255, 0.4) !important;
        margin: 0 !important;
        background: rgba(255, 255, 255, 0.3) !important;
        flex: 1;
        text-align: center;
        min-width: 140px;
        display: flex;
        justify-content: center;
        align-items: center;
    }}
    
    /* ホバー時（未選択タブ） */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"]:not(:has(input:checked)):hover {{
        background: rgba(255, 255, 255, 0.6) !important;
        transform: translateY(-1px);
    }}

    /* 選択中のスタイル */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"]:has(input:checked) {{
        background: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05), 0 1px 3px rgba(0, 0, 0, 0.1) !important;
        transform: translateY(-2px);
        z-index: 10;
    }}
    
    /* 選択中の文字装飾 */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"]:has(input:checked) p {{
        color: {Theme.primary_hover} !important; /* 選択時はアクセントカラー */
        font-weight: 800 !important;
        font-size: 1rem !important;
    }}
    
    /* 未選択時の文字装飾 */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"] p {{
        color: #475569 !important; /* 未選択時はグレー */
        font-weight: 600 !important;
        margin: 0 !important;
        font-size: 0.95rem !important;
        text-align: center;
        width: 100%;
    }}

    /* 全般的な入力ウィジェットのラベル文字色をダークグレーにする */
    div[data-testid="stWidgetLabel"] p,
    div[data-testid="stMarkdownContainer"] p {{
        color: {Theme.text_main} !important;
    }}
    /* ヘッダーや強調テキストなどはより濃く */
    h1, h2, h3, h4, h5, h6 {{
        color: {Theme.text_dark} !important;
    }}

    /* ヘルプ用のTooltipアイコン(?マーク)の色 */
    div[data-testid="stTooltipIcon"] svg {{
        stroke: #94a3b8 !important;
        fill: #94a3b8 !important;
    }}
    
    .alert-box {{
        padding: {Theme.spacing_sm} {Theme.spacing_md};
        border-radius: {Theme.radius_md};
        margin-bottom: {Theme.spacing_md};
        display: flex;
        align-items: center;
        gap: 12px;
        font-weight: 600;
        backdrop-filter: blur(8px);
        box-shadow: {Theme.shadow_sm};
    }}
    .alert-warning {{ background: {Theme.alert_warning_bg}; border: 1px solid {Theme.alert_warning_border}; color: {Theme.alert_warning_text}; }}
    .alert-danger {{ background: {Theme.badge_red_bg}; border: 1px solid #fecaca; color: {Theme.badge_red_text}; }}
    .alert-info {{ background: {Theme.alert_info_bg}; border: 1px solid {Theme.alert_info_border}; color: {Theme.alert_info_text}; }}
    .alert-icon {{ font-size: 1.4rem; }}

    /* ─── サイドバー ─────────────────────────────────── */
    [data-testid="stSidebar"] {{
        background: {Theme.white} !important;
        border-right: 1px solid {Theme.border_light} !important;
    }}
    [data-testid="stSidebar"] * {{
        color: {Theme.text_main} !important;
    }}
    [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span {{
        color: {Theme.text_main} !important;
    }}
    [data-testid="stSidebar"] hr {{
        border-color: {Theme.border_light} !important;
    }}

    /* ─── 入力ウィジェット全般（ライト化） ────────────── */
    /* テキスト入力・セレクトボックス・スライダーのラベル */
    .stTextInput label, .stSelectbox label, .stMultiSelect label,
    .stDateInput label, .stSlider label, .stRadio label,
    div[data-testid="stWidgetLabel"] > p {{
        color: {Theme.text_sec} !important;
        font-weight: 600 !important;
    }}
    /* インプットボックスの背景・枠色 */
    .stTextInput input, .stSelectbox select,
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div,
    div[data-testid="stDateInput"] input {{
        background-color: {Theme.white} !important;
        border-color: {Theme.border_dark} !important;
        color: {Theme.text_main} !important;
    }}
    
    /* ─── 入力ウィジェット全般のテキスト色を強制隔離 ── */
    /* あらゆる入力フィールド、プルダウン、日付選択のテキストを強制的に黒にする */
    /* .st-bb は Streamlit の内部的な入力フィールドの色設定 */
    .stApp .main input,
    .stApp .main select,
    .stApp .main textarea,
    .stApp .main [data-baseweb="input"] input,
    .stApp .main [data-baseweb="select"] div,
    .stApp .main [data-testid="stDateInput"] input,
    .stApp .main div[class*="datepicker"] input,
    .stApp .main div[role="combobox"],
    .stApp .main .st-bb,
    .stApp .main [data-baseweb="base-input"] input {{
        color: {Theme.text_dark} !important;
        -webkit-text-fill-color: {Theme.text_dark} !important;
        background-color: {Theme.white} !important;
        opacity: 1 !important;
    }}
    
    div[data-testid="stWidgetLabel"] label p {{
        color: {Theme.text_sec} !important;
    }}
    /* マルチセレクトのタグ */
    [data-baseweb="tag"] {{
        background-color: {Theme.alert_info_bg} !important;
        color: {Theme.alert_info_text} !important;
    }}
    /* ドロップダウンメニュー */
    ul[role="listbox"] {{
        background: {Theme.white} !important;
        border: 1px solid {Theme.border_light} !important;
    }}
    ul[role="listbox"] li, ul[role="listbox"] span, ul[role="listbox"] div {{
        color: {Theme.text_main} !important;
    }}
    ul[role="listbox"] li:hover {{
        background: {Theme.bg_hover} !important;
    }}
    /* スライダーのつまみと選択されたトラックの色をテーマカラーに合わせる */
    div[data-testid="stSlider"] [data-testid="stThumb"],
    div[data-testid="stSlider"] [style*="background: rgb(255, 75, 75)"] {{
        background-color: {Theme.primary} !important;
    }}

    /* st.data_editor に関する強制上書きスタイルを削除（描画面が真っ白になる不具合の原因と思われるため） */

    /* ─── Streamlit デフォルトUI（dataframe, buttonなど）のライト化 ── */
    /* ボタン */
    .stButton > button {{
        background: {Theme.primary_alpha} !important;
        color: {Theme.primary} !important;
        border: 1px solid {Theme.primary_border} !important;
        border-radius: {Theme.radius_sm} !important;
        font-weight: 600 !important;
    }}
    .stButton > button:hover {{
        background: {Theme.primary_alpha.replace('0.1', '0.2')} !important;
        color: {Theme.primary_hover} !important;
        border-color: {Theme.primary} !important;
    }}
    /* expander */
    [data-testid="stExpander"], details {{
        background-color: #ffffff !important;
        border: 1px solid {Theme.border_light} !important;
        border-radius: {Theme.radius_sm} !important;
    }}
    details summary {{
        background-color: #ffffff !important;
        color: {Theme.text_main} !important;
        font-weight: 600 !important;
        padding: 10px !important;
        border-radius: {Theme.radius_sm} !important;
    }}
    details[open] summary {{
        color: {Theme.primary_hover} !important;
    }}
    
    /* アプリ全体のメイン背景色を強制的に白/ライト系にする */
    .stApp, .stApp > header, .main {{
        background-color: {Theme.bg_main} !important;
    }}

    /* info/warning/success メッセージボックス */
    div[data-testid="stAlert"] {{
        border-radius: {Theme.radius_sm} !important;
    }}
    /* caption */
    div[data-testid="stCaptionContainer"] p {{
        color: {Theme.text_muted} !important;
    }}

    /* ─── 環境依存（ダークモード等）の強制上書き ─── */
    /* ツールチップのリセット */
    div[data-testid="stTooltipContent"] {{
        background-color: {Theme.tooltip_bg} !important;
        color: {Theme.tooltip_text} !important;
        border: 1px solid {Theme.border_dark} !important;
    }}
    /* Iframe 背景のリセット (グラフなど) */
    iframe {{
        background-color: transparent !important;
    }}
    /* スクロールバーのカスタマイズ（ブラウザに依らずライト系に固定） */
    ::-webkit-scrollbar {{
        width: 8px;
        height: 8px;
    }}
    ::-webkit-scrollbar-track {{
        background: {Theme.bg_main};
    }}
    ::-webkit-scrollbar-thumb {{
        background: {Theme.border_dark};
        border-radius: 10px;
        border: 2px solid {Theme.bg_main};
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background: {Theme.text_muted};
    }}
    /* Firefox 用 */
    * {{
        scrollbar-width: thin;
        scrollbar-color: {Theme.border_dark} {Theme.bg_main};
    }}
    </style>
    """, unsafe_allow_html=True)

def render_alerts(results, inv_df, packages, get_velocity_ratio_func):
    """共通のアラート通知エリアを描画する"""
    alerts = []
    
    # 1. 自動ブレーキ発動中の商品
    braked = [r for r in results if r.get("is_brake_active")]
    for b in braked:
        dep_val = b.get("departure_date", "")
        dep_str = f"（{str(dep_val)[:10]} 出発）" if pd.notna(dep_val) and dep_val else ""
        alerts.append(("danger", "🚔", f"<b>緊急ブレーキ発動中</b>: {b['name']}{dep_str} は売れすぎのため、AIが自動で値上げ調整を行っています。"))
    
    # 2. 売れ行き鈍化（在庫処分推奨）
    for r in results:
        inv_matches = inv_df[inv_df["id"].astype(str) == str(r["inventory_id"])]
        if inv_matches.empty: continue
        inv = inv_matches.iloc[0]
        dep_val = r.get("departure_date", "")
        dep_str = f"（{str(dep_val)[:10]} 出発）" if pd.notna(dep_val) and dep_val else ""
        try:
            vr = get_velocity_ratio_func(r["inventory_id"], int(inv["total_stock"]), int(inv["remaining_stock"]), r["lead_days"])
            if vr and vr < 0.5 and r["inv_ratio"] > 0.6:
                alerts.append(("warning", "⚠️", f"<b>販売鈍化警告</b>: {r['name']}{dep_str} の消化が遅れています。パッケージ割引の強化を推奨します。"))
        except: pass

    # 3. 未救済の切迫在庫
    if packages:
        top_pkg = packages[0]
        if top_pkg.get("strategy_score", 0) > 0.8:
            dep_val = top_pkg.get("departure_date", "")
            dep_str = f"（{str(dep_val)[:10]} 出発）" if pd.notna(dep_val) and dep_val else ""
            alerts.append(("info", "💡", f"<b>利益最大化のチャンス</b>: {top_pkg['hotel_name']}{dep_str} を含むパッケージが非常に高いスコアを記録しています。"))

    if alerts:
        for level, icon, msg in alerts:
            st.markdown(f"""
            <div class="alert-box alert-{level}">
                <span class="alert-icon">{icon}</span>
                <span>{msg}</span>
            </div>
            """, unsafe_allow_html=True)