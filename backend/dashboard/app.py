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
import copy
import random
import math
from datetime import date, datetime, timezone, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── 設定 ────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "inventory.db")

import sys as _sys
import importlib
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import constants
importlib.reload(constants)

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
from constants import (
    MAX_DISCOUNT_PCT, MAX_MARKUP_PCT, 
    BRAKE_THRESHOLD, BRAKE_STRENGTH_PCT,
    DEFAULT_RULE_INV_PREMIUM_PCT, DEFAULT_RULE_INV_HIGH_PCT, DEFAULT_RULE_INV_DISCOUNT_PCT,
    DEFAULT_RULE_TIME_LAST_MIN_PCT, DEFAULT_RULE_TIME_PEAK_PCT, DEFAULT_RULE_TIME_EARLY_PCT,
    DEFAULT_DECAY_K, DEFAULT_DECAY_P,
    FORECAST_MULTIPLIERS,
    INV_THRESHOLD_PREMIUM, INV_THRESHOLD_HIGH, INV_THRESHOLD_NORMAL,
    TIME_THRESHOLD_LAST_MIN, TIME_THRESHOLD_PEAK, TIME_THRESHOLD_NORMAL,
    SCORE_WEIGHT_MAPE, SCORE_WEIGHT_LIFT, SCORE_WEIGHT_SPOILAGE, SCORE_WEIGHT_DIR_ACC,
    DEFAULT_COST_RATIO,
    CLASS_POPULAR_THRESHOLD, CLASS_NICHE_DAYS, CLASS_NICHE_RATIO,
    SIM_FINAL_SPRINT_DAYS, SIM_MARKUP_STEP_HIGH_PCT, SIM_MARKUP_STEP_LOW_PCT,
    SIM_MARKDOWN_STEP_HIGH_PCT, SIM_MARKDOWN_STEP_LOW_PCT, SIM_FORECAST_BOOST_PCT,
    SIM_ELASTICITY_PRICE_RATIO_HIGH_THRES, SIM_ELASTICITY_PRICE_RATIO_LOW_THRES,
    SIM_ELASTICITY_DAMPEN_PCT, SIM_ELASTICITY_AMPLIFY_PCT
)
# 共通ユーティリティのインポート
from dashboard.theme import Theme
from dashboard.utils import (
    apply_custom_css, light_layout, render_metric_card, render_alerts, hex_to_rgba, log_price_history, light_dataframe
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
    import sys, os
    if "model_evaluator" in sys.modules:
        del sys.modules["model_evaluator"]
    if "pricing_engine" in sys.modules:
        del sys.modules["pricing_engine"]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from pricing_engine import calculate_pricing_result
    from model_evaluator import get_product_classification, get_model_setting
    
    results = []
    for _, row in inv_df.iterrows():
        inv_id = int(row["id"])
        item_type = row["item_type"]
        
        # ─── 商品カテゴリ別の個別保存モデルの優先適用（Per-Product Override） ───
        applied_strategy = strategy
        applied_config = config
        
        cls_data = get_product_classification(row["name"], item_type)
        if cls_data:
            char = cls_data["characteristic"]
            saved_setting = get_model_setting(item_type, char)
            if saved_setting:
                applied_strategy = saved_setting["strategy"]
                # 辞書型として保存されたスナップショットをそのままconfigとして使う
                applied_config = saved_setting["config"]
        # ───────────────────────────────────────────────────────────────────────
        
        # スライダーで上書き設定された基本弾力性があれば優先適用（なければDBまたは1.5）
        base_elasticity = config.get("sim_base_elasticity") if config and "sim_base_elasticity" in config else abs(row.get("elasticity", -1.5))
        
        r = calculate_pricing_result(
            inventory_id    = inv_id,
            name            = row["name"],
            base_price      = int(row["base_price"]),
            total_stock     = int(row["total_stock"]),
            remaining_stock = int(row["remaining_stock"]),
            departure_date  = row.get("departure_date"),
            elasticity      = base_elasticity,
            config          = applied_config,
            strategy        = applied_strategy,
            reference_date  = reference_date,
        )
        results.append(r)
    return results

def calculate_auto_tune_parameters(item_name, past_period_start, past_period_end):
    inv_df = load_inventory()
    similar_invs = inv_df[(inv_df["name"] == item_name)].copy()
    if not similar_invs.empty:
        query_date_col = pd.to_datetime(similar_invs["departure_date"]).dt.date
        if type(past_period_start) == tuple or type(past_period_start) == list:
            p_start = past_period_start[0]
            p_end = past_period_start[-1]
        else:
            p_start = past_period_start
            p_end = past_period_end
        similar_invs = similar_invs[(query_date_col >= p_start) & (query_date_col <= p_end)]
        
    if similar_invs.empty:
        return None, None, "対象期間に類似商品のデータが存在しません。", ""
        
    all_events = load_booking_events()
    sim_events_list = []
    
    for _, sim_inv in similar_invs.iterrows():
        evs = all_events[all_events["inventory_id"] == sim_inv["id"]].copy()
        if not evs.empty:
            evs["base_price"] = sim_inv["base_price"]
            sim_events_list.append(evs)
            
    if not sim_events_list:
        return None, None, "予約履歴が存在しません。", ""
        
    sim_events = pd.concat(sim_events_list)
    sim_events["sold_price_ratio"] = sim_events["sold_price"] / sim_events["base_price"]
    
    daily_sales = sim_events.groupby(sim_events["booked_at"].dt.date).agg(
        total_quantity=("quantity", "sum"),
        avg_price_ratio=("sold_price_ratio", "mean")
    ).reset_index()
    
    if len(daily_sales) < 3:
        return None, None, "実績データの日数が少なすぎます。", ""
        
    base_days = daily_sales[daily_sales["avg_price_ratio"] >= 0.95]
    discount_days = daily_sales[daily_sales["avg_price_ratio"] <= 0.90]
    
    base_v = base_days["total_quantity"].mean() if not base_days.empty else 0
    discount_v = discount_days["total_quantity"].mean() if not discount_days.empty else 0
    
    elas = 1.5
    elas_reason = ""
    if base_v > 0 and discount_v > 0 and not discount_days.empty:
        avg_discount_ratio = 1.0 - discount_days["avg_price_ratio"].mean()
        if avg_discount_ratio > 0:
            sales_increase_ratio = (discount_v / base_v) - 1.0
            if sales_increase_ratio > 0:
                elas = sales_increase_ratio / avg_discount_ratio
                elas = round(min(5.0, max(0.1, elas)), 1)
                elas_reason = f"平均して価格が **{avg_discount_ratio*100:.1f}%** 安かった時、1日の販売個数は定価時に比べて **{sales_increase_ratio*100:.1f}%** 伸びていました。この実績から、価格弾力性を **{elas:.1f}** として自動設定しました。"
            else:
                elas_reason = f"割引時（平均{avg_discount_ratio*100:.1f}%引）に販売数の増加が見られなかったため、価格弾力性は標準の設定値（1.5）を適用しています。"
        else:
            elas_reason = f"明確な割引率が計算できなかったため、価格弾力性は標準の設定値（1.5）を適用しています。"
    else:
        elas_reason = f"過去実績において明確な価格の変動（割引実績）または定価販売実績が十分確認できなかったため、価格弾力性は標準の設定値（1.5）を適用しています。"
        
    overall_v = daily_sales["total_quantity"].mean()
    window_size = 7 if len(daily_sales) >= 14 else 3
    daily_sales["rolling_v"] = daily_sales["total_quantity"].rolling(window=window_size, min_periods=1).mean()
    peak_v = daily_sales["rolling_v"].max()
    
    boost = 15.0
    boost_reason = ""
    if overall_v > 0 and peak_v > overall_v:
        boost_ratio = (peak_v / overall_v) - 1.0
        boost = round(min(50.0, boost_ratio * 100), 1)
        boost_reason = f"平均販売ペースは1日 **{overall_v:.1f}個** ですが、ピーク時（{window_size}日移動平均）には最大で1日 **{peak_v:.1f}個 (+{boost_ratio*100:.1f}%)** 売れるポテンシャルがあることが分かりました。この最大伸びしろをAI予測ブースト係数 **{boost:.1f}%** として自動設定しました。"
    else:
        boost_reason = f"需要の明確なピーク（伸びしろ）が検出できなかったため、AI予測ブースト係数は標準の設定値（15.0%）を適用しています。"
        
    return elas, boost, elas_reason, boost_reason

# ─── ヘッダー ──────────────────────────────────────────────────────
st.markdown(f"""
<h1>🔍 Explainable Pricing Dashboard</h1>
<p style='color:{Theme.text_muted}; margin-top:{Theme.spacing_sm}; margin-bottom:{Theme.spacing_md};'>
  価格の根拠を可視化し、アルゴリズムのブラックボックス化を防ぐ —
  <span style='color:{Theme.chart_accent}'>White-box Pricing Engine</span>
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
    st.markdown("### ⏳ タイムトラベル設定")
    virtual_today = st.date_input(
        "シミュレーション基準日 (Virtual Today)",
        value=datetime.now(timezone.utc).date(),
        help="指定した日付時点での「残在庫」「販売ペース」を再計算し、それより過去（または当日）に出発した在庫は分析対象から除外します。"
    )
    st.session_state["virtual_today"] = virtual_today
    
    st.markdown("---")
    st.markdown("### 🌐 全体設定")
    
    st.session_state["pricing_strategy"] = "rule_based" # デフォルト値
    st.session_state["market_scenario"] = "base"       # デフォルト値
    
    st.markdown("---")
    st.markdown("### 🎛 AI Command Center")
    st.markdown(f"<p style='color:{Theme.text_muted}; font-size:{Theme.font_size_caption}'>AIの行動ルールをリアルタイム編集</p>", unsafe_allow_html=True)
    
    with st.expander("🛡 セーフティガード (上下限)", expanded=False):
        max_discount = st.slider("最大割引率 (%)", 0, 80, 30, help="これ以上安くしない限界値")
        max_markup   = st.slider("最大値上げ率 (%)", 0, 200, 50, help="需要超過時の値上げ上限")
        cost_ratio   = st.slider("標準原価率", 0.1, 1.0, DEFAULT_COST_RATIO, 0.05, help="利益計算のベースとなる原価率")
    
    with st.expander("🚔 自動調整 (Velocity Brake)", expanded=False):
        brake_threshold = st.slider("ブレーキ発動閾値", 1.0, 5.0, 1.5, 0.1, help="期待ペースの何倍でブレーキをかけるか")
        brake_strength  = st.slider("ブレーキ強度 (%)", 0, 30, 5, help="ブレーキ時に上乗セする価格比率")

    with st.expander("📈 シミュレータ設定 (推移・予測用)", expanded=False):
        st.markdown("**行動アルゴリズム**")
        sim_final_sprint_days = st.slider("スパート開始日数", 1, 30, SIM_FINAL_SPRINT_DAYS, help="出発日の何日前からラストスパートをかけるか")
        
        c1, c2 = st.columns(2)
        with c1:
            sim_markup_high = st.slider("強気値上げ率 (%)", 0.0, 10.0, float(SIM_MARKUP_STEP_HIGH_PCT), 0.5)
            sim_markdown_high = st.slider("強気値下げ率 (%)", -20.0, 0.0, float(SIM_MARKDOWN_STEP_HIGH_PCT), 0.5)
        with c2:
            sim_markup_low = st.slider("微増値上げ率 (%)", 0.0, 10.0, float(SIM_MARKUP_STEP_LOW_PCT), 0.5)
            sim_markdown_low = st.slider("微減値下げ率 (%)", -20.0, 0.0, float(SIM_MARKDOWN_STEP_LOW_PCT), 0.5)
        
        st.markdown("**需要モデリング（動的価格弾力性）**")
        base_elasticity_val = st.slider("基本価格弾力性", 0.1, 5.0, 1.5, 0.1, help="価格変動に対する需要の基本感度")
        sim_boost = st.slider("ベース需要底上げ効果 (%)", 0.0, 50.0, float(SIM_FORECAST_BOOST_PCT), 1.0, help="戦略適用による基準需要の向上")
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("値引しすぎ（安売り限界）")
            sim_elas_high_th = st.slider("限界割引率 (Ratio)", 1.0, 3.0, float(SIM_ELASTICITY_PRICE_RATIO_HIGH_THRES), 0.1, help="この比率(定価/時価)を超えると需要の伸びが鈍る")
            sim_elas_damp = st.slider("弾力性鈍化 (%)", 0.0, 100.0, float(SIM_ELASTICITY_DAMPEN_PCT), 5.0, help="限界を超えた場合の弾力性減少率")
        with c4:
            st.markdown("値上げ（客離れ境界）")
            sim_elas_low_th = st.slider("限界値上げ率 (Ratio)", 0.5, 1.0, float(SIM_ELASTICITY_PRICE_RATIO_LOW_THRES), 0.05, help="この比率(定価/時価)を下回ると客離れが加速する")
            sim_elas_amp = st.slider("弾力性増幅 (%)", 100.0, 300.0, float(SIM_ELASTICITY_AMPLIFY_PCT), 10.0, help="限界を下回った場合の弾力性増加率")

    ai_config = {
        "max_discount_pct": max_discount,
        "max_markup_pct":   max_markup,
        "cost_ratio":       cost_ratio,
        "brake_threshold":  brake_threshold,
        "brake_strength_pct": brake_strength,
        "rule_inv_premium_pct": DEFAULT_RULE_INV_PREMIUM_PCT,
        "rule_inv_high_pct":    DEFAULT_RULE_INV_HIGH_PCT,
        "rule_inv_discount_pct": DEFAULT_RULE_INV_DISCOUNT_PCT,
        "rule_time_last_min_pct": DEFAULT_RULE_TIME_LAST_MIN_PCT,
        "rule_time_peak_pct":    DEFAULT_RULE_TIME_PEAK_PCT,
        "rule_time_early_pct":   DEFAULT_RULE_TIME_EARLY_PCT,
        "decay_k": DEFAULT_DECAY_K,
        "decay_p": DEFAULT_DECAY_P,
        "inv_threshold_premium": INV_THRESHOLD_PREMIUM,
        "inv_threshold_high":    INV_THRESHOLD_HIGH,
        "inv_threshold_normal":  INV_THRESHOLD_NORMAL,
        "time_threshold_last_min": TIME_THRESHOLD_LAST_MIN,
        "time_threshold_peak":     TIME_THRESHOLD_PEAK,
        "time_threshold_normal":   TIME_THRESHOLD_NORMAL,
        "score_weight_mape":     SCORE_WEIGHT_MAPE,
        "score_weight_lift":     SCORE_WEIGHT_LIFT,
        "score_weight_spoilage": SCORE_WEIGHT_SPOILAGE,
        "score_weight_dir_acc":  SCORE_WEIGHT_DIR_ACC,
        "class_popular_threshold": CLASS_POPULAR_THRESHOLD,
        "class_niche_days":      CLASS_NICHE_DAYS,
        "class_niche_ratio":     CLASS_NICHE_RATIO,
        "sim_final_sprint_days": sim_final_sprint_days,
        "sim_markup_high_pct":   sim_markup_high,
        "sim_markup_low_pct":    sim_markup_low,
        "sim_markdown_high_pct": sim_markdown_high,
        "sim_markdown_low_pct":  sim_markdown_low,
        "sim_base_elasticity":   base_elasticity_val,
        "sim_forecast_boost_pct": sim_boost,
        "sim_elas_high_th":      sim_elas_high_th,
        "sim_elas_low_th":       sim_elas_low_th,
        "sim_elas_damp_pct":     sim_elas_damp,
        "sim_elas_amp_pct":      sim_elas_amp
    }
    
    st.markdown("---")
    if st.button("🔄 データを再読み込み"):
        st.cache_data.clear()
        st.rerun()

# ─── 基準日（Virtual Today）に基づく在庫の再計算とフィルタリング ───
v_today = st.session_state.get("virtual_today", datetime.now(timezone.utc).date())

# 1. 基準日より過去（または当日）に出発する在庫を自動的に除外
filtered_inv_df = inv_df.copy()
if not filtered_inv_df.empty:
    filtered_inv_df = filtered_inv_df[pd.to_datetime(filtered_inv_df["departure_date"]).dt.date > v_today].copy()

# UI表示用に「商品名 (日付)」のカラムを作成
if not filtered_inv_df.empty:
    filtered_inv_df["display_name"] = filtered_inv_df.apply(
        lambda x: f"{x['name']} ({x['departure_date']})", axis=1
    )

# 2. 基準日時点の「残在庫」を再計算
# (DBの現時点の残数を使うのではなく、全件の予約履歴から基準日までの販売数を引くことで、データ整合性を担保)
all_events = load_booking_events()
if not all_events.empty and not filtered_inv_df.empty:
    # 基準日（含む）までの予約を合計
    past_events = all_events[all_events["booked_at"].dt.date <= v_today]
    if not past_events.empty:
        past_sales = past_events.groupby("inventory_id")["quantity"].sum().reset_index()
        filtered_inv_df = pd.merge(filtered_inv_df, past_sales, how="left", left_on="id", right_on="inventory_id")
        filtered_inv_df["quantity"] = filtered_inv_df["quantity"].fillna(0)
        # 整合性のため、total_stock から基準日までの売上を引く
        filtered_inv_df["remaining_stock"] = filtered_inv_df["total_stock"] - filtered_inv_df["quantity"]
        filtered_inv_df.drop(columns=["inventory_id", "quantity"], inplace=True)
    else:
        # 予約がまだ一件もない場合は、total_stock = remaining_stock
        filtered_inv_df["remaining_stock"] = filtered_inv_df["total_stock"]

target_ids = filtered_inv_df["id"].tolist()

strategy_val = st.session_state.get("pricing_strategy", "rule_based")
results = get_pricing_results(filtered_inv_df, config=ai_config, strategy=strategy_val, reference_date=v_today)
log_price_history(results, DB_PATH)
history_df = load_history() # 履歴を再読み込みして最新化

# 履歴データもフィルタリング (基準日以前のものだけ表示)
if not history_df.empty:
    history_df = history_df[history_df["inventory_id"].isin(target_ids)]
    history_df = history_df[history_df["recorded_at"].dt.date <= v_today]

# --- 共通のテーブルデータ作成 (アラート判定と共有) ---
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
        "出発日": inv.get("departure_date", "不明"),
        "商品名": inv["name"],
        "販売速度": f"{vr:.2f}x",
        "ステータス": status,
        "時価": f"¥{r['final_price']:,}",
        "残庫": f"{int(inv['remaining_stock'])}/{int(inv['total_stock'])}",
        "ID": r["inventory_id"]
    })
table_df = pd.DataFrame(table_data)

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
        config=ai_config,
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


# ─── ナビゲーションタブ ──────────────────────────────
tabs = [
    "🎯 本日のアクション",
    "🔍 販売シミュレータ(単体)",
    "🧪 販売シミュレータ（パッケージ）",
    "🛒 事前仕入と初期価格の最適化",
    "🔬 販売モデル設定"
]
selected_tab = st.radio("MainNavigation", tabs, horizontal=True, label_visibility="collapsed", key="main_nav_tab")


# ══════════════════════════════════════════════════════════════════
# Tab 2: 【アクション】Today's Action
# ══════════════════════════════════════════════════════════════════
if selected_tab == "🎯 本日のアクション":
    def get_velocity_ratio_with_ref(inv_id, ts, rs, ld):
        return get_velocity_ratio(inv_id, ts, rs, ld, reference_date=v_today)



    st.markdown("### 🚨 本日のAI優先対応アラート")
    render_alerts(results, filtered_inv_df, [], get_velocity_ratio_with_ref)





    # ══════════════════════════════════════════════════════════════════
    # 🏆 Hero KPI: AI最適化インパクト (Prescriptive Analytics - Phase 14)
    # ══════════════════════════════════════════════════════════════════
    ai_impact      = optimal_strategy["ai_impact"]
    total_sa       = optimal_strategy["total_standalone_profit"]
    total_opt      = optimal_strategy["total_optimized_profit"]
    impact_color   = Theme.success if ai_impact >= 0 else Theme.danger
    impact_sign    = "+" if ai_impact >= 0 else ""
    scenario_label = {"base": "ベース", "optimistic": "楽観", "pessimistic": "悲観"}.get(curr_scenario, "ベース")



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
                    <div style="background:{Theme.success}; color:{Theme.white}; border-radius:8px; padding:4px 10px; font-size:0.75rem; font-weight:900; white-space:nowrap;">
                        📦 パッケージ推奨
                    </div>
                    <div style="background:rgba(99,102,241,0.2); color:#a5b4fc; border:1px solid rgba(99,102,241,0.4); border-radius:6px; padding:3px 10px; font-size:0.8rem; font-weight:700;">
                        📅 {dep_label}出発
                    </div>
                    <div style="color:{Theme.chart_accent}; font-size:{Theme.size_md}; font-weight:600; margin-left:auto;">+¥{rec['gain']:,} 改善</div>
                </div>
                <div style="font-size:1rem; font-weight:800; color:{Theme.text_dark}; margin-bottom:6px;">
                    {item_icon} {rec['item_name']} ＋ ✈️ {rec['partner_name']}
                </div>
                <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:6px;">
                    <span style="color:{Theme.success}; font-weight:700;">推奨価格: ¥{rec['optimal_price']:,}</span>
                    <span style="color:{Theme.text_muted};">上限セット数: {rec['max_sets']} セット</span>
                </div>
                <div style="font-size:{Theme.size_md}; color:{Theme.text_sec};">{rec['reason']}</div>
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
                    <span style="background:rgba(99,102,241,0.15); color:#a5b4fc; border-radius:6px; padding:2px 8px; font-size:{Theme.size_sm}; font-weight:700;">📅 {dep_label}</span>
                    <span style="font-weight:700; color:{Theme.text_sec};">{item_icon} {rec['item_name']}</span>
                    <span style="color:{Theme.text_sec}; font-size:{Theme.size_md};">現行価格: ¥{rec['optimal_price']:,}</span>
                    <div style="width:100%; font-size:{Theme.size_xs}; color:{Theme.text_muted}; margin-top:4px;">{rec['reason']}</div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 🚚 商品一覧 & 異常検知")
    st.dataframe(light_dataframe(table_df), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════
# Tab 3: Analysis & Tracking (旧ドリルダウン + ライブ動向)
# ══════════════════════════════════════════════════════════════════
if selected_tab == "🔍 販売シミュレータ(単体)":
    st.markdown("### 🔍 販売シミュレータ(単体)")

    # --- 共通の商品選択エリア (ライブリストを兼ねる) ---
    st.markdown("#### 🎯 対象商品の詳細分析")
    

    
    # 選択（日付と製品でボックスを分ける）
    col_sel_date, col_sel_name, col_sel_past = st.columns([1,1,1])
    with col_sel_date:
        available_dates = sorted([d for d in table_df["出発日"].unique() if d != "不明"])
        if not available_dates:
            available_dates = ["不明"]
        sel_date = st.selectbox("分析対象の出発日", available_dates, key="global_date_selector")
        
    with col_sel_name:
        available_products = sorted(table_df[table_df["出発日"] == sel_date]["商品名"].unique().tolist())
        sel_name = st.selectbox("分析対象の製品", available_products, key="global_name_selector")
        
    with col_sel_past:
        # 参考にする過去期間（Auto-Tuneおよび表示の基準）
        past_period = st.date_input(
            "参考にする過去期間", 
            value=(v_today - timedelta(days=365), v_today),
            key="past_period_input"
        )
        
    selected_item_df = table_df[(table_df["出発日"] == sel_date) & (table_df["商品名"] == sel_name)]
    if selected_item_df.empty:
        st.warning("対象となる商品履歴が見つかりません。")
        st.stop()
    selected_item_id = selected_item_df["ID"].iloc[0]
    
    st.markdown("---")

    # --- 選ばれた商品の詳細分析 (旧ドリルダウン) ---
    r_sel = next(r for r in results if r["inventory_id"] == selected_item_id)
    inv_sel = filtered_inv_df[filtered_inv_df["id"] == selected_item_id].iloc[0]
    
    all_events = load_booking_events()
    item_events = all_events[all_events["inventory_id"] == selected_item_id].sort_values("booked_at")

    # 販売シミュレータ (将来の要件拡張のため全幅を使用)
    st.markdown("#### 📈 販売シミュレータ (累積販売率予測)")
    
    # --- 自動推計の実行 ---
    p_start = past_period[0] if type(past_period) in (tuple, list) else past_period
    p_end = past_period[-1] if type(past_period) in (tuple, list) else past_period
    auto_elas, auto_boost, e_reason, b_reason = calculate_auto_tune_parameters(sel_name, p_start, p_end)
    
    # 推計のフォールバック
    if auto_elas is None: auto_elas = 1.5
    if auto_boost is None: auto_boost = 15.0
    
    elas_key = f"local_elas_{selected_item_id}"
    boost_key = f"local_boost_{selected_item_id}"
    
    # SessionStateに初期値として書き込む（ユーザーが手動スライダーを動かした場合はそれが優先される）
    if elas_key not in st.session_state:
        st.session_state[elas_key] = auto_elas
    if boost_key not in st.session_state:
        st.session_state[boost_key] = auto_boost
        
    local_elas_val = st.session_state[elas_key]
    local_boost_val = st.session_state[boost_key]
    
    # --- 将来予測に関するUI ---
    with st.expander("⚙️ シミュレーション詳細設定", expanded=True):
        col_scenario, col_pred, col_auto, col_compare = st.columns(4)
        with col_scenario:
            # このタブ専用の需要予測シナリオ選択
            ana_scenario = st.selectbox(
                "需要予測シナリオ:",
                ["base", "pessimistic", "optimistic"],
                format_func=lambda x: "ベース (1.0x)" if x=="base" else ("切迫・悲観 (0.7x)" if x=="pessimistic" else "好調・楽観 (1.3x)"),
                key="ana_scenario_selectbox"
            )
            st.session_state["market_scenario"] = ana_scenario
            scenario_multiplier = FORECAST_MULTIPLIERS.get(ana_scenario, 1.0)
            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    
        with col_pred:
            import os, sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from model_evaluator import get_product_classification, get_model_setting
            
            cls_data = get_product_classification(inv_sel["name"], inv_sel["item_type"])
            char = cls_data["characteristic"] if cls_data else "stable"
            saved_setting = get_model_setting(inv_sel["item_type"], char)
            
            is_registered = saved_setting is not None
            if is_registered:
                applied_strategy_choice = saved_setting["strategy"]
                applied_config_choice = saved_setting["config"]
                
                label_html = f"<div style='font-size: 14px; margin-bottom: 8px; font-weight: 600; color: #31333F;'>登録モデル: <span style='font-weight: normal; color: #4F46E5;'>{char} 特性 / {'ルールベース' if applied_strategy_choice == 'rule_based' else '需要予測ベース'}</span></div>"
                st.markdown(label_html, unsafe_allow_html=True)
                with st.expander("モデル詳細パラメータ", expanded=False):
                    st.json(applied_config_choice)
            else:
                applied_strategy_choice = "rule_based"
                applied_config_choice = ai_config
                
                label_html = "<div style='font-size: 14px; margin-bottom: 8px; font-weight: 600; color: #31333F;'>登録モデル: <span style='font-weight: normal; color: #64748B;'>未設定 (デフォルト適用)</span></div>"
                st.markdown(label_html, unsafe_allow_html=True)
                with st.expander("デフォルトパラメータ", expanded=False):
                    st.json(applied_config_choice)
                    
            if applied_strategy_choice == "rule_based":
                pred_strategy = "現在の価格戦略を継続"
            else:
                pred_strategy = "需要予測ベース戦略を適用"
            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    
        with col_auto:
            label_html = "<div style='font-size: 14px; margin-bottom: 8px; font-weight: 600; color: #31333F;'>🪄 自動推計予測パラメータ</div>"
            st.markdown(label_html, unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:13px; line-height:1.5; background:#f8fafc; padding:8px; border-radius:6px; margin-bottom:12px;'><b>基本価格弾力性:</b> <span style='color:{Theme.primary}; font-weight:700;'>{local_elas_val:.1f}</span><br><b>AI予測ブースト:</b> <span style='color:{Theme.primary}; font-weight:700;'>{local_boost_val:.1f}%</span></div>", unsafe_allow_html=True)
            
            with st.expander("算出根拠 / 手動微調整", expanded=False):
                st.markdown(f"<div style='font-size:12px; color:gray; line-height:1.4;'>{e_reason}<br><br>{b_reason}</div>", unsafe_allow_html=True)
                st.markdown("---")
                st.slider("価格弾力性の手動調整", 0.1, 5.0, key=elas_key, step=0.1)
                st.slider("予測ブーストの手動調整 (%)", 0.0, 50.0, key=boost_key, step=1.0)
    
        with col_compare:
            st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)
            # 固定モードか毎日変動かを選択する比較UIを追加
            compare_mode = st.radio(
                "定価維持(ベースライン)と比較するシナリオ",
                options=["一定期間ごとで単価を固定", "毎日単価を変更 (ダイナミック)"],
                index=0,
                horizontal=False,
                key="pred_compare_mode"
            )
            if compare_mode == "一定期間ごとで単価を固定":
                fixed_interval = st.selectbox("単価固定期間", [3, 7, 14, 30], index=1, format_func=lambda x: f"{x}日間ごと", key="fixed_interval_days", label_visibility="collapsed")
            else:
                fixed_interval = 1 # 毎日
                
        # レイアウトの余白調整用
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
            
    # 日付から「残り日数（Lead Days）」に変換する関数
    def to_lead_days(target_date, departure_date):
        return (departure_date - target_date).days
    
    dep_date = pd.to_datetime(inv_sel["departure_date"]).date()
    total_stock_sel = max(1, int(inv_sel["total_stock"]))
    
    from plotly.subplots import make_subplots
    fig_curve = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.1,
        subplot_titles=("累計販売率推移 (%)", "販売単価推移 (¥)"),
        row_heights=[0.6, 0.4]
    )

    # ① 類似商品（過去の指定期間）の平均実績線を描画
    similar_invs = inv_df[(inv_df["name"] == inv_sel["name"]) & (inv_df["id"] != selected_item_id)].copy()
    
    if isinstance(past_period, (tuple, list)):
        p_start = past_period[0]
        p_end = past_period[-1]
    else:
        p_start = p_end = past_period
        
    if not similar_invs.empty:
        query_date_col = pd.to_datetime(similar_invs["departure_date"]).dt.date
        similar_invs = similar_invs[(query_date_col >= p_start) & (query_date_col <= p_end)]
        
    past_lines = []
    for _, sim_inv in similar_invs.iterrows():
        sim_events = all_events[all_events["inventory_id"] == sim_inv["id"]].sort_values("booked_at").copy()
        if not sim_events.empty:
            if "departure_date" in sim_inv and pd.notna(sim_inv["departure_date"]):
                sim_dep_date = pd.to_datetime(sim_inv["departure_date"]).date()
            else:
                continue
            sim_events["lead_days"] = sim_events["booked_at"].dt.date.apply(lambda d: -to_lead_days(d, sim_dep_date))
            t_stock = max(1, int(sim_inv.get("total_stock", 1)))
            sim_events["cum_rate"] = sim_events["quantity"].cumsum() / t_stock * 100
            
            # 日数(-90~0)ごとにフォワードフィルして平均計算用の配列を作成
            df_daily = pd.DataFrame({"lead_days": range(-90, 1)})
            merged = pd.merge(df_daily, sim_events[["lead_days", "cum_rate"]].drop_duplicates("lead_days", keep="last"), on="lead_days", how="left")
            merged["cum_rate"] = merged["cum_rate"].ffill().fillna(0)
            past_lines.append(merged["cum_rate"].values)

    if past_lines:
        import numpy as np
        avg_rates = np.mean(past_lines, axis=0)
        fig_curve.add_trace(go.Scatter(
            x=list(range(-90, 1)), y=avg_rates,
            mode="lines", line=dict(color="rgba(148,163,184,0.8)", width=2, dash="dash"),
            name="過去実績(平均)",
            legendgroup="actual",
            legendgrouptitle_text="<b>📊 実績</b>",
            hoverinfo="y"
        ), row=1, col=1)

    # ② 選択された商品の実績（基準日まで）を描画
    item_events_filtered = item_events[item_events["booked_at"].dt.date <= v_today].copy()
    current_sales_rate = 0
    current_sales = 0
    current_lead_day = -to_lead_days(v_today, dep_date)
    
    if not item_events_filtered.empty:
        item_events_filtered["lead_days"] = item_events_filtered["booked_at"].dt.date.apply(lambda d: -to_lead_days(d, dep_date))
        item_events_filtered["cum_sales_rate"] = item_events_filtered["quantity"].cumsum() / total_stock_sel * 100
        current_sales = item_events_filtered["quantity"].cumsum().iloc[-1]
        
        # 連続した線にするため、現在地点(v_today)まで最終実績を水平に延ばす
        last_event_day = item_events_filtered["lead_days"].iloc[-1]
        current_sales_rate = item_events_filtered["cum_sales_rate"].iloc[-1]
        if last_event_day < current_lead_day:
            new_row = pd.DataFrame({
                "lead_days": [current_lead_day],
                "cum_sales_rate": [current_sales_rate]
            })
            item_events_filtered = pd.concat([item_events_filtered, new_row], ignore_index=True)
            
        fig_curve.add_trace(go.Scatter(
            x=item_events_filtered["lead_days"], y=item_events_filtered["cum_sales_rate"],
            mode="lines+markers", line=dict(color=Theme.chart_accent, width=3),
            name="実績値", fill="tozeroy", fillcolor=Theme.chart_fill_alpha2,
            legendgroup="actual"
        ), row=1, col=1)
        
        # 販売単価推移 (実績)
        if "sold_price" in item_events_filtered.columns:
            daily_price = item_events_filtered.groupby("lead_days")["sold_price"].mean().reset_index()
            daily_price = daily_price.sort_values("lead_days")
            
            if not daily_price.empty:
                # 最小のlead_daysから現在のlead_days(または0)までの全整数の範囲を作成
                min_day = int(daily_price["lead_days"].min())
                target_end_day = int(max(current_lead_day, daily_price["lead_days"].max()))
                
                # 全日数のDataFrameを作成して結合し、欠損日を前日の価格で補完(ffill)する
                all_days = pd.DataFrame({"lead_days": range(min_day, target_end_day + 1)})
                daily_price = pd.merge(all_days, daily_price, on="lead_days", how="left")
                daily_price["sold_price"] = daily_price["sold_price"].ffill()

            fig_curve.add_trace(go.Scatter(
                x=daily_price["lead_days"], y=daily_price["sold_price"],
                mode="lines+markers", line=dict(color=Theme.warning, width=2),
                name="販売単価 (実績)",
                legendgroup="actual"
            ), row=2, col=1)
    
    # ③ 将来予測の描画（基準日〜出発日まで）
    if current_lead_day < 0:
        days_remaining = abs(current_lead_day)
        
        # まず現在価格を取得
        if 'daily_price' in locals() and not daily_price.empty:
            last_price = daily_price["sold_price"].iloc[-1]
        elif not item_events_filtered.empty:
            last_price = item_events_filtered["sold_price"].iloc[-1]
        else:
            last_price = r_sel['base_price']
            
        # 単価の予測と販売率の予測シミュレーション配列作成
        sim_days = list(range(current_lead_day, 1))
        sim_prices = [last_price]
        sim_sales_rates = [current_sales_rate]
        sim_sales_count = [current_sales]
        
        curr_p = last_price
        curr_s = current_sales
        base_price = r_sel['base_price']
        cost = int(inv_sel.get('cost', base_price * 0.75)) # DBから原価を取得（フォールバックあり）
        
        revenue_strategy_future = 0
        
        # --- 直近の実績に合わせた予測ベロシティ(ベースの傾き)の計算 ---
        lookback_days = 30
        
        # 修正: 90日固定ではなく、販売開始からの実際の期間（最大180日程度など）を考慮するか、
        # 少なくとも分母がゼロ以下にならないように max(1か月の営業日数など, ...) を設定
        # 安全のため、分母は「最低30日」でキャップしておく（異常値防止）
        denominator_days = max(30, (90 - days_remaining))
        overall_v = current_sales / denominator_days

        if not item_events_filtered.empty and denominator_days >= lookback_days:
            # 基準日(current_lead_day)から過去30日間のデータを取り出す
            recent_events = item_events_filtered[
                (item_events_filtered["lead_days"] <= current_lead_day) & 
                (item_events_filtered["lead_days"] > (current_lead_day - lookback_days))
            ]
            recent_v = recent_events["quantity"].sum() / lookback_days
            # 直近トレンドを強く反映(80%)しつつ、全体平均もわずかに加味(20%)して極端なゼロを回避
            # シナリオ倍率を適用
            base_daily_v = ((recent_v * 0.8) + (overall_v * 0.2)) * scenario_multiplier
        else:
            base_daily_v = overall_v * scenario_multiplier
            
        # 自動推計されたローカルの弾力性を適用
        elasticity_val = local_elas_val
        
        # 修正: 1日当たりの最大販売件数（キャップ）を設定（例: 総在庫の10%か最低5件の大きい方）
        max_daily_sales_cap = max(5, total_stock_sel * 0.10)

        # --- 動的弾力性計算ヘルパー関数 ---
        def get_dynamic_elasticity(price_ratio, base_elasticity):
            elas_high_th = ai_config.get("sim_elas_high_th", 2.0)
            elas_low_th  = ai_config.get("sim_elas_low_th", 1.0)
            elas_damp    = ai_config.get("sim_elas_damp_pct", 50.0) / 100.0
            elas_amp     = ai_config.get("sim_elas_amp_pct", 150.0) / 100.0
            
            if price_ratio > elas_high_th:
                # 値引きしすぎて「安かろう悪かろう」となり需要の伸びが鈍化する
                return base_elasticity * elas_damp
            elif price_ratio < elas_low_th:
                # 定価より高くすると客離れが加速する
                return base_elasticity * elas_amp
            else:
                return base_elasticity

        for i in range(1, len(sim_days)):
            d = abs(sim_days[i])
            
            # 完売チェック (すでに在庫が尽きている場合は、それ以上の予測販売や価格変動をストップする)
            if curr_s >= total_stock_sel:
                sim_prices.append(curr_p)
                sim_sales_count.append(total_stock_sel)  # 上限で固定
                sim_sales_rates.append(100.0)             # 上限で固定
                continue
            
            # === 一定期間ごとの最適価格探索ロジック ===
            # 初日、または設定した固定期間(fixed_interval)の日数が経過したタイミングで新しい価格を一つ決める
            if compare_mode == "一定期間ごとで単価を固定" and (i == 1 or i % fixed_interval == 0):
                # 向こう [fixed_interval] 日間 (または出発日までの残り日数) での利益相当スコアが最大化される単価を探索
                days_to_simulate = min(fixed_interval, len(sim_days) - i)
                best_block_price = curr_p
                best_block_profit_score = -1
                
                # 候補となる価格倍率 (現在価格を中心に ±30% など)
                price_multipliers = [0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3]
                
                for pm in price_multipliers:
                    test_p = int(curr_p * pm)
                    # 異常値防止のための上下限
                    test_p = max(test_p, int(base_price * 0.4))
                    test_p = min(test_p, int(base_price * 2.0))
                    
                    test_s = curr_s
                    test_rev = 0
                    test_sales_count = 0
                    
                    # 候補価格 test_p を days_to_simulate 日間適用した場合のシミュレーション
                    for tj in range(days_to_simulate):
                        test_d = abs(sim_days[i + tj])
                        if test_s >= total_stock_sel:
                            break # 売り切れたら終了
                        
                        price_ratio = base_price / test_p if test_p > 0 else 1.0
                        test_elasticity = get_dynamic_elasticity(price_ratio, elasticity_val)
                        
                        # ペース倍率の適用（ルールベースか需要予測か）
                        boost = 1.0
                        if pred_strategy != "現在の価格戦略を継続":
                            boost = 1.0 + (local_boost_val / 100)
                        
                        test_v = (base_daily_v * boost) * (price_ratio ** test_elasticity)
                        test_v = min(test_v, max_daily_sales_cap)
                        
                        actual_test_sales = min(test_v, total_stock_sel - test_s)
                        test_s += actual_test_sales
                        test_sales_count += actual_test_sales
                        test_rev += actual_test_sales * test_p
                    
                    # 利益相当スコア (売上 + 期間内販売数 * 原価) を算出。これにより最終評価（売上高 - 廃棄損）とのねじれを解消
                    test_profit_score = test_rev + (test_sales_count * cost)
                    
                    if test_profit_score > best_block_profit_score:
                        best_block_profit_score = test_profit_score
                        best_block_price = test_p
                
                # 探索したベストな価格を、向こう [fixed_interval] 日間の適用価格（curr_p）としてセットする
                curr_p = best_block_price

            elif compare_mode == "毎日単価を変更 (ダイナミック)":
                # これまでの毎日変動ロジック
                if pred_strategy == "現在の価格戦略を継続":
                    ideal_sales = total_stock_sel * (1 - (d / 90))
                    if curr_s > ideal_sales:
                        curr_p = int(min(curr_p * 1.015, base_price * 1.5))
                    else:
                        curr_p = int(max(curr_p * 0.985, base_price * 0.5))
                else:
                    sprint_days = ai_config.get("sim_final_sprint_days", 14) 
                    markup_rate_high = 1.0 + (ai_config.get("sim_markup_high_pct", 2.5) / 100)
                    markup_rate_low  = 1.0 + (ai_config.get("sim_markup_low_pct", 1.0) / 100)
                    markdown_rate_high = 1.0 + (ai_config.get("sim_markdown_high_pct", -5.0) / 100)
                    markdown_rate_low  = 1.0 + (ai_config.get("sim_markdown_low_pct", -2.0) / 100)

                    ideal_sales = total_stock_sel * (1 - (d / 90))
                    
                    if d > sprint_days:
                        if curr_s > ideal_sales * 1.1:
                            curr_p = int(min(curr_p * markup_rate_high, base_price * 1.8))
                        elif curr_s > ideal_sales:
                            curr_p = int(min(curr_p * markup_rate_low, base_price * 1.4))
                        else:
                            curr_p = int(max(curr_p * markdown_rate_low, base_price * 0.6))
                    else:
                        if curr_s < total_stock_sel * 0.9:
                            curr_p = int(max(curr_p * markdown_rate_high, base_price * 0.4))
                        else:
                            curr_p = int(min(curr_p * markup_rate_low, base_price * 1.2))

            # --- 需要・販売数の反映（固定／毎日共通） ---
            price_ratio = base_price / curr_p if curr_p > 0 else 1.0
            curr_elasticity = get_dynamic_elasticity(price_ratio, elasticity_val)
            
            boost_rate = 1.0
            if pred_strategy != "現在の価格戦略を継続":
                boost_rate = 1.0 + (local_boost_val / 100)
                
            curr_v = (base_daily_v * boost_rate) * (price_ratio ** curr_elasticity)
            curr_v = min(curr_v, max_daily_sales_cap)
            curr_s += curr_v
            
            # 販売数が総在庫を超えないようにキャップ処理
            actual_curr_s = min(curr_s, total_stock_sel)
            actual_daily_sales = actual_curr_s - sim_sales_count[-1]
            revenue_strategy_future += (actual_daily_sales * curr_p)
            
            # 以降のループ用に curr_s 自体も直近の実際の値でリセットしておく
            curr_s = actual_curr_s
            
            sim_prices.append(curr_p)
            sim_sales_count.append(curr_s)
            sim_sales_rates.append(min(100.0, (curr_s / total_stock_sel) * 100))
            
        projected_sales_rate = sim_sales_rates[-1]
        projected_sales = int(min(total_stock_sel, sim_sales_count[-1]))
        
        # 過去の実績売上（簡易計算：現在までの売上合計）
        current_revenue = current_sales * last_price 
        projected_revenue_strategy = current_revenue + revenue_strategy_future
        
        # 廃棄損の計算 (売れ残り数 * 原価)
        spoilage_qty_strategy = max(0, total_stock_sel - projected_sales)
        spoilage_cost_strategy = spoilage_qty_strategy * cost
        net_profit_strategy = projected_revenue_strategy - spoilage_cost_strategy
        
        # 予測販売率推移（動的または固定化）
        fig_curve.add_trace(go.Scatter(
            x=sim_days, y=sim_sales_rates,
            mode="lines", line=dict(color=Theme.primary, width=3, dash="dot"),
            name=f"予測推移 ({compare_mode})",
            legendgroup="rate",
            legendgrouptitle_text="<br><b>📈 累計販売率推移</b>"
        ), row=1, col=1)
        
        fig_curve.add_trace(go.Scatter(
            x=[0], y=[projected_sales_rate],
            mode="markers", marker=dict(color=Theme.primary, size=10, symbol="star"),
            name="最終着地（予測）",
            legendgroup="rate",
            showlegend=False  # 凡例が煩雑になるため非表示
        ), row=1, col=1)

        # 単価の予測線 (動的変動または段階的固定)
        if last_price > 0:
            # 固定モードの場合は、Stepプロット（階段状）にする
            line_shape = "vh" if compare_mode == "一定期間ごとで単価を固定" else "linear"
            fig_curve.add_trace(go.Scatter(
                x=sim_days, y=sim_prices,
                mode="lines", line=dict(color=Theme.warning, width=2, dash="dot", shape=line_shape),
                name=f"予測推移単価 ({compare_mode})",
                legendgroup="price",
                legendgrouptitle_text="<br><b>💴 販売単価推移</b>"
            ), row=2, col=1)

        # ④ 価格据え置き（ベースライン）シナリオの予測と比較
        # 定価で販売し続けた場合の予測販売数（戦略側とキャップ条件等を統一するため日次ループで計算）
        base_velocity = base_daily_v
        # (戦略側が base_price 基準での弾力性を 1.0 として計算しているため、ベースラインも base_daily_v をそのまま用いる)
            
        sim_sales_count_baseline = [current_sales]
        curr_s_baseline = current_sales
        revenue_baseline_future = 0
            
        for i in range(1, len(sim_days)):
            if curr_s_baseline >= total_stock_sel:
                sim_sales_count_baseline.append(total_stock_sel)
                continue
                
            # ベースラインの1日あたりの予測販売数にも同じ日次キャップを適用
            daily_v_baseline = min(base_velocity, max_daily_sales_cap)
            
            curr_s_baseline += daily_v_baseline
            actual_curr_s_baseline = min(curr_s_baseline, total_stock_sel)
            
            actual_daily_sales_baseline = actual_curr_s_baseline - sim_sales_count_baseline[-1]
            revenue_baseline_future += (actual_daily_sales_baseline * base_price)
            
            curr_s_baseline = actual_curr_s_baseline
            sim_sales_count_baseline.append(curr_s_baseline)
            
        # 最終的な販売率と販売数
        projected_sales_baseline = int(min(total_stock_sel, sim_sales_count_baseline[-1]))
        projected_sales_rate_baseline = (projected_sales_baseline / total_stock_sel) * 100
        
        # 定価維持時の売上と廃棄損
        projected_revenue_baseline = current_revenue + revenue_baseline_future
        spoilage_qty_baseline = max(0, total_stock_sel - projected_sales_baseline)
        spoilage_cost_baseline = spoilage_qty_baseline * cost
        net_profit_baseline = projected_revenue_baseline - spoilage_cost_baseline
        
        revenue_lift = net_profit_strategy - net_profit_baseline

        # ベースラインの販売率予測線（グレー点線）
        fig_curve.add_trace(go.Scatter(
            x=[current_lead_day, 0], y=[current_sales_rate, projected_sales_rate_baseline],
            mode="lines", line=dict(color=Theme.text_muted, width=2, dash="dot"),
            name="定価据え置き予測 (販売率)",
            legendgroup="rate"
        ), row=1, col=1)
        
        # ベースラインの販売単価予測線（グレー点線：定価の維持）
        fig_curve.add_trace(go.Scatter(
            x=[current_lead_day, 0], y=[base_price, base_price],
            mode="lines", line=dict(color=Theme.text_muted, width=1, dash="dot"),
            name="定価ライン",
            legendgroup="price"
        ), row=2, col=1)
        
        # 売上インパクトのハイライトパネル（HTMLマトリクス表示）をグラフ上部に表示
        if revenue_lift > 0:
           lift_text = f"<span style='color:{Theme.success};'><b>+¥{revenue_lift:,.0f}の増益効果</b></span>"
        else:
           lift_text = f"<span style='color:{Theme.danger};'><b>¥{revenue_lift:,.0f}の減益リスク</b></span>"
        
        st.markdown(f"""
        <div style="background:{Theme.bg_card}; padding:15px; border-radius:8px; border:1px dashed {Theme.primary}; margin-bottom:15px;">
            <div style="font-size:0.95rem; color:{Theme.text_dark}; margin-bottom:10px; font-weight:bold;">💡 What-If 分析結果明細 (最終着地推計)</div>
            <table style="width:100%; border-collapse:collapse; font-size:0.85rem; text-align:right;">
                <tr style="border-bottom:1px solid {Theme.border_light}; color:{Theme.text_muted}; text-align:right;">
                    <th style="text-align:left; padding:6px;">シナリオ / 更新頻度</th>
                    <th style="padding:6px; color:{Theme.primary};">現在(基準日)の残数</th>
                    <th style="padding:6px;">最終販売数</th>
                    <th style="padding:6px;">廃棄ロス (最終残数)</th>
                    <th style="padding:6px;">売上高</th>
                    <th style="padding:6px; color:{Theme.danger};">廃棄損 (原価¥{cost:,})</th>
                    <th style="padding:6px; font-weight:bold; color:{Theme.text_dark};">最終利益評価額</th>
                </tr>
                <tr style="border-bottom:1px solid {Theme.border_light};">
                    <td style="text-align:left; padding:8px; color:{Theme.text_muted};">全期間 定価維持 (ベースライン)</td>
                    <td style="padding:8px; color:{Theme.text_dark};">{total_stock_sel - current_sales}</td>
                    <td style="padding:8px;">{projected_sales_baseline} / {total_stock_sel}</td>
                    <td style="padding:8px;">{spoilage_qty_baseline}</td>
                    <td style="padding:8px;">¥{projected_revenue_baseline:,.0f}</td>
                    <td style="padding:8px; color:{Theme.danger};">-¥{spoilage_cost_baseline:,.0f}</td>
                    <td style="padding:8px; font-weight:bold; color:{Theme.text_muted}; font-size:1rem;">¥{net_profit_baseline:,.0f}</td>
                </tr>
                <tr style="background:#f4f6f8;">
                    <td style="text-align:left; padding:8px; font-weight:bold; color:{Theme.primary};">戦略適用 ({compare_mode})</td>
                    <td style="padding:8px; font-weight:bold; color:{Theme.text_dark};">{total_stock_sel - current_sales}</td>
                    <td style="padding:8px; font-weight:bold;">{projected_sales} / {total_stock_sel}</td>
                    <td style="padding:8px; font-weight:bold;">{spoilage_qty_strategy}</td>
                    <td style="padding:8px; font-weight:bold;">¥{projected_revenue_strategy:,.0f}</td>
                    <td style="padding:8px; font-weight:bold; color:{Theme.danger};">-¥{spoilage_cost_strategy:,.0f}</td>
                    <td style="padding:8px; font-weight:bold; color:{Theme.text_dark}; font-size:1.1rem;">¥{net_profit_strategy:,.0f}</td>
                </tr>
            </table>
            <div style="text-align:right; margin-top:12px; font-size:1.1rem; font-weight:bold;">
                ベースライン比 効果: {lift_text}
            </div>
        </div>
        """, unsafe_allow_html=True)

    # === 最大単価の計算 (Y軸上限用) ===
    overall_max_price = base_price if 'base_price' in locals() else 10000
    if 'daily_price' in locals() and not daily_price.empty:
        overall_max_price = max(overall_max_price, daily_price["sold_price"].max())
    if 'sim_prices' in locals() and sim_prices:
        overall_max_price = max(overall_max_price, max(sim_prices))
    y_price_upper_limit = overall_max_price * 1.5

    # グラフのレイアウト調整（X軸を負数から0へ向かうようにする）
    light_layout(fig_curve)
    
    # 累計販売率（上段: row=1）
    fig_curve.update_xaxes(
        range=[-90, 5], 
        tickfont=dict(color="black"),
        row=1, col=1
    )
    fig_curve.update_yaxes(
        title_text="累計販売率 (%)", 
        range=[0, 100], 
        title_font=dict(color="black", size=15, weight="bold"), 
        tickfont=dict(color="black", size=13), 
        row=1, col=1
    )
    
    # 販売単価（下段: row=2）
    fig_curve.update_xaxes(
        title_text="残り日数 (出発日まで)", 
        range=[-90, 5], 
        title_font=dict(color="black", size=15, weight="bold"),
        tickfont=dict(color="black", size=13),
        row=2, col=1
    )
    fig_curve.update_yaxes(
        title_text="販売単価 (¥)", 
        range=[0, y_price_upper_limit],
        title_font=dict(color="black", size=15, weight="bold"),
        tickfont=dict(color="black", size=13),
        row=2, col=1
    )
    
    fig_curve.update_layout(
        hovermode="x unified",
        showlegend=False,  # 右カラムにカスタム凡例を配置するため非表示
        margin=dict(r=20, b=40, t=20),
        height=700
    )
    
    # === [追加] 価格カレンダーとアノテーションの生成 ===
    calendar_html = ""
    if current_lead_day < 0 and 'sim_prices' in locals() and len(sim_prices) > 0:
        blocks = []
        current_block_price = sim_prices[0]
        current_block_start_idx = 0
        for i in range(1, len(sim_prices)):
            if sim_prices[i] != current_block_price:
                blocks.append((current_block_start_idx, i - 1, current_block_price))
                current_block_price = sim_prices[i]
                current_block_start_idx = i
        blocks.append((current_block_start_idx, len(sim_prices) - 1, current_block_price))
        
        sold_out_idx = None
        for i, s_count in enumerate(sim_sales_count):
            if s_count >= total_stock_sel:
                sold_out_idx = i
                break
                
        text_x = []
        text_y = []
        texts = []
        calendar_cards = []
        week_kanji = ["月", "火", "水", "木", "金", "土", "日"]
        
        from datetime import timedelta
        
        for (start_idx, end_idx, price) in blocks:
            # 既に完売している期間は表示しない
            if sold_out_idx is not None and start_idx >= sold_out_idx:
                break
            
            display_end_idx = end_idx
            if sold_out_idx is not None and end_idx >= sold_out_idx:
                display_end_idx = sold_out_idx
            
            # グラフ内アノテーション生成 (期間の中央にテキスト描画)
            mid_idx = (start_idx + display_end_idx) // 2
            text_x.append(sim_days[mid_idx])
            text_y.append(price)
            texts.append(f"<b>¥{price:,.0f}</b>")
            
            # カレンダーリスト用の期間日付算出
            start_date = dep_date + timedelta(days=int(sim_days[start_idx]))
            end_date = dep_date + timedelta(days=int(sim_days[display_end_idx]))
            
            start_str = f"{start_date.month}/{start_date.day}({week_kanji[start_date.weekday()]})"
            if start_idx == display_end_idx:
                date_str = start_str
            else:
                end_str = f"{end_date.month}/{end_date.day}({week_kanji[end_date.weekday()]})"
                date_str = f"{start_str} 〜 {end_str}"
            
            is_sold_out_block = (sold_out_idx is not None and sold_out_idx <= end_idx)
            badge = f"<span style='background:{Theme.success}; color:white; padding:2px 6px; border-radius:4px; font-size:0.75rem; margin-left:6px;'>🎉完売予測</span>" if is_sold_out_block else ""
            
            # ▼ HTMLインデントがMarkdownのコードブロックとして解釈されないよう、行頭から記述します
            calendar_cards.append(
f"""<div style="background:white; border-left:4px solid {Theme.warning}; border-radius:4px; padding:12px; margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">
<div style="font-size:0.85rem; color:{Theme.text_muted}; margin-bottom:6px;">📅 {date_str} {badge}</div>
<div style="font-size:1.15rem; font-weight:bold; color:{Theme.text_dark};">¥{price:,.0f}</div>
</div>"""
            )
            
        # アノテーション（テキスト）をグラフ本体(row=2)に追加描画
        if texts:
            fig_curve.add_trace(go.Scatter(
                x=text_x, y=text_y,
                mode="text",
                text=texts,
                textposition="top center",
                textfont=dict(color="#d97706", size=14, weight="bold"), # 単価線に近い濃い警告色
                showlegend=False,
                hoverinfo="skip"
            ), row=2, col=1)
            
        cards_html = "".join(calendar_cards)


    # カスタム凡例の構築 (Plotlyとは独立したHTML)
    # ▼ Markdownコードブロックとして解釈されないよう行頭から記述
    custom_legend_html = f"""<div style="background:white; padding:15px; border-radius:8px; border:1px solid #e2e8f0; margin-bottom:15px; flex-shrink:0;">
<div style="font-weight:bold; color:{Theme.text_dark}; margin-bottom:10px; font-size:0.95rem;">📊 実績</div>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:rgba(148,163,184,0.8); border-top:2px dashed rgba(148,163,184,0.8);"></div> 過去実績(平均)
</div>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:{Theme.chart_accent};"></div> 実績値
</div>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:15px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:{Theme.warning};"></div> 販売単価(実績)
</div>

<div style="font-weight:bold; color:{Theme.text_dark}; margin-bottom:10px; font-size:0.95rem;">📈 累計販売率推移</div>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:{Theme.primary}; border-top:2px dotted {Theme.primary};"></div> 予測推移 ({compare_mode})
</div>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:15px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:rgba(148,163,184,0.8); border-top:2px dotted rgba(148,163,184,0.8);"></div> 定価据え置き予測
</div>

<div style="font-weight:bold; color:{Theme.text_dark}; margin-bottom:10px; font-size:0.95rem;">💴 販売単価推移</div>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:{Theme.warning}; border-top:2px dotted {Theme.warning};"></div> 予測設定単価 ({compare_mode})
</div>
<div style="display:flex; align-items:center; gap:8px; font-size:0.85rem; color:{Theme.text_sec};">
<div style="width:20px; height:2px; background:rgba(148,163,184,0.8); border-top:2px dotted rgba(148,163,184,0.8);"></div> 定価ライン
</div>
</div>"""

    # カレンダーのHTML構築
    cards_html = "".join(calendar_cards) if 'calendar_cards' in locals() and calendar_cards else ""
    calendar_container_html = f"""<div style="background:{Theme.bg_hover}; padding:15px; border-radius:8px; display:flex; flex-direction:column; flex-grow:1; overflow-y:auto;">
<div style="font-weight:bold; color:{Theme.primary}; margin-bottom:15px; font-size:1.05rem; display:flex; align-items:center; gap:6px;">
<span>🎯 今後の設定価格カレンダー</span>
</div>
<div style="display:flex; flex-direction:column; gap:8px;">
{cards_html if cards_html else '<div style="color:#64748b; font-size:0.9rem;">予測データまたは予定がありません。</div>'}
</div>
</div>"""

    # --- 四分割レイアウト (左3.5：右1) ---
    col_chart, col_side = st.columns([3.5, 1])
    
    with col_chart:
        # 左側（上：販売率推移、下：販売単価）
        st.plotly_chart(Theme.apply_chart_theme(fig_curve), use_container_width=True, key="tracking_curve_chart_unique")
    
    with col_side:
        # 右側（グラフのheight=700pxと合わせるためのラッパーコンテナ）
        wrapper_html = f"""
        <div style="height: 700px; display: flex; flex-direction: column;">
            {custom_legend_html}
            {calendar_container_html}
        </div>
        """
        st.markdown(wrapper_html, unsafe_allow_html=True)
    
    st.markdown("---")

    # --- [追加] 詳細設定・チューニング ---
    st.markdown("---")
    with st.expander("🛠 アルゴリズム詳細設定（開発者・高度な調整用）", expanded=False):
        st.markdown(f"<p style='color:{Theme.text_muted};'>※ これらの値はリファクタリングにより global 定数から取得されています。将来的にここから上書き可能にする予定です。</p>", unsafe_allow_html=True)
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("**在庫判定しきい値**")
            st.number_input("希少プレミアム閾値", value=INV_THRESHOLD_PREMIUM, disabled=True)
            st.number_input("需要増加閾値", value=INV_THRESHOLD_HIGH, disabled=True)
            st.number_input("標準価格閾値", value=INV_THRESHOLD_NORMAL, disabled=True)
        with col_t2:
            st.markdown("**期間判定しきい値**")
            st.number_input("直前割引（日）", value=TIME_THRESHOLD_LAST_MIN, disabled=True)
            st.number_input("需要ピーク（日）", value=TIME_THRESHOLD_PEAK, disabled=True)
            st.number_input("標準期間（日）", value=TIME_THRESHOLD_NORMAL, disabled=True)
            
        st.markdown("**スコアリング重み（総合スコア）**")
        cw1, cw2, cw3, cw4 = st.columns(4)
        cw1.metric("MAPE", f"{int(SCORE_WEIGHT_MAPE*100)}%")
        cw2.metric("Lift", f"{int(SCORE_WEIGHT_LIFT*100)}%")
        cw3.metric("Spoilage", f"{int(SCORE_WEIGHT_SPOILAGE*100)}%")
        cw4.metric("DirAcc", f"{int(SCORE_WEIGHT_DIR_ACC*100)}%")

        st.markdown("**商品分類判定基準**")
        cb1, cb2, cb3 = st.columns(3)
        cb1.number_input("大人気販売率", value=CLASS_POPULAR_THRESHOLD, disabled=True)
        cb2.number_input("ニッチ期間（日）", value=CLASS_NICHE_DAYS, disabled=True)
        cb3.number_input("ニッチ集中率", value=CLASS_NICHE_RATIO, disabled=True)

# 🧪 Tab 5: Custom Simulator
if selected_tab == "🧪 販売シミュレータ（パッケージ）":
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
        st.markdown(f"<div style='margin-bottom: -15px;'><span style='background:#e0f2fe; color:{Theme.info}; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;'>✨ AI事前探索</span> <span style='font-size:0.8rem; color:{Theme.text_muted};'>このペアの利益が最大化する割引額は <b>¥{auto_discount_amt:,}</b> です</span></div>", unsafe_allow_html=True)
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
            <div style='background:rgba(99,102,241,0.1); border:1px solid {Theme.primary}; border-radius:12px; padding:15px;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:8px; letter-spacing:0.05em;'>📦 パッケージ価格構成</div>
                <table style='width:100%; font-size:0.85rem; border-collapse:collapse;'>
                    <tr>
                        <td style='padding:4px 0; color:{Theme.text_sec};'>🏨 {target_hotel['name'][:20]}</td>
                        <td style='text-align:right; color:{Theme.text_sec};'>¥{h_price:,}</td>
                        <td style='text-align:right; color:{Theme.danger}; font-size:0.75rem;'>&nbsp;(-¥{int(h_discount):,})</td>
                    </tr>
                    <tr>
                        <td style='padding:4px 0; color:{Theme.text_sec};'>✈️ {target_flight['name'][:20]}</td>
                        <td style='text-align:right; color:{Theme.text_sec};'>¥{f_price:,}</td>
                        <td style='text-align:right; color:{Theme.danger}; font-size:0.75rem;'>&nbsp;(-¥{int(f_discount):,})</td>
                    </tr>
                    <tr style='border-top:1px solid {Theme.text_sec};'>
                        <td style='padding:8px 0 4px; color:#818cf8; font-weight:700;'>🎁 定価合計</td>
                        <td style='text-align:right; color:#818cf8; font-size:0.9rem; font-weight:600;'>¥{pkg_price_before_disc:,}</td>
                        <td></td>
                    </tr>
                    <tr>
                        <td style='padding:4px 0; color:{Theme.success_light}; font-weight:700;'>🏷️ 割引後パッケージ価格</td>
                        <td style='text-align:right; color:{Theme.success_light}; font-size:1.2rem; font-weight:900;'>¥{pkg_price_after_disc:,}</td>
                        <td></td>
                    </tr>
                </table>
            </div>
            """, unsafe_allow_html=True)
            
        with si_col2:
            h_stock_pct = int(h_stock / target_hotel['total_stock'] * 100) if target_hotel['total_stock'] else 0
            f_stock_pct = int(f_stock / target_flight['total_stock'] * 100) if target_flight['total_stock'] else 0
            st.markdown(f"""
            <div style='background:{Theme.white}; border:1px solid {Theme.border_light}; border-radius:12px; padding:15px; height:100%;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:10px; letter-spacing:0.05em;'>📦 現在の残件数 (基準日時点)</div>
                <div style='margin-bottom:10px;'>
                    <div style='font-size:0.75rem; color:{Theme.text_sec};'>🏨 ホテル</div>
                    <div style='font-size:1.4rem; font-weight:800; color:{Theme.text_sec};'>{h_stock}<span style='font-size:0.75rem; color:{Theme.text_sec};'> / {target_hotel['total_stock']}室</span></div>
                    <div style='background:{Theme.border_light}; border-radius:4px; height:6px; margin-top:4px;'>
                        <div style='background:{Theme.primary}; height:6px; border-radius:4px; width:{h_stock_pct}%;'></div>
                    </div>
                    <div style='font-size:0.7rem; color:{Theme.text_muted}; margin-top:2px;'>残存率 {h_stock_pct}%</div>
                </div>
                <div>
                    <div style='font-size:0.75rem; color:{Theme.text_sec};'>✈️ フライト</div>
                    <div style='font-size:1.4rem; font-weight:800; color:{Theme.text_sec};'>{f_stock}<span style='font-size:0.75rem; color:{Theme.text_sec};'> / {target_flight['total_stock']}席</span></div>
                    <div style='background:{Theme.border_light}; border-radius:4px; height:6px; margin-top:4px;'>
                        <div style='background:{Theme.primary}; height:6px; border-radius:4px; width:{f_stock_pct}%;'></div>
                    </div>
                    <div style='font-size:0.7rem; color:{Theme.text_muted}; margin-top:2px;'>残存率 {f_stock_pct}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with si_col3:
            st.markdown(f"""
            <div style='background:{Theme.white}; border:1px solid {Theme.border_light}; border-radius:12px; padding:15px; height:100%;'>
                <div style='font-size:0.75rem; color:#818cf8; margin-bottom:10px; letter-spacing:0.05em;'>⏳ 出発まで {lead_days}日</div>
                <div style='margin-bottom:8px;'>
                    <div style='font-size:0.75rem; color:{Theme.text_sec};'>🪨 対象ホテル</div>
                    <div style='font-size:0.8rem; color:{Theme.text_sec};'>{target_hotel['name'][:18]}</div>
                    <div style='font-size:0.7rem; color:{Theme.text_muted};'>出発日: {target_hotel.get('departure_date', '---')}</div>
                </div>
                <div>
                    <div style='font-size:0.75rem; color:{Theme.text_sec};'>✈ 対象フライト</div>
                    <div style='font-size:0.8rem; color:{Theme.text_sec};'>{target_flight['name'][:18]}</div>
                    <div style='font-size:0.7rem; color:{Theme.text_muted};'>出発日: {target_flight.get('departure_date', '---')}</div>
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
            config=ai_config,
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
            config=ai_config,
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
            h_item_sim_rule, f_item_sim_rule, int(total_discount), lead_days, market_condition, config=ai_config, reference_date=v_today
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
            config=ai_config,
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
            config=ai_config,
            reference_date=v_today,
            strategy="demand_based"
        )
        h_item_sim_demand = h_item_sim_rule.copy()
        h_item_sim_demand["current_price"] = h_pricing_demand["final_price"]
        f_item_sim_demand = f_item_sim_rule.copy()
        f_item_sim_demand["current_price"] = f_pricing_demand["final_price"]
        f_item_sim_demand["velocity_ratio"] = f_pricing_demand.get("velocity_ratio") or 1.0
        sim_demand = simulate_sales_scenario(
            h_item_sim_demand, f_item_sim_demand, int(total_discount), lead_days, market_condition, config=ai_config, reference_date=v_today
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
            line=dict(color='rgba(100, 116, 139, 0.5)', width=2, dash='dash')
        ), secondary_y=False)

        # ─── 過去実績部分 (売上 - 左軸) ───
        if past_x:
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_revenue, name="💰 累積売上実績 (全体合算)",
                line=dict(color='#94a3b8', width=3)
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
                line=dict(color='rgba(59, 130, 246, 0.6)', width=2, dash='dot') # blue-500
            ), secondary_y=True)
            fig_sim.add_trace(go.Scatter(
                x=past_x, y=past_f_stock_pct, name="✈️ 残席割合実績 (フライト)",
                line=dict(color='rgba(168, 85, 247, 0.6)', width=2, dash='dot') # purple-500
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
            line_color_rev = Theme.color_pos
            line_color_rev_sub = hex_to_rgba(Theme.color_pos, 0.5)
            line_color_h = Theme.chart_h_alpha
            line_color_f = Theme.chart_f_alpha
            name_rev = "💰 予測売上 全体 (需要予測ハイブリッド)"
            name_rev_h = "💰 予測売上 ホテル (需要予測ハイブリッド)"
            name_rev_f = "💰 予測売上 フライト (需要予測ハイブリッド)"
            name_h = "🏨 予測残室割合 (需要予測ハイブリッド)"
            name_f = "✈️ 予測残席割合 (需要予測ハイブリッド)"
        else:
            line_color_rev = Theme.color_neg
            line_color_rev_sub = hex_to_rgba(Theme.color_neg, 0.5)
            line_color_h = Theme.color_neg
            line_color_f = "#f97316" # orange-500 (Add this to theme later if needed, or keep for now)
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
            fig_sim.add_vline(x=past_x[-1], line_width=2, line_dash="dash", line_color=Theme.primary)
            fig_sim.add_annotation(
                x=past_x[-1], y=1.0, yref="paper",
                text="本日 (実績/予測 境界)",
                showarrow=False,
                font=dict(color=Theme.primary, size=10),
                xanchor="right", yanchor="bottom"
            )

        # ─── その他の補助線（マイルストーン） ───
        # 例：D-30 (パッケージ用キャンセル無料終了の目安)
        d30_label = "D-30"
        if d30_label in full_x:
            fig_sim.add_vline(x=d30_label, line_width=1, line_dash="dot", line_color=Theme.chart_line_muted)
            fig_sim.add_annotation(
                x=d30_label, y=0.05, yref="paper",
                text="D-30",
                showarrow=False,
                font=dict(color=Theme.text_muted, size=10),
                xanchor="left", yanchor="bottom"
            )
            
        # 例：D-14 (単品航空券需要ピークなど)
        d14_label = "D-14"
        if d14_label in full_x:
            fig_sim.add_vline(x=d14_label, line_width=1, line_dash="dot", line_color=Theme.chart_line_muted)
            fig_sim.add_annotation(
                x=d14_label, y=0.05, yref="paper",
                text="D-14",
                showarrow=False,
                font=dict(color=Theme.text_muted, size=10),
                xanchor="left", yanchor="bottom"
            )

        # レイアウト調整
        light_layout(fig_sim, secondary_y=True)
        fig_sim.update_layout(
            xaxis=dict(
                title="タイムライン（右端 = 期限・出発日 D-0）",
                gridcolor=Theme.border_light,
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

        fig_sim.update_yaxes(title_text="累積金額 (円)", secondary_y=False, range=[0, max_y], gridcolor=Theme.border_light, tickformat=",d")
        fig_sim.update_yaxes(title_text="残在庫割合 (%)", secondary_y=True, range=[0, 105], gridcolor="rgba(0,0,0,0)", tickformat=".1f")

        st.plotly_chart(Theme.apply_chart_theme(fig_sim), use_container_width=True, key="sim_timeseries_chart")
        
        # --- 4. 決着 KPI ---
        diff = res_sel - res_n
        
        st.markdown("#### 🏁 予測結果・着地点比較（Day 0 廃棄損計上済み）")
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            st.markdown(f"""
            <div style='background:{Theme.alert_info_bg}; border:1px solid {Theme.border_dark}; border-radius:12px; padding:15px; text-align:center;'>
                <div style='font-size:0.8rem; color:{Theme.text_muted};'>① 現状維持 (固定価格・何もしない) の着地点</div>
                <div style='font-size:1.5rem; font-weight:800; color:{Theme.text_main};'>¥{int(res_n):,}</div>
                <div style='font-size:0.8rem; margin-top:10px; color:{Theme.text_sec};'>🏨 販売: {int(total_sold_n_h)}室 / 売れ残り: {int(curr_n_h_stock_fin)}室</div>
                <div style='font-size:0.8rem; color:{Theme.text_sec};'>✈️ 販売: {int(total_sold_n_f)}席 / 売れ残り: {int(curr_n_f_stock_fin)}席</div>
            </div>
            """, unsafe_allow_html=True)
        with ck2:
            h_sold_sel_total = int(total_sold_b_pkg + total_sold_sel_h_solo)
            f_sold_sel_total = int(total_sold_b_pkg + total_sold_sel_f_solo)
            h_unsold_sel = int(curr_b_h_stock)
            f_unsold_sel = int(flight_stock_b)
            
            box_bg = Theme.color_pos_light if is_hybrid else Theme.color_neg_light
            box_bc = Theme.color_pos if is_hybrid else Theme.color_neg
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
            diff_color = Theme.color_pos if diff >= 0 else Theme.color_neg
            diff_bg = Theme.color_pos_light if diff >= 0 else Theme.color_neg_light
            st.markdown(f"""
            <div style='background:{diff_bg}; border:1px solid {diff_color}; border-radius:12px; padding:15px; text-align:center; box-shadow: {Theme.shadow_info};'>
                <div style='font-size:0.8rem; color:{diff_color};'>トータル収益改善の見込み</div>
                <div style='font-size:1.5rem; font-weight:900; color:{diff_color};'>+¥{int(diff):,}</div>
                <div style='font-size:0.8rem; margin-top:10px; color:{Theme.text_sec};'>（リスク回避後の純増利益）</div>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown(f"""
        <div style='background:#eef2ff; border:1px solid {Theme.alert_info_border}; border-radius:10px; padding:15px; margin-top:20px; margin-bottom:20px;'>
            <h5 style='margin-top:0; color:{Theme.alert_info_text};'>💡 AI 戦略アドバイス</h5>
            <p style='font-size:0.9rem; color:{Theme.text_main};'>
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
            st.dataframe(light_dataframe(pd.DataFrame(pl_data)), use_container_width=True, hide_index=True)

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
            st.dataframe(light_dataframe(pd.DataFrame(bd_data)), use_container_width=True, hide_index=True)
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
            st.dataframe(light_dataframe(pd.DataFrame(param_data)), use_container_width=True, hide_index=True)

    else:
        st.info("比較対象となるホテルとフライトをそれぞれ選択してください。")

# ══════════════════════════════════════════════════════════════════
# Tab 6: 🛒 Procurement & Pricing Strategy
# ══════════════════════════════════════════════════════════════════
if selected_tab == "🛒 事前仕入と初期価格の最適化":
    # 遅延インポート（依存関係やメモリ節約のため）
    from pricing_engine import estimate_demand_and_elasticity, optimize_procurement_strategy
    
    st.markdown("### 🛒 Procurement & Pricing Strategy (事前仕入・初期価格最適化)")
    st.markdown('<p class="section-description">指定商品の過去の実績データから基準需要と価格弾力性を推定し、目標利益を最大化する初期仕入セット数と販売価格をシミュレーションします。</p>', unsafe_allow_html=True)
    
    # 商品選択:
    available_products = sorted(inv_df["name"].unique().tolist())
    selected_prod = st.selectbox("分析対象の商品を選択", available_products, help="過去の予約実績に基づいて需要と価格弾力性を推計します")
    
    st.markdown("---")
    
    # デフォルトの需要と弾力性を推計
    with st.spinner("過去データよりパラメータを推計中..."):
        est_demand, est_elasticity = estimate_demand_and_elasticity(selected_prod, DB_PATH)
    
    # 対象商品のベース価格をデフォルト値として取得
    prod_info = inv_df[inv_df["name"] == selected_prod]
    default_base_price = int(prod_info.iloc[0]["base_price"]) if not prod_info.empty else 30000
    default_max_cap = int(prod_info.iloc[0]["total_stock"]) if not prod_info.empty else 150
            
    # ユーザー入力フォーム
    st.markdown("#### ⚙️ 前提条件の設定")
    col_p1, col_p2, col_p3 = st.columns(3)
    
    with col_p1:
        st.markdown("**市場の反応**")
        ui_base_demand = st.number_input("基準需要（件/期間）※推計値", min_value=1, max_value=10000, value=est_demand, step=10, help="過去の平均販売数から推測された基本需要です")
        ui_elasticity = st.slider("価格弾力性 ※推計値", min_value=-5.0, max_value=-0.1, value=est_elasticity, step=0.1, help="価格変化に対する需要の敏感度。通常は負の値です。")
        ui_ref_price = st.number_input("基準となる価格 (円)", min_value=1000, max_value=500000, value=default_base_price, step=1000)
    
    with col_p2:
        st.markdown("**制約とコスト**")
        ui_max_capacity = st.number_input("仕入上限数（ハード限界）", min_value=10, max_value=1000, value=default_max_cap, step=10)
        ui_fixed_cost = st.number_input("固定費（全体）", min_value=0, max_value=10000000, value=0, step=10000)
        ui_var_cost = st.number_input("１ユニットあたりの変動費 (仕入原価等)", min_value=0, max_value=300000, value=int(default_base_price * 0.9), step=1000)
        
    with col_p3:
        st.markdown("**シミュレーション実行**")
        st.info("左記のパラメータに基づいて、「利益が最大」となるベストな仕入数と初期ベース価格を導出します。")
        run_sim = st.button("🚀 最適化シミュレーションを実行", type="primary", use_container_width=True)
        
    if run_sim:
        res = optimize_procurement_strategy(
            base_demand=ui_base_demand,
            reference_price=ui_ref_price,
            elasticity=ui_elasticity,
            max_capacity=ui_max_capacity,
            fixed_cost=ui_fixed_cost,
            variable_cost=ui_var_cost
        )
        
        st.markdown("---")
        st.markdown("#### 🎯 最適化結果")
        
        # KPIカード
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            st.markdown(f"""
            <div style="background:{Theme.grad_ai}; border:1px solid {Theme.border_ai_alpha}; border-radius:15px; padding:20px; text-align:center;">
                <div style="font-size:0.9rem; color:{Theme.text_dark}; font-weight:700;">推奨ベース販売価格</div>
                <div style="font-size:2rem; font-weight:900; color:{Theme.chart_accent};">¥{res['best_base_price']:,}</div>
            </div>
            """, unsafe_allow_html=True)
        with rc2:
            st.markdown(f"""
            <div style="background:{Theme.grad_info}; border:1px solid {Theme.border_info_alpha}; border-radius:15px; padding:20px; text-align:center;">
                <div style="font-size:0.9rem; color:{Theme.text_dark}; font-weight:700;">推奨初期仕入数</div>
                <div style="font-size:2rem; font-weight:900; color:{Theme.info};">{res['best_procurement_stock']:,} ユニット</div>
            </div>
            """, unsafe_allow_html=True)
        with rc3:
            st.markdown(f"""
            <div style="background:{Theme.bg_success_alpha}; border:1px solid {Theme.border_success_alpha}; border-radius:15px; padding:20px; text-align:center;">
                <div style="font-size:0.9rem; color:{Theme.text_dark}; font-weight:700;">予想最大利益</div>
                <div style="font-size:2rem; font-weight:900; color:{Theme.success};">¥{res['expected_max_profit']:,}</div>
            </div>
            """, unsafe_allow_html=True)
            
        # グラフ表示
        st.markdown("#### 📈 価格弾力性に基づく利益・売上シミュレーションカーブ")
        df_sim = res['simulation_data']
        from plotly.subplots import make_subplots
        
        fig_curve = make_subplots(specs=[[{"secondary_y": True}]])
        
        # 利益カーブ (主軸)
        fig_curve.add_trace(go.Scatter(
            x=df_sim['price'], y=df_sim['profit'], name="予測利益",
            mode='lines', line=dict(color=Theme.success, width=4)
        ), secondary_y=False)
        
        # 売上カーブ (主軸)
        fig_curve.add_trace(go.Scatter(
            x=df_sim['price'], y=df_sim['revenue'], name="予測売上",
            mode='lines', line=dict(color=Theme.info, width=2, dash='dash')
        ), secondary_y=False)
        
        # 需要カーブ (副軸)
        fig_curve.add_trace(go.Scatter(
            x=df_sim['price'], y=df_sim['demand'], name="予測需要数",
            mode='lines', line=dict(color=Theme.chart_accent, width=2, dash='dot')
        ), secondary_y=True)
        
        # ピーク値（最適価格）にマーカー
        fig_curve.add_trace(go.Scatter(
            x=[res['best_base_price']], y=[res['expected_max_profit']], 
            mode='markers+text', name="利益最大化ポイント",
            marker=dict(color=Theme.danger, size=12, symbol='star'),
            text=[f"Peak: ¥{res['expected_max_profit']:,}"], textposition="top center"
        ), secondary_y=False)
        
        light_layout(fig_curve, secondary_y=True)
        fig_curve.update_layout(
            xaxis_title="設定販売価格 (円)",
            hovermode="x unified",
            height=500
        )
        fig_curve.update_yaxes(title_text="金額 (円)", secondary_y=False, tickformat=",d")
        fig_curve.update_yaxes(title_text="需要数 (ユニット)", secondary_y=True, showgrid=False)
        
        st.plotly_chart(Theme.apply_chart_theme(fig_curve), use_container_width=True)

# ══════════════════════════════════════════════════════════════════
# Tab 5: 🔬 販売モデル設定
# ══════════════════════════════════════════════════════════════════
elif selected_tab == "🔬 販売モデル設定":
    st.markdown("## 🔬 販売モデル設定 (A/B バックテスト)")
    st.markdown("過去の販売実績に基づき、各商品カテゴリに対してどのアルゴリズム（モデル）が最も収益への貢献度が高いかを客観的に評価し、最適な設定を保存します。")
    
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    
    # 強制リロード (Streamlitのキャッシュ対策)
    if "model_evaluator" in sys.modules:
        del sys.modules["model_evaluator"]
        
    from model_evaluator import (
        get_product_classification, save_product_classification,
        run_batch_evaluation, save_model_setting, get_model_setting
    )
    
    # ─── データロード ───
    # バックテストは全ての商品を対象とする（またはフィルターされたもの）
    bt_inv_df = inv_df.copy()
    bt_events_df = load_booking_events()
    
    st.markdown("---")
    
    # === Section 0: 商品分類マスタ設定 ===
    st.markdown("### 🏷️ Section 0: 商品分類マスタ設定")
    st.write("各商品を「ホテル/フライト」×「大人気/安定/ニッチ」のマトリクスに分類します。ここでの設定はすべての推論のベースとなります。")

    # nameとitem_typeの組み合わせで重複排除
    unique_products_df = bt_inv_df.drop_duplicates(subset=["name", "item_type"])

    # 現在の分類をロード
    cls_records = []
    for _, row in unique_products_df.iterrows():
        it_type = row["item_type"]
        p_name = row["name"]
        
        # 最終販売率の計算 (過去の全履歴に基づく平均的着地実績)
        item_sales = bt_events_df[bt_events_df["inventory_id"].isin(
            bt_inv_df[(bt_inv_df["name"] == p_name) & (bt_inv_df["item_type"] == it_type)]["id"]
        )]
        if not item_sales.empty:
            total_sold = item_sales["quantity"].sum()
            total_stock_all = bt_inv_df[(bt_inv_df["name"] == p_name) & (bt_inv_df["item_type"] == it_type)]["total_stock"].sum()
            final_sales_rate = (total_sold / max(1, total_stock_all)) * 100
        else:
            final_sales_rate = 0.0
            
        # カタカナ変換
        display_type = "ホテル" if it_type == "hotel" else ("フライト" if it_type == "flight" else it_type)

        c_data = get_product_classification(p_name, it_type)
        if c_data:
            char = c_data["characteristic"]
            src = c_data["source"]
        else:
            char = "stable" # デフォルト
            src = "未設定"
            
        # 登録モデル名の取得 (設定元の代わりに表示)
        saved_setting = get_model_setting(it_type, char)
        if saved_setting:
            base_strat = saved_setting["strategy"]
            # 過去に保存された等でscenario_nameがない場合は、デフォルトの戦略名を日本語化して表示
            fallback_name = "ルールベース" if base_strat == "rule_based" else ("需要予測ベース" if base_strat == "demand_forecast" else base_strat)
            model_name = saved_setting["config"].get("scenario_name", fallback_name)
        else:
            model_name = "未設定 (デフォルト)"
            
        # 特性の日本語マッピング (UI表示用)
        char_label = {"popular": "人気", "stable": "安定", "niche": "ニッチ"}.get(char, char)

        cls_records.append({
            "商品種別": display_type,
            "商品名": p_name,
            "モデルカテゴリ": char_label,
            "モデル種別": model_name,
            "最終販売率": f"{final_sales_rate:.1f}%",
            "_raw_type": it_type,
            "_raw_char": char
        })
    cls_df = pd.DataFrame(cls_records)

    # st.data_editor を用いて直接編集可能な表を表示
    # 内部データ（_raw_type 等）は hidden で保持して編集後に利用できるようにする工夫
    edited_cls_df = st.data_editor(
        cls_df,
        use_container_width=True,
        hide_index=True,
        column_order=["商品種別", "商品名", "モデルカテゴリ", "モデル種別", "最終販売率"],
        column_config={
            "商品種別": st.column_config.TextColumn("商品種別", disabled=True),
            "商品名": st.column_config.TextColumn("商品名", disabled=True),
            "モデルカテゴリ": st.column_config.SelectboxColumn(
                "モデルカテゴリ",
                help="商品特性を変更（人気 / 安定 / ニッチ）",
                options=["人気", "安定", "ニッチ"],
                required=True,
            ),
            "モデル種別": st.column_config.TextColumn("モデル種別", disabled=True),
            "最終販売率": st.column_config.TextColumn("過去の最終販売率", disabled=True),
        }
    )

    if st.button("💾 分類マスタを保存", type="primary"):
        with st.spinner("DBに分類を保存中..."):
            count = 0
            # 特性の逆マッピング (保存用)
            char_unmap = {"人気": "popular", "安定": "stable", "ニッチ": "niche"}
            
            for idx, row in edited_cls_df.iterrows():
                # DB保存用に元の英語コードへ戻す
                it_type = row["_raw_type"]
                p_name = row["商品名"]
                new_char_label = row["モデルカテゴリ"]
                new_char = char_unmap.get(new_char_label, "stable")
                
                # 古い値（_raw_char）から変わっている場合のみ更新
                if new_char != row["_raw_char"]:
                    save_product_classification(p_name, it_type, new_char, "manual")
                    count += 1
        st.success(f"{count}件の分類を保存しました！バックテストを実行するには下のシナリオ設定へお進みください。")
        import time
        time.sleep(1)
        st.rerun()

    st.markdown("---")

    # === Section 1: 評価シナリオ設定 ===
    st.markdown("### 🛠️ Section 1: パラメータ・評価指標の詳細設定")
    st.write("アルゴリズムの判定基準や、商品の分類しきい値、スコアリングの重み付けを微調整します。")

    # === スコア重み付け（優先度）設定 UI ===
    with st.expander("⚙️ 評価スコアの優先度・重み付け設定", expanded=False):
        st.markdown("<small>※自動最適化やスコア算出時に、どの指標を重視するかを設定します。（合計100になるように自動計算されます）</small>", unsafe_allow_html=True)
        w_col1, w_col2, w_col3 = st.columns(3)
        w_col4, w_col5, _ = st.columns(3)
        
        # デフォルトは「波形再現を最優先」する設定
        raw_w_mape = w_col1.slider("MAPE (全体の誤差の少なさ)", 0, 100, 40, 5, help="予測が実績からどれくらいブレないか")
        raw_w_dtw  = w_col2.slider("DTW (波形の似ている度合い)", 0, 100, 30, 5, help="グラフの形がどれくらい似ているか")
        raw_w_lift = w_col3.slider("Revenue Lift (収益改善)", 0, 100, 15, 5, help="ベースシナリオからの収益増加率")
        raw_w_spoil = w_col4.slider("Spoilage (廃棄量削減)", 0, 100, 10, 5, help="ベースシナリオからの廃棄ロス削減率")
        raw_w_dir  = w_col5.slider("Directional Acc (方向の一致)", 0, 100, 5, 5, help="実績が伸びた日に予測も伸びているか")
        
        total_raw_w = raw_w_mape + raw_w_dtw + raw_w_lift + raw_w_spoil + raw_w_dir
        if total_raw_w == 0: total_raw_w = 1 # ゼロ除算回避
        
        score_weights = {
            "score_weight_mape": raw_w_mape / total_raw_w,
            "score_weight_dtw": raw_w_dtw / total_raw_w,
            "score_weight_lift": raw_w_lift / total_raw_w,
            "score_weight_spoilage": raw_w_spoil / total_raw_w,
            "score_weight_dir_acc": raw_w_dir / total_raw_w
        }

    st.markdown("---")
    st.markdown("### 🧪 Section 2: シナリオ設定")
    st.write("特定のカテゴリに対して、複数のアルゴリズムやパラメータを組み合わせた「シナリオ」を定義し、比較テストを行います。")

    cat_options = edited_cls_df["商品種別"] + "---" + edited_cls_df["モデルカテゴリ"]
    cat_options = sorted(list(cat_options.unique()))

    if not cat_options:
        st.warning("商品データが存在しません。")
        st.stop()

    t_col1, t_col2 = st.columns([3, 2])
    target_category = t_col1.selectbox("🎯 カテゴリを設定", cat_options, help="このカテゴリに属する商品群に対して複数のシナリオをテストします。")
    t_item_display, t_char_display = target_category.split("---")
    
    # 選択された表示名から元のコードを復元
    item_type_unmap = {"ホテル": "hotel", "フライト": "flight"}
    t_item = item_type_unmap.get(t_item_display, t_item_display)
    
    char_unmap = {"人気": "popular", "安定": "stable", "ニッチ": "niche"}
    t_char = char_unmap.get(t_char_display, t_char_display)

    # 実績平均販売率を算出
    cat_products1 = edited_cls_df[(edited_cls_df["商品種別"] == t_item_display) & (edited_cls_df["モデルカテゴリ"] == t_char_display)]
    target_product_names = cat_products1["商品名"].tolist()
    
    # カテゴリに属する全商品の個別販売率を計算
    individual_rates = []
    category_inv_bt = bt_inv_df[(bt_inv_df["name"].isin(target_product_names)) & (bt_inv_df["item_type"] == t_item)]
    
    for _, row in category_inv_bt.iterrows():
        inv_id_bt = row["id"]
        total_stock_bt = row["total_stock"]
        if total_stock_bt > 0:
            booked_count_bt = bt_events_df[bt_events_df["inventory_id"] == inv_id_bt]["quantity"].sum()
            individual_rates.append(min(1.0, booked_count_bt / total_stock_bt))
            
    avg_sell_through_val = sum(individual_rates) / len(individual_rates) if individual_rates else 1.0
    
    global_target_sr = t_col2.slider(
        "最終目標販売率(%)", 1, 100, int(avg_sell_through_val * 100), 1,
        help="全シナリオで共通の目標値です。デフォルトはカテゴリ内商品の平均実績値です。"
    ) / 100.0
    
    # 共通設定に目標販売率を反映
    ai_config["target_sell_rate"] = global_target_sr

    with st.expander("⚙️ アルゴリズム・分類・スコアの詳細設定", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📏 在庫・時期の判定しきい値**")
            inv_p = st.number_input("希少プレミアム在庫率", 0.0, 1.0, float(ai_config["inv_threshold_premium"]), 0.05)
            inv_h = st.number_input("需要増加調整在庫率", 0.0, 1.0, float(ai_config["inv_threshold_high"]), 0.05)
            time_l = st.number_input("直前割引開始日", 0, 90, int(ai_config["time_threshold_last_min"]))
            ai_config["inv_threshold_premium"] = inv_p
            ai_config["inv_threshold_high"] = inv_h
            ai_config["time_threshold_last_min"] = time_l
            
        with c2:
            st.markdown("**🏷️ 商品分類の自動判定基準**")
            pop_t = st.number_input("大人気判定(販売率)", 0.0, 1.0, float(CLASS_POPULAR_THRESHOLD), 0.05)
            niche_d = st.number_input("ニッチ判定(直前期日数)", 1, 90, int(CLASS_NICHE_DAYS))
            niche_r = st.number_input("ニッチ判定(直前期売上比)", 0.0, 1.0, float(CLASS_NICHE_RATIO), 0.05)
            # これらはグローバル定数のため、再計算時に参照されるようにai_configへも入れる
            ai_config["class_popular_threshold"] = pop_t
            ai_config["class_niche_days"] = niche_d
            ai_config["class_niche_ratio"] = niche_r

    if "eval_scenarios" not in st.session_state:
        # 深いコピーを使用して各シナリオの設定を完全に独立させる
        st.session_state["eval_scenarios"] = [
            {"id": "A", "name": "安定・ルールベース", "strategy": "rule_based", "config": copy.deepcopy(ai_config)},
            {"id": "B", "name": "強気・ルールベース", "strategy": "rule_based", "config": copy.deepcopy(ai_config)},
            {"id": "C", "name": "標準・需要予測", "strategy": "demand_forecast", "config": copy.deepcopy(ai_config)},
            {"id": "D", "name": "早割特化・需要予測", "strategy": "demand_forecast", "config": copy.deepcopy(ai_config)},
            {"id": "E", "name": "直前特化・需要予測", "strategy": "demand_forecast", "config": copy.deepcopy(ai_config)}
        ]
        
        # 個別調整
        st.session_state["eval_scenarios"][1]["config"]["peak_markup"] = 1.30
        st.session_state["eval_scenarios"][1]["config"]["last_minute_discount"] = 0.60
        st.session_state["eval_scenarios"][2]["config"]["decay_pattern"] = "standard"
        st.session_state["eval_scenarios"][3]["config"]["decay_pattern"] = "early_rush"
        st.session_state["eval_scenarios"][3]["config"]["decay_k"] = 10.0
        st.session_state["eval_scenarios"][4]["config"]["decay_pattern"] = "last_minute_rush"
        st.session_state["eval_scenarios"][4]["config"]["decay_k"] = 25.0

    def add_scenario():
        new_id = chr(65 + len(st.session_state["eval_scenarios"]))
        st.session_state["eval_scenarios"].append({
            "id": new_id, "name": f"シナリオ {new_id}", "strategy": "demand_forecast", "config": ai_config.copy()
        })
        
    def clear_scenarios():
        if "eval_scenarios" in st.session_state:
            del st.session_state["eval_scenarios"]

    with st.expander("⚙️ 個別シナリオの追加・編集", expanded=False):
        sc_col1, sc_col2, _ = st.columns([2, 2, 4])
        sc_col1.button("➕ 新しいシナリオを追加", on_click=add_scenario)
        sc_col2.button("🗑️ シナリオをリセット", on_click=clear_scenarios)

        scenarios = st.session_state["eval_scenarios"]

        # シナリオ入力UI
        for i, sc in enumerate(scenarios):
            with st.expander(f"シナリオ {sc['id']}: {sc['name']} ({'ルールベース' if sc['strategy']=='rule_based' else '需要予測'})", expanded=(i==0)):
                c1, c2 = st.columns([2, 1])
                sc["name"] = c1.text_input("シナリオ名", value=sc["name"], key=f"sc_name_{i}")
                sc["strategy"] = c2.selectbox("アルゴリズム", ["rule_based", "demand_forecast"], 
                                              index=0 if sc["strategy"]=="rule_based" else 1,
                                              format_func=lambda x: "ルールベース" if x=="rule_based" else "需要予測ベース",
                                              key=f"sc_strat_{i}")
                
                cfg = sc["config"]
                cfg["target_sell_rate"] = global_target_sr

                pc1, pc2, pc3, pc4 = st.columns(4)
                if sc["strategy"] == "rule_based":
                    rp = pc1.slider("希少割増(%)", 0, 100, int(cfg.get("rare_premium", 1.4)*100-100), 5, key=f"rp_{i}")
                    pkm = pc2.slider("ピーク割増(%)", 0, 50, int(cfg.get("peak_markup", 1.15)*100-100), 5, key=f"pd_{i}")
                    ad = pc3.slider("余裕割引(%)", 0, 50, int(100-cfg.get("abundant_discount", 0.9)*100), 5, key=f"ad_{i}")
                    lm = pc4.slider("見切り割引(%)", 0, 50, int(100-cfg.get("last_minute_discount", 0.8)*100), 5, key=f"lm_{i}")
                    cfg["rare_premium"] = 1.0 + rp/100
                    cfg["peak_markup"] = 1.0 + pkm/100
                    cfg["abundant_discount"] = 1.0 - ad/100
                    cfg["last_minute_discount"] = 1.0 - lm/100
                else:
                    ptn_opts = ["standard", "early_rush", "last_minute_rush", "linear", "concave", "convex", "sigmoid", "bimodal"]
                    ptn = pc1.selectbox("減衰パターン", ptn_opts,
                                       index=ptn_opts.index(cfg.get("decay_pattern", "standard")),
                                       key=f"ptn_{i}")
                    dek = pc2.slider("鋭さ (k)", 5.0, 80.0, float(cfg.get("decay_k", 20.0)), 1.0, key=f"dek_{i}", 
                                    help="linear/concave/convex/bimodal時は無視されます", disabled=(ptn in ["linear", "concave", "convex", "bimodal"]))
                    dep = pc3.slider("柔軟性 (p)", 0.01, 0.99, float(cfg.get("decay_p", 0.12)), 0.01, key=f"dep_{i}",
                                    help="linear/concave/convex/bimodal時は無視されます", disabled=(ptn in ["linear", "concave", "convex", "bimodal"]))
                    dm = pc4.slider("需要倍率", 0.1, 8.0, float(cfg.get("demand_multiplier", 1.0)), 0.1, key=f"dm_{i}",
                                    help="ベースの売れ行きボリュームを何倍にするか調整します")
                    cfg["decay_pattern"] = ptn
                    cfg["decay_k"] = dek
                    cfg["decay_p"] = dep
                    cfg["demand_multiplier"] = dm

                # 共通: 価格弾力性 (Elasticity) の個別調整
                st.markdown("<small>※弾力性はマスタ値を上書きします</small>", unsafe_allow_html=True)
                el_val = st.slider("価格弾力性 (Elasticity)", 0.1, 3.0, float(abs(cfg.get("elasticity", 1.5))), 0.1, key=f"el_{i}")
                cfg["elasticity"] = el_val

    st.markdown("---")

    # === バックテスト実行と推移グラフ ===
    import plotly.graph_objects as go

    def run_backtest_scenarios(target_scenarios, target_ids, bt_inv_df, bt_events_df):
        from model_evaluator import backtest_strategy
        import numpy as np
        import copy
        
        results = []
        for s_idx, sc in enumerate(target_scenarios):
            evals = []
            sum_pred_rates = None
            sum_act_rates = None
            all_lead_days = None
            cnt = 0
            
            for inv_id in target_ids:
                row_q = bt_inv_df[bt_inv_df["id"] == inv_id]
                if row_q.empty: continue
                row = row_q.iloc[0]
                ev = bt_events_df[bt_events_df["inventory_id"] == inv_id]
                res = backtest_strategy(sc["strategy"], row, ev, sc["config"])
                evals.append(res)
                
                p_r = np.array(res.get("predicted_rates", []))
                a_r = np.array(res.get("actual_rates", []))
                l_d = np.array(res.get("lead_days", []))
                
                if len(l_d) > 0:
                    if sum_pred_rates is None:
                        sum_pred_rates = p_r.copy()
                        sum_act_rates = a_r.copy()
                        all_lead_days = l_d.copy()
                    else:
                        m_len = min(len(sum_pred_rates), len(p_r))
                        sum_pred_rates[:m_len] += p_r[:m_len]
                        sum_act_rates[:m_len] += a_r[:m_len]
                    cnt += 1
            
            # スコア平均と安定性(Robustness)の計算
            df_e = pd.DataFrame(evals)
            if not df_e.empty:
                avg_mape = df_e["mape"].mean()
                avg_dtw = df_e["dtw_distance"].mean()
                avg_lift = df_e["revenue_lift"].mean()
                avg_comp_raw = df_e["composite_score"].mean()
                # 安定性ペナルティ: スコアのばらつきが大きいほどマイナス
                std_comp = df_e["composite_score"].std() if len(df_e) > 1 else 0
                avg_comp = avg_comp_raw - (std_comp * 0.5) 
                
                avg_mae = df_e["mae"].mean()
                avg_rmse = df_e["rmse"].mean()
                avg_bias = df_e["bias"].mean()
                avg_spoil = df_e["spoilage_reduction"].mean()
            else:
                avg_mape, avg_dtw, avg_comp, avg_mae, avg_rmse, avg_bias, avg_lift, avg_spoil = 999.0, 1.0, 0, 0, 0, 0, 0, 0

            results.append({
                "id": sc["id"],
                "name": sc["name"],
                "mape": avg_mape,
                "dtw": avg_dtw,
                "strategy": sc["strategy"],
                "config": copy.deepcopy(sc["config"]),
                "mae": avg_mae, "rmse": avg_rmse, "bias": avg_bias,
                "lift": avg_lift, "spoilage": avg_spoil, "score": avg_comp,
                "avg_pred": (sum_pred_rates / cnt) if cnt > 0 else None,
                "avg_act": (sum_act_rates / cnt) if cnt > 0 else None,
                "lead_days": all_lead_days
            })
        return results

    st.markdown("---")
    
    b_col1, b_col2 = st.columns(2)
    if b_col1.button("▶ 全シナリオのバックテストを実行", type="primary", use_container_width=True):
        with st.spinner("各シナリオのシミュレーション中..."):
            cat_products = edited_cls_df[(edited_cls_df["商品種別"] == t_item_display) & (edited_cls_df["モデルカテゴリ"] == t_char_display)]
            target_ids = bt_inv_df[bt_inv_df["name"].isin(cat_products["商品名"]) & (bt_inv_df["item_type"] == t_item)]["id"].tolist()
            
            if not target_ids:
                st.warning("このカテゴリに属する商品実績がありません。")
            else:
                # 重み付け設定を全シナリオに適用
                for sc in scenarios:
                    sc["config"].update(score_weights)
                st.session_state["backtest_results"] = run_backtest_scenarios(scenarios, target_ids, bt_inv_df, bt_events_df)
                st.success("全てのシナリオのシミュレーションが完了しました。")

    if b_col2.button("🚀 パラメータの自動最適化 (Auto-tune)", type="secondary", use_container_width=True, help="各シナリオの設定をHill Climbing法で自動調整し、最も実績に近い設定を探します。"):
        cat_products = edited_cls_df[(edited_cls_df["商品種別"] == t_item_display) & (edited_cls_df["モデルカテゴリ"] == t_char_display)]
        target_ids = bt_inv_df[bt_inv_df["name"].isin(cat_products["商品名"]) & (bt_inv_df["item_type"] == t_item)]["id"].tolist()
        
        if not target_ids:
            st.warning("このカテゴリに属する商品実績がありません。")
        else:
            p_bar = st.progress(0)
            status_text = st.empty()
            
            # ログ表示用コンテナ
            debug_expander = st.expander("🛠️ 最適化プロセス・ログ (デバッグ用)", expanded=True)
            log_container = debug_expander.container()
            
            all_trials = []
            
            # --- Round 0: 広域スクリーニング (砂まきフェーズ v3) ---
            num_sand_sowing = 150
            log_container.write(f"**[Round 0] 広域スクリーニング開始 ({num_sand_sowing}パターン)**")
            
            base_patterns = ["standard", "linear", "concave", "convex", "sigmoid", "early_rush", "last_minute_rush", "bimodal"]
            candidates = []
            
            # 定番パターンの全網羅
            for bp in base_patterns:
                for strat in ["rule_based", "demand_forecast"]:
                    cand = {"name": f"Base_{strat}_{bp}", "strategy": strat, "config": copy.deepcopy(ai_config)}
                    cand["config"]["decay_pattern"] = bp
                    cand["config"].update(score_weights) # 重みを適用
                    candidates.append(cand)
            
            # 残りを広域ランダムで埋める
            for i in range(num_sand_sowing - len(candidates)):
                strategy = random.choice(["rule_based", "demand_forecast"])
                config = copy.deepcopy(ai_config)
                config["decay_pattern"] = random.choice(base_patterns)
                config["decay_k"] = random.uniform(5.0, 80.0)
                config["decay_p"] = random.uniform(0.01, 0.99)
                config["demand_multiplier"] = random.uniform(0.1, 8.0)
                config["elasticity"] = random.uniform(0.1, 4.0)
                config.update(score_weights) # 重みを適用
                
                if strategy == "rule_based":
                    config["peak_markup"] = random.uniform(1.0, 2.0)
                    config["last_minute_discount"] = random.uniform(0.2, 1.0)
                    config["rare_premium"] = random.uniform(1.0, 3.0)
                    config["abundant_discount"] = random.uniform(0.3, 1.0)
                
                candidates.append({"name": f"Rand_{i}", "strategy": strategy, "config": config})
            
            for i, cand in enumerate(candidates):
                status_text.text(f"スクリーニング中: {cand['name']} ({i+1}/{num_sand_sowing})")
                cand["id"] = "Temp"
                cand["config"]["target_sell_rate"] = global_target_sr
                res = run_backtest_scenarios([cand], target_ids, bt_inv_df, bt_events_df)[0]
                all_trials.append(res)
            
            # 初期選定 (スコア順)
            all_trials.sort(key=lambda x: x["score"], reverse=True)
            seeds = all_trials[:2]
            
            best_score_mape = seeds[0]["mape"]
            log_container.write(f"Round 0 完了. Best Score: {seeds[0]['score']:.1f} (MAPE: {best_score_mape:.2f}%)")

            def mutate_config_v3(cfg, strategy, intensity=1.0):
                new_cfg = copy.deepcopy(cfg)
                # マルチポイント変異 (同時に1〜3個のパラメータを動かす)
                num_mutations = random.randint(1, 3)
                for _ in range(num_mutations):
                    r = random.random()
                    if strategy == "rule_based":
                        if r < 0.25:
                            new_cfg["peak_markup"] = max(1.0, min(2.5, new_cfg.get("peak_markup", 1.15) + random.uniform(-0.25, 0.25) * intensity))
                        elif r < 0.50:
                            new_cfg["last_minute_discount"] = max(0.2, min(1.0, new_cfg.get("last_minute_discount", 0.8) + random.uniform(-0.2, 0.2) * intensity))
                        elif r < 0.75:
                            new_cfg["rare_premium"] = max(1.0, min(3.5, new_cfg.get("rare_premium", 1.4) + random.uniform(-0.4, 0.4) * intensity))
                        else:
                            new_cfg["abundant_discount"] = max(0.3, min(1.0, new_cfg.get("abundant_discount", 0.9) + random.uniform(-0.2, 0.2) * intensity))
                    else:
                        if r < 0.10: 
                            new_cfg["decay_pattern"] = random.choice(base_patterns)
                        elif r < 0.40: 
                            new_cfg["decay_k"] = max(5.0, min(150.0, new_cfg.get("decay_k", 20.0) + random.uniform(-30, 30) * intensity))
                        elif r < 0.70: 
                            new_cfg["decay_p"] = max(0.01, min(0.99, new_cfg.get("decay_p", 0.12) + random.uniform(-0.3, 0.3) * intensity))
                        else: 
                            new_cfg["demand_multiplier"] = max(0.01, min(15.0, new_cfg.get("demand_multiplier", 1.0) + random.uniform(-1.5, 1.5) * intensity))
                    
                    if random.random() < 0.3:
                        new_cfg["elasticity"] = max(0.05, min(5.0, new_cfg.get("elasticity", 1.5) + random.uniform(-0.5, 0.5) * intensity))
                
                new_cfg["target_sell_rate"] = global_target_sr
                return new_cfg

            def crossover_configs(p1, p2):
                # 遺伝子交叉: 二つの親からランダムにキーを引き継ぐ
                child_cfg = copy.deepcopy(p1["config"])
                p2_cfg = p2["config"]
                for key in ["decay_pattern", "decay_k", "decay_p", "demand_multiplier", "elasticity", "peak_markup", "last_minute_discount", "rare_premium", "abundant_discount"]:
                    if key in p2_cfg and random.random() < 0.5:
                        child_cfg[key] = p2_cfg[key]
                return child_cfg

            # --- Round 1-10: 反復最適化 / Genetic Evolution ---
            max_rounds = 10
            for round_idx in range(1, max_rounds + 1):
                round_population = []
                status_text.text(f"最適化ラウンド {round_idx}/{max_rounds} (進化中)...")
                p_bar.progress(round_idx / max_rounds)
                
                # 1. 交叉個体の生成
                if len(seeds) >= 2:
                    for c_idx in range(6):
                        crossed = {
                            "id": "Temp", "name": f"Cross{round_idx}_{c_idx}",
                            "strategy": random.choice([seeds[0]["strategy"], seeds[1]["strategy"]]),
                            "config": crossover_configs(seeds[0], seeds[1])
                        }
                        round_population.append(crossed)
                
                # 2. 変異個体の生成
                for s_idx, seed in enumerate(seeds):
                    for m_idx in range(12):
                        mutated = {
                            "id": "Temp", "name": f"Mut{round_idx}_{s_idx}_{m_idx}", 
                            "strategy": seed["strategy"], 
                            "config": mutate_config_v3(seed["config"], seed["strategy"], intensity=(1.2 - round_idx/10.0))
                        }
                        round_population.append(mutated)
                
                # 一括実行
                results = run_backtest_scenarios(round_population, target_ids, bt_inv_df, bt_events_df)
                all_trials.extend(results)
                
                # 選定: 多様性を維持しつつ上位2つを次世代の親に
                all_trials.sort(key=lambda x: x["score"], reverse=True)
                
                new_seeds = [all_trials[0]]
                # 2つ目の親は、違うアルゴリズムか、違うパターンを優先
                for t in all_trials[1:100]:
                    is_diff = (t["strategy"] != new_seeds[0]["strategy"]) or \
                              (t["config"].get("decay_pattern") != new_seeds[0]["config"].get("decay_pattern"))
                    if is_diff:
                        new_seeds.append(t)
                        break
                if len(new_seeds) < 2:
                    new_seeds.append(all_trials[1])
                seeds = new_seeds
                
                best_t = max(all_trials, key=lambda x: x["score"])
                log_container.write(f"Round {round_idx}: Best Score={best_t['score']:.1f} (MAPE: {best_t['mape']:.2f}%) (Genetics Action: Crossover & Multi-Mutation)")
                
                # 成功条件 (総合スコアの改善が飽和したら終了)
                if round_idx > 3 and abs(all_trials[0]["score"] - all_trials[10]["score"]) < 0.5:
                    log_container.write(f"✅ 進化が収束したため、早期終了します。")
                    break

            # 最終選出 (多様性フィルタを適用)
            all_trials.sort(key=lambda x: x["score"], reverse=True)
            diverse_final = []
            for t in all_trials:
                is_duplicate = False
                for df in diverse_final:
                    # 指標がほぼ同じものは同一とみなす
                    if abs(t["mape"] - df["mape"]) < 0.1 and abs(t["score"] - df["score"]) < 0.1:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    diverse_final.append(t)
                if len(diverse_final) >= 5:
                    break
            
            final_5 = diverse_final

            # --- Round 11: 最終微調整 (Fine-Tuning) ---
            log_container.write(f"**[Round 11] 最終微調整 (Fine-Tuning) 開始**")
            status_text.text("最終微調整フェーズを実行中...")
            
            def mutate_config_micro(cfg, strategy):
                """微小な局所探索: パターンの変更はせず、数%のブレンドのみ行う"""
                new_cfg = copy.deepcopy(cfg)
                if strategy == "rule_based":
                    if "peak_markup" in new_cfg: new_cfg["peak_markup"] *= random.uniform(0.98, 1.02)
                    if "last_minute_discount" in new_cfg: new_cfg["last_minute_discount"] *= random.uniform(0.98, 1.02)
                    if "rare_premium" in new_cfg: new_cfg["rare_premium"] *= random.uniform(0.98, 1.02)
                    if "abundant_discount" in new_cfg: new_cfg["abundant_discount"] *= random.uniform(0.98, 1.02)
                else:
                    if "decay_k" in new_cfg: new_cfg["decay_k"] *= random.uniform(0.95, 1.05)
                    if "decay_p" in new_cfg: new_cfg["decay_p"] = max(0.01, min(0.99, new_cfg["decay_p"] + random.uniform(-0.02, 0.02)))
                    if "demand_multiplier" in new_cfg: new_cfg["demand_multiplier"] *= random.uniform(0.95, 1.05)
                
                if "elasticity" in new_cfg: new_cfg["elasticity"] *= random.uniform(0.98, 1.02)
                
                new_cfg["target_sell_rate"] = global_target_sr
                return new_cfg

            finetuned_final = []
            for s_idx, base_cand in enumerate(final_5):
                # 局所探索用の微小変異体を生成 (10件)
                micro_population = [base_cand] # オリジナルも比較対象に含める
                for m_idx in range(10):
                    micro_mutant = {
                        "id": "Temp", "name": f"Micro_{s_idx}_{m_idx}",
                        "strategy": base_cand["strategy"],
                        "config": mutate_config_micro(base_cand["config"], base_cand["strategy"])
                    }
                    micro_population.append(micro_mutant)
                
                # 局所バックテスト
                res_micro = run_backtest_scenarios(micro_population, target_ids, bt_inv_df, bt_events_df)
                
                # 最も成績の良いものをこのスロットの最終版とする (Hill Climbing)
                best_micro = max(res_micro, key=lambda x: x["score"])
                if best_micro["score"] > base_cand["score"]:
                    log_container.write(f"Fine-Tuning: シナリオ枠 {s_idx+1} で改善を確認 (Score {base_cand['score']:.1f} -> {best_micro['score']:.1f})")
                finetuned_final.append(best_micro)

            final_5 = finetuned_final
            
            for i, f in enumerate(final_5):
                f["id"] = chr(65 + i)
            
            st.session_state["eval_scenarios"] = [
                {"id": f["id"], "name": f["name"], "strategy": f["strategy"], "config": f["config"]}
                for f in final_5
            ]
            st.session_state["backtest_results"] = final_5
            p_bar.progress(100)
            status_text.text("最適化完了！")
            st.success("遺伝的アルゴリズム v3 により、実績データの波を捉えた最も堅牢な5プランを選出しました。")

    if "backtest_results" in st.session_state:
        bt_res = st.session_state["backtest_results"]
        
        # グラフ描画
        fig = go.Figure()
        colors = Theme.palette
        styles = ['solid', 'dash', 'dot', 'dashdot', 'longdash']
        actual_line_drawn = False

        for i, r in enumerate(bt_res):
            c = colors[i % len(colors)]
            dash_style = styles[i % len(styles)]
            if r["avg_pred"] is not None and r["lead_days"] is not None:
                # シナリオAのみ太実線、他は破線スタイルで区別
                width = 4 if i == 0 else 3
                fig.add_trace(go.Scatter(
                    x=-r["lead_days"], y=r["avg_pred"] * 100, mode='lines',
                    name=f"[{r['id']}] {r['name']}",
                    line=dict(color=c, width=width, dash=dash_style)
                ))
                
                if not actual_line_drawn and r["avg_act"] is not None:
                    fig.add_trace(go.Scatter(
                        x=-r["lead_days"], y=r["avg_act"] * 100, mode='lines',
                        name='実際の販売ペース', line=dict(color=Theme.chart_actual, width=5)
                    ))
                    actual_line_drawn = True

        st.write("")
        fig.update_layout(
            title=f"`{target_category}` カテゴリの仮想販売推移シミュレーション",
            xaxis_title="リードタイム (日前)",
            yaxis_title="累計販売率 (%)",
            yaxis=dict(range=[0, 100]),
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        # === Section 3-4: 比較表と登録 ===
        st.markdown("### 🏆 Section 3: シナリオ評価スコア・マトリクス")
        
        with st.expander("ℹ️ 各評価指標の解説（クリックで開く）"):
            st.markdown("""
            - **MAPE (平均絶対パーセント誤差)**: 実績に対する予測誤差の割合の平均。低いほど誤差が少なく優秀。0に近づくほど理想的です。
            - **MAE (平均絶対誤差)**: 予測が実績から平均して全体で「何%」ずれているかを絶対値で表したもの。単位も含めて直感的に把握しやすい指標です。
            - **RMSE (二乗平均平方根誤差)**: 大きな誤差に対してペナルティを重くした指標。この値が大きい場合、たまに極端に外れる予測をしている可能性があります。
            - **DTW (Dynamic Time Warping)**: 形状の「似ている度合い」を測る距離指標。値が小さいほど実績の波形に近いことを示します。
            - **Bias (偏り)**: 誤差の単純な平均。プラスなら「予測が実績より過大（強気すぎる）」、マイナスなら「予測が実績より過小（弱気すぎる）」傾向を示します。
            - **Revenue Lift (収益リフト)**: 基準価格で販売し続けた場合と比較した収益の増加率(%)。高いほど収益性が向上します。
            - **Composite Score (総合スコア)**: これらの指標を総合勘案して算出した100点満点の独自スコア。シナリオの最終判定に使用されます。
            """)
            
        scenario_table_data = []
        for r in bt_res:
            scenario_table_data.append({
                "シナリオ": f"[{r['id']}] {r['name']}",
                "アルゴリズム": "🌟ルールベース" if r['strategy']=='rule_based' else "📈需要予測",
                "MAPE": r["mape"],
                "MAE": r["mae"],
                "DTW": r["dtw"],
                "RMSE": r["rmse"],
                "Bias": r["bias"],
                "Revenue Lift": r["lift"],
                "廃棄損低減率": r["spoilage"],
                "Composite Score": r["score"],
                "Ref_strategy": r["strategy"],
                "Ref_config": r["config"],
                "Ref_name": r["name"]
            })
            
        res_df = pd.DataFrame(scenario_table_data)

        # スコア降順にソート (Composite Scoreが高い順)
        res_df = res_df.sort_values("Composite Score", ascending=False).reset_index(drop=True)

        # 表示用DF
        disp_df = res_df.copy()
        disp_df["MAPE"] = disp_df["MAPE"].map(lambda x: f"{x:.1f}%")
        disp_df["MAE"] = disp_df["MAE"].map(lambda x: f"{x:.1f}%")
        disp_df["DTW"] = disp_df["DTW"].map(lambda x: f"{x:.3f}")
        disp_df["RMSE"] = disp_df["RMSE"].map(lambda x: f"{x:.1f}%")
        disp_df["Bias"] = disp_df["Bias"].map(lambda x: f"{x:+.1f}%")
        disp_df["Revenue Lift"] = disp_df["Revenue Lift"].map(lambda x: f"{x:+.1f}%")
        disp_df["廃棄損低減率"] = disp_df["廃棄損低減率"].map(lambda x: f"{x:+.1f}%")
        disp_df["Composite Score"] = disp_df["Composite Score"].map(lambda x: f"{x:.1f}点")

        # スコア1位に王冠をつける
        if len(disp_df) > 0:
            disp_df.loc[0, "シナリオ"] = "👑 " + disp_df.loc[0, "シナリオ"]

        st.dataframe(light_dataframe(disp_df.drop(columns=["Ref_strategy", "Ref_config", "Ref_name"])), use_container_width=True, hide_index=True)

        st.markdown("### 💾 Section 4: 最適シナリオの登録")
        st.write(f"決定したシナリオを `{target_category}` に登録（永続化）します。登録されたモデル設定は全体（本日のアクション等）に波及します。")

        s_col1, s_col2 = st.columns([3, 1])
        selected_sc_name = s_col1.selectbox("📝 登録するシナリオを選択", res_df["シナリオ"].tolist(), index=0)

        st.write("")
        if s_col2.button("💾 このシナリオを登録", type="primary", use_container_width=True):
            sc_data = res_df[res_df["シナリオ"] == selected_sc_name].iloc[0]
            
            # シナリオ名を保存できるようにconfigに追加
            import copy
            config_to_save = copy.deepcopy(sc_data["Ref_config"])
            # 生のシナリオ名（Mut1_0_4等）を保存
            config_to_save["scenario_name"] = sc_data["Ref_name"]

            save_model_setting(
                item_type=t_item, 
                characteristic=t_char, 
                strategy=sc_data["Ref_strategy"], 
                config=config_to_save, 
                score=sc_data["Composite Score"], 
                mape=sc_data["MAPE"], 
                lift=sc_data["Revenue Lift"], 
                spoilage=sc_data["廃棄損低減率"]
            )
            st.success(f"{target_category} に {selected_sc_name} の設定を登録しました！")
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# Footer & Logs
# ══════════════════════════════════════════════════════════════════
last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(f'<p style="color:{Theme.text_muted};text-align:right;font-size:.8rem">最終更新: {last_upd}</p>', unsafe_allow_html=True)
