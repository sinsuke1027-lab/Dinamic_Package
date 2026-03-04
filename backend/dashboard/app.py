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
from pricing_engine import calculate_inventory_decay_factor, calculate_pricing_result
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
    min_date_val = datetime.now(timezone.utc).date() - timedelta(days=90) # デフォルト安全値
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
    # 最終的な着地利益 ＝ (過去の実績売上 ＋ 未販売在庫の予測売上) － (全在庫の仕入原価)
    total_expected_profit = 0
    total_unsold = 0
    
    total_past_revenue = 0
    total_full_cost = 0
    total_future_revenue = 0

    all_events = load_booking_events()

    for r in results:
        inv = filtered_inv_df[filtered_inv_df["id"] == r["inventory_id"]].iloc[0]
        cost = int(r["base_price"] * 0.9) # 原価率90%
        total_full_cost += int(inv["total_stock"] * cost)

        # 過去の実績売上（選択された日付フィルタに関わらず、Virtual Todayまでの売上を計上）
        if not all_events.empty:
            past_events = all_events[(all_events["inventory_id"] == r["inventory_id"]) & (pd.to_datetime(all_events["booked_at"]).dt.date <= v_today)]
            if not past_events.empty:
                total_past_revenue += past_events["sold_price"].sum()

        # 未来の予測売上（原価を0として売上だけ取得する。利益計算は全体で行うため）
        forecast = calculate_demand_forecast(r["inventory_id"], r["lead_days"], int(inv["remaining_stock"]), int(inv["total_stock"]), r["base_price"], 0, reference_date=v_today)
        
        # expected_profit は ここでは原価0を渡しているので「未来の売上額」となる
        total_future_revenue += forecast[curr_scenario]["expected_profit"]
        total_unsold += forecast[curr_scenario]["unsold_stock"]

    total_expected_profit = total_past_revenue + total_future_revenue - total_full_cost

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
    
    # ─── 自動最適割引額の事前計算 ───
    auto_discount_amt = 8000
    if target_hotel is not None and target_flight is not None:
        try:
            from packaging_engine import find_optimal_bundle_discount
            # dfからの抽出値は辞書相当の振る舞いをするため、必要なキーを辞書化して渡す
            h_cost = int(target_hotel["base_price"] * 0.9)
            f_cost = int(target_flight["base_price"] * 0.9)
            
            # f_pricing を一時計算してVR等を取得
            f_pricing = next((r for r in results if r["inventory_id"] == target_flight["id"]), None)
            from packaging_engine import get_velocity_ratio
            lead_days_search = (datetime.fromisoformat(str(target_flight.get("departure_date"))).date() - v_today).days if target_flight.get("departure_date") else 30
            
            mock_h = {
                "id": target_hotel["id"],
                "current_price": next((r["final_price"] for r in results if r["inventory_id"] == target_hotel["id"]), target_hotel["base_price"]),
                "base_price": target_hotel["base_price"],
                "lead_days": max(1, lead_days_search),
                "remaining_stock": target_hotel["remaining_stock"],
                "total_stock": target_hotel["total_stock"],
                "cost": h_cost,
                "elasticity": target_hotel.get("elasticity", -1.5)
            }
            mock_f = {
                "id": target_flight["id"],
                "current_price": next((r["final_price"] for r in results if r["inventory_id"] == target_flight["id"]), target_flight["base_price"]),
                "base_price": target_flight["base_price"],
                "lead_days": max(1, lead_days_search),
                "remaining_stock": target_flight["remaining_stock"],
                "total_stock": target_flight["total_stock"],
                "cost": f_cost,
                "velocity_ratio": get_velocity_ratio(target_flight["id"], int(target_flight["total_stock"]), int(target_flight["remaining_stock"]), max(1, lead_days_search), reference_date=v_today) or 1.0,
                "elasticity": target_flight.get("elasticity", -1.5)
            }
            
            market_condition = st.session_state.get("market_scenario", "base")
            optimal_disc, _ = find_optimal_bundle_discount(mock_h, mock_f, market_condition, reference_date=v_today)
            auto_discount_amt = optimal_disc
        except Exception as e:
            auto_discount_amt = 8000

    # パラメータ（グローバル調整）
    c_p1, c_p2 = st.columns([1, 1], gap="large")
    with c_p1:
        st.markdown(f"<div style='margin-bottom: -15px;'><span style='background:rgba(56,189,248,0.2); color:#38bdf8; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;'>✨ AI事前探索</span> <span style='font-size:0.8rem; color:#cbd5e1;'>このペアの利益が最大化する割引額は <b>¥{auto_discount_amt:,}</b> です</span></div>", unsafe_allow_html=True)
        # sliderのkeyをホテル・フライト・基準日の識別子ベースにすることで、条件が変わったときに毎回新しいsliderとして認識させ、初期値を強制適用する
        v_today_str = v_today.strftime("%Y%m%d") if hasattr(v_today, 'strftime') else str(v_today)
        slider_key = f"sim_discount_{target_hotel['id']}_{target_flight['id']}_{v_today_str}"
        total_discount = st.slider("💰 パッケージ割引総額 (円)", 0, 20000, int(auto_discount_amt), step=100, key=slider_key)
    with c_p2:
        st.markdown("<div style='margin-bottom: 5px; height:0px;'>&nbsp;</div>", unsafe_allow_html=True)
        split_ratio = st.slider("🤝 割引負担の割合 (ホテル負担 %)", 0, 100, 80, help="ホテルの在庫が重い場合は、ホテルの負担を増やしてフライト側の利益（単品売上の期待値）を守ります。", key="sim_split")

    if target_hotel is not None and target_flight is not None:
        # --- 2. シミュレーションエンジンの実行 ---
        # A. 基礎データの取得
        f_pricing = next((r for r in results if r["inventory_id"] == target_flight["id"]), None)
        h_pricing = next((r for r in results if r["inventory_id"] == target_hotel["id"]), None)
        
        lead_days = f_pricing["lead_days"] or 30

        # ─── 過去実績の集計 (販売開始日〜基準日) ───
        # ※ 未来シミュレーションの初期在庫パラメーターを正しく設定するため、シミュレーション実行前に過去実績を計算します。
        dep_dt = pd.to_datetime(target_hotel.get("departure_date", "") or target_flight.get("departure_date", ""))
        
        try:
            h_proc_dt = pd.to_datetime(target_hotel.get("procurement_date"))
            h_lead = (dep_dt.date() - h_proc_dt.date()).days
        except Exception:
            h_lead = 90
            
        try:
            f_proc_dt = pd.to_datetime(target_flight.get("procurement_date"))
            f_lead = (dep_dt.date() - f_proc_dt.date()).days
        except Exception:
            f_lead = 90

        total_lead_days = max(h_lead, f_lead)
        v_today_dt = pd.to_datetime(v_today)
        v_today_date = v_today_dt.date()
            
        past_x = []
        past_revenue = []
        past_revenue_h = []
        past_revenue_f = []
        past_h_stock = []
        past_f_stock = []
        
        if not all_events.empty:
            all_events["booked_date"] = pd.to_datetime(all_events["booked_at"]).dt.date
            past_events_h = all_events[(all_events["inventory_id"] == target_hotel["id"]) & (all_events["booked_date"] <= v_today_date)]
            past_events_f = all_events[(all_events["inventory_id"] == target_flight["id"]) & (all_events["booked_date"] <= v_today_date)]
        else:
            past_events_h = pd.DataFrame()
            past_events_f = pd.DataFrame()
        
        total_initial_cost = (target_hotel["total_stock"] * target_hotel["base_price"] * 0.9) + (target_flight["total_stock"] * target_flight["base_price"] * 0.9)
        cum_rev = 0
        cum_rev_h = 0
        cum_rev_f = 0
        current_h_stk = target_hotel["total_stock"]
        current_f_stk = target_flight["total_stock"]

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
            
            if d <= h_lead:
                if not past_events_h.empty:
                    day_sales_h = past_events_h[past_events_h["booked_date_str"] == current_date_str]
                    sales_val_h = day_sales_h["sold_price"].sum()
                    cum_rev += sales_val_h
                    cum_rev_h += sales_val_h
                    current_h_stk -= day_sales_h["quantity"].sum()
                past_revenue_h.append(cum_rev_h)
                past_h_stock.append(int(current_h_stk))
            else:
                past_revenue_h.append(None)
                past_h_stock.append(None)
                
            if d <= f_lead:
                if not past_events_f.empty:
                    day_sales_f = past_events_f[past_events_f["booked_date_str"] == current_date_str]
                    sales_val_f = day_sales_f["sold_price"].sum()
                    cum_rev += sales_val_f
                    cum_rev_f += sales_val_f
                    current_f_stk -= day_sales_f["quantity"].sum()
                past_revenue_f.append(cum_rev_f)
                past_f_stock.append(int(current_f_stk))
            else:
                past_revenue_f.append(None)
                past_f_stock.append(None)
                
            if d <= max(h_lead, f_lead):
                past_revenue.append(cum_rev)
            else:
                past_revenue.append(None)

        # UI表示およびシミュレーション引き渡し用の残在庫を、過去実績の最終値に更新
        def get_last_valid(lst):
            for item in reversed(lst):
                if item is not None:
                    return item
            return 0
            
        # DB上のズレを防ぐため、実績がない場合はDB値を利用
        h_stock = get_last_valid(past_h_stock) if past_x and get_last_valid(past_h_stock) > 0 else target_hotel["remaining_stock"]
        f_stock = get_last_valid(past_f_stock) if past_x and get_last_valid(past_f_stock) > 0 else target_flight["remaining_stock"]
        
        h_cost = target_hotel["base_price"] * 0.9 # 仮の原価
        f_cost = target_flight["base_price"] * 0.9
        
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
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:8px; letter-spacing:0.05em;'>📦 パッケージ価格構成</div>
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
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:10px; letter-spacing:0.05em;'>📦 現在の残件数 (基準日時点)</div>
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
        # 市場シナリオを取得
        market_condition = st.session_state.get("market_scenario", "base")
        
        # 1. ルールベースのシミュレーション
        h_pricing_rule = calculate_pricing_result(
            inventory_id=target_hotel["id"],
            name=target_hotel["name"],
            base_price=target_hotel["base_price"],
            total_stock=target_hotel["total_stock"],
            remaining_stock=h_stock,
            departure_date=target_hotel.get("departure_date"),
            elasticity=target_hotel.get("elasticity", -1.5),
            reference_date=v_today,
            strategy="rule_based"
        )
        f_pricing_rule = calculate_pricing_result(
            inventory_id=target_flight["id"],
            name=target_flight["name"],
            base_price=target_flight["base_price"],
            total_stock=target_flight["total_stock"],
            remaining_stock=f_stock,
            departure_date=target_flight.get("departure_date"),
            elasticity=target_flight.get("elasticity", -1.5),
            reference_date=v_today,
            strategy="rule_based"
        )
        h_item_sim_rule = {
            "id": target_hotel["id"],
            "remaining_stock": h_stock,
            "total_stock": target_hotel["total_stock"],
            "base_price": target_hotel["base_price"],
            "current_price": h_pricing_rule["final_price"],
            "original_price": target_hotel.get("current_price", target_hotel["base_price"]),
            "cost": int(target_hotel["base_price"] * 0.9),
            "elasticity": target_hotel.get("elasticity", -1.5)
        }
        f_item_sim_rule = {
            "id": target_flight["id"],
            "remaining_stock": f_stock,
            "total_stock": target_flight["total_stock"],
            "base_price": target_flight["base_price"],
            "current_price": f_pricing_rule["final_price"],
            "original_price": target_flight.get("current_price", target_flight["base_price"]),
            "cost": int(target_flight["base_price"] * 0.9),
            "velocity_ratio": f_pricing_rule.get("velocity_ratio") or 1.0,
            "elasticity": target_flight.get("elasticity", -1.5)
        }
        sim_rule = simulate_sales_scenario(
            h_item_sim_rule, f_item_sim_rule, int(total_discount), lead_days, market_condition, reference_date=v_today
        )

        # 2. 需要予測ベースのシミュレーション
        h_pricing_demand = calculate_pricing_result(
            inventory_id=target_hotel["id"],
            name=target_hotel["name"],
            base_price=target_hotel["base_price"],
            total_stock=target_hotel["total_stock"],
            remaining_stock=h_stock,
            departure_date=target_hotel.get("departure_date"),
            elasticity=target_hotel.get("elasticity", -1.5),
            reference_date=v_today,
            strategy="demand_based"
        )
        f_pricing_demand = calculate_pricing_result(
            inventory_id=target_flight["id"],
            name=target_flight["name"],
            base_price=target_flight["base_price"],
            total_stock=target_flight["total_stock"],
            remaining_stock=f_stock,
            departure_date=target_flight.get("departure_date"),
            elasticity=target_flight.get("elasticity", -1.5),
            reference_date=v_today,
            strategy="demand_based"
        )
        h_item_sim_demand = h_item_sim_rule.copy()
        h_item_sim_demand["current_price"] = h_pricing_demand["final_price"]
        f_item_sim_demand = f_item_sim_rule.copy()
        f_item_sim_demand["current_price"] = f_pricing_demand["final_price"]
        f_item_sim_demand["velocity_ratio"] = f_pricing_demand.get("velocity_ratio") or 1.0
        sim_demand = simulate_sales_scenario(
            h_item_sim_demand, f_item_sim_demand, int(total_discount), lead_days, market_condition, reference_date=v_today
        )

        st.markdown("#### 📈 P/L 予測シミュレーション（実績＋将来予測）")
        
        # グラフ描画用シナリオの切り替え
        selected_sim_scenario = st.radio(
            "比較する予測シナリオを選択",
            ["ルールベースのプライシング戦略", "需要予測ハイブリッド"],
            horizontal=True,
            key="sim_display_scenario"
        )
        is_hybrid = selected_sim_scenario == "需要予測ハイブリッド"
        
        sim_res = sim_demand if is_hybrid else sim_rule
        history_selected = sim_res["history"]
        history_baseline = sim_rule["history"] # ベースラインの在庫減は共通(naive)
        


        # ─── 未来シナリオの抽出 ───
        # ベースライン (シナリオ N: 共通)
        scenario_n_revenue = [h["revenue_n"] for h in history_baseline]
        scenario_n_revenue_h = [h["revenue_n_h"] for h in history_baseline]
        scenario_n_revenue_f = [h["revenue_n_f"] for h in history_baseline]
        scenario_n_h_stock = [h["h_stock_a"] for h in history_baseline]
        scenario_n_f_stock = [h["f_stock_a"] for h in history_baseline]
        
        # 選択されたシナリオ (is_hybrid なら B=ハイブリッド, そうでなければ A=固定じゃないルールベース単品)
        selected_revenue = [h["revenue_b"] if is_hybrid else h["revenue_a"] for h in history_selected]
        selected_revenue_h = [h["revenue_b_h"] if is_hybrid else h["revenue_a_h"] for h in history_selected]
        selected_revenue_f = [h["revenue_b_f"] if is_hybrid else h["revenue_a_f"] for h in history_selected]
        selected_h_stock = [h["h_stock_b"] if is_hybrid else h["h_stock_a"] for h in history_selected]
        selected_f_stock = [h["f_stock_b"] if is_hybrid else h["f_stock_a"] for h in history_selected]

        # ─── スライスされた履歴データと合体 ───
            
        offset_rev = get_last_valid(past_revenue)
        offset_rev_h = get_last_valid(past_revenue_h)
        offset_rev_f = get_last_valid(past_revenue_f)

        scenario_n_revenue = [r + offset_rev for r in scenario_n_revenue]
        scenario_n_revenue_h = [r + offset_rev_h for r in scenario_n_revenue_h]
        scenario_n_revenue_f = [r + offset_rev_f for r in scenario_n_revenue_f]
        
        selected_revenue = [r + offset_rev for r in selected_revenue]
        selected_revenue_h = [r + offset_rev_h for r in selected_revenue_h]
        selected_revenue_f = [r + offset_rev_f for r in selected_revenue_f]
        
        # 過去から未来へ線をはみ出さずシームレスに繋ぐためのブリッジ処理
        if past_x:
            days_x_bridged = [past_x[-1]] + days_x
            scenario_n_revenue = [get_last_valid(past_revenue)] + scenario_n_revenue
            scenario_n_revenue_h = [get_last_valid(past_revenue_h)] + scenario_n_revenue_h
            scenario_n_revenue_f = [get_last_valid(past_revenue_f)] + scenario_n_revenue_f
            
            selected_revenue = [get_last_valid(past_revenue)] + selected_revenue
            selected_revenue_h = [get_last_valid(past_revenue_h)] + selected_revenue_h
            selected_revenue_f = [get_last_valid(past_revenue_f)] + selected_revenue_f
            
            # 在庫は絶対値として返ってきているため、過去ログの最終日と未来予測の初日をそのまま繋ぐ
            # (ただし、描画上で線が途切れないように、過去の最終日=未来の0日目前を挟み込む)
            scenario_n_h_stock = [get_last_valid(past_h_stock)] + scenario_n_h_stock
            scenario_n_f_stock = [get_last_valid(past_f_stock)] + scenario_n_f_stock
            selected_h_stock = [get_last_valid(past_h_stock)] + selected_h_stock
            selected_f_stock = [get_last_valid(past_f_stock)] + selected_f_stock
        else:
            days_x_bridged = days_x
        
        full_x = past_x + days_x
        full_rev_n = past_revenue + scenario_n_revenue[1:] if past_x else scenario_n_revenue
        full_rev_sel = past_revenue + selected_revenue[1:] if past_x else selected_revenue
        
        # 在庫のフル履歴も、ブリッジ済みの未来配列の[1:]以降を過去実績の末尾に結合する
        full_h_stock_sel = past_h_stock + selected_h_stock[1:] if past_x else selected_h_stock
        full_f_stock_sel = past_f_stock + selected_f_stock[1:] if past_x else selected_f_stock
        full_h_stock_n = past_h_stock + scenario_n_h_stock[1:] if past_x else scenario_n_h_stock
        full_f_stock_n = past_f_stock + scenario_n_f_stock[1:] if past_x else scenario_n_f_stock

        # 総仕入原価ライン（固定）
        total_costs_line = [total_initial_cost] * len(full_x)

        # KPI用数値の抽出
        final_revenue_n = full_rev_n[-1]
        final_revenue_sel = full_rev_sel[-1]
        
        final_waste_n = (full_h_stock_n[-1] * h_item_sim_rule["cost"]) + (full_f_stock_n[-1] * f_item_sim_rule["cost"])
        final_waste_sel = (full_h_stock_sel[-1] * h_item_sim_rule["cost"]) + (full_f_stock_sel[-1] * f_item_sim_rule["cost"])
        
        # 利益指標の再計算 (Cash Profit: 単純に最終売上 - 総仕入原価)
        res_n = final_revenue_n - total_initial_cost
        res_sel = final_revenue_sel - total_initial_cost

        total_sold_b_pkg = sim_res["packages_sold"] if is_hybrid else 0
        curr_b_h_stock = history_selected[-1]["h_stock_b" if is_hybrid else "h_stock_a"] if history_selected else h_stock
        flight_stock_b = history_selected[-1]["f_stock_b" if is_hybrid else "f_stock_a"] if history_selected else f_stock
        
        # シミュレーション期間中の販売数の逆算 (= シミュレーション開始時点の在庫 - 最終日の在庫)
        curr_n_h_stock_fin = full_h_stock_n[-1]
        curr_n_f_stock_fin = full_f_stock_n[-1]
        
        total_sold_n_h = int(h_stock - curr_n_h_stock_fin)
        total_sold_n_f = int(f_stock - curr_n_f_stock_fin)
        
        total_sold_sel_h_solo = max(0, int(h_stock - total_sold_b_pkg - curr_b_h_stock))
        total_sold_sel_f_solo = max(0, int(f_stock - total_sold_b_pkg - flight_stock_b))
        
        vel_b_boosted = 2.5 * (1.0 + (total_discount / 10000.0))
        h_cost = h_item_sim_rule["cost"]
        f_cost = f_item_sim_rule["cost"]

        # --- 3. 視覚化 (Plotly) ---
        from plotly.subplots import make_subplots
        
        # 在庫数から割合(%)への変換処理
        def to_pct(stock_list, total):
            return [(s / total * 100) if s is not None else None for s in stock_list]
            
        past_h_stock_pct = to_pct(past_h_stock, target_hotel["total_stock"])
        past_f_stock_pct = to_pct(past_f_stock, target_flight["total_stock"])
        
        scenario_n_h_stock_pct = to_pct(scenario_n_h_stock, target_hotel["total_stock"])
        scenario_n_f_stock_pct = to_pct(scenario_n_f_stock, target_flight["total_stock"])
        selected_h_stock_pct = to_pct(selected_h_stock, target_hotel["total_stock"])
        selected_f_stock_pct = to_pct(selected_f_stock, target_flight["total_stock"])

        fig_sim = make_subplots(specs=[[{"secondary_y": True}]])

        # 総仕入原価（水平線）
        fig_sim.add_trace(go.Scatter(
            x=full_x, y=total_costs_line, name="総仕入原価 (損益分岐点)",
            line=dict(color='rgba(255,255,255,0.7)', width=2, dash='dash')
        ), secondary_y=False)

        # ─── 過去実績部分 (売上 - 左軸) ───
        if past_x:
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue, name="💰 累積売上実績 (全体合算)",
                line=dict(color='#cbd5e1', width=3)
            ), secondary_y=False)
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue_h, name="💰 累積売上実績 (ホテル)",
                line=dict(color='rgba(148, 163, 184, 0.7)', width=2, dash='dot')
            ), secondary_y=False)
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue_f, name="💰 累積売上実績 (フライト)",
                line=dict(color='rgba(148, 163, 184, 0.7)', width=2, dash='dot')
            ), secondary_y=False)

        # ─── 過去実績部分 (残在庫割合 - 右軸) ───
        if past_x:
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_h_stock_pct, name="🏨 残室割合実績 (ホテル)",
                line=dict(color='rgba(96, 165, 250, 0.6)', width=2, dash='dot')
            ), secondary_y=True)
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_f_stock_pct, name="✈️ 残席割合実績 (フライト)",
                line=dict(color='rgba(192, 132, 252, 0.6)', width=2, dash='dot')
            ), secondary_y=True)

        # ─── 未来予測部分 (共通ベースライン: 現状維持・固定価格) ───
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_revenue, name="💰 予測売上 全体 (現状維持: 固定価格)",
            line=dict(color='rgba(148, 163, 184, 0.6)', width=2, dash='dash')
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_revenue_h, name="💰 予測売上 ホテル (現状維持)",
            line=dict(color='rgba(148, 163, 184, 0.4)', width=1, dash='dash')
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_revenue_f, name="💰 予測売上 フライト (現状維持)",
            line=dict(color='rgba(148, 163, 184, 0.4)', width=1, dash='dash')
        ), secondary_y=False)

        # ─── 未来予測部分 (残在庫 ベースライン) ───
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_h_stock_pct, name="🏨 予測残室割合 (現状維持)",
            line=dict(color='rgba(148, 163, 184, 0.4)', width=1, dash='dot')
        ), secondary_y=True)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=scenario_n_f_stock_pct, name="✈️ 予測残席割合 (現状維持)",
            line=dict(color='rgba(148, 163, 184, 0.4)', width=1, dash='dot')
        ), secondary_y=True)

        # ─── 未来予測部分 (選択された戦略) ───
        if is_hybrid:
            line_color_rev = '#4ade80' # emerald-400
            line_color_rev_sub = 'rgba(74, 222, 128, 0.5)'
            line_color_h = 'rgba(52, 211, 153, 0.9)'
            line_color_f = 'rgba(45, 212, 191, 0.9)'
            name_rev = "💰 予測売上 全体 (需要予測ハイブリッド)"
            name_rev_h = "💰 予測売上 ホテル (需要予測ハイブリッド)"
            name_rev_f = "💰 予測売上 フライト (需要予測ハイブリッド)"
            name_h = "🏨 予測残室割合 (需要予測ハイブリッド)"
            name_f = "✈️ 予測残席割合 (需要予測ハイブリッド)"
        else:
            line_color_rev = '#f87171' # red-400
            line_color_rev_sub = 'rgba(248, 113, 113, 0.5)'
            line_color_h = 'rgba(248, 113, 113, 0.9)'
            line_color_f = 'rgba(251, 146, 60, 0.9)'  # orange-400
            name_rev = "💰 予測売上 全体 (ルールベース)"
            name_rev_h = "💰 予測売上 ホテル (ルールベース)"
            name_rev_f = "💰 予測売上 フライト (ルールベース)"
            name_h = "🏨 予測残室割合 (ルールベース)"
            name_f = "✈️ 予測残席割合 (ルールベース)"
            
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=selected_revenue, name=name_rev,
            line=dict(color=line_color_rev, width=4)
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=selected_revenue_h, name=name_rev_h,
            line=dict(color=line_color_rev_sub, width=2, dash='solid')
        ), secondary_y=False)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=selected_revenue_f, name=name_rev_f,
            line=dict(color=line_color_rev_sub, width=2, dash='solid')
        ), secondary_y=False)

        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=selected_h_stock_pct, name=name_h,
            line=dict(color=line_color_h, width=2, dash='solid')
        ), secondary_y=True)
        fig_sim.add_trace(go.Scatter(
            x=days_x_bridged, y=selected_f_stock_pct, name=name_f,
            line=dict(color=line_color_f, width=2, dash='solid')
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
        if full_rev_n: max_y_candidates.append(max(full_rev_n))
        if full_rev_sel: max_y_candidates.append(max(full_rev_sel))
        max_y = max(max_y_candidates) * 1.2
        
        max_stock = max(target_hotel["total_stock"], target_flight["total_stock"]) * 1.05

        fig_sim.update_yaxes(title_text="累積金額 (円)", secondary_y=False, range=[0, max_y], gridcolor="#1e293b", tickformat=",d")
        fig_sim.update_yaxes(title_text="残在庫割合 (%)", secondary_y=True, range=[0, 105], gridcolor="rgba(0,0,0,0)", tickformat=".1f")

        st.plotly_chart(fig_sim, use_container_width=True, key="sim_timeseries_chart")
        
        # --- 4. 決着 KPI ---
        diff = res_sel - res_n
        
        st.markdown("#### 🏁 予測結果・着地点比較（Day 0 廃棄損計上済み）")
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            st.markdown(f"""
            <div style='background:rgba(148, 163, 184, 0.1); border:1px solid #94a3b8; border-radius:12px; padding:15px; text-align:center;'>
                <div style='font-size:0.8rem; color:#94a3b8;'>① 現状維持 (固定価格・何もしない) の着地点</div>
                <div style='font-size:1.5rem; font-weight:800; color:#e2e8f0;'>¥{int(res_n):,}</div>
                <div style='font-size:0.8rem; margin-top:10px; color:#cbd5e1;'>🏨 販売: {int(total_sold_n_h)}室 / 売れ残り: {int(curr_n_h_stock_fin)}室</div>
                <div style='font-size:0.8rem; color:#cbd5e1;'>✈️ 販売: {int(total_sold_n_f)}席 / 売れ残り: {int(curr_n_f_stock_fin)}席</div>
            </div>
            """, unsafe_allow_html=True)
        with ck2:
            h_sold_sel_total = int(total_sold_b_pkg + total_sold_sel_h_solo)
            f_sold_sel_total = int(total_sold_b_pkg + total_sold_sel_f_solo)
            h_unsold_sel = int(curr_b_h_stock)
            f_unsold_sel = int(flight_stock_b)
            
            box_bg = "rgba(74,222,128,0.1)" if is_hybrid else "rgba(248,113,113,0.1)"
            box_bc = "#4ade80" if is_hybrid else "#f87171"
            title = "② 需要予測ハイブリッドの理想着地点" if is_hybrid else "② ルールベース・プライシングの着地点"
            st.markdown(f"""
            <div style='background:{box_bg}; border:1px solid {box_bc}; border-radius:12px; padding:15px; text-align:center;'>
                <div style='font-size:0.8rem; color:{box_bc};'>{title}</div>
                <div style='font-size:1.5rem; font-weight:800;'>¥{int(res_sel):,}</div>
                <div style='font-size:0.75rem; color:{box_bc}; margin-top:8px;'>📦 パッケージ: {int(total_sold_b_pkg)}組</div>
                <div style='font-size:0.8rem; margin-top:4px;'>🏨 販売: {h_sold_sel_total}室（単品切替{int(total_sold_sel_h_solo)}室）/ 売れ残り: {h_unsold_sel}室</div>
                <div style='font-size:0.8rem;'>✈️ 販売: {f_sold_sel_total}席（単品切替{int(total_sold_sel_f_solo)}席）/ 売れ残り: {f_unsold_sel}席</div>
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
                現状維持(単品販売)のままではホテルに <b>{int(curr_n_h_stock_fin)}室</b> の売れ残りが発生し、仕入原価 <b>¥{int(curr_n_h_stock_fin * h_cost):,}</b> 分が丸損となる予測です。<br>
                戦略適用後には販売速度を <b>{vel_b_boosted:.1f}件/日</b> まで引き上げることで、売れ残り数を <b>{int(h_unsold_sel)}室</b> まで圧縮し、機会損失を最小化します。
                結果としてトータルの利益着地点が <b>¥{int(diff):,}</b> 改善される見込みです。
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
            
            # P/L詳細の表示も全体の最終売上等を反映する
            det_n_rev = final_revenue_n
            det_sel_rev = final_revenue_sel
            
            # 各シナリオの実質的な原価（売れた分の原価＋廃棄になった分の原価）は「総仕入原価と同じ」
            pl_data = [
                {"項目": "① 累計総売上額", "現状維持": f"¥{int(det_n_rev):,}", "選択戦略": f"¥{int(det_sel_rev):,}", "差分 (戦略 - 現状)": f"¥{int(det_sel_rev - det_n_rev):,}"},
                {"項目": "② 総仕入原価 (固定)", "現状維持": f"-¥{int(total_initial_cost):,}", "選択戦略": f"-¥{int(total_initial_cost):,}", "差分 (戦略 - 現状)": "¥0"},
                {"項目": "③ 内、廃棄損 (売れ残り分)", "現状維持": f"(-¥{int(final_waste_n):,})", "選択戦略": f"(-¥{int(final_waste_sel):,})", "差分 (戦略 - 現状)": f"¥{int(final_waste_n - final_waste_sel):,} (ロス回避)"},
                {"項目": "⭐ 最終着地利益 (① + ②)", "現状維持": f"¥{int(res_n):,}", "選択戦略": f"¥{int(res_sel):,}", "差分 (戦略 - 現状)": f"¥{int(diff):,}"},
                {"項目": "※ 参考: パッケージ割引還元総額", "現状維持": "¥0", "選択戦略": f"¥{int(sim_res['details_b'].get('discount_loss', 0)):,}", "差分 (戦略 - 現状)": f"¥{int(sim_res['details_b'].get('discount_loss', 0)):,}"},
            ]
            st.dataframe(pd.DataFrame(pl_data), use_container_width=True, hide_index=True)

        with tab_breakdown:
            title_bd = "**シナリオB（需要予測ハイブリッド戦略）**" if is_hybrid else "**シナリオA（ルールベース・プライシング戦略）**"
            st.markdown(f"{title_bd}の、商材ごとの販売実績とロスの内訳です。")
            
            det_sel = sim_res["details_b"] if is_hybrid else sim_res["details_a"]
            
            bd_data = [
                {
                    "商材": "🏨 " + target_hotel["name"], 
                    "合計販売数": f"{h_sold_sel_total}室",
                    "うちPKG販売": f"{int(total_sold_b_pkg)}セット",
                    "売れ残り数": f"{h_unsold_sel}室",
                    "売上貢献": f"¥{det_sel.get('revenue_pkg', 0) // 2 + det_sel.get('revenue_h_solo', det_sel.get('revenue_h', 0)):,} (推計)", 
                    "廃棄損(コスト)": f"¥{det_sel.get('waste_h', 0):,}"
                },
                {
                    "商材": "✈️ " + target_flight["name"], 
                    "合計販売数": f"{f_sold_sel_total}席",
                    "うちPKG販売": f"{int(total_sold_b_pkg)}セット",
                    "売れ残り数": f"{f_unsold_sel}席",
                    "売上貢献": f"¥{det_sel.get('revenue_pkg', 0) // 2 + det_sel.get('revenue_f_solo', det_sel.get('revenue_f', 0)):,} (推計)", 
                    "廃棄損(コスト)": f"¥{det_sel.get('waste_f', 0):,}"
                }
            ]
            st.dataframe(pd.DataFrame(bd_data), use_container_width=True, hide_index=True)
            if is_hybrid and det_sel.get('cannibal_loss', 0) > 0:
                st.caption(f"※ フライトはパッケージに取られたことによる機会損失（動的カニバリゼーションロス）額 **¥{det_sel['cannibal_loss']:,}** も計算に加味されています。")

        with tab_params:
            st.markdown("本シミュレーションを決定づけている裏側の計算パラメータ（カンペ）です。")
            param_data = [
                {"パラメータ名": "ホテルの価格弾力性", "現在値": f"{h_item_sim_rule['elasticity']}", "説明": "価格変更に対する需要の敏感さ（負の数値が小さいほど値上げに強い）"},
                {"パラメータ名": "フライトの価格弾力性", "現在値": f"{f_item_sim_rule['elasticity']}", "説明": "同上"},
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
