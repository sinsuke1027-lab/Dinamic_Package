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
from datetime import date, datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── 設定 ────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "inventory.db")

import sys as _sys
import importlib
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import packaging_engine
importlib.reload(packaging_engine)
from packaging_engine import (
    get_velocity_ratio, calc_velocity_adjustment,
    hotel_urgency_score, calculate_roi_metrics, calculate_inventory_rescue_metrics,
    calculate_demand_forecast, calculate_optimal_strategy, simulate_sales_scenario
)
import pricing_engine
importlib.reload(pricing_engine)
from pricing_engine import calculate_inventory_decay_factor

# 共通ユーティリティのインポート
from dashboard.utils import (
    apply_custom_css, dark_layout, render_metric_card, render_alerts, hex_to_rgba, log_price_history
)

st.set_page_config(
    page_title="Explainable Pricing Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── カスタム CSS ─────────────────────────────────────────────────
apply_custom_css()

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

def get_pricing_results(inv_df: pd.DataFrame, config: dict = None, strategy: str = "rule_based", reference_date: date = None) -> list[dict]:
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
            elasticity      = row.get("elasticity", -1.5),
            config          = config,
            strategy        = strategy,
            reference_date  = reference_date,
        )
        results.append(r)
    return results



# ─── ヘッダー ──────────────────────────────────────────────────────
st.markdown("""
<h1>🔍 Explainable Pricing Dashboard</h1>
<p style='color:#cbd5e1; margin-top:-12px; margin-bottom:20px;'>
  価格の根拠を可視化し、アルゴリズムのブラックボックス化を防ぐ —
  <span style='color:#a78bfa'>White-box Pricing Engine</span>
</p>
""", unsafe_allow_html=True)

# ─── データロード ─────────────────────────────────────────────────
inv_df     = load_inventory()
history_df = load_history()

if inv_df.empty:
    st.error("⚠️ 在庫データが見つかりません。`python init_db.py` を先に実行してください。")
    st.stop()

# ──────────────────────────────────────────────────────────────────
# Sidebar - Global Settings & Forecast Scenario & AI Command Center
# ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📅 出発日・宿泊日フィルタ")
    all_dates = sorted(inv_df["departure_date"].dropna().unique().tolist())
    selected_dates = st.multiselect(
        "表示対象の日程を選択",
        all_dates,
        default=all_dates,
        help="選択した日程の在庫のみを分析・表示の対象にします。"
    )
    
    st.markdown("---")
    st.markdown("### ⏳ タイムトラベル設定")
    virtual_today = st.date_input(
        "シミュレーション基準日 (Virtual Today)",
        value=datetime.now(timezone.utc).date(),
        help="指定した日付時点での「残在庫」「販売ペース」を再計算し、それより過去（または当日）に出発した在庫は分析対象から除外します。"
    )
    st.session_state["virtual_today"] = virtual_today
    
    st.markdown("---")
    st.markdown("### 🌐 全体設定")
    
    pricing_strategy = st.radio(
        "プライシング戦略",
        ["rule_based", "demand_based"],
        format_func=lambda x: "ルールベース (現行: 相対価格調整)" if x=="rule_based" else "需要予測ベース (新規: 弾力性逆算)",
        help="価格計算エンジンが使用するアルゴリズムを切り替えます。"
    )
    st.session_state["pricing_strategy"] = pricing_strategy

    selected_scenario = st.radio(
        "需要予測シナリオ (Market Condition)",
        ["base", "pessimistic", "optimistic"],
        format_func=lambda x: "ベース (Base)" if x=="base" else ("切迫・悲観 (Pessimistic: 0.7x)" if x=="pessimistic" else "好調・楽観 (Optimistic: 1.3x)"),
        help="ダッシュボード全体の予測値（着地点、ブッキングカーブ延伸、シミュレーター初期値）に影響します。"
    )
    st.session_state["market_scenario"] = selected_scenario
    
    st.markdown("---")
    st.markdown("### 🎛 AI Command Center")
    st.markdown("<p style='color:#e2e8f0;font-size:.8rem'>AIの行動ルールをリアルタイム編集</p>", unsafe_allow_html=True)
    
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
    if st.button("🔄 データを再読み込み"):
        st.cache_data.clear()
        st.rerun()




# 選択された日付に基づいて在庫をフィルタリング
if not selected_dates:
    st.warning("⚠️ 日程が選択されていません。全ての日程を表示します。")
    filtered_inv_df = inv_df.copy()
else:
    filtered_inv_df = inv_df[inv_df["departure_date"].isin(selected_dates)].copy()

# UI表示用に「商品名 (日付)」のカラムを作成
filtered_inv_df["display_name"] = filtered_inv_df.apply(
    lambda x: f"{x['name']} ({x['departure_date']})", axis=1
)

# ─── 基準日（Virtual Today）に基づく在庫の再計算とフィルタリング ───
v_today = st.session_state.get("virtual_today", datetime.now(timezone.utc).date())

# 1. 基準日より過去（または当日）に出発する在庫を除外
if not filtered_inv_df.empty:
    filtered_inv_df = filtered_inv_df[pd.to_datetime(filtered_inv_df["departure_date"]).dt.date > v_today].copy()

# 2. 基準日時点の「残在庫」を再計算
# (Virtual Today以降に発生した予約イベントをキャンセルしたとみなす)
all_events = load_booking_events()
if not all_events.empty and not filtered_inv_df.empty:
    # 基準日以降の予約
    future_events = all_events[all_events["booked_at"].dt.date > v_today]
    if not future_events.empty:
        # inventory_id ごとに数量を集計
        future_sales = future_events.groupby("inventory_id")["quantity"].sum().reset_index()
        # filtered_inv_df にマージして remaining_stock を復元
        filtered_inv_df = pd.merge(filtered_inv_df, future_sales, how="left", left_on="id", right_on="inventory_id")
        filtered_inv_df["quantity"] = filtered_inv_df["quantity"].fillna(0)
        filtered_inv_df["remaining_stock"] = filtered_inv_df["remaining_stock"] + filtered_inv_df["quantity"]
        filtered_inv_df.drop(columns=["inventory_id", "quantity"], inplace=True)

target_ids = filtered_inv_df["id"].tolist()

strategy_val = st.session_state.get("pricing_strategy", "rule_based")
results = get_pricing_results(filtered_inv_df, config=ai_config, strategy=strategy_val, reference_date=v_today)
log_price_history(results, DB_PATH)
history_df = load_history() # 履歴を再読み込みして最新化

# 履歴データもフィルタリング (基準日以前のものだけ表示)
if not history_df.empty:
    history_df = history_df[history_df["inventory_id"].isin(target_ids)]
    history_df = history_df[history_df["recorded_at"].dt.date <= v_today]

# ─── パッケージエンジン読み込み（全タブ共通） ─────────────────────
curr_scenario = st.session_state.get("market_scenario", "base")
try:
    roi_metrics = calculate_roi_metrics(inventory_ids=target_ids, reference_date=v_today)
    rescue_metrics = calculate_inventory_rescue_metrics(inventory_ids=target_ids, reference_date=v_today)
    
    # --- Prescriptive Analytics (Phase 14 / Phase 27) ---
    # AI現在価格（時価）をマッピングしてエンジンに渡す
    current_prices = {r["inventory_id"]: r["final_price"] for r in results}
    optimal_strategy = calculate_optimal_strategy(
        scenario=curr_scenario, 
        inventory_ids=target_ids,
        current_prices=current_prices,
        reference_date=v_today
    )
except Exception as _e:
    packages = []
    roi_metrics = {"lift": 0, "lift_pct": 0, "total_fixed": 0, "total_dynamic": 0, "daily_data": []}
    rescue_metrics = {"overall_rescue_rate": 0, "rescued_units": 0, "hotel_rescue_rate": 0, "total_units": 0}
    optimal_strategy = {"recommendations": [], "total_standalone_profit": 0, "total_optimized_profit": 0, "ai_impact": 0}
    _pkg_err = str(_e)
    st.warning(f"分析エンジンの初期化に失敗しました: {_pkg_err}")


# ─── 5タブ構成 ──────────────────────────────
tabs = [
    "📈 Executive Summary",
    "🎯 Today's Action",
    "🔍 Analysis & Tracking",
    "📦 Strategy Map",
    "🧪 Custom Simulator"
]
selected_tab = st.radio("MainNavigation", tabs, horizontal=True, label_visibility="collapsed", key="main_nav_tab")


