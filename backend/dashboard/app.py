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



# ─── ヘッダー ──────────────────────────────────────────────────────
st.markdown("""
<h1>🔍 Explainable Pricing Dashboard</h1>
<p style='color:#64748b; margin-top:-12px; margin-bottom:20px;'>
  価格の根拠を可視化し、アルゴリズムのブラックボックス化を防ぐ —
  <span style='color:#a78bfa'>White-box Pricing Engine</span>
</p>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────
# Sidebar - Global Settings & Forecast Scenario & AI Command Center
# ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🌐 全体設定")
    selected_scenario = st.radio(
        "需要予測シナリオ (Market Condition)",
        ["base", "pessimistic", "optimistic"],
        format_func=lambda x: "ベース (Base)" if x=="base" else ("切迫・悲観 (Pessimistic: 0.7x)" if x=="pessimistic" else "好調・楽観 (Optimistic: 1.3x)"),
        help="ダッシュボード全体の予測値（着地点、ブッキングカーブ延伸、シミュレーター初期値）に影響します。"
    )
    st.session_state["market_scenario"] = selected_scenario
    
    st.markdown("---")
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
    if st.button("🔄 データを再読み込み"):
        st.cache_data.clear()
        st.rerun()

# ─── データロード ─────────────────────────────────────────────────
inv_df     = load_inventory()
history_df = load_history()

if inv_df.empty:
    st.error("⚠️ 在庫データが見つかりません。`python init_db.py` を先に実行してください。")
    st.stop()

# ─── 出発日フィルタ実装 ───────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.markdown("### 📅 出発日・宿泊日フィルタ")
    all_dates = sorted(inv_df["departure_date"].dropna().unique().tolist())
    selected_dates = st.multiselect(
        "表示対象の日程を選択",
        all_dates,
        default=all_dates,
        help="選択した日程の在庫のみを分析・表示の対象にします。"
    )

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

# フィルタリング後の ID リスト
target_ids = filtered_inv_df["id"].tolist()

results = get_pricing_results(filtered_inv_df, config=ai_config)
log_price_history(results, DB_PATH)
history_df = load_history() # 履歴を再読み込みして最新化

# 履歴データもフィルタリング
if not history_df.empty:
    history_df = history_df[history_df["inventory_id"].isin(target_ids)]

# ─── パッケージエンジン読み込み（全タブ共通） ─────────────────────
curr_scenario = st.session_state.get("market_scenario", "base")
try:
    roi_metrics = calculate_roi_metrics(inventory_ids=target_ids)
    rescue_metrics = calculate_inventory_rescue_metrics(inventory_ids=target_ids)
    
    # --- Prescriptive Analytics (Phase 14 / Phase 27) ---
    # AI現在価格（時価）をマッピングしてエンジンに渡す
    current_prices = {r["inventory_id"]: r["final_price"] for r in results}
    optimal_strategy = calculate_optimal_strategy(
        scenario=curr_scenario, 
        inventory_ids=target_ids,
        current_prices=current_prices
    )
except Exception as _e:
    packages = []
    roi_metrics = {"lift": 0, "lift_pct": 0, "total_fixed": 0, "total_dynamic": 0, "daily_data": []}
    rescue_metrics = {"overall_rescue_rate": 0, "rescued_units": 0, "hotel_rescue_rate": 0, "total_units": 0}
    optimal_strategy = {"recommendations": [], "total_standalone_profit": 0, "total_optimized_profit": 0, "ai_impact": 0}
    _pkg_err = str(_e)
    st.warning(f"分析エンジンの初期化に失敗しました: {_pkg_err}")


# ─── 4タブ（統合版） ──────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Executive Summary",
    "🔍 Analysis & Tracking",
    "📦 Strategy Map",
    "🧪 Custom Simulator"
])


# ══════════════════════════════════════════════════════════════════
# Step 1: 【観察】エグゼクティブ・サマリ (Observe)
# ══════════════════════════════════════════════════════════════════
with tab1:
    render_alerts(results, filtered_inv_df, [], get_velocity_ratio)

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
        <div style="font-size:0.85rem; color:#94a3b8; text-transform:uppercase; letter-spacing:0.15em; margin-bottom:6px;">
            💡 AI最適化インパクト — シナリオ: {scenario_label}
        </div>
        <div style="display:flex; gap:30px; align-items:center; flex-wrap:wrap;">
            <div style="flex:1; min-width:160px;">
                <div style="font-size:0.75rem; color:#94a3b8; margin-bottom:4px;">現状維持（全単品）の予測利益</div>
                <div style="font-size:1.5rem; font-weight:800; color:#e2e8f0;">¥{total_sa:,}</div>
            </div>
            <div style="font-size:2rem; color:#a78bfa;">→</div>
            <div style="flex:1; min-width:160px;">
                <div style="font-size:0.75rem; color:#94a3b8; margin-bottom:4px;">AI推奨プラン実行後の予測利益</div>
                <div style="font-size:1.5rem; font-weight:800; color:#10b981;">¥{total_opt:,}</div>
            </div>
            <div style="flex:1.5; min-width:200px; background:rgba(16,185,129,0.1); border-radius:12px; padding:16px; text-align:center; border:1px solid rgba(16,185,129,0.3);">
                <div style="font-size:0.75rem; color:#94a3b8; margin-bottom:4px;">📈 利益改善見込み</div>
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
                <div style="font-size:0.85rem; color:#94a3b8;">{rec['reason']}</div>
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
                    <span style="color:#94a3b8; font-size:0.85rem;">現行価格: ¥{rec['optimal_price']:,}</span>
                    <div style="width:100%; font-size:0.8rem; color:#64748b; margin-top:4px;">{rec['reason']}</div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("---")

    # --- [NEW] 需要予測・着地点セクション ---
    curr_scenario = st.session_state.get("market_scenario", "base")
    st.markdown("### 🔮 ビジネス着地点予測 (End-of-Term Forecast)")
    st.markdown(f'<p class="section-description">※選択中のシナリオ: <b>{curr_scenario.upper()}</b> に基づく Day 0 までの予測</p>', unsafe_allow_html=True)
    
    # 全商品の予測を集計
    total_expected_profit = 0
    total_unsold = 0
    for r in results:
        inv = inv_df[inv_df["id"] == r["inventory_id"]].iloc[0]
        # 原価（cost）を base_price * 0.5 と仮定した簡易コスト算出
        forecast = calculate_demand_forecast(r["inventory_id"], r["lead_days"], int(inv["remaining_stock"]), int(inv["total_stock"]), r["base_price"], int(r["base_price"]*0.5))
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

    st.markdown("---")
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
            dark_layout(fig_roi, "累積売上の推移", yaxis_title="累積売上 (円)")
            # 2本のラインが近い場合に差異を見やすくするため、Y軸の範囲を自動調整（0から開始しない）
            fig_roi.update_layout(yaxis=dict(rangemode='tozero')) # 累積なので0は含めるがズームは許容
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
    st.markdown(f'<p style="color:#475569;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>',
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# Tab 2: Analysis & Tracking (旧ドリルダウン + ライブ動向)
# ══════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 🔍 Analysis & Tracking")
    render_alerts(results, filtered_inv_df, [], get_velocity_ratio)

    # --- 共通の商品選択エリア (ライブリストを兼ねる) ---
    st.markdown("#### 🚚 商品一覧 & 異常検知")
    
    # 簡易テーブルの作成
    table_data = []
    for r in results:
        inv_matches = filtered_inv_df[filtered_inv_df["id"] == r["inventory_id"]]
        if inv_matches.empty: continue
        inv = inv_matches.iloc[0]
        try:
            vr = get_velocity_ratio(r["inventory_id"], int(inv["total_stock"]), int(inv["remaining_stock"]), r["lead_days"])
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
    
    st.dataframe(table_df, use_container_width=True, hide_index=True)
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
        p_elast       = min(abs(r_sel["final_price"] - r_sel["base_price"]) / r_sel["base_price"], 1.0) if r_sel["base_price"] > 0 else 0.0
        try:
            vr_k = get_velocity_ratio(r_sel["inventory_id"], int(inv_sel["total_stock"]), int(inv_sel["remaining_stock"]), r_sel["lead_days"])
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
        st.markdown(f'<div class="reason-box">{r_sel["reason"]}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # 価格形成 WF とブッキングカーブ
    col_wf, col_curve = st.columns(2)
    with col_wf:
        st.markdown("#### 🌊 価格形成プロセス")
        wf_labels = ["在庫調整", "時期調整", "速度調整", "合計調整"]
        # 簡易調整額の算出
        vel_adj = r_sel['final_price'] - (r_sel['base_price'] + r_sel['inventory_adjustment'] + r_sel['time_adjustment'])
        wf_values = [r_sel["inventory_adjustment"], r_sel["time_adjustment"], vel_adj, (r_sel['final_price'] - r_sel['base_price'])]
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
        if not item_events.empty:
            item_events["cum_sales"] = item_events["quantity"].cumsum()
            fig_curve = go.Figure()
            fig_curve.add_trace(go.Scatter(
                x=item_events["booked_at"], y=item_events["cum_sales"],
                mode="lines+markers", line=dict(color="#a78bfa", width=3),
                fill="tozeroy", fillcolor="rgba(167,139,250,0.1)"
            ))
            dark_layout(fig_curve)
            st.plotly_chart(fig_curve, use_container_width=True, key="tracking_curve_chart_unique")
        else:
            st.info("販売データがありません")
# 🪟 Tab 3: Strategy Map
with tab3:
    st.markdown("### 📦 Strategy Map")
    render_alerts(results, filtered_inv_df, [], get_velocity_ratio)

    col_map, col_kpi = st.columns([2, 1], gap="large")
    
    with col_map:
        st.markdown("#### 🗺 パッケージ・シナジー・マップ")
        # バブルチャートで「在庫切迫度」x「利益改善額」を可視化
        bubble_data = []
        for rec in optimal_strategy["recommendations"]:
            if rec["strategy"] == "bundle":
                bubble_data.append({
                    "name": rec["item_name"],
                    "urgency": -rec["gain"] / 1000, # 仮の軸
                    "lift": rec["gain"],
                    "score": 40
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
            st.plotly_chart(fig_bubble, use_container_width=True, key="strategy_bubble_map_unique")
        else:
            st.info("表示可能な戦略データがありません")

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

# 🧪 Tab 4: Custom Simulator
with tab4:
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
                        <td style='padding:4px 0; color:#94a3b8;'>🏨 {target_hotel['name'][:20]}</td>
                        <td style='text-align:right; color:#e2e8f0;'>¥{h_price:,}</td>
                        <td style='text-align:right; color:#f87171; font-size:0.75rem;'>&nbsp;(-¥{int(h_discount):,})</td>
                    </tr>
                    <tr>
                        <td style='padding:4px 0; color:#94a3b8;'>✈️ {target_flight['name'][:20]}</td>
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
                    <div style='font-size:0.75rem; color:#94a3b8;'>🏨 ホテル</div>
                    <div style='font-size:1.4rem; font-weight:800; color:#e2e8f0;'>{h_stock}<span style='font-size:0.75rem; color:#94a3b8;'> / {target_hotel['total_stock']}室</span></div>
                    <div style='background:#1e293b; border-radius:4px; height:6px; margin-top:4px;'>
                        <div style='background:#6366f1; height:6px; border-radius:4px; width:{h_stock_pct}%;'></div>
                    </div>
                    <div style='font-size:0.7rem; color:#64748b; margin-top:2px;'>残存率 {h_stock_pct}%</div>
                </div>
                <div>
                    <div style='font-size:0.75rem; color:#94a3b8;'>✈️ フライト</div>
                    <div style='font-size:1.4rem; font-weight:800; color:#e2e8f0;'>{f_stock}<span style='font-size:0.75rem; color:#94a3b8;'> / {target_flight['total_stock']}席</span></div>
                    <div style='background:#1e293b; border-radius:4px; height:6px; margin-top:4px;'>
                        <div style='background:#6366f1; height:6px; border-radius:4px; width:{f_stock_pct}%;'></div>
                    </div>
                    <div style='font-size:0.7rem; color:#64748b; margin-top:2px;'>残存率 {f_stock_pct}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with si_col3:
            st.markdown(f"""
            <div style='background:rgba(15,23,42,0.8); border:1px solid #1e293b; border-radius:12px; padding:15px; height:100%;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:10px; letter-spacing:0.05em;'>⏳ 出発まで {lead_days}日</div>
                <div style='margin-bottom:8px;'>
                    <div style='font-size:0.75rem; color:#94a3b8;'>🪨 対象ホテル</div>
                    <div style='font-size:0.8rem; color:#e2e8f0;'>{target_hotel['name'][:18]}</div>
                    <div style='font-size:0.7rem; color:#64748b;'>出発日: {target_hotel.get('departure_date', '---')}</div>
                </div>
                <div>
                    <div style='font-size:0.75rem; color:#94a3b8;'>✈ 対象フライト</div>
                    <div style='font-size:0.8rem; color:#e2e8f0;'>{target_flight['name'][:18]}</div>
                    <div style='font-size:0.7rem; color:#64748b;'>出発日: {target_flight.get('departure_date', '---')}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        
        # B. タイムライン計算 (Day 0 = 仕入日/シミュレーション開始, Day lead_days = 出発日)
        # ─── X軸設計 ───────────────────────────────────────────────
        # 時間軸の定義 (t: 出発日までの残り日数)
        # ユーザー要望: 今日(lead_days日前)を左端、出発日(0日前)を右端にする。
        # days_x: グラフのX軸ラベル (lead_days, ..., 0)
        # days_t: 計算ロジック用 (lead_days, ..., 0)
        # autorange="reversed" を使うため、x=lead_days が左、x=0 が右にプロットされる。
        days_x = list(range(lead_days, -1, -1))
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
            "cost": int(target_hotel["base_price"] * 0.7),
        }
        f_item_sim = {
            "id": target_flight["id"],
            "remaining_stock": f_stock,
            "total_stock": target_flight["total_stock"],
            "base_price": target_flight["base_price"],
            "current_price": f_pricing["final_price"],
            "cost": int(target_flight["base_price"] * 0.7),
            "velocity_ratio": f_pricing.get("velocity_ratio", 1.0)
        }
        
        # 市場シナリオを取得
        market_condition = st.session_state.get("market_scenario", "base")
        
        # 共通関数呼び出し
        sim_res = simulate_sales_scenario(
            h_item_sim, f_item_sim, int(total_discount), lead_days, market_condition
        )
        history = sim_res["history"]
        
        # グラフ用データの抽出
        days_x = [f"D-{h['day_idx']}" for h in history]
        asset_value = [h["h_stock_b"] * h_item_sim["cost"] * h["decay_factor"] for h in history]
        scenario_a_profit = [h["profit_a"] for h in history]
        scenario_b_profit = [h["profit_b"] for h in history]

        # KPI用数値の抽出
        res_a = sim_res["profit_a"]
        res_b = sim_res["profit_b"]
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

        # --- 3. 視覚化 (Plotly / Dual Y-axis) ---
        # days_x = 0→lead_days (昇順) でそのままプロット
        # autorange="reversed" は使わない（X軸を「時間の経過」として左→右に流す）
        from plotly.subplots import make_subplots
        fig_sim = make_subplots(specs=[[{"secondary_y": True}]])

        # 資産価値（副軸: 右）
        fig_sim.add_trace(go.Scatter(
            x=days_x, y=asset_value, name="在庫の資産価値（含み損リスク）",
            fill='tozeroy', fillcolor='rgba(148,163,184,0.1)',
            line=dict(color='#94a3b8', width=2, dash='dot')
        ), secondary_y=True)

        # シナリオA
        fig_sim.add_trace(go.Scatter(
            x=days_x, y=scenario_a_profit, name="シナリオA：単品で粘る",
            line=dict(color='#f87171', width=3)
        ), secondary_y=False)

        # シナリオB (ハイブリッド)
        fig_sim.add_trace(go.Scatter(
            x=days_x, y=scenario_b_profit, name="シナリオB：今すぐハイブリッド（パッケージ後単品切替）",
            line=dict(color='#4ade80', width=4)
        ), secondary_y=False)

        # レイアウト調整
        dark_layout(fig_sim, secondary_y=True)
        fig_sim.update_layout(
            title="出発日までの利益予測シミュレーション",
            xaxis=dict(
                title="タイムライン（右端 = D-0 出発当日）",
                gridcolor="#1e293b",
                ticksuffix="日前",
                dtick=1 if lead_days <= 14 else (2 if lead_days <= 30 else 5)
            ),
            hovermode="x unified",
            height=500
        )
        # 左右の軸個別設定
        fig_sim.update_yaxes(title_text="累積利益 (円)", secondary_y=False, autorange=True, fixedrange=False, gridcolor="#1e293b")
        fig_sim.update_yaxes(
            title_text="在庫資産価値 (円)", 
            secondary_y=True, 
            range=[0, max(asset_value) * 1.1 if asset_value else 1000000],
            fixedrange=False, 
            gridcolor="rgba(0,0,0,0)"
        )

        st.plotly_chart(fig_sim, use_container_width=True, key="sim_timeseries_chart")
        
        # --- 4. 決着 KPI ---
        res_a = scenario_a_profit[-1]
        res_b = scenario_b_profit[-1]
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
        <div style='background:rgba(30,27,75,0.4); border:1px solid rgba(167,139,250,0.4); border-radius:10px; padding:15px; margin-top:20px;'>
            <h5 style='margin-top:0;'>💡 AI 戦略アドバイス</h5>
            <p style='font-size:0.9rem; color:#e2e8f0;'>
                シナリオAでは <b>{int(curr_a_h_stock)}個</b> の売れ残りが発生し、仕入原価 <b>¥{int(curr_a_h_stock * h_cost):,}</b> が丸損となる予測です。<br>
                パッケージ化（シナリオB）では販売速度を <b>{vel_b_boosted:.1f}件/日</b> まで引き上げることで、売れ残り数を <b>{int(curr_b_h_stock)}個</b> まで圧縮します。
                フライトのカニバリゼーションを考慮しても、この在庫リスク回避が <b>¥{int(diff):,}</b> の利益貢献につながります。
            </p>
        </div>
        """, unsafe_allow_html=True)

    else:
        st.info("比較対象となるホテルとフライトをそれぞれ選択してください。")

# ══════════════════════════════════════════════════════════════════
# Footer & Logs
# ══════════════════════════════════════════════════════════════════
last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(f'<p style="color:#94a3b8;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>', unsafe_allow_html=True)
