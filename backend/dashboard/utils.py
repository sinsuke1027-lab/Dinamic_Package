"""
dashboard/utils.py
Streamlit UI で使用するスタイル設定や共通データ変換関数を管理。
"""

import plotly.graph_objects as go
import streamlit as st
import sqlite3
import os
from datetime import datetime, timezone

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

def dark_layout(fig: go.Figure, title: str = "", secondary_y: bool = False, yaxis_title: str = "") -> go.Figure:
    """PlotlyのFigureにダークテーマの共通レイアウトを適用する"""
    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=40),
        font=dict(family="Outfit, sans-serif", color="#e2e8f0"),
        xaxis=dict(gridcolor="#1e293b", linecolor="#334155"),
        yaxis=dict(gridcolor="#1e293b", linecolor="#334155", title=yaxis_title),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#334155")
    )
    if secondary_y:
        fig.update_layout(yaxis2=dict(gridcolor="#1e293b", linecolor="#334155"))
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
    """カスタムCSSを適用する"""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;900&family=Inter:wght@400;700&display=swap');
    
    .stApp { background: #020617; color: #f8fafc; font-family: 'Inter', sans-serif; }
    
    /* グラスモーフィズム・カード */
    .metric-card {
        background: rgba(30, 41, 59, 0.4);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 16px;
        padding: 24px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        margin-bottom: 20px;
    }
    .metric-card:hover { 
        transform: translateY(-4px); 
        background: rgba(30, 41, 59, 0.6); 
        border-color: rgba(167, 139, 250, 0.2);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2);
    }
    
    .metric-label { font-size: 0.85rem; color: #e2e8f0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-value { font-size: 2rem; font-weight: 900; color: #ffffff; margin: 8px 0; font-family: 'Outfit', sans-serif; }
    .metric-sub { font-size: 0.9rem; color: #cbd5e1; font-weight: 400; }
    
    .badge-up { background: rgba(34, 197, 94, 0.1); color: #4ade80; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(34, 197, 94, 0.2); }
    .badge-down { background: rgba(239, 68, 68, 0.1); color: #f87171; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(239, 68, 68, 0.2); }
    .badge-brake { background: rgba(251, 191, 36, 0.1); color: #fbbf24; padding: 4px 10px; border-radius: 999px; font-size: 0.7rem; font-weight: 800; border: 1px solid rgba(251, 191, 36, 0.3); margin-top: 10px; display: inline-block; }
    
    /* タブ・サイドバーの装飾 */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; background: rgba(15, 23, 42, 0.5); padding: 5px; border-radius: 12px; }
    .stTabs [data-baseweb="tab"] { height: 45px; border-radius: 8px; color: #e2e8f0; transition: all 0.2s; border: none; }
    .stTabs [aria-selected="true"] { background: #334155; color: #ffffff; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
    

    /* ナビゲーション用のラジオボタン（疑似タブ）をモダンなボタン・タブ風に整形 */
    /* st.radioの「点/円」を非表示にする */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"] > div:first-child {
        display: none !important;
    }

    div[data-testid="stRadio"] div[aria-label="MainNavigation"] div[role="radiogroup"] {
        display: flex;
        justify-content: center;
        gap: 8px;
        background: rgba(15, 23, 42, 0.4);
        padding: 6px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        width: 100%;
    }
    
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"] {
        padding: 8px 20px !important;
        border-radius: 10px !important;
        transition: all 0.25s ease !important;
        cursor: pointer !important;
        border: 1px solid transparent !important;
        margin: 0 !important;
        background: transparent !important;
        flex: 1;
        text-align: center;
        min-width: 140px;
        display: flex;
        justify-content: center;
        align-items: center;
    }
    
    /* ホバー時 */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"]:hover {
        background: rgba(255, 255, 255, 0.08) !important;
        border-color: rgba(255, 255, 255, 0.1) !important;
    }

    /* 選択中のスタイル */
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"]:has(input:checked) {
        background: rgba(167, 139, 250, 0.25) !important;
        border-color: rgba(167, 139, 250, 0.6) !important;
        box-shadow: 0 4px 15px rgba(167, 139, 250, 0.2) !important;
    }
    
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"]:has(input:checked) p {
        color: #ffffff !important;
        font-weight: 800 !important;
    }
    
    div[data-testid="stRadio"] div[aria-label="MainNavigation"] label[data-baseweb="radio"] p {
        color: #cbd5e1 !important;
        font-weight: 600 !important;
        margin: 0 !important;
        font-size: 0.95rem !important;
        text-align: center;
    }

    /* 全般的な入力ウィジェットのラベル文字色を明るくする */
    div[data-testid="stWidgetLabel"] p,
    div[data-testid="stMarkdownContainer"] p {
        color: #e2e8f0 !important;
    }

    /* ヘルプ用のTooltipアイコン(?マーク)の色を明るくする */
    div[data-testid="stTooltipIcon"] svg {
        stroke: #94a3b8 !important;
        fill: #94a3b8 !important;
    }
    
    /* 通知アラート */
    .alert-box {
        padding: 12px 20px;
        border-radius: 12px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        font-weight: 600;
        backdrop-filter: blur(4px);
    }
    .alert-warning { background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.4); color: #fbbf24; }
    .alert-danger { background: rgba(248,113,113,0.1); border: 1px solid rgba(248,113,113,0.4); color: #f87171; }
    .alert-info { background: rgba(96,165,250,0.1); border: 1px solid rgba(96,165,250,0.4); color: #60a5fa; }
    .alert-icon { font-size: 1.2rem; }
    </style>
    """, unsafe_allow_html=True)

def render_alerts(results, inv_df, packages, get_velocity_ratio_func):
    """共通のアラート通知エリアを描画する"""
    alerts = []
    
    # 1. 自動ブレーキ発動中の商品
    braked = [r for r in results if r.get("is_brake_active")]
    for b in braked:
        alerts.append(("danger", "🚔", f"<b>緊急ブレーキ発動中</b>: {b['name']} は売れすぎのため、AIが自動で値上げ調整を行っています。"))
    
    # 2. 売れ行き鈍化（在庫処分推奨）
    for r in results:
        inv_matches = inv_df[inv_df["id"] == r["inventory_id"]]
        if inv_matches.empty: continue
        inv = inv_matches.iloc[0]
        try:
            vr = get_velocity_ratio_func(r["inventory_id"], int(inv["total_stock"]), int(inv["remaining_stock"]), r["lead_days"])
            if vr and vr < 0.5 and r["inv_ratio"] > 0.6:
                alerts.append(("warning", "⚠️", f"<b>販売鈍化警告</b>: {r['name']} の消化が遅れています。パッケージ割引の強化を推奨します。"))
        except: pass

    # 3. 未救済の切迫在庫
    if packages:
        top_pkg = packages[0]
        if top_pkg.get("strategy_score", 0) > 0.8:
            alerts.append(("info", "💡", f"<b>利益最大化のチャンス</b>: {top_pkg['hotel_name']} を含むパッケージが非常に高いスコアを記録しています。"))

    if alerts:
        for level, icon, msg in alerts:
            st.markdown(f"""
            <div class="alert-box alert-{level}">
                <span class="alert-icon">{icon}</span>
                <span>{msg}</span>
            </div>
            """, unsafe_allow_html=True)