# ══════════════════════════════════════════════════════════════════
# Tab 1: 【観察】エグゼクティブ・サマリ (Observe)
# ══════════════════════════════════════════════════════════════════
if selected_tab == "📈 Executive Summary":
    # ─── 過去の実績スライサー追加 ───
    st.markdown("---")
    st.markdown("### 🗓️ 販売実績期間フィルタ")
    st.caption("ROI・売上推移グラフの集計対象期間")
    
    # booking_events の最小・最大日付を概算で取得
    min_date_val = datetime.now(timezone.utc).date() - timedelta(days=180) # デフォルト安全値
    max_date_val = datetime.now(timezone.utc).date()
    # 実際はクエリで最小値をとるのが正確ですが、デモでは固定範囲でUI提供します
    
    selected_hist_dates = st.date_input(
        "集計対象期間を選択",
        value=(min_date_val, max_date_val),
        help="この期間内に発生した予約データのみがROIグラフの対象になります。"
    )

    if isinstance(selected_hist_dates, tuple) and len(selected_hist_dates) == 2:
        hist_start, hist_end = selected_hist_dates
    elif isinstance(selected_hist_dates, tuple) and len(selected_hist_dates) == 1:
        hist_start = hist_end = selected_hist_dates[0]
    else:
        hist_start, hist_end = min_date_val, max_date_val

    roi_metrics = calculate_roi_metrics(
        inventory_ids=target_ids,
        target_start_date=hist_start.isoformat(),
        target_end_date=hist_end.isoformat(),
        reference_date=v_today
    )

    # --- [NEW] 需要予測・着地点セクション ---
    curr_scenario = st.session_state.get("market_scenario", "base")
    st.markdown("### 🔮 ビジネス着地点予測 (End-of-Term Forecast)")
    st.markdown(f'<p class="section-description">※選択中のシナリオ: <b>{curr_scenario.upper()}</b> に基づく Day 0 までの予測</p>', unsafe_allow_html=True)
    
    # 全商品の予測を集計
    total_expected_profit = 0
    total_unsold = 0
    for r in results:
        inv = filtered_inv_df[filtered_inv_df["id"] == r["inventory_id"]].iloc[0]
        # 原価（cost）を base_price * 0.5 と仮定した簡易コスト算出
        forecast = calculate_demand_forecast(r["inventory_id"], r["lead_days"], int(inv["remaining_stock"]), int(inv["total_stock"]), r["base_price"], int(r["base_price"]*0.5), reference_date=v_today)
        total_expected_profit += forecast[curr_scenario]["expected_profit"]
        total_unsold += forecast[curr_scenario]["unsold_stock"]

    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label" style="color:var(--text-heading) !important;">見込み最終純利益</div>
            <div class="metric-value" style="color:#10b981; font-size:1.8rem;">¥{int(total_expected_profit):,}</div>
            <div class="metric-sub">前回比: +¥{int(total_expected_profit - roi_metrics['total_dynamic']):,}</div>
        </div>""", unsafe_allow_html=True)
    with f_col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label" style="color:var(--text-heading) !important;">予測売れ残り数</div>
            <div class="metric-value" style="color:#f87171; font-size:1.8rem;">{int(total_unsold)} units</div>
            <div class="metric-sub">Day 0 到着時の余剰在庫</div>
        </div>""", unsafe_allow_html=True)
    with f_col3:
        risk_level = "高" if total_unsold > 50 else ("中" if total_unsold > 20 else "低")
        risk_color = "#f87171" if risk_level == "高" else ("#fbbf24" if risk_level == "中" else "#4ade80")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label" style="color:var(--text-heading) !important;">在庫破棄リスク</div>
            <div class="metric-value" style="color:{risk_color}; font-size:1.8rem;">{risk_level}</div>
            <div class="metric-sub">売れ残り予測に基づく判定</div>
        </div>""", unsafe_allow_html=True)

    
    
    

    

    
    col_chart, col_donut = st.columns([2, 1])
    with col_chart:
        st.markdown("#### 📈 累積売上と廃棄損の推移：固定 vs 動的")
        df_daily = pd.DataFrame(roi_metrics["daily_data"])
        if not df_daily.empty:
            df_daily["cum_dyn_sales"] = df_daily.get("day_dyn_sales", 0).cumsum()
            df_daily["cum_dyn_waste"] = df_daily.get("day_dyn_waste", 0).cumsum()
            df_daily["cum_fix_sales"] = df_daily.get("day_fix_sales", 0).cumsum()
            df_daily["cum_fix_waste"] = df_daily.get("day_fix_waste", 0).cumsum()

            fig_roi = go.Figure()
            
            # 1. 動的価格・売上 (Green, solid/filled)
            fig_roi.add_trace(go.Scatter(
                x=df_daily["day"], y=df_daily["cum_dyn_sales"], name="動的価格・売上 (実績)",
                mode='lines+markers', line=dict(color='#10b981', width=3),
                fill='tozeroy', fillcolor='rgba(16,185,129,0.1)'
            ))
            # 2. 固定価格・売上 (Blue, dashed)
            fig_roi.add_trace(go.Scatter(
                x=df_daily["day"], y=df_daily["cum_fix_sales"], name="固定価格・売上 (想定)",
                mode='lines', line=dict(color='#0ea5e9', width=2, dash='dash')
            ))
            # 3. 固定価格・廃棄損 (Orange, dashed)
            fig_roi.add_trace(go.Scatter(
                x=df_daily["day"], y=df_daily["cum_fix_waste"], name="固定価格・廃棄損 (想定)",
                mode='lines', line=dict(color='#fb923c', width=2, dash='dash')
            ))
            # 4. 動的価格・廃棄損 (Red, solid) - グラフ上で比較対象として明示
            fig_roi.add_trace(go.Scatter(
                x=df_daily["day"], y=df_daily["cum_dyn_waste"], name="動的価格・廃棄損 (実績)",
                mode='lines+markers', line=dict(color='#f43f5e', width=3)
            ))
            
            dark_layout(fig_roi, "累積売上と廃棄損の推移", yaxis_title="累積金額 (円)")
            st.plotly_chart(fig_roi, use_container_width=True, key="summary_roi_chart")
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
        dark_layout(fig_donut, "救済状況内訳")
        st.plotly_chart(fig_donut, use_container_width=True, key="summary_donut_chart")

    st.markdown("---")

    st.markdown("---")
    last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.markdown(f'<p style="color:#e2e8f0;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>',
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# Tab 2: 【アクション】Today's Action
# ══════════════════════════════════════════════════════════════════
if selected_tab == "🎯 Today's Action":
    def get_velocity_ratio_with_ref(inv_id, ts, rs, ld):
        return get_velocity_ratio(inv_id, ts, rs, ld, reference_date=v_today)
        
    render_alerts(results, filtered_inv_df, [], get_velocity_ratio_with_ref)

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%); border:1px solid rgba(56,189,248,0.4); border-radius:20px; padding:24px; margin-top:20px; margin-bottom:20px; box-shadow:0 0 30px rgba(56,189,248,0.15);">
        <div style="font-size:0.85rem; color:#e2e8f0; text-transform:uppercase; letter-spacing:0.15em; margin-bottom:12px;">
            ✨ これまでのAI導入効果・ROIサマリ (純利益ベース) ※設定した「販売実績期間」内での実績
        </div>
        <div style="display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap;">
            <div style="flex:1; min-width:180px; background:rgba(255,255,255,0.05); border-radius:12px; padding:16px;">
                <div style="font-size:0.75rem; color:#e2e8f0; margin-bottom:4px;">合計純利益リフト</div>
                <div style="font-size:2rem; font-weight:800; color:#e2e8f0; line-height:1;">+¥{roi_metrics['lift']:,}</div>
                <div style="font-size:0.75rem; color:#cbd5e1; margin-top:6px;">固定価格比 <span style="color:#bae6fd; font-weight:700;">+{roi_metrics['lift_pct']:.1f}%</span></div>
            </div>
            <div style="flex:1; min-width:180px; background:rgba(255,255,255,0.05); border-radius:12px; padding:16px;">
                <div style="font-size:0.75rem; color:#e2e8f0; margin-bottom:4px;">回避した廃棄損失額</div>
                <div style="font-size:2rem; font-weight:800; color:#38bdf8; line-height:1;">+¥{roi_metrics.get('avoided_waste_loss', 0):,}</div>
                <div style="font-size:0.75rem; color:#cbd5e1; margin-top:6px;">値引き/パッケージによる救済額</div>
            </div>
            <div style="flex:1; min-width:180px; background:rgba(255,255,255,0.05); border-radius:12px; padding:16px;">
                <div style="font-size:0.75rem; color:#e2e8f0; margin-bottom:4px;">値上げによる純増益</div>
                <div style="font-size:2rem; font-weight:800; color:#f472b6; line-height:1;">+¥{roi_metrics.get('surge_profit', 0):,}</div>
                <div style="font-size:0.75rem; color:#cbd5e1; margin-top:6px;">需要高騰時の自動価格調整効果</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


    # ══════════════════════════════════════════════════════════════════
    # 🏆 Hero KPI: AI最適化インパクト (Prescriptive Analytics - Phase 14)
    # ══════════════════════════════════════════════════════════════════
    ai_impact      = optimal_strategy["ai_impact"]
    total_sa       = optimal_strategy["total_standalone_profit"]
    total_opt      = optimal_strategy["total_optimized_profit"]
    impact_color   = "#10b981" if ai_impact >= 0 else "#f87171"
    impact_sign    = "+" if ai_impact >= 0 else ""
    scenario_label = {"base": "ベース", "optimistic": "楽観", "pessimistic": "悲観"}.get(curr_scenario, "ベース")

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d1b2a 0%,#1a2e4a 100%); border:1px solid rgba(167,139,250,0.4); border-radius:20px; padding:24px; margin-bottom:20px; box-shadow:0 0 30px rgba(167,139,250,0.15);">
        <div style="font-size:0.85rem; color:#e2e8f0; text-transform:uppercase; letter-spacing:0.15em; margin-bottom:6px;">
            💡 AI最適化インパクト — シナリオ: {scenario_label}
        </div>
        <div style="display:flex; gap:30px; align-items:center; flex-wrap:wrap;">
            <div style="flex:1; min-width:160px;">
                <div style="font-size:0.75rem; color:#e2e8f0; margin-bottom:4px;">現状維持（全単品）の予測利益</div>
                <div style="font-size:1.5rem; font-weight:800; color:#e2e8f0;">¥{total_sa:,}</div>
            </div>
            <div style="font-size:2rem; color:#a78bfa;">→</div>
            <div style="flex:1; min-width:160px;">
                <div style="font-size:0.75rem; color:#e2e8f0; margin-bottom:4px;">AI推奨プラン実行後の予測利益</div>
                <div style="font-size:1.5rem; font-weight:800; color:#10b981;">¥{total_opt:,}</div>
            </div>
            <div style="flex:1.5; min-width:200px; background:rgba(16,185,129,0.1); border-radius:12px; padding:16px; text-align:center; border:1px solid rgba(16,185,129,0.3);">
                <div style="font-size:0.75rem; color:#e2e8f0; margin-bottom:4px;">📈 利益改善見込み</div>
                <div style="font-size:2.4rem; font-weight:900; color:{impact_color};">{impact_sign}¥{ai_impact:,}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    # 🎯 本日の AI 推奨アクション（Actionable Recommendations）
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### 🎯 本日の AI 推奨アクション")
    st.markdown('<p class="section-description">各商品の最適販売戦略。パッケージ推奨は在庫ロスを最小化し、全体利益を最大化する組み合わせです。</p>', unsafe_allow_html=True)

    recs = optimal_strategy["recommendations"]
    bundle_recs     = [r for r in recs if r["strategy"] == "bundle"]
    standalone_recs = [r for r in recs if r["strategy"] == "standalone"]
    # bundle_partner は表示リストから除外（バンドル推奨に統合表示）

    if not recs:
        st.info("商品データがないため、推奨アクションを計算できませんでした。")
    else:
        # パッケージ推奨カード（緑系）― 出発日インパクト順に表示
        sorted_bundle_recs = sorted(bundle_recs, key=lambda r: r.get("gain", 0), reverse=True)
        for rec in sorted_bundle_recs:
            item_icon = "🏨" if rec["item_type"] == "hotel" else "✈️"
            dep_date  = rec.get("departure_date", "---")
            # 日付表示用に整形（YYYY-MM-DD → M/D）
            try:
                from datetime import datetime as _dt
                dep_label = _dt.strptime(dep_date[:10], "%Y-%m-%d").strftime("%-m/%-d")
            except Exception:
                dep_label = dep_date
            st.markdown(f"""
            <div style="background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.5); border-radius:14px; padding:18px; margin:8px 0;">
                <div style="display:flex; gap:10px; align-items:center; margin-bottom:8px; flex-wrap:wrap;">
                    <div style="background:#10b981; color:#fff; border-radius:8px; padding:4px 10px; font-size:0.75rem; font-weight:900; white-space:nowrap;">
                        📦 パッケージ推奨
                    </div>
                    <div style="background:rgba(99,102,241,0.2); color:#a5b4fc; border:1px solid rgba(99,102,241,0.4); border-radius:6px; padding:3px 10px; font-size:0.8rem; font-weight:700;">
                        📅 {dep_label}出発
                    </div>
                    <div style="color:#a78bfa; font-size:0.85rem; font-weight:600; margin-left:auto;">+¥{rec['gain']:,} 改善</div>
                </div>
                <div style="font-size:1rem; font-weight:800; color:#ffffff; margin-bottom:6px;">
                    {item_icon} {rec['item_name']} ＋ ✈️ {rec['partner_name']}
                </div>
                <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:6px;">
                    <span style="color:#10b981; font-weight:700;">推奨価格: ¥{rec['optimal_price']:,}</span>
                    <span style="color:#cbd5e1;">上限セット数: {rec['max_sets']} セット</span>
                </div>
                <div style="font-size:0.85rem; color:#e2e8f0;">{rec['reason']}</div>
            </div>
            """, unsafe_allow_html=True)

        # 単品維持カード（グレー系）
        with st.expander(f"⚪ 単品維持 ({len(standalone_recs)}商品) — 現行価格を維持"):
            for rec in standalone_recs:
                item_icon = "🏨" if rec["item_type"] == "hotel" else "✈️"
                dep_date  = rec.get("departure_date", "---")
                try:
                    from datetime import datetime as _dt
                    dep_label = _dt.strptime(dep_date[:10], "%Y-%m-%d").strftime("%-m/%-d")
                except Exception:
                    dep_label = dep_date
                st.markdown(f"""
                <div style="background:rgba(100,116,139,0.1); border:1px solid rgba(100,116,139,0.4); border-radius:10px; padding:12px; margin:6px 0; display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                    <span style="background:rgba(99,102,241,0.15); color:#a5b4fc; border-radius:6px; padding:2px 8px; font-size:0.75rem; font-weight:700;">📅 {dep_label}</span>
                    <span style="font-weight:700; color:#e2e8f0;">{item_icon} {rec['item_name']}</span>
                    <span style="color:#e2e8f0; font-size:0.85rem;">現行価格: ¥{rec['optimal_price']:,}</span>
                    <div style="width:100%; font-size:0.8rem; color:#cbd5e1; margin-top:4px;">{rec['reason']}</div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("---")

