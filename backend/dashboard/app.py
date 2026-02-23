"""
dashboard/app.py  ― フェーズ1 ホワイトボックス化（タブ型 SaaS レイアウト）

【3タブ構成】
  🏠 ライブ概況       : KPI カード / パッケージランキング / 販売速度
  🔍 価格の内訳分析   : 単品5ステップ WF / パッケージ7ステップ WF
  🃏 商品カルテ       : 5軸レーダーチャート / 特性バッジ / 数値サマリー

【起動方法】
  cd backend
  source venv/bin/activate
  streamlit run dashboard/app.py
"""

import os
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── 設定 ────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "inventory.db")

st.set_page_config(
    page_title="Explainable Pricing Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── カスタム CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: #0a0a0f; color: #e2e8f0; }
h1 { color: #a78bfa !important; font-weight: 900 !important; font-size: 2rem !important; }
h2, h3, h4 { color: #c4b5fd !important; }

/* タブ */
button[data-baseweb="tab"] {
    font-size: 1rem !important; font-weight: 600 !important;
    color: #64748b !important; border-radius: 10px 10px 0 0 !important;
    padding: 10px 24px !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #a78bfa !important;
    border-bottom: 3px solid #a78bfa !important;
    background: rgba(167,139,250,.08) !important;
}

/* KPI カード */
.metric-card {
    background: linear-gradient(135deg,#1e1b4b 0%,#312e81 100%);
    border:1px solid #4338ca; border-radius:16px;
    padding:20px; text-align:center; margin:6px; height:100%;
}
.metric-value { font-size:2rem; font-weight:900; color:#a78bfa; margin:8px 0; }
.metric-label { font-size:.75rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.1em; }
.metric-sub   { font-size:.9rem; color:#c4b5fd; }

/* バッジ */
.badge-up   { display:inline-block; background:rgba(248,113,113,.2); color:#f87171;
              border-radius:999px; padding:2px 10px; font-size:.8rem; font-weight:700; }
.badge-down { display:inline-block; background:rgba(74,222,128,.2);  color:#4ade80;
              border-radius:999px; padding:2px 10px; font-size:.8rem; font-weight:700; }
.badge-high { display:inline-block; background:rgba(248,113,113,.15); color:#f87171;
              border:1px solid rgba(248,113,113,.4);
              border-radius:999px; padding:3px 14px; font-size:.8rem; font-weight:700; margin:2px; }
.badge-med  { display:inline-block; background:rgba(251,191,36,.15); color:#fbbf24;
              border:1px solid rgba(251,191,36,.4);
              border-radius:999px; padding:3px 14px; font-size:.8rem; font-weight:700; margin:2px; }
.badge-low  { display:inline-block; background:rgba(74,222,128,.15); color:#4ade80;
              border:1px solid rgba(74,222,128,.4);
              border-radius:999px; padding:3px 14px; font-size:.8rem; font-weight:700; margin:2px; }
.badge-brake { display:inline-block; background:rgba(251,191,36,.25); color:#fbbf24;
               border:1px solid #fbbf24; box-shadow: 0 0 10px rgba(251,191,36,.3);
               border-radius:999px; padding:2px 10px; font-size:.75rem; font-weight:900; margin-top:8px; }

/* テキストボックス */
.reason-box {
    background:rgba(99,102,241,.08); border:1px solid rgba(99,102,241,.3);
    border-radius:10px; padding:12px 16px; font-size:.9rem;
    color:#c4b5fd; margin:6px 0;
}

/* カルテカード */
.karte-card {
    background: rgba(30,27,75,.6);
    border: 1px solid rgba(99,102,241,.4);
    border-radius: 16px; padding: 24px; margin: 8px 0;
    backdrop-filter: blur(8px);
    box-shadow: 0 0 24px rgba(99,102,241,.12);
}
/* ROI KPI カード */
.metric-card-roi {
    background: linear-gradient(135deg,#064e3b 0%,#065f46 100%);
    border:1px solid #10b981; border-radius:16px;
    padding:20px; text-align:center; margin:6px; height:100%;
    box-shadow: 0 0 20px rgba(16,185,129,0.2);
}
.roi-value { font-size:2.2rem; font-weight:900; color:#10b981; margin:8px 0; text-shadow: 0 0 10px rgba(16,185,129,0.4); }
hr { border-color: #1e293b; }

/* 通知アラート */
.alert-box {
    padding: 12px 20px;
    border-radius: 12px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.alert-warning {
    background: rgba(251,191,36,0.1);
    border: 1px solid rgba(251,191,36,0.4);
    color: #fbbf24;
}
.alert-danger {
    background: rgba(248,113,113,0.1);
    border: 1px solid rgba(248,113,113,0.4);
    color: #f87171;
}
.alert-info {
    background: rgba(96,165,250,0.1);
    border: 1px solid rgba(96,165,250,0.4);
    color: #60a5fa;
}
.alert-icon { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

# ─── データ取得 ───────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_inventory() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM inventory", conn)
    conn.close()
    return df

@st.cache_data(ttl=60)
def load_history() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT h.inventory_id, i.name, i.total_stock, i.base_price,
               i.departure_date,
               h.recorded_at, h.remaining_stock, h.dynamic_price, h.lead_days
        FROM price_history h
        JOIN inventory i ON h.inventory_id = i.id
        ORDER BY h.recorded_at ASC
    """, conn)
    conn.close()
    if not df.empty:
        df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
        df["recorded_at"] = df["recorded_at"].dt.tz_convert("Asia/Tokyo")
    return df

@st.cache_data(ttl=60)
def load_booking_events() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM booking_events", conn)
    conn.close()
    if not df.empty:
        df["booked_at"] = pd.to_datetime(df["booked_at"], utc=True)
        df["booked_at"] = df["booked_at"].dt.tz_convert("Asia/Tokyo")
    return df

def get_pricing_results(inv_df: pd.DataFrame, config: dict = None) -> list[dict]:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from pricing_engine import calculate_pricing_result
    results = []
    for _, row in inv_df.iterrows():
        r = calculate_pricing_result(
            inventory_id    = int(row["id"]),
            name            = row["name"],
            base_price      = int(row["base_price"]),
            total_stock     = int(row["total_stock"]),
            remaining_stock = int(row["remaining_stock"]),
            departure_date  = row.get("departure_date"),
            config          = config,
        )
        results.append(r)
    return results

# ─── Plotly 共通スタイル ──────────────────────────────────────────
PLOT_BG    = "#0d0d1a"
PAPER_BG   = "#0d0d1a"
FONT_COLOR = "#94a3b8"
GRID_COLOR = "#1e293b"
COLORS     = ["#a78bfa","#f472b6","#34d399","#fbbf24","#60a5fa","#fb923c","#38bdf8","#a3e635"]

def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB 形式のヘックスカラーを rgba(r, g, b, a) 形式に変換する"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    return hex_color

def dark_layout(fig: go.Figure, title: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(color="#c4b5fd", size=15)),
        paper_bgcolor=PAPER_BG, plot_bgcolor=PLOT_BG,
        font=dict(color=FONT_COLOR, family="Inter"),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_COLOR,
                    font=dict(color=FONT_COLOR)),
        xaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        yaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        margin=dict(l=16, r=16, t=48, b=16),
        hovermode="x unified",
    )
    return fig

# ─── ヘッダー ──────────────────────────────────────────────────────
st.markdown("""
<h1>🔍 Explainable Pricing Dashboard</h1>
<p style='color:#64748b; margin-top:-12px; margin-bottom:20px;'>
  価格の根拠を可視化し、アルゴリズムのブラックボックス化を防ぐ —
  <span style='color:#a78bfa'>White-box Pricing Engine</span>
</p>
""", unsafe_allow_html=True)

# ─── サイドバー: AI Command Center ───────────────────────────────
with st.sidebar:
    st.markdown("### 🎛 AI Command Center")
    st.markdown("<p style='color:#94a3b8;font-size:.8rem'>AIの行動ルールをリアルタイム編集</p>", unsafe_allow_html=True)
    
    with st.expander("🛡 セーフティガード (上下限)", expanded=True):
        max_discount = st.slider("最大割引率 (%)", 0, 80, 30, help="これ以上安くしない限界値")
        max_markup   = st.slider("最大値上げ率 (%)", 0, 200, 50, help="需要超過時の値上げ上限")
    
    with st.expander("🚔 自動調整 (Velocity Brake)", expanded=True):
        brake_threshold = st.slider("ブレーキ発動閾値", 1.0, 5.0, 1.5, 0.1, help="期待ペースの何倍でブレーキをかけるか")
        brake_strength  = st.slider("ブレーキ強度 (%)", 0, 30, 5, help="ブレーキ時に上乗セする価格比率")

    ai_config = {
        "max_discount_pct": max_discount,
        "max_markup_pct":   max_markup,
        "brake_threshold":  brake_threshold,
        "brake_strength_pct": brake_strength
    }
    
    st.markdown("---")
    if st.button("設定をデフォルトに戻す"):
        st.session_state["reset_trigger"] = True # 簡易的なリセット実装

# ─── データロード ─────────────────────────────────────────────────
inv_df     = load_inventory()
history_df = load_history()

if inv_df.empty:
    st.error("⚠️ 在庫データが見つかりません。`python init_db.py` を先に実行してください。")
    st.stop()

results = get_pricing_results(inv_df, config=ai_config)

# ─── パッケージエンジン読み込み（全タブ共通） ─────────────────────
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from packaging_engine import (
        generate_packages, get_velocity_ratio, calc_velocity_adjustment,
        hotel_urgency_score, calculate_roi_metrics, calculate_inventory_rescue_metrics,
    )
    packages = generate_packages()
    roi_metrics = calculate_roi_metrics()
    rescue_metrics = calculate_inventory_rescue_metrics()
except Exception as _e:
    packages = []
    roi_metrics = {"lift": 0, "lift_pct": 0, "total_fixed": 0, "daily_data": []}
    rescue_metrics = {"overall_rescue_rate": 0, "rescued_units": 0, "hotel_rescue_rate": 0, "total_units": 0}
    _pkg_err = str(_e)
    st.warning(f"分析エンジンの読み込みに失敗しました: {_pkg_err}")

# ─── アラート・通知ロジック ─────────────────────────────
def render_alerts(results, inv_df, packages):
    alerts = []
    
    # 1. 自動ブレーキ発動中の商品
    braked = [r for r in results if r.get("is_brake_active")]
    for b in braked:
        alerts.append(("danger", "🚔", f"<b>緊急ブレーキ発動中</b>: {b['name']} は売れすぎのため、AIが自動で値上げ調整を行っています。"))
    
    # 2. 売れ行き鈍化（在庫処分推奨）
    for r in results:
        inv = inv_df[inv_df["id"] == r["inventory_id"]].iloc[0]
        try:
            vr = get_velocity_ratio(r["inventory_id"], inv["total_stock"], inv["remaining_stock"], r["lead_days"])
            if vr and vr < 0.5 and r["inv_ratio"] > 0.6:
                alerts.append(("warning", "⚠️", f"<b>販売鈍化警告</b>: {r['name']} の消化が遅れています。パッケージ割引の強化を推奨します。"))
        except: pass

    # 3. 未救済の切迫在庫
    if packages:
        top_pkg = packages[0]
        if top_pkg["strategy_score"] > 0.8:
            alerts.append(("info", "💡", f"<b>利益最大化のチャンス</b>: {top_pkg['hotel_name']} を含むパッケージが非常に高いスコアを記録しています。"))

    if alerts:
        for level, icon, msg in alerts:
            st.markdown(f"""
            <div class="alert-box alert-{level}">
                <span class="alert-icon">{icon}</span>
                <span>{msg}</span>
            </div>
            """, unsafe_allow_html=True)

# ─── 4タブ（新導線） ──────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 エグゼクティブ・サマリ",
    "🔍 商品別ドリルダウン分析",
    "📦 パッケージ戦略分析",
    "🚚 ライブ動向・一覧",
])


# ══════════════════════════════════════════════════════════════════
# Step 1: 【観察】エグゼクティブ・サマリ (Observe)
# ══════════════════════════════════════════════════════════════════
with tab1:
    render_alerts(results, inv_df, packages)

    st.markdown("### 💰 導入効果・ROIサマリ")
    
    # ROI KPI
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""
        <div class="metric-card-roi">
            <div class="metric-label">合計収益リフト</div>
            <div class="roi-value">+¥{roi_metrics['lift']:,}</div>
            <div class="metric-sub">固定価格比 <b>+{roi_metrics['lift_pct']}%</b></div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-card-roi">
            <div class="metric-label">在庫救済率 (全体)</div>
            <div class="roi-value">{rescue_metrics['overall_rescue_rate']}%</div>
            <div class="metric-sub">切迫在庫の <b>{rescue_metrics['rescued_units']}個</b> を救済</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-card-roi">
            <div class="metric-label">ホテル販売改善</div>
            <div class="roi-value">{rescue_metrics['hotel_rescue_rate']}%</div>
            <div class="metric-sub">パッケージによる救済寄与</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    
    col_chart, col_donut = st.columns([2, 1])
    with col_chart:
        st.markdown("#### 📈 売上推移：固定 vs 動的（累計）")
        df_daily = pd.DataFrame(roi_metrics["daily_data"])
        if not df_daily.empty:
            df_daily["cum_dynamic"] = df_daily["day_dynamic"].cumsum()
            df_daily["cum_fixed"]   = df_daily["day_fixed"].cumsum()

            fig_roi = go.Figure()
            fig_roi.add_trace(go.Scatter(
                x=df_daily["day"], y=df_daily["cum_dynamic"], name="動的価格 (実績)",
                mode='lines+markers', line=dict(color='#10b981', width=4),
                fill='tonexty', fillcolor='rgba(16,185,129,0.1)'
            ))
            fig_roi.add_trace(go.Scatter(
                x=df_daily["day"], y=df_daily["cum_fixed"], name="固定価格 (想定)",
                mode='lines', line=dict(color='#64748b', width=2, dash='dash')
            ))
            dark_layout(fig_roi, "累積売上の推移")
            st.plotly_chart(fig_roi, use_container_width=True)
        else:
            st.info("📊 ROI分析用の販売データがまだ蓄積されていません。")

    with col_donut:
        st.markdown("#### 🛡 在庫救済の内訳")
        rescued = rescue_metrics["rescued_units"]
        abandoned = rescue_metrics["total_units"] - rescued
        fig_donut = go.Figure(data=[go.Pie(
            labels=["救済済", "未売/通常"], values=[rescued, abandoned],
            hole=.6, marker_colors=["#10b981", "#1e293b"]
        )])
        fig_donut.update_layout(paper_bgcolor="rgba(0,0,0,0)", showlegend=False, height=250, margin=dict(t=0,b=0,l=0,r=0))
        st.plotly_chart(fig_donut, use_container_width=True)

    st.markdown("---")
    st.markdown("### 🏆 推奨アクション（パッケージ最適化）")
    if packages:
        best = packages[0]
        st.markdown(f"#### 🥇 最優先推奨: {best['flight_name']} ＋ {best['hotel_name']}")
        st.markdown(f'<div class="reason-box">{best["reason"]}</div>', unsafe_allow_html=True)

    st.markdown("---")
    last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.markdown(f'<p style="color:#475569;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>',
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# Tab 2: 価格の内訳分析
# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════
# Step 2: 【分析】商品別ドリルダウン分析 (Analyze)
# ══════════════════════════════════════════════════════════════════
with tab2:
    render_alerts(results, inv_df, packages)
    
    st.markdown("### 🔎 商品別ドリルダウン分析")
    selected_item = st.selectbox("分析する商品を選択", [r["name"] for r in results], key="tab2_drilldown")
    r_sel = next(r for r in results if r["name"] == selected_item)
    inv_sel = inv_df[inv_df["name"] == selected_item].iloc[0]
    all_events = load_booking_events()
    item_events = all_events[all_events["inventory_id"] == int(inv_sel["id"])].sort_values("booked_at")

    col_radar, col_info = st.columns([1.2, 1], gap="large")
    with col_radar:
        st.markdown(f"#### 🃏 特性プロファイル")
        inv_urgency   = 1.0 - r_sel["inv_ratio"]
        time_urgency  = max(0.0, 1.0 - (r_sel["lead_days"] or 90) / 60.0)
        p_elast       = min(abs(r_sel["final_price"] - r_sel["base_price"]) / r_sel["base_price"], 1.0) if r_sel["base_price"] > 0 else 0.0
        try:
            vr_k = get_velocity_ratio(r_sel["inventory_id"], int(inv_sel["total_stock"]), int(inv_sel["remaining_stock"]), r_sel["lead_days"])
            vel_score = min((vr_k or 0.0) / 3.0, 1.0)
        except: vr_k, vel_score = 0, 0
        try: bundle_score = hotel_urgency_score(int(inv_sel["remaining_stock"]), int(inv_sel["total_stock"]), r_sel["lead_days"])
        except: bundle_score = inv_urgency * 0.6 + time_urgency * 0.4

        radar_labels = ["在庫切迫度", "時間切迫度", "販売速度", "価格弾力性", "バンドル適性"]
        radar_scores = [inv_urgency, time_urgency, vel_score, p_elast, bundle_score]
        fig_radar = go.Figure(go.Scatterpolar(
            r=radar_scores + [radar_scores[0]], theta=radar_labels + [radar_labels[0]],
            fill="toself", fillcolor="rgba(167,139,250,0.18)", line=dict(color="#a78bfa", width=2.5),
        ))
        fig_radar.update_layout(polar=dict(bgcolor=PLOT_BG, radialaxis=dict(visible=True, range=[0, 1])), paper_bgcolor=PAPER_BG, height=350)
        st.plotly_chart(fig_radar, use_container_width=True)
    
    with col_info:
        st.markdown(f"#### ℹ️ {selected_item}")
        st.markdown(f'<div class="karte-card">', unsafe_allow_html=True)
        st.markdown(f"**動的価格:** ¥{r_sel['final_price']:,}")
        st.markdown(f"**価格偏差:** {'+' if r_sel['final_price']>=r_sel['base_price'] else ''}¥{r_sel['final_price']-r_sel['base_price']:,}")
        st.markdown(f"**残在庫:** {inv_sel['remaining_stock']}/{inv_sel['total_stock']} ({int(r_sel['inv_ratio']*100)}%)")
        st.markdown(f'<div class="reason-box">{r_sel["reason"]}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("---")
    st.markdown("#### 🌊 価格形成プロセス")
    vel_adj = r_sel['final_price'] - (r_sel['base_price'] + r_sel['inventory_adjustment'] + r_sel['time_adjustment'])
    wf_values = [r_sel["base_price"], r_sel["inventory_adjustment"], r_sel["time_adjustment"], vel_adj, r_sel["final_price"]]
    fig_wf = go.Figure(go.Waterfall(
        measure=["absolute", "relative", "relative", "relative", "total"],
        x=["基本", "在庫", "時期", "速度", "最終"], y=wf_values,
        increasing=dict(marker=dict(color="#f87171")), decreasing=dict(marker=dict(color="#4ade80")), totals=dict(marker=dict(color="#a78bfa")),
    ))
    st.plotly_chart(dark_layout(fig_wf), use_container_width=True)

    # ── [NEW] 高度な分析ビュー (全部盛り) ────────────────────────
    st.markdown("---")
    st.markdown("### 📊 高度なトレンド分析（収益管理者向け）")
    
    col_curve, col_partner = st.columns([1.5, 1], gap="large")
    
    with col_curve:
        if not item_events.empty:
            st.markdown("#### ① ブッキング・カーブ（予約ペース曲線）")
            # 累計販売数の算出
            item_events["cum_sales"] = item_events["quantity"].cumsum()
            
            # 理想の販売曲線 (出発60日前から出発日まで、target_sell_ratio=0.9を目指す)
            dep_dt = pd.to_datetime(inv_sel["departure_date"]).tz_localize("Asia/Tokyo")
            start_dt = dep_dt - pd.Timedelta(days=60)
            target_qty = int(inv_sel["total_stock"] * 0.9)
            
            ideal_x = [start_dt, dep_dt]
            ideal_y = [0, target_qty]
            
            fig_curve = go.Figure()
            # 理想曲線 (点線)
            fig_curve.add_trace(go.Scatter(
                x=ideal_x, y=ideal_y, name="理想のペース (目標90%)",
                line=dict(color="#64748b", width=2, dash="dash")
            ))
            # 実績曲線 (実線)
            fig_curve.add_trace(go.Scatter(
                x=item_events["booked_at"], y=item_events["cum_sales"], name="現在の進捗 (実績)",
                mode="lines+markers", line=dict(color="#a78bfa", width=3),
                fill="tozeroy", fillcolor="rgba(167,139,250,0.1)"
            ))
            
            fig_curve.update_layout(xaxis_title="予約日時", yaxis_title="累計販売数")
            st.plotly_chart(dark_layout(fig_curve), use_container_width=True)
        else:
            st.info("📊 ブッキング・カーブ：販売データがまだありません。")

    with col_partner:
        if not item_events.empty:
            st.markdown("#### ③ 相棒（パッケージ）貢献度分析")
            # パッケージ vs 単体の集計
            pkg_counts = item_events["is_package"].value_counts().to_dict()
            labels = ["パッケージ販売", "単体販売"]
            values = [pkg_counts.get(1, 0), pkg_counts.get(0, 0)]
            
            # partner_id がある場合、相手の名前を特定
            partner_ids = item_events[item_events["is_package"] == 1]["partner_id"].dropna().unique()
            partner_names = {pid: inv_df[inv_df["id"] == pid]["name"].iloc[0] for pid in partner_ids if not inv_df[inv_df["id"] == pid].empty}
            
            fig_donut = go.Figure(data=[go.Pie(
                labels=labels, values=values, hole=.5,
                marker=dict(colors=["#a78bfa", "#1e293b"]),
                textinfo='percent+label'
            )])
            fig_donut.update_layout(showlegend=False, paper_bgcolor="rgba(0,0,0,0)", height=350)
            st.plotly_chart(fig_donut, use_container_width=True)
            
            if partner_names:
                partner_str = " / ".join(list(partner_names.values())[:3])
                st.markdown(f"<p style='color:#94a3b8;font-size:.8rem;text-align:center'>主なセット販売相手: {partner_str} など</p>", unsafe_allow_html=True)
        else:
            st.info("🤝 パッケージ貢献度：データなし")

    if not item_events.empty:
        st.markdown("#### ② 限界利益（マージン）推移")
        # マージン = sold_price - base_price_at_sale
        item_events["margin"] = item_events["sold_price"] - item_events["base_price_at_sale"]
        
        fig_margin = go.Figure()
        # 原価ライン (Base Price)
        fig_margin.add_trace(go.Scatter(
            x=[item_events["booked_at"].min(), item_events["booked_at"].max()],
            y=[0, 0], name="損益分岐点 (Base Price)",
            line=dict(color="#64748b", width=1, dash="dash")
        ))
        
        # マージン棒グラフ (プラスは緑、マイナスは赤)
        colors = ["#4ade80" if m >= 0 else "#f87171" for m in item_events["margin"]]
        fig_margin.add_trace(go.Bar(
            x=item_events["booked_at"], y=item_events["margin"],
            name="マージン (利益幅)", marker_color=colors
        ))
        
        fig_margin.update_layout(xaxis_title="販売日時", yaxis_title="利益幅 (円)")
        st.plotly_chart(dark_layout(fig_margin), use_container_width=True)
    else:
        st.info("💸 マージン推移：販売データなし")

    st.markdown("---")

    st.markdown("---")

    # ── パッケージ: 7ステップ ─────────────────────────────────────
    st.markdown("### 📦 パッケージ 価格内訳ウォーターフォール")
    st.markdown("<p style='color:#64748b;font-size:.9rem'>フライト＋ホテルの各調整とクロスセル割引が最終パッケージ価格に与える影響</p>",
                unsafe_allow_html=True)

    if packages:
        pkg_opts = [f"Rank {p['rank']}: {p['flight_name']} ＋ {p['hotel_name']}" for p in packages]
        selected_pkg_label = st.selectbox("📦 パッケージを選択", pkg_opts, key="tab2_pkg")
        sel_rank = int(selected_pkg_label.split(":")[0].replace("Rank", "").strip())
        pkg = next(p for p in packages if p["rank"] == sel_rank)

        f_adj_total = pkg["flight_velocity_adjustment"]
        h_adj_total = pkg["hotel_velocity_adjustment"]

        pkg_labels   = ["フライト原価", "フライト調整", "ホテル原価", "ホテル調整",
                        "小計", "クロスセル割引", "最終価格"]
# ══════════════════════════════════════════════════════════════════
# Step 3: 【戦略】パッケージ戦略分析 (Strategy)
# ══════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 📦 パッケージ戦略分析（収益最大化マップ）")
    all_events = load_booking_events()
    pkg_events = all_events[all_events["is_package"] == 1]
    
    if not pkg_events.empty:
        col_st1, col_st2 = st.columns([1.5, 1], gap="large")
        
        with col_st1:
            st.markdown("#### ① 相性ヒートマップ（フライト×ホテル）")
            # データのクロス集計
            df_heat = pkg_events.copy()
            inv_map = {row["id"]: row["name"] for _, row in inv_df.iterrows()}
            
            def get_f_h_names(r):
                # 自分がフライトなら相手がホテル、自分がホテルなら相手がフライト
                my_type = inv_df[inv_df["id"]==r["inventory_id"]].iloc[0]["item_type"]
                if my_type == "flight":
                    return inv_map.get(r["inventory_id"]), inv_map.get(r["partner_id"])
                else:
                    return inv_map.get(r["partner_id"]), inv_map.get(r["inventory_id"])

            names_list = df_heat.apply(get_f_h_names, axis=1)
            df_heat["f_name"] = [n[0] for n in names_list]
            df_heat["h_name"] = [n[1] for n in names_list]
            
            # ペア単位で1件と数える（現在は1トランザクションで2レコードあるため、件数を2で割るか、片方のタイプに絞る）
            df_heat_f = df_heat[df_heat["inventory_id"].isin(inv_df[inv_df["item_type"]=="flight"]["id"])]
            
            if not df_heat_f.empty:
                heat_pivot = df_heat_f.pivot_table(index="f_name", columns="h_name", values="quantity", aggfunc="sum", fill_value=0)
                fig_heat = go.Figure(data=go.Heatmap(
                    z=heat_pivot.values, x=heat_pivot.columns, y=heat_pivot.index,
                    colorscale='Viridis', text=heat_pivot.values, texttemplate="%{text}", showscale=False
                ))
                fig_heat.update_layout(height=400, margin=dict(t=20, b=20))
                st.plotly_chart(dark_layout(fig_heat), use_container_width=True)
            else:
                st.info("ヒートマップ：表示可能なペアデータがありません。")

        with col_st2:
            st.markdown("#### ④ 在庫救済のMVPランキング")
            # 「不人気ホテル（在庫消化率が低い）」を助けているフライトを探す
            at_risk_hotels = inv_df[(inv_df["item_type"]=="hotel") & (inv_df["remaining_stock"]/inv_df["total_stock"] > 0.6)]["id"].tolist()
            if at_risk_hotels:
                rescue_data = pkg_events[pkg_events["inventory_id"].isin(at_risk_hotels) | pkg_events["partner_id"].isin(at_risk_hotels)]
                # 度数分布
                mvp_series = df_heat[df_heat["h_name"].isin([inv_map[id] for id in at_risk_hotels])]["f_name"].value_counts().head(3)
                
                if not mvp_series.empty:
                    for i, (name, val) in enumerate(mvp_series.items()):
                        st.markdown(f"""
                        <div style="background:rgba(16,185,129,0.1); border-left:4px solid #10b981; padding:10px; margin:10px 0;">
                            <span style="font-weight:900; color:#10b981;">RANK {i+1}</span><br>
                            {name} <span style="float:right; color:#94a3b8;">救済数: {val}件</span>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("現在、顕著な救済活動は記録されていません。")
            else:
                st.info("現在、高リスクな在庫はありません。")

        st.markdown("---")
        col_st3, col_st4 = st.columns(2, gap="large")
        
        with col_st3:
            st.markdown("#### ② 利益比較シミュレーション")
            # パッケージ利益 vs 単品想定利益
            # 実益 = 実際に売れた合計利益 (Sold - Base)
            pkg_actual_profit = (pkg_events["sold_price"] - pkg_events["base_price_at_sale"]).sum()
            
            # 理論上の利益 = もしセット割引を行わずに販売していた場合
            # データベースに記録された discount_amount (実績値) を使用して正確に逆算
            total_discount_given = pkg_events["discount_amount"].sum()
            pkg_theoretical_profit = pkg_actual_profit + total_discount_given 
            
            fig_comp = go.Figure()
            fig_comp.add_trace(go.Bar(
                x=["単品価格(想定)", "パッケージ(実益)"],
                y=[pkg_theoretical_profit, pkg_actual_profit],
                marker_color=["#64748b", "#a78bfa"],
                text=[f"¥{pkg_theoretical_profit:,.0f}", f"¥{pkg_actual_profit:,.0f}"],
                textposition='auto',
            ))
            dark_layout(fig_comp, "プロモーションによる収益変動")
            st.plotly_chart(fig_comp, use_container_width=True)
            st.markdown("<p style='color:#64748b;font-size:.8rem'>※パッケージ割引（実績ベース合計: ¥{total_discount_given:,}）による収益影響を表示。</p>".format(total_discount_given=int(total_discount_given)), unsafe_allow_html=True)

        with col_st4:
            st.markdown("#### ③ 不透明価格の内訳スケルトン")
            if packages:
                top_pkg = packages[0]
                # 内訳: フライト原価, ホテル原価, 価格調整, 最終割引
                # 簡易化して表示
                skeleton_labels = ["フライト", "ホテル", "AI調整", "セット割引"]
                skeleton_values = [top_pkg["flight_base"], top_pkg["hotel_base"], 
                                   (top_pkg["flight_velocity_adjustment"] + top_pkg["hotel_velocity_adjustment"]),
                                   -top_pkg["bundle_discount"]]
                
                fig_skel = go.Figure(data=[
                    go.Bar(name='構成要素', x=skeleton_labels, y=skeleton_values, 
                           marker_color=["#60a5fa", "#34d399", "#fbbf24", "#f87171"])
                ])
                dark_layout(fig_skel, f"代表：{top_pkg['flight_name']}セット")
                st.plotly_chart(fig_skel, use_container_width=True)
    else:
        st.warning("パッケージの販売データが不足しています。")

# Step 4: 【行動】ライブ動向・一覧 (Detail / Act)
# ══════════════════════════════════════════════════════════════════
with tab4:
    render_alerts(results, inv_df, packages)
    st.markdown("### 📦 ライブ商品ステータス")
    # 個別カード一覧 (4列)
    n_cols = 4
    for i in range(0, len(results), n_cols):
        cols = st.columns(n_cols)
        for ci, r in enumerate(results[i:i+n_cols]):
            diff = r["final_price"] - r["base_price"]
            badge_class = "badge-up" if diff >= 0 else "badge-down"
            brake_html = '<div class="badge-brake">🚔 AUTO BRAKE ACTIVE</div>' if r.get("is_brake_active") else ""
            with cols[ci]:
                st.markdown(f"""
                <div class="metric-card">
                  <div class="metric-label">ID #{r['inventory_id']}</div>
                  <div class="metric-sub">{r['name']}</div>
                  <div class="metric-value">¥{r['final_price']:,}</div>
                  <div><span class="{badge_class}">{'↑' if diff>=0 else '↓'} ¥{abs(diff):,}</span></div>
                  {brake_html}
                </div>""", unsafe_allow_html=True)

    st.markdown("---")
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown("#### ⚡ 販売速度シグナル")
        if results:
            v_names = [r["name"] for r in results]
            v_vals = []
            for r in results:
                inv = inv_df[inv_df["id"] == r["inventory_id"]].iloc[0]
                vr = get_velocity_ratio(r["inventory_id"], int(inv["total_stock"]), int(inv["remaining_stock"]), r["lead_days"])
                v_vals.append(vr or 0)
            st.plotly_chart(dark_layout(go.Figure(go.Bar(x=v_names, y=v_vals, marker_color="#a78bfa"))), use_container_width=True)
        else:
            st.info("速度データなし")

    with c_right:
        st.markdown("#### 📈 価格推移（時系列）")
        if not history_df.empty:
            fig_h = go.Figure()
            for name in history_df["name"].unique():
                sub = history_df[history_df["name"] == name]
                fig_h.add_trace(go.Scatter(x=sub["recorded_at"], y=sub["dynamic_price"], name=name, mode="lines"))
            st.plotly_chart(dark_layout(fig_h), use_container_width=True)

    st.markdown("---")
    st.markdown("### 📋 全在庫明細データ")
    st.dataframe(inv_df, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.success(f"""
    **💡 ビジネスインサイト:**
    動的価格調整により、本来の想定売上 ¥{roi_metrics['total_fixed']:,} に対して **¥{roi_metrics['lift']:,} の増分収益** を生み出しています。
    また、パッケージ化（クロスセル）により、ホテルの切迫在庫のうち **{rescue_metrics['hotel_rescue_rate']}%** が効率的に消化されました。
    """)
    last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.markdown(f'<p style="color:#475569;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>', unsafe_allow_html=True)