# ══════════════════════════════════════════════════════════════════
# Tab 3: Analysis & Tracking (旧ドリルダウン + ライブ動向)
# ══════════════════════════════════════════════════════════════════
if selected_tab == "🔍 Analysis & Tracking":
    st.markdown("### 🔍 Analysis & Tracking")

    # --- 共通の商品選択エリア (ライブリストを兼ねる) ---
    st.markdown("#### 🎯 対象商品の詳細分析")
    
    # 簡易テーブルの作成
    table_data = []
    for r in results:
        inv_matches = filtered_inv_df[filtered_inv_df["id"] == r["inventory_id"]]
        if inv_matches.empty: continue
        inv = inv_matches.iloc[0]
        try:
            vr = get_velocity_ratio(r["inventory_id"], int(inv["total_stock"]), int(inv["remaining_stock"]), r["lead_days"], reference_date=v_today)
            status = "🚨 Over" if vr > 1.5 else ("⚠️ Slow" if vr < 0.6 else "✅ Normal")
        except: vr, status = 0, "---"
        
        table_data.append({
            "商品名": inv["name"],
            "販売速度": f"{vr:.2f}x",
            "ステータス": status,
            "時価": f"¥{r['final_price']:,}",
            "残庫": f"{int(inv['remaining_stock'])}/{int(inv['total_stock'])}",
            "ID": r["inventory_id"]
        })
    
    table_df = pd.DataFrame(table_data)
    
    # 選択
    selected_item_id = st.selectbox(
        "詳細分析する商品を選択してください", 
        table_df["ID"].tolist(), 
        format_func=lambda x: table_df[table_df["ID"]==x]["商品名"].iloc[0],
        key="global_item_selector"
    )
    
    st.markdown("---")

    # --- 選ばれた商品の詳細分析 (旧ドリルダウン) ---
    r_sel = next(r for r in results if r["inventory_id"] == selected_item_id)
    inv_sel = filtered_inv_df[filtered_inv_df["id"] == selected_item_id].iloc[0]
    
    all_events = load_booking_events()
    item_events = all_events[all_events["inventory_id"] == selected_item_id].sort_values("booked_at")

    col_radar, col_info = st.columns([1.2, 1], gap="large")
    with col_radar:
        st.markdown(f"#### 🃏 商品カルテ")
        inv_urgency   = 1.0 - r_sel["inv_ratio"]
        time_urgency  = max(0.0, 1.0 - (r_sel["lead_days"] or 90) / 60.0)
        p_elast       = min(abs(r_sel["elasticity"]) / 3.0, 1.0) # 弾力性（絶対値）のスコア化
        try:
            vr_k = get_velocity_ratio(r_sel["inventory_id"], int(inv_sel["total_stock"]), int(inv_sel["remaining_stock"]), r_sel["lead_days"], reference_date=v_today)
            vel_score = min((vr_k or 0.0) / 3.0, 1.0)
        except: vel_score = 0
        try: bundle_score = hotel_urgency_score(int(inv_sel["remaining_stock"]), int(inv_sel["total_stock"]), r_sel["lead_days"])
        except: bundle_score = 0

        radar_labels = ["在庫切迫度", "時間切迫度", "販売速度", "価格弾力性", "バンドル適性"]
        radar_scores = [inv_urgency, time_urgency, vel_score, p_elast, bundle_score]
        fig_radar = go.Figure(go.Scatterpolar(
            r=radar_scores + [radar_scores[0]], theta=radar_labels + [radar_labels[0]],
            fill="toself", fillcolor="rgba(167,139,250,0.18)", line=dict(color="#a78bfa", width=2.5),
        ))
        fig_radar.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)", radialaxis=dict(visible=True, range=[0, 1])), paper_bgcolor="rgba(0,0,0,0)", height=350)
        st.plotly_chart(fig_radar, use_container_width=True, key="tracking_radar_chart")
    
    with col_info:
        st.markdown(f"#### ℹ️ {inv_sel['name']}")
        st.markdown(f'<div class="karte-card">', unsafe_allow_html=True)
        st.markdown(f"**動的価格:** ¥{r_sel['final_price']:,}")
        st.markdown(f"**価格偏差:** {'+' if r_sel['final_price']>=r_sel['base_price'] else ''}¥{r_sel['final_price']-r_sel['base_price']:,}")
        st.markdown(f"**残在庫:** {int(inv_sel['remaining_stock'])}/{int(inv_sel['total_stock'])} ({int(r_sel['inv_ratio']*100)}%)")
        st.markdown(f"**価格弾力性:** {r_sel.get('elasticity', -1.5)}")
        st.markdown(f'<div class="reason-box">{r_sel["reason"]}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # 価格形成 WF とブッキングカーブ
    col_wf, col_curve = st.columns(2)
    with col_wf:
        st.markdown("#### 🌊 価格形成プロセス")
        if "waterfall" in r_sel and r_sel["waterfall"]:
            wf_data = r_sel["waterfall"]
            wf_labels = [item["label"] for item in wf_data]
            wf_values = [item["value"] for item in wf_data]
            wf_measure = [item["measure"] for item in wf_data]

            fig_wf = go.Figure(go.Waterfall(
                measure=wf_measure,
                x=wf_labels, y=wf_values,
                increasing=dict(marker=dict(color="#f87171")),
                decreasing=dict(marker=dict(color="#4ade80")),
                totals=dict(marker=dict(color="#a78bfa")),
            ))
        else:
            wf_labels = ["在庫調整", "時期調整", "速度調整", "合計調整"]
            vel_adj = r_sel['final_price'] - (r_sel['base_price'] + r_sel.get('inventory_adjustment', 0) + r_sel.get('time_adjustment', 0))
            wf_values = [r_sel.get("inventory_adjustment", 0), r_sel.get("time_adjustment", 0), vel_adj, (r_sel['final_price'] - r_sel['base_price'])]
            fig_wf = go.Figure(go.Waterfall(
                measure=["relative", "relative", "relative", "total"],
                x=wf_labels, y=wf_values,
                increasing=dict(marker=dict(color="#f87171")),
                decreasing=dict(marker=dict(color="#4ade80")),
                totals=dict(marker=dict(color="#a78bfa")),
            ))
        
        dark_layout(fig_wf)
        st.plotly_chart(fig_wf, use_container_width=True, key="tracking_wf_chart_unique")

    with col_curve:
        st.markdown("#### 📈 ブッキング傾向")
        
        # 基準日までのイベントのみにフィルタリング
        item_events_filtered = item_events[item_events["booked_at"].dt.date <= v_today].copy()
        
        if not item_events_filtered.empty:
            item_events_filtered["cum_sales"] = item_events_filtered["quantity"].cumsum()
            fig_curve = go.Figure()
            fig_curve.add_trace(go.Scatter(
                x=item_events_filtered["booked_at"], y=item_events_filtered["cum_sales"],
                mode="lines+markers", line=dict(color="#a78bfa", width=3),
                fill="tozeroy", fillcolor="rgba(167,139,250,0.1)"
            ))
            dark_layout(fig_curve)
            st.plotly_chart(fig_curve, use_container_width=True, key="tracking_curve_chart_unique")
        else:
            st.info("販売データがありません")
    st.markdown("---")
    st.markdown("#### 🚚 商品一覧 & 異常検知")
    st.dataframe(table_df, use_container_width=True, hide_index=True)

# 🪟 Tab 4: Strategy Map
if selected_tab == "📦 Strategy Map":
    st.markdown("### 📦 Strategy Map")

    col_map, col_kpi = st.columns([2, 1], gap="large")
    
    with col_map:
        st.markdown("#### 🗺 パッケージ・シナジー・マップ")
        # バブルチャートで「在庫切迫度」x「利益改善額」を可視化
        bubble_data = []
        for rec in optimal_strategy["recommendations"]:
            if rec["strategy"] == "bundle":
                h_id = rec.get("item_id")
                inv_matches = filtered_inv_df[filtered_inv_df["id"] == h_id]
                r_matches = [r for r in results if r["inventory_id"] == h_id]
                urg = 0.5
                if not inv_matches.empty and r_matches:
                    inv = inv_matches.iloc[0]
                    r_h = r_matches[0]
                    try:
                        from packaging_engine import hotel_urgency_score
                        urg = hotel_urgency_score(int(inv["remaining_stock"]), int(inv["total_stock"]), r_h.get("lead_days", 90))
                    except: pass

                bubble_data.append({
                    "name": rec["item_name"],
                    "urgency": urg,
                    "lift": rec["gain"],
                    "score": min(100, 20 + (rec["gain"] / 5000)) # スコア（バブルサイズ）も利益に応じて変動
                })
        if bubble_data:
            b_df = pd.DataFrame(bubble_data)
            fig_bubble = go.Figure(data=[go.Scatter(
                x=b_df["urgency"], y=b_df["lift"],
                mode='markers+text',
                text=b_df["name"],
                textposition="top center",
                marker=dict(size=b_df["score"], color=b_df["lift"], colorscale='Viridis', showscale=True)
            )])
            dark_layout(fig_bubble, "在庫切迫度 vs 利益改善リフト", yaxis_title="期待利益改善額 (円)")
            fig_bubble.update_layout(xaxis_title="在庫切迫度スコア (1.0=緊急)")
            st.plotly_chart(fig_bubble, use_container_width=True, key="strategy_bubble_map_unique")
        else:
            st.info("表示可能な戦略データがありません")

        st.markdown("#### 🏆 ペアリング利益ランキング")
        pairing_data = []
        for rec in optimal_strategy["recommendations"]:
            if rec["strategy"] == "bundle":
                h_name = rec['item_name']
                f_name = rec.get('partner_name', 'Unknown Flight')
                pairing_data.append({
                    "pair": f"{h_name}<br><span style='font-size:10px;color:#e2e8f0'>+ {f_name}</span>",
                    "gain": rec["gain"],
                    "text": f"+¥{rec['gain']:,}"
                })
        
        if pairing_data:
            # 利益順に並び替え (Plotlyの横棒は下から上へ描画されるため昇順ソート)
            pairing_data = sorted(pairing_data, key=lambda x: x["gain"])
            pairs = [p["pair"] for p in pairing_data]
            gains = [p["gain"] for p in pairing_data]
            texts = [p["text"] for p in pairing_data]

            fig_bar = go.Figure(go.Bar(
                x=gains,
                y=pairs,
                orientation='h',
                text=texts,
                textposition='outside',
                marker=dict(
                    color=gains,
                    colorscale='Emrld',
                    line=dict(color='rgba(0,0,0,0)', width=1)
                )
            ))
            dark_layout(fig_bar)
            fig_bar.update_layout(
                height=max(300, len(pairs) * 60 + 100),
                margin=dict(t=20, l=150, r=50, b=20),
                xaxis=dict(title="利益改善額 (円)", gridcolor="#1e293b", showgrid=True),
                yaxis=dict(title="", showgrid=False)
            )
            st.plotly_chart(fig_bar, use_container_width=True, key="strategy_bar_unique")
        else:
            st.info("ペアリングデータがありません")

    with col_kpi:
        st.markdown("#### 🛡 全体在庫救済率")
        rescued = rescue_metrics["rescued_units"]
        abandoned = rescue_metrics["total_units"] - rescued
        fig_donut = go.Figure(data=[go.Pie(
            labels=["救済済", "未売不可避"], values=[rescued, abandoned],
            hole=.6, marker_colors=["#10b981", "#1e293b"]
        )])
        fig_donut.update_layout(height=300, margin=dict(t=0, b=0, l=0, r=0))
        dark_layout(fig_donut)
        st.plotly_chart(fig_donut, use_container_width=True, key="strategy_donut_unique")
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">自動調整発動数</div>
            <div class="metric-value">{len([r for r in results if r.get('is_brake_active')])}</div>
        </div>
        """, unsafe_allow_html=True)

# 🧪 Tab 5: Custom Simulator
if selected_tab == "🧪 Custom Simulator":
    st.markdown("### 🧪 カスタム・シミュレーター（時系列シナリオ分析）")
    st.markdown('<p class="section-description">「今すぐパッケージで売り切る」vs「単品で粘る」の利益推移を描画し、在庫の価値が消える前に打つべき最適解を導き出します。</p>', unsafe_allow_html=True)
    
    # --- 1. 入力コントロールエリア ---
    with st.container():
        # ─── Step 1: 出発日選択（最上位フィルタ）───────────────────────
        # ホテルとフライト両方が存在する日付のみを選択肢に出す
        h_dates = set(filtered_inv_df[filtered_inv_df["item_type"]=="hotel"]["departure_date"].dropna().tolist())
        f_dates = set(filtered_inv_df[filtered_inv_df["item_type"]=="flight"]["departure_date"].dropna().tolist())
        common_dates = sorted(h_dates & f_dates)  # 両方に在庫がある日付のみ

        if not common_dates:
            st.warning("⚠️ ホテルとフライト両方の在庫がある出発日が見つかりません。")
            st.stop()

        # 表示ラベルを「M/D (YYYY-MM-DD)」形式に
        from datetime import datetime as _sim_dt
        def _fmt_date(d: str) -> str:
            try:
                return _sim_dt.strptime(d[:10], "%Y-%m-%d").strftime("%-m/%-d (%Y-%m-%d)")
            except Exception:
                return str(d)

        date_labels    = [_fmt_date(d) for d in common_dates]
        date_label_map = dict(zip(date_labels, common_dates))

        sel_date_label = st.selectbox(
            "📅 対象とする出発日を選択",
            date_labels,
            key="sim_date_sel",
            help="ホテルとフライト両方の在庫がある日付のみ表示されます"
        )
        selected_target_date = date_label_map[sel_date_label]

        # ─── Step 2 & 3: 出発日でフィルタした商品を選択 ─────────────────
        c_ctrl1, c_ctrl2 = st.columns([1, 1], gap="medium")
        with c_ctrl1:
            hotels_list = filtered_inv_df[
                (filtered_inv_df["item_type"]=="hotel") &
                (filtered_inv_df["departure_date"]==selected_target_date)
            ]
            if hotels_list.empty:
                st.warning("選択した日付のホテル在庫がありません。")
                st.stop()
            sel_h_display = st.selectbox("🏨 売り切りたいホテルを選択", hotels_list["display_name"].tolist(), key="sim_h_sel")
            target_hotel = hotels_list[hotels_list["display_name"]==sel_h_display].iloc[0]

        with c_ctrl2:
            flights_list = filtered_inv_df[
                (filtered_inv_df["item_type"]=="flight") &
                (filtered_inv_df["departure_date"]==selected_target_date)
            ]
            if flights_list.empty:
                st.warning("選択した日付のフライト在庫がありません。")
                st.stop()
            sel_f_display = st.selectbox("✈ 組み合わせるフライトを選択", flights_list["display_name"].tolist(), key="sim_f_sel")
            target_flight = flights_list[flights_list["display_name"]==sel_f_display].iloc[0]

    st.markdown("---")
    
    # パラメータ（グローバル調整）
    c_p1, c_p2 = st.columns([1, 1], gap="large")
    with c_p1:
        total_discount = st.slider("💰 パッケージ割引総額 (円)", 0, 20000, 8000, step=500, key="sim_discount")
    with c_p2:
        split_ratio = st.slider("🤝 割引負担の割合 (ホテル負担 %)", 0, 100, 80, help="ホテルの在庫が重い場合は、ホテルの負担を増やしてフライト側の利益（単品売上の期待値）を守ります。", key="sim_split")

    if target_hotel is not None and target_flight is not None:
        # --- 2. シミュレーションエンジンの実行 ---
        # A. 基礎データの取得
        f_pricing = next((r for r in results if r["inventory_id"] == target_flight["id"]), None)
        h_pricing = next((r for r in results if r["inventory_id"] == target_hotel["id"]), None)
        
        lead_days = f_pricing["lead_days"] or 30
        h_stock = target_hotel["remaining_stock"]
        f_stock = target_flight["remaining_stock"]
        
        h_cost = target_hotel["base_price"] * 0.7 # 仮の原価
        f_cost = target_flight["base_price"] * 0.7
        
        h_unit_profit_standalone = h_pricing["final_price"] - h_cost
        f_unit_profit_standalone = f_pricing["final_price"] - f_cost
        
        h_discount = total_discount * (split_ratio / 100)
        f_discount = total_discount * (1 - split_ratio / 100)

        # ─── パッケージ構成サマリーパネル ───────────────────────────────────────
        h_price = h_pricing["final_price"]
        f_price = f_pricing["final_price"]
        pkg_price_before_disc = h_price + f_price
        pkg_price_after_disc  = pkg_price_before_disc - total_discount

        st.markdown("#### 📊 選択中のコンビネーション概要")
        si_col1, si_col2, si_col3 = st.columns([2, 1, 1], gap="medium")

        with si_col1:
            st.markdown(f"""
            <div style='background:rgba(99,102,241,0.1); border:1px solid #6366f1; border-radius:12px; padding:15px;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:8px; letter-spacing:0.05em;'>ἄ8 パッケージ価格構成</div>
                <table style='width:100%; font-size:0.85rem; border-collapse:collapse;'>
                    <tr>
                        <td style='padding:4px 0; color:#e2e8f0;'>🏨 {target_hotel['name'][:20]}</td>
                        <td style='text-align:right; color:#e2e8f0;'>¥{h_price:,}</td>
                        <td style='text-align:right; color:#f87171; font-size:0.75rem;'>&nbsp;(-¥{int(h_discount):,})</td>
                    </tr>
                    <tr>
                        <td style='padding:4px 0; color:#e2e8f0;'>✈️ {target_flight['name'][:20]}</td>
                        <td style='text-align:right; color:#e2e8f0;'>¥{f_price:,}</td>
                        <td style='text-align:right; color:#f87171; font-size:0.75rem;'>&nbsp;(-¥{int(f_discount):,})</td>
                    </tr>
                    <tr style='border-top:1px solid #334155;'>
                        <td style='padding:8px 0 4px; color:#818cf8; font-weight:700;'>🎁 定価合計</td>
                        <td style='text-align:right; color:#818cf8; font-size:0.9rem; font-weight:600;'>¥{pkg_price_before_disc:,}</td>
                        <td></td>
                    </tr>
                    <tr>
                        <td style='padding:4px 0; color:#4ade80; font-weight:700;'>🏷️ 割引後パッケージ価格</td>
                        <td style='text-align:right; color:#4ade80; font-size:1.2rem; font-weight:900;'>¥{pkg_price_after_disc:,}</td>
                        <td></td>
                    </tr>
                </table>
            </div>
            """, unsafe_allow_html=True)

        with si_col2:
            h_stock_pct = int(h_stock / target_hotel['total_stock'] * 100) if target_hotel['total_stock'] else 0
            f_stock_pct = int(f_stock / target_flight['total_stock'] * 100) if target_flight['total_stock'] else 0
            st.markdown(f"""
            <div style='background:rgba(15,23,42,0.8); border:1px solid #1e293b; border-radius:12px; padding:15px; height:100%;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:10px; letter-spacing:0.05em;'>📦 現在の残件数</div>
                <div style='margin-bottom:10px;'>
                    <div style='font-size:0.75rem; color:#e2e8f0;'>🏨 ホテル</div>
                    <div style='font-size:1.4rem; font-weight:800; color:#e2e8f0;'>{h_stock}<span style='font-size:0.75rem; color:#e2e8f0;'> / {target_hotel['total_stock']}室</span></div>
                    <div style='background:#1e293b; border-radius:4px; height:6px; margin-top:4px;'>
                        <div style='background:#6366f1; height:6px; border-radius:4px; width:{h_stock_pct}%;'></div>
                    </div>
                    <div style='font-size:0.7rem; color:#cbd5e1; margin-top:2px;'>残存率 {h_stock_pct}%</div>
                </div>
                <div>
                    <div style='font-size:0.75rem; color:#e2e8f0;'>✈️ フライト</div>
                    <div style='font-size:1.4rem; font-weight:800; color:#e2e8f0;'>{f_stock}<span style='font-size:0.75rem; color:#e2e8f0;'> / {target_flight['total_stock']}席</span></div>
                    <div style='background:#1e293b; border-radius:4px; height:6px; margin-top:4px;'>
                        <div style='background:#6366f1; height:6px; border-radius:4px; width:{f_stock_pct}%;'></div>
                    </div>
                    <div style='font-size:0.7rem; color:#cbd5e1; margin-top:2px;'>残存率 {f_stock_pct}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with si_col3:
            st.markdown(f"""
            <div style='background:rgba(15,23,42,0.8); border:1px solid #1e293b; border-radius:12px; padding:15px; height:100%;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:10px; letter-spacing:0.05em;'>⏳ 出発まで {lead_days}日</div>
                <div style='margin-bottom:8px;'>
                    <div style='font-size:0.75rem; color:#e2e8f0;'>🪨 対象ホテル</div>
                    <div style='font-size:0.8rem; color:#e2e8f0;'>{target_hotel['name'][:18]}</div>
                    <div style='font-size:0.7rem; color:#cbd5e1;'>出発日: {target_hotel.get('departure_date', '---')}</div>
                </div>
                <div>
                    <div style='font-size:0.75rem; color:#e2e8f0;'>✈ 対象フライト</div>
                    <div style='font-size:0.8rem; color:#e2e8f0;'>{target_flight['name'][:18]}</div>
                    <div style='font-size:0.7rem; color:#cbd5e1;'>出発日: {target_flight.get('departure_date', '---')}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        
        # B. タイムライン計算 (Day 0 = 仕入日/シミュレーション開始, Day lead_days = 出発日)
        # 1. 販売開始日・出発日の特定 (ホテルとフライトのうち早い方等)
        dep_dt = pd.to_datetime(target_hotel.get("departure_date", "") or target_flight.get("departure_date", ""))
        
        # ─── X軸設計 ───────────────────────────────────────────────
        # 時間軸の定義 (t: 出発日までの残り日数)
        # ユーザー要望: 今日(lead_days日前)を左端、出発日(0日前)を右端にする。
        # days_x: グラフのX軸ラベル (YY/MM/DD)
        # days_t: 計算ロジック用 (lead_days, ..., 0)
        days_x = []
        for d in range(lead_days, -1, -1):
            days_x.append(f"D-{d}")
        # ---------------------------------------------------------
        # フェーズ27: 共通シミュレーションエンジンへの統合
        # ---------------------------------------------------------
        # 準備
        h_item_sim = {
            "id": target_hotel["id"],
            "remaining_stock": h_stock,
            "total_stock": target_hotel["total_stock"],
            "base_price": target_hotel["base_price"],
            "current_price": h_pricing["final_price"],
            "original_price": target_hotel.get("current_price", target_hotel["base_price"]),
            "cost": int(target_hotel["base_price"] * 0.7),
            "elasticity": target_hotel.get("elasticity", -1.5)
        }
        f_item_sim = {
            "id": target_flight["id"],
            "remaining_stock": f_stock,
            "total_stock": target_flight["total_stock"],
            "base_price": target_flight["base_price"],
            "current_price": f_pricing["final_price"],
            "original_price": target_flight.get("current_price", target_flight["base_price"]),
            "cost": int(target_flight["base_price"] * 0.7),
            "velocity_ratio": f_pricing.get("velocity_ratio") or 1.0,
            "elasticity": target_flight.get("elasticity", -1.5)
        }
        
        # 市場シナリオを取得
        market_condition = st.session_state.get("market_scenario", "base")
        
        # 共通関数呼び出し
        sim_res = simulate_sales_scenario(
            h_item_sim, f_item_sim, int(total_discount), lead_days, market_condition, reference_date=v_today
        )
        history = sim_res["history"]
        
        # グラフ用データの抽出
        days_x = [f"D-{h['day_idx']}" for h in history]
        scenario_a_revenue = [h["revenue_a"] for h in history]
        scenario_b_revenue = [h["revenue_b"] for h in history]
        potential_waste_a = [h["potential_waste_a"] for h in history]
        potential_waste_b = [h["potential_waste_b"] for h in history]

        # ─── 過去実績の集計 (販売開始日〜基準日) ───
        # 1. 販売開始日の特定 (ホテルとフライトのうち早い方)
        dep_dt = pd.to_datetime(target_hotel.get("departure_date", "") or target_flight.get("departure_date", ""))
        h_proc_str = target_hotel.get("procurement_date")
        f_proc_str = target_flight.get("procurement_date")
        if h_proc_str and f_proc_str:
            proc_dt = min(pd.to_datetime(h_proc_str), pd.to_datetime(f_proc_str))
        else:
            proc_dt = dep_dt - timedelta(days=90) # fail-safe
            
        v_today_dt = pd.to_datetime(v_today)
        
        # 過去日数の計算
        total_lead_days = (dep_dt.date() - proc_dt.date()).days
        past_days = (v_today_dt.date() - proc_dt.date()).days
        if past_days < 0:
            past_days = 0
            
        # 過去時系列用配列の初期化
        past_x = []
        past_revenue = []
        past_revenue_h = []
        past_revenue_f = []
        past_potential_waste = []
        
        # 過去イベントのフィルタリング（タイムゾーン影響を防ぐためDate型で比較）
        v_today_date = v_today_dt.date()
        
        if not all_events.empty:
            all_events["booked_date"] = pd.to_datetime(all_events["booked_at"]).dt.date
            past_events_h = all_events[(all_events["inventory_id"] == target_hotel["id"]) & (all_events["booked_date"] <= v_today_date)]
            past_events_f = all_events[(all_events["inventory_id"] == target_flight["id"]) & (all_events["booked_date"] <= v_today_date)]
        else:
            past_events_h = pd.DataFrame()
            past_events_f = pd.DataFrame()
        
        # 初期状態
        total_initial_cost = (target_hotel["total_stock"] * target_hotel["base_price"] * 0.7) + (target_flight["total_stock"] * target_flight["base_price"] * 0.7)
        cum_rev = 0
        cum_rev_h = 0
        cum_rev_f = 0
        current_h_stk = target_hotel["total_stock"]
        current_f_stk = target_flight["total_stock"]

        # 日次で集計ループ
        # d は 出発日までの残り日数 (total_lead_days -> lead_days)
        # つまり、古い日付から現在に向かって進むループにする必要がある
        
        # タイムゾーン等の影響を排除するため、イベント側の日付をDate型または文字列(YYYY-MM-DD)に前処理しておく
        if not past_events_h.empty:
            past_events_h = past_events_h.copy()
            past_events_h["booked_date_str"] = pd.to_datetime(past_events_h["booked_at"]).dt.strftime("%Y-%m-%d")
        if not past_events_f.empty:
            past_events_f = past_events_f.copy()
            past_events_f["booked_date_str"] = pd.to_datetime(past_events_f["booked_at"]).dt.strftime("%Y-%m-%d")

        for d in range(total_lead_days, lead_days, -1):
            current_date_dt = dep_dt - timedelta(days=d)
            current_date_str = current_date_dt.strftime("%Y-%m-%d")
            past_x.append(f"D-{d}")
            
            # その日の売上・消化を追加
            if not past_events_h.empty:
                day_sales_h = past_events_h[past_events_h["booked_date_str"] == current_date_str]
                sales_val_h = day_sales_h["sold_price"].sum()
                cum_rev += sales_val_h
                cum_rev_h += sales_val_h
                current_h_stk -= day_sales_h["quantity"].sum()
                
            if not past_events_f.empty:
                day_sales_f = past_events_f[past_events_f["booked_date_str"] == current_date_str]
                sales_val_f = day_sales_f["sold_price"].sum()
                cum_rev += sales_val_f
                cum_rev_f += sales_val_f
                current_f_stk -= day_sales_f["quantity"].sum()
                
            past_revenue.append(cum_rev)
            past_revenue_h.append(cum_rev_h)
            past_revenue_f.append(cum_rev_f)
            
            # 日次の含み損
            pw = (current_h_stk * target_hotel["base_price"] * 0.7) + (current_f_stk * target_flight["base_price"] * 0.7)
            past_potential_waste.append(pw)

        # ─── スライスされた履歴データと合体 ───
        # ※未来予測は、過去の最終日の売上を引き継ぐ必要があるためオフセットを加算
        offset_rev = past_revenue[-1] if past_revenue else 0
        offset_rev_h = past_revenue_h[-1] if past_revenue_h else 0
        offset_rev_f = past_revenue_f[-1] if past_revenue_f else 0

        scenario_a_revenue = [r + offset_rev for r in [h["revenue_a"] for h in history]]
        scenario_b_revenue = [r + offset_rev for r in [h["revenue_b"] for h in history]]
        scenario_n_revenue = [r + offset_rev for r in [h["revenue_n"] for h in history]]
        
        scenario_a_rev_h = [r + offset_rev_h for r in [h["revenue_a_h"] for h in history]]
        scenario_a_rev_f = [r + offset_rev_f for r in [h["revenue_a_f"] for h in history]]
        scenario_b_rev_h = [r + offset_rev_h for r in [h["revenue_b_h"] for h in history]]
        scenario_b_rev_f = [r + offset_rev_f for r in [h["revenue_b_f"] for h in history]]
        scenario_n_rev_h = [r + offset_rev_h for r in [h["revenue_n_h"] for h in history]]
        scenario_n_rev_f = [r + offset_rev_f for r in [h["revenue_n_f"] for h in history]]
        
        # 過去から未来へ線をはみ出さずシームレスに繋ぐためのブリッジ処理
        # full_x の生成の際、重複を防ぐため調整
        if past_x:
            days_x_bridged = [past_x[-1]] + days_x
            scenario_a_revenue = [past_revenue[-1]] + scenario_a_revenue
            scenario_b_revenue = [past_revenue[-1]] + scenario_b_revenue
            scenario_n_revenue = [past_revenue[-1]] + scenario_n_revenue
            
            scenario_a_rev_h = [past_revenue_h[-1]] + scenario_a_rev_h
            scenario_a_rev_f = [past_revenue_f[-1]] + scenario_a_rev_f
            scenario_b_rev_h = [past_revenue_h[-1]] + scenario_b_rev_h
            scenario_b_rev_f = [past_revenue_f[-1]] + scenario_b_rev_f
            scenario_n_rev_h = [past_revenue_h[-1]] + scenario_n_rev_h
            scenario_n_rev_f = [past_revenue_f[-1]] + scenario_n_rev_f
            
            potential_waste_a = [past_potential_waste[-1]] + potential_waste_a
            potential_waste_b = [past_potential_waste[-1]] + potential_waste_b
        else:
            days_x_bridged = days_x
        
        full_x = past_x + days_x
        full_rev_a = past_revenue + scenario_a_revenue[1:] if past_x else scenario_a_revenue
        full_rev_b = past_revenue + scenario_b_revenue[1:] if past_x else scenario_b_revenue
        
        full_rev_a_h = past_revenue_h + scenario_a_rev_h
        full_rev_a_f = past_revenue_f + scenario_a_rev_f
        full_rev_b_h = past_revenue_h + scenario_b_rev_h
        full_rev_b_f = past_revenue_f + scenario_b_rev_f

        full_waste_a = past_potential_waste + potential_waste_a
        full_waste_b = past_potential_waste + potential_waste_b
        
        # 総仕入原価ライン（固定）
        total_costs_line = [total_initial_cost] * len(full_x)

        # KPI用数値の抽出
        res_a = sim_res["profit_a"] + offset_rev # 修正：過去の利益（売上ー原価）を加味すべきだが、簡略化のため最終着地は全体の利益
        # ※正確な着地利益は = 総売上 - 総仕入原価 - 最終廃棄損 - 逸失利益
        final_revenue_a = full_rev_a[-1]
        final_revenue_b = full_rev_b[-1]
        final_waste_a = full_waste_a[-1]
        final_waste_b = full_waste_b[-1]
        
        total_cost_a = int((target_hotel["total_stock"] - history[-1]["h_stock_a"]) * h_item_sim["cost"]) + int((target_flight["total_stock"] - history[-1]["f_stock_a"]) * f_item_sim["cost"]) + int(offset_rev/2)
        
        # 利益指標の再計算
        res_a = final_revenue_a - total_initial_cost
        res_b = final_revenue_b - total_initial_cost - sim_res["details_b"]["discount_loss"] - sim_res["details_b"]["cannibal_loss"]

        total_sold_b_pkg = sim_res["packages_sold"]
        curr_b_h_stock = history[-1]["h_stock_b"] if history else h_stock
        flight_stock_b = history[-1]["f_stock_b"] if history else f_stock
        
        # 単品販売数の逆算
        total_sold_a = int(target_hotel["remaining_stock"] - curr_b_h_stock)
        total_sold_b_h_solo = max(0, int(target_hotel["remaining_stock"] - total_sold_b_pkg - curr_b_h_stock))
        total_sold_b_f_solo = max(0, int(target_flight["remaining_stock"] - total_sold_b_pkg - flight_stock_b))
        
        # 単品シナリオの在庫残
        # 簡易的に計算
        curr_a_h_stock = target_hotel["remaining_stock"] - total_sold_a
        flight_stock_a = target_flight["remaining_stock"] - total_sold_a
        
        # 旧変数との互換性
        vel_b_boosted = 2.5 * (1.0 + (total_discount / 10000.0))
        h_cost = h_item_sim["cost"]
        f_cost = f_item_sim["cost"]

        # --- 3. 視覚化 (Plotly) ---
        from plotly.subplots import make_subplots
        fig_sim = make_subplots(specs=[[{"secondary_y": True}]])

        # 総仕入原価（水平線）
        fig_sim.add_trace(go.Scatter(
            x=full_x, y=total_costs_line, name="総仕入原価 (損益分岐点)",
            line=dict(color='rgba(255,255,255,0.7)', width=2, dash='dash')
        ), secondary_y=False)

        # ─── 過去実績部分 ───
        if past_x:
            # 実績 ホテル単体
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue_h, name="🏨 累積売上実績 (ホテル)",
                line=dict(color='rgba(96, 165, 250, 0.6)', width=2) # blue-400
            ), secondary_y=False)
            # 実績 フライト単体
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue_f, name="✈️ 累積売上実績 (フライト)",
                line=dict(color='rgba(192, 132, 252, 0.6)', width=2) # purple-400
            ), secondary_y=False)
            # 実績 全体合算
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue, name="💰 累積売上実績 (全体合算)",
                line=dict(color='#cbd5e1', width=3)
            ), secondary_y=False)
            
            # 実績 含み損
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_potential_waste, name="含み廃棄損リスク (実績)",
                line=dict(color='#94a3b8', width=2, dash='dot')
            ), secondary_y=True)

        # ─── 未来予測部分 (シナリオN: ナイーブ・現状推移) ───
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_rev_h, name="🏨 予測売上 (現状推移・ホテル)",
            line=dict(color='rgba(148, 163, 184, 0.4)', width=2, dash='dot') # slate-400
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_rev_f, name="✈️ 予測売上 (現状推移・フライト)",
            line=dict(color='rgba(148, 163, 184, 0.4)', width=2, dash='dot') # slate-400
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_revenue, name="💰 予測売上 全体 (現状推移)",
            line=dict(color='rgba(148, 163, 184, 0.6)', width=2, dash='dash')
        ), secondary_y=False)

        # ─── 未来予測部分 (シナリオA: 単体維持) ───
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_a_rev_h, name="🏨 予測売上 (ホテル・シナリオA)",
            line=dict(color='rgba(248, 113, 113, 0.4)', width=2, dash='dot') # red-400
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_a_rev_f, name="✈️ 予測売上 (フライト・シナリオA)",
            line=dict(color='rgba(251, 146, 60, 0.4)', width=2, dash='dot') # orange-400
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_a_revenue, name="💰 予測売上 全体 (シナリオA)",
            line=dict(color='#f87171', width=3, dash='dot')
        ), secondary_y=False)

        # ─── 未来予測部分 (シナリオB: ハイブリッド) ───
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_b_rev_h, name="🏨 予測売上 (ホテル・シナリオB)",
            line=dict(color='rgba(52, 211, 153, 0.6)', width=2) # emerald-400
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_b_rev_f, name="✈️ 予測売上 (フライト・シナリオB)",
            line=dict(color='rgba(45, 212, 191, 0.6)', width=2) # teal-400
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_b_revenue, name="💰 予測売上 全体 (シナリオB)",
            line=dict(color='#4ade80', width=4)
        ), secondary_y=False)

        # 含み廃棄損 (未来予測 B)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=potential_waste_b, name="予測含み廃棄損 (シナリオB)",
            fill='tozeroy', fillcolor='rgba(74,222,128,0.1)',
            line=dict(color='#4ade80', width=2, dash='dot')
        ), secondary_y=True)

        # 基準日（V-Line）
        if past_x:
            fig_sim.add_vline(x=past_x[-1], line_width=2, line_dash="dash", line_color="#a78bfa")
            fig_sim.add_annotation(
                x=past_x[-1], y=1.0, yref="paper",
                text="本日 (実績/予測 境界)",
                showarrow=False,
                font=dict(color="#a78bfa", size=10),
                xanchor="right", yanchor="bottom"
            )

        # ─── その他の補助線（マイルストーン） ───
        # 例：D-30 (パッケージ用キャンセル無料終了の目安)
        d30_label = "D-30"
        if d30_label in full_x:
            fig_sim.add_vline(x=d30_label, line_width=1, line_dash="dot", line_color="rgba(148, 163, 184, 0.5)")
            fig_sim.add_annotation(
                x=d30_label, y=0.05, yref="paper",
                text="D-30",
                showarrow=False,
                font=dict(color="rgba(148, 163, 184, 0.8)", size=10),
                xanchor="left", yanchor="bottom"
            )
            
        # 例：D-14 (単品航空券需要ピークなど)
        d14_label = "D-14"
        if d14_label in full_x:
            fig_sim.add_vline(x=d14_label, line_width=1, line_dash="dot", line_color="rgba(148, 163, 184, 0.5)")
            fig_sim.add_annotation(
                x=d14_label, y=0.05, yref="paper",
                text="D-14",
                showarrow=False,
                font=dict(color="rgba(148, 163, 184, 0.8)", size=10),
                xanchor="left", yanchor="bottom"
            )

        # レイアウト調整
        dark_layout(fig_sim, secondary_y=True)
        fig_sim.update_layout(
            title="P/L 予測シミュレーション（実績＋将来予測）",
            xaxis=dict(
                title="タイムライン（右端 = 期限・出発日 D-0）",
                gridcolor="#1e293b",
                dtick=10 if len(full_x) > 30 else 5
            ),
            hovermode="x unified",
            height=500
        )
        # 左右の軸個別設定
        max_y_candidates = [total_initial_cost]
        if full_rev_a: max_y_candidates.append(max(full_rev_a))
        if full_rev_b: max_y_candidates.append(max(full_rev_b))
        if scenario_n_revenue: max_y_candidates.append(max(scenario_n_revenue))
        max_y = max(max_y_candidates) * 1.2
        
        fig_sim.update_yaxes(title_text="累積金額 (円)", secondary_y=False, range=[0, max_y], gridcolor="#1e293b", tickformat=",d")
        fig_sim.update_yaxes(title_text="含み廃棄損 (円)", secondary_y=True, range=[0, max_y], gridcolor="rgba(0,0,0,0)", showticklabels=False, tickformat=",d")

        st.plotly_chart(fig_sim, use_container_width=True, key="sim_timeseries_chart")
        
        # --- 4. 決着 KPI ---
        # 利益指標は上で再計算された res_a, res_b を利用するため不要な代入を削除
        diff = res_b - res_a
        
        st.markdown("#### 🏁 予測結果・着地点比較（Day 0 廃棄損計上済み）")
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            st.markdown(f"""
            <div style='background:rgba(248,113,113,0.1); border:1px solid #f87171; border-radius:12px; padding:15px; text-align:center;'>
                <div style='font-size:0.8rem; color:#f87171;'>① 単品で粘る場合の着地点</div>
                <div style='font-size:1.5rem; font-weight:800;'>¥{int(res_a):,}</div>
                <div style='font-size:0.8rem; margin-top:10px;'>🏨 販売: {int(total_sold_a)}室 / 売れ残り: {int(curr_a_h_stock)}室</div>
                <div style='font-size:0.8rem;'>✈️ 販売: {int(f_stock - flight_stock_a)}席 / 売れ残り: {int(flight_stock_a)}席</div>
            </div>
            """, unsafe_allow_html=True)
        with ck2:
            h_sold_b_total = int(total_sold_b_pkg + total_sold_b_h_solo)
            f_sold_b_total = int(total_sold_b_pkg + total_sold_b_f_solo)
            h_unsold_b = int(curr_b_h_stock)
            f_unsold_b = int(flight_stock_b)
            st.markdown(f"""
            <div style='background:rgba(74,222,128,0.1); border:1px solid #4ade80; border-radius:12px; padding:15px; text-align:center;'>
                <div style='font-size:0.8rem; color:#4ade80;'>② ハイブリッド化の理想着地点</div>
                <div style='font-size:1.5rem; font-weight:800;'>¥{int(res_b):,}</div>
                <div style='font-size:0.75rem; color:#4ade80; margin-top:8px;'>📦 パッケージ: {int(total_sold_b_pkg)}組</div>
                <div style='font-size:0.8rem; margin-top:4px;'>🏨 販売: {h_sold_b_total}室（単品切替{int(total_sold_b_h_solo)}室）/ 売れ残り: {h_unsold_b}室</div>
                <div style='font-size:0.8rem;'>✈️ 販売: {f_sold_b_total}席（単品切替{int(total_sold_b_f_solo)}席）/ 売れ残り: {f_unsold_b}席</div>
            </div>
            """, unsafe_allow_html=True)
        with ck3:
            st.markdown(f"""
            <div style='background:rgba(167,139,250,0.2); border:1px solid #a78bfa; border-radius:12px; padding:15px; text-align:center; box-shadow: 0 0 15px rgba(167,139,250,0.3);'>
                <div style='font-size:0.8rem; color:#a78bfa;'>トータル収益改善の見込み</div>
                <div style='font-size:1.5rem; font-weight:900;'>+¥{int(diff):,}</div>
                <div style='font-size:0.8rem; margin-top:10px;'>（リスク回避後の純増利益）</div>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown(f"""
        <div style='background:rgba(30,27,75,0.4); border:1px solid rgba(167,139,250,0.4); border-radius:10px; padding:15px; margin-top:20px; margin-bottom:20px;'>
            <h5 style='margin-top:0;'>💡 AI 戦略アドバイス</h5>
            <p style='font-size:0.9rem; color:#e2e8f0;'>
                シナリオAでは <b>{int(curr_a_h_stock)}個</b> の売れ残りが発生し、仕入原価 <b>¥{int(curr_a_h_stock * h_cost):,}</b> が丸損となる予測です。<br>
                パッケージ化（シナリオB）では販売速度を <b>{vel_b_boosted:.1f}件/日</b> まで引き上げることで、売れ残り数を <b>{int(curr_b_h_stock)}個</b> まで圧縮します。
                フライトのカニバリゼーションを考慮しても、この在庫リスク回避が <b>¥{int(diff):,}</b> の利益貢献につながります。
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # --- 5. P/L マトリクスと詳細明細表 ---
        st.markdown("#### 📊 シミュレーション詳細明細")
        tab_pl, tab_breakdown, tab_params = st.tabs(["① 全体P/L比較マトリクス", "② 商材別 売上・ロス内訳", "③ シミュレーション前提条件"])
        
        det_a = sim_res["details_a"]
        det_b = sim_res["details_b"]
        par = sim_res["params"]
        
        with tab_pl:
            st.markdown("シナリオA（単品維持）とシナリオB（ハイブリッド戦略）の収支構造の違いを比較します。")
            pl_data = [
                {"項目": "① 総売上額", "シナリオA": f"¥{det_a['revenue']:,}", "シナリオB": f"¥{det_b['revenue']:,}", "差分 (B - A)": f"¥{det_b['revenue'] - det_a['revenue']:,}"},
                {"項目": "② 仕入原価 (販売分・廃棄分合計)", "シナリオA": f"-¥{det_a['cost'] + det_a['waste']:,}", "シナリオB": f"-¥{det_b['cost'] + det_b['waste']:,}", "差分 (B - A)": f"¥{(det_a['cost'] + det_a['waste']) - (det_b['cost'] + det_b['waste']):,}"},
                {"項目": "③ 廃棄損 (売れ残り分)", "シナリオA": f"-¥{det_a['waste']:,}", "シナリオB": f"-¥{det_b['waste']:,}", "差分 (B - A)": f"¥{det_a['waste'] - det_b['waste']:,} (ロス回避)"},
                {"項目": "④ 各種割引・逸失利益等", "シナリオA": "¥0", "シナリオB": f"-¥{det_b['discount_loss'] + det_b['cannibal_loss']:,}", "差分 (B - A)": f"-¥{det_b['discount_loss'] + det_b['cannibal_loss']:,}"},
                {"項目": "⭐ 最終着地利益", "シナリオA": f"¥{res_a:,}", "シナリオB": f"¥{res_b:,}", "差分 (B - A)": f"¥{res_b - res_a:,}"},
            ]
            st.dataframe(pd.DataFrame(pl_data), use_container_width=True, hide_index=True)

        with tab_breakdown:
            st.markdown("**シナリオB（ハイブリッド戦略稼働時）**の、商材ごとの販売実績とロスの内訳です。")
            bd_data = [
                {
                    "商材": "🏨 " + target_hotel["name"], 
                    "合計販売数": f"{int(total_sold_b_pkg + total_sold_b_h_solo)}室",
                    "うちPKG販売": f"{int(total_sold_b_pkg)}セット",
                    "売れ残り数": f"{int(curr_b_h_stock)}室",
                    "売上貢献": f"¥{det_b['revenue_pkg'] // 2 + det_b['revenue_h_solo']:,} (推計)", 
                    "廃棄損(コスト)": f"¥{det_b['waste_h']:,}"
                },
                {
                    "商材": "✈️ " + target_flight["name"], 
                    "合計販売数": f"{int(total_sold_b_pkg + total_sold_b_f_solo)}席",
                    "うちPKG販売": f"{int(total_sold_b_pkg)}セット",
                    "売れ残り数": f"{int(flight_stock_b)}席",
                    "売上貢献": f"¥{det_b['revenue_pkg'] // 2 + det_b['revenue_f_solo']:,} (推計)", 
                    "廃棄損(コスト)": f"¥{det_b['waste_f']:,}"
                }
            ]
            st.dataframe(pd.DataFrame(bd_data), use_container_width=True, hide_index=True)
            if det_b['cannibal_loss'] > 0:
                st.caption(f"※ フライトはパッケージに取られたことによる機会損失（動的カニバリゼーションロス）額 **¥{det_b['cannibal_loss']:,}** も計算に加味されています。")

        with tab_params:
            st.markdown("本シミュレーションを決定づけている裏側の計算パラメータ（カンペ）です。")
            param_data = [
                {"パラメータ名": "ホテルの価格弾力性", "現在値": f"{h_item_sim['elasticity']}", "説明": "価格変更に対する需要の敏感さ（負の数値が小さいほど値上げに強い）"},
                {"パラメータ名": "フライトの価格弾力性", "現在値": f"{f_item_sim['elasticity']}", "説明": "同上"},
                {"パラメータ名": "ホテル基本販売ペース", "現在値": f"{par['vel_a_base']:.2f} 件/日", "説明": "現在の時価と同条件で単品販売した場合の、直近の1日あたり販売速度"},
                {"パラメータ名": "PKG化による加速ペース", "現在値": f"{par['vel_b_boosted']:.2f} 件/日", "説明": "パッケージ化と割引によってブーストされた販売速度。この速度で売れ残りを消化します"},
                {"パラメータ名": "動的カニバリゼーション係数", "現在値": f"{par['dynamic_cannibal_rate'] * 100:.1f} %", "説明": "フライトがPKGに使われたことで「単品のフライト需要」が食い潰される損失割合"}
            ]
            st.dataframe(pd.DataFrame(param_data), use_container_width=True, hide_index=True)

    else:
        st.info("比較対象となるホテルとフライトをそれぞれ選択してください。")

# ══════════════════════════════════════════════════════════════════
# Footer & Logs
# ══════════════════════════════════════════════════════════════════
last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(f'<p style="color:#e2e8f0;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>', unsafe_allow_html=True)
