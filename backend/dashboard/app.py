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
    CLASS_POPULAR_THRESHOLD, CLASS_NICHE_DAYS, CLASS_NICHE_RATIO
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
        
        r = calculate_pricing_result(
            inventory_id    = inv_id,
            name            = row["name"],
            base_price      = int(row["base_price"]),
            total_stock     = int(row["total_stock"]),
            remaining_stock = int(row["remaining_stock"]),
            departure_date  = row.get("departure_date"),
            elasticity      = row.get("elasticity", -1.5),
            config          = applied_config,
            strategy        = applied_strategy,
            reference_date  = reference_date,
        )
        results.append(r)
    return results

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
        "class_niche_ratio":     CLASS_NICHE_RATIO
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
    "🔍 販売推移と実績分析",
    "🧪 パッケージ販売シミュレータ",
    "🛒 事前仕入と初期価格の最適化",
    "🔬 モデル性能評価と最適化選択"
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
if selected_tab == "🔍 販売推移と実績分析":
    st.markdown("### 🔍 Analysis & Tracking")

    # --- 共通の商品選択エリア (ライブリストを兼ねる) ---
    st.markdown("#### 🎯 対象商品の詳細分析")
    

    
    # 選択（日付と製品でボックスを分ける）
    col_sel_date, col_sel_name = st.columns(2)
    with col_sel_date:
        available_dates = sorted([d for d in table_df["出発日"].unique() if d != "不明"])
        if not available_dates:
            available_dates = ["不明"]
        sel_date = st.selectbox("分析対象の出発日", available_dates, key="global_date_selector")
        
    with col_sel_name:
        available_products = sorted(table_df[table_df["出発日"] == sel_date]["商品名"].unique().tolist())
        sel_name = st.selectbox("分析対象の製品", available_products, key="global_name_selector")
        
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

    # ブッキング傾向 (将来の要件拡張のため全幅を使用)
    st.markdown("#### 📈 ブッキング傾向 (累積販売率予測)")
    
    # --- 将来予測に関するUI ---
    col_scenario, col_pred, col_compare = st.columns([1.5, 1.5, 1.0])
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

    with col_pred:
        pred_strategy = st.radio("予測アルゴリズム:", ["現在の価格戦略を継続", "需要予測ベース戦略を適用"], horizontal=True)

    with col_compare:
        show_baseline = st.checkbox("定価比較", value=False)
    
    # 過去実績の期間設定 (NameError回避のため復元)
    past_period = st.date_input(
        "参考にする過去の出発日期間", 
        value=(v_today - timedelta(days=365), v_today),
        key="past_period_input"
    )
    
    # 日付から「残り日数（Lead Days）」に変換する関数
    def to_lead_days(target_date, departure_date):
        return (departure_date - target_date).days
    
    dep_date = pd.to_datetime(inv_sel["departure_date"]).date()
    total_stock_sel = max(1, int(inv_sel["total_stock"]))
    
    fig_curve = go.Figure()

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
            hoverinfo="y"
        ))

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
            name="実績値", fill="tozeroy", fillcolor=Theme.chart_fill_alpha2
        ))
        
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
                name="販売単価 (実績)", yaxis="y2"
            ))
    
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
        overall_v = current_sales / max(1, (90 - days_remaining))
        if not item_events_filtered.empty and (90 - days_remaining) >= lookback_days:
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
            
        elasticity_val = abs(r_sel.get('elasticity', 1.5))

        for i in range(1, len(sim_days)):
            d = abs(sim_days[i])
            
            if pred_strategy == "現在の価格戦略を継続":
                ideal_sales = total_stock_sel * (1 - (d / 90))
                if curr_s > ideal_sales:
                    curr_p = int(min(curr_p * 1.015, base_price * 1.5))
                else:
                    curr_p = int(max(curr_p * 0.985, base_price * 0.5))
                # 価格変動による需要(販売数)への影響をシミュレーション
                price_ratio = base_price / curr_p if curr_p > 0 else 1.0
                curr_v = base_daily_v * (price_ratio ** elasticity_val)
                curr_s += curr_v
            else:
                # 需要予測: 弾力性に基づいてより機動的に動かす
                if d > 14:
                    curr_p = int(min(curr_p * 1.025, base_price * 1.8))
                else:
                    curr_p = int(max(curr_p * 0.95, base_price * 0.4))
                
                # 価格変動による需要(販売数)への影響をシミュレーション
                price_ratio = base_price / curr_p if curr_p > 0 else 1.0
                # 需要予測ベースの場合、さらにベース需要を15%引き上げる効果を想定
                curr_v = (base_daily_v * 1.15) * (price_ratio ** elasticity_val)
                curr_s += curr_v
            
            actual_daily_sales = curr_s - sim_sales_count[-1]
            revenue_strategy_future += (actual_daily_sales * curr_p)
            
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
        
        # 予測販売率推移（動的）
        fig_curve.add_trace(go.Scatter(
            x=sim_days, y=sim_sales_rates,
            mode="lines", line=dict(color=Theme.primary, width=3, dash="dot"),
            name="予測推移"
        ))
        
        fig_curve.add_trace(go.Scatter(
            x=[0], y=[projected_sales_rate],
            mode="markers", marker=dict(color=Theme.primary, size=10, symbol="star"),
            name="最終着地（予測）"
        ))

        # 単価の予測線 (動的変動)
        if last_price > 0:
            fig_curve.add_trace(go.Scatter(
                x=sim_days, y=sim_prices,
                mode="lines", line=dict(color=Theme.warning, width=2, dash="dot"),
                name="予測推移 (単価)", yaxis="y2"
            ))

        # ④ 価格据え置き（ベースライン）シナリオの予測と比較（トグルON時のみ）
        if show_baseline:
            # 定価で販売し続けた場合の予測販売数
            base_velocity = current_sales / max(1, (90 - days_remaining))
            if base_price > last_price:
                price_ratio = last_price / base_price
                base_velocity = base_velocity * (price_ratio ** abs(r_sel.get('elasticity', 1.5))) 
            
            projected_sales_baseline = int(min(total_stock_sel, current_sales + (base_velocity * days_remaining)))
            projected_sales_rate_baseline = (projected_sales_baseline / total_stock_sel) * 100
            
            # 定価維持時の売上と廃棄損
            projected_revenue_baseline = current_revenue + ((projected_sales_baseline - current_sales) * base_price)
            spoilage_qty_baseline = max(0, total_stock_sel - projected_sales_baseline)
            spoilage_cost_baseline = spoilage_qty_baseline * cost
            net_profit_baseline = projected_revenue_baseline - spoilage_cost_baseline
            
            revenue_lift = net_profit_strategy - net_profit_baseline

            # ベースラインの販売率予測線（グレー点線）
            fig_curve.add_trace(go.Scatter(
                x=[current_lead_day, 0], y=[current_sales_rate, projected_sales_rate_baseline],
                mode="lines", line=dict(color=Theme.text_muted, width=2, dash="dot"),
                name="価格据え置き予測 (販売率)"
            ))
            
            # ベースラインの販売単価予測線（グレー点線：定価の維持）
            fig_curve.add_trace(go.Scatter(
                x=[current_lead_day, 0], y=[base_price, base_price],
                mode="lines", line=dict(color=Theme.text_muted, width=1, dash="dot"),
                name="定価ライン", yaxis="y2"
            ))
            
            # 売上インパクトのハイライトパネル（HTMLマトリクス表示）をグラフ上部に表示
            if revenue_lift > 0:
               lift_text = f"<span style='color:{Theme.success};'><b>+¥{revenue_lift:,.0f}の増益効果</b></span>"
            else:
               lift_text = f"<span style='color:{Theme.danger};'><b>¥{revenue_lift:,.0f}の減益リスク</b></span>"
            
            st.markdown(f"""
            <div style="background:{Theme.bg_card}; padding:15px; border-radius:8px; border:1px dashed {Theme.primary}; margin-bottom:15px;">
                <div style="font-size:0.95rem; color:{Theme.text_dark}; margin-bottom:10px; font-weight:bold;">💡 What-If 分析結果明細 (最終着地予測)</div>
                <table style="width:100%; border-collapse:collapse; font-size:0.85rem; text-align:right;">
                    <tr style="border-bottom:1px solid {Theme.border_light}; color:{Theme.text_muted}; text-align:right;">
                        <th style="text-align:left; padding:6px;">シナリオ</th>
                        <th style="padding:6px; color:{Theme.primary};">現在(基準日)の残在庫</th>
                        <th style="padding:6px;">最終販売数</th>
                        <th style="padding:6px;">最終残数 (廃棄ロス)</th>
                        <th style="padding:6px;">売上高</th>
                        <th style="padding:6px; color:{Theme.danger};">廃棄損 (原価¥{cost:,})</th>
                        <th style="padding:6px; font-weight:bold; color:{Theme.text_dark};">最終利益評価額</th>
                    </tr>
                    <tr style="border-bottom:1px solid {Theme.border_light};">
                        <td style="text-align:left; padding:8px; color:{Theme.text_muted};">定価維持 (ベースライン)</td>
                        <td style="padding:8px; color:{Theme.text_dark};">{total_stock_sel - current_sales}</td>
                        <td style="padding:8px;">{projected_sales_baseline} / {total_stock_sel}</td>
                        <td style="padding:8px;">{spoilage_qty_baseline}</td>
                        <td style="padding:8px;">¥{projected_revenue_baseline:,.0f}</td>
                        <td style="padding:8px; color:{Theme.danger};">-¥{spoilage_cost_baseline:,.0f}</td>
                        <td style="padding:8px; font-weight:bold; color:{Theme.text_muted}; font-size:1rem;">¥{net_profit_baseline:,.0f}</td>
                    </tr>
                    <tr style="background:#f4f6f8;">
                        <td style="text-align:left; padding:8px; font-weight:bold; color:{Theme.primary};">戦略適用時 ({pred_strategy})</td>
                        <td style="padding:8px; font-weight:bold; color:{Theme.text_dark};">{total_stock_sel - current_sales}</td>
                        <td style="padding:8px; font-weight:bold;">{projected_sales} / {total_stock_sel}</td>
                        <td style="padding:8px; font-weight:bold;">{spoilage_qty_strategy}</td>
                        <td style="padding:8px; font-weight:bold;">¥{projected_revenue_strategy:,.0f}</td>
                        <td style="padding:8px; font-weight:bold; color:{Theme.danger};">-¥{spoilage_cost_strategy:,.0f}</td>
                        <td style="padding:8px; font-weight:bold; color:{Theme.text_dark}; font-size:1.1rem;">¥{net_profit_strategy:,.0f}</td>
                    </tr>
                </table>
                <div style="text-align:right; margin-top:12px; font-size:1.1rem; font-weight:bold;">
                    ダイナミックプライシング適用効果: {lift_text}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # グラフのレイアウト調整（X軸を負数から0へ向かうようにする）
    light_layout(fig_curve)
    fig_curve.update_layout(
        xaxis_title="残り日数 (出発日まで)",
        yaxis_title="累計販売率 (%)",
        xaxis=dict(range=[-90, 5]),  # -90日前から出発日(0)の少し後まで
        yaxis=dict(range=[0, 100], side="left"),
        yaxis2=dict(
            title="販売単価 (¥)",
            overlaying="y",
            side="right",
            rangemode="tozero",
            showgrid=False
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(Theme.apply_chart_theme(fig_curve), use_container_width=True, key="tracking_curve_chart_unique")
    
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
if selected_tab == "🧪 パッケージ販売シミュレータ":
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
# Tab 5: 🔬 モデル性能評価と最適化選択
# ══════════════════════════════════════════════════════════════════
elif selected_tab == "🔬 モデル性能評価と最適化選択":
    st.markdown("## 🔬 モデル性能評価と最適化選択 (A/B バックテスト)")
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
        c_data = get_product_classification(p_name, it_type)
        if c_data:
            char = c_data["characteristic"]
            src = c_data["source"]
        else:
            char = "stable" # デフォルト
            src = "auto"
        cls_records.append({
            "商品種別": it_type,
            "商品名": p_name,
            "特性 (クリックで変更)": char,
            "設定元": src
        })
    cls_df = pd.DataFrame(cls_records)

    # セッションステートで編集内容を管理（st.data_editor の代替）
    if "cls_edits" not in st.session_state or st.session_state.get("cls_df_hash") != str(hash(str(cls_df.values.tolist()))):
        st.session_state["cls_edits"] = {f"{r['商品種別']}:{r['商品名']}": r["特性 (クリックで変更)"] for _, r in cls_df.iterrows()}
        st.session_state["cls_df_hash"] = str(hash(str(cls_df.values.tolist())))

    # 現在の分類をライトテーマで表示
    disp_cls_df = cls_df.copy()
    disp_cls_df["特性 (クリックで変更)"] = [
        st.session_state["cls_edits"].get(f"{r['商品種別']}:{r['商品名']}", r["特性 (クリックで変更)"])
        for _, r in cls_df.iterrows()
    ]
    st.dataframe(light_dataframe(disp_cls_df), use_container_width=True, hide_index=True)

    # 各商品の特性を個別に変更
    with st.expander("✏️ 特性を個別に変更する", expanded=False):
        edited_cls_records = []
        for _, row in cls_df.iterrows():
            key = f"{row['商品種別']}:{row['商品名']}"
            current_char = st.session_state["cls_edits"].get(key, row["特性 (クリックで変更)"])
            char_options = ["popular", "stable", "niche"]
            new_char = st.selectbox(
                f"{row['商品種別']} | {row['商品名']}",
                options=char_options,
                index=char_options.index(current_char) if current_char in char_options else 1,
                key=f"cls_select_{key}"
            )
            st.session_state["cls_edits"][key] = new_char
            edited_cls_records.append({
                "商品種別": row["商品種別"],
                "商品名": row["商品名"],
                "特性 (クリックで変更)": new_char,
                "設定元": "manual"
            })

    # edited_cls_df をセッションステートから再構築（後続コードとの互換性維持）
    edited_cls_df = pd.DataFrame([
        {
            "商品種別": r["商品種別"],
            "商品名": r["商品名"],
            "特性 (クリックで変更)": st.session_state["cls_edits"].get(f"{r['商品種別']}:{r['商品名']}", r["特性 (クリックで変更)"]),
            "設定元": "manual"
        }
        for _, r in cls_df.iterrows()
    ])

    if st.button("💾 分類マスタを保存", type="primary"):
        with st.spinner("DBに分類を保存中..."):
            for _, row in edited_cls_df.iterrows():
                save_product_classification(row["商品名"], row["商品種別"], row["特性 (クリックで変更)"], "manual")
        st.success("分類を保存しました！バックテストを実行するには下のシナリオ設定へお進みください。")
        import time
        time.sleep(1)
        st.rerun()

    st.markdown("---")

    # === Section 1: 評価シナリオ設定 ===
    st.markdown("### 🛠️ Section 1: パラメータ・評価指標の詳細設定")
    st.write("アルゴリズムの判定基準や、商品の分類しきい値、スコアリングの重み付けを微調整します。")

    with st.expander("⚙️ アルゴリズム・分類・スコアの詳細設定", expanded=False):
        c1, c2, c3 = st.columns(3)
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

        with c3:
            st.markdown("**🏆 評価スコアの重み付け (合計1.0)**")
            w_mape = st.slider("MAPE (精度)", 0.0, 1.0, float(SCORE_WEIGHT_MAPE), 0.05)
            w_lift = st.slider("Lift (収益)", 0.0, 1.0, float(SCORE_WEIGHT_LIFT), 0.05)
            w_spoil = st.slider("Spoilage (廃棄)", 0.0, 1.0, float(SCORE_WEIGHT_SPOILAGE), 0.05)
            ai_config["score_weight_mape"] = w_mape
            ai_config["score_weight_lift"] = w_lift
            ai_config["score_weight_spoilage"] = w_spoil
            ai_config["score_weight_dir_acc"] = max(0.0, 1.0 - (w_mape + w_lift + w_spoil))
            st.caption(f"Directional Accuracy 重み: {ai_config['score_weight_dir_acc']:.2f}")

    st.markdown("---")
    st.markdown("### 🧪 Section 2: 評価シナリオ設定")
    st.write("特定のカテゴリに対して、複数のアルゴリズムやパラメータを組み合わせた「シナリオ」を定義し、比較テストを行います。")

    cat_options = edited_cls_df["商品種別"] + "---" + edited_cls_df["特性 (クリックで変更)"]
    cat_options = sorted(list(cat_options.unique()))

    if not cat_options:
        st.warning("商品データが存在しません。")
        st.stop()

    target_category = st.selectbox("🎯 バックテスト対象のカテゴリ", cat_options, help="このカテゴリに属する商品群に対して複数のシナリオをテストします。")
    t_item, t_char = target_category.split("---")

    # 実績平均販売率を算出
    cat_products1 = edited_cls_df[(edited_cls_df["商品種別"] == t_item) & (edited_cls_df["特性 (クリックで変更)"] == t_char)]
    target_inv_ids1 = bt_inv_df[bt_inv_df["name"].isin(cat_products1["商品名"]) & (bt_inv_df["item_type"] == t_item)]["id"].tolist()
    avg_sell_through = 1.0
    if target_inv_ids1:
        total_inv1 = bt_inv_df[bt_inv_df["id"].isin(target_inv_ids1)]["total_stock"].sum()
        total_booked1 = bt_events_df[bt_events_df["inventory_id"].isin(target_inv_ids1)]["quantity"].sum()
        if total_inv1 > 0:
            avg_sell_through = min(1.0, total_booked1 / total_inv1) # 最大100%

    if "eval_scenarios" not in st.session_state:
        c_r_std = ai_config.copy()
        c_r_agg = ai_config.copy()
        c_r_agg["peak_markup"] = 1.30
        c_r_agg["last_minute_discount"] = 0.60
        c_d_std = ai_config.copy()
        c_d_std["decay_pattern"] = "standard"
        c_d_std["decay_k"] = 15.0
        c_d_std["decay_p"] = 0.15
        c_d_early = ai_config.copy()
        c_d_early["decay_pattern"] = "early_rush"
        c_d_early["decay_k"] = 10.0
        c_d_early["decay_p"] = 0.20
        c_d_late = ai_config.copy()
        c_d_late["decay_pattern"] = "last_minute_rush"
        c_d_late["decay_k"] = 25.0
        c_d_late["decay_p"] = 0.10

        st.session_state["eval_scenarios"] = [
            {"id": "A", "name": "安定・ルールベース", "strategy": "rule_based", "config": c_r_std},
            {"id": "B", "name": "強気・ルールベース", "strategy": "rule_based", "config": c_r_agg},
            {"id": "C", "name": "標準・需要予測", "strategy": "demand_forecast", "config": c_d_std},
            {"id": "D", "name": "早割特化・需要予測", "strategy": "demand_forecast", "config": c_d_early},
            {"id": "E", "name": "直前特化・需要予測", "strategy": "demand_forecast", "config": c_d_late}
        ]

    def add_scenario():
        new_id = chr(65 + len(st.session_state["eval_scenarios"]))
        st.session_state["eval_scenarios"].append({
            "id": new_id, "name": f"シナリオ {new_id}", "strategy": "demand_forecast", "config": ai_config.copy()
        })
        
    def clear_scenarios():
        if "eval_scenarios" in st.session_state:
            del st.session_state["eval_scenarios"]

    sc_col1, sc_col2, _ = st.columns([2, 2, 4])
    sc_col1.button("➕ 新しいシナリオを追加", on_click=add_scenario)
    sc_col2.button("🗑️ シナリオをリセット", on_click=clear_scenarios)

    scenarios = st.session_state["eval_scenarios"]

    # シナリオ入力UI
    for i, sc in enumerate(scenarios):
        with st.expander(f"シナリオ {sc['id']}: {sc['name']} ({'ルールベース' if sc['strategy']=='rule_based' else '需要予測'})", expanded=(i==0)):
            c1, c2, c3 = st.columns([2, 1, 1])
            sc["name"] = c1.text_input("シナリオ名", value=sc["name"], key=f"sc_name_{i}")
            sc["strategy"] = c2.selectbox("アルゴリズム", ["rule_based", "demand_forecast"], 
                                          index=0 if sc["strategy"]=="rule_based" else 1,
                                          format_func=lambda x: "ルールベース" if x=="rule_based" else "需要予測ベース",
                                          key=f"sc_strat_{i}")
            
            cfg = sc["config"]
            trg_sr = c3.slider("最終目標販売率(%)", 1, 100, int(cfg.get("target_sell_rate", avg_sell_through)*100), 1, 
                               help="デフォルト値は過去実績の平均です。ニッチ商品など100%売り切らない想定の場合は下げてください。", key=f"trg_sr_{i}")
            cfg["target_sell_rate"] = trg_sr / 100.0

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
                ptn = pc1.selectbox("減衰パターン", ["standard", "early_rush", "last_minute_rush"],
                                   index=["standard", "early_rush", "last_minute_rush"].index(cfg.get("decay_pattern", "standard")),
                                   key=f"ptn_{i}")
                dek = pc2.slider("鋭さ (k)", 5.0, 50.0, float(cfg.get("decay_k", 15.0)), 1.0, key=f"dek_{i}")
                dep = pc3.slider("柔軟性 (p)", 0.05, 0.50, float(cfg.get("decay_p", 0.15)), 0.05, key=f"dep_{i}")
                cfg["decay_pattern"] = ptn
                cfg["decay_k"] = dek
                cfg["decay_p"] = dep

    st.markdown("---")

    # === Section 2: バックテスト実行と推移グラフ ===
    import plotly.graph_objects as go

    st.markdown("### 📊 Section 2: バックテスト実行と推移グラフ")
    st.write(f"**対象カテゴリ:** `{target_category}` に対して、全シナリオのシミュレーションを実行します。")

    if st.button("▶ 全シナリオのバックテストを実行", type="primary", use_container_width=True):
        with st.spinner("各シナリオのシミュレーション中..."):

            # 対象カテゴリの商品だけ抽出
            cat_products = edited_cls_df[(edited_cls_df["商品種別"] == t_item) & (edited_cls_df["特性 (クリックで変更)"] == t_char)]
            target_inv_ids = bt_inv_df[bt_inv_df["name"].isin(cat_products["商品名"]) & (bt_inv_df["item_type"] == t_item)]["id"].tolist()

            if not target_inv_ids:
                st.warning("このカテゴリに属する商品実績がありません。")
            else:
                # 分析結果を格納
                scenario_results = []
                from model_evaluator import backtest_strategy, _empty_eval

                # シナリオごとのグラフ用データ
                fig = go.Figure()
                colors = Theme.palette

                # 実績線の加算用
                all_actual_rates = None
                all_lead_days = None

                for s_idx, sc in enumerate(scenarios):
                    evals = []
                    sum_pred_rates = None
                    sum_act_rates = None
                    cnt = 0

                    for inv_id in target_inv_ids:
                        target_row_q = bt_inv_df[bt_inv_df["id"] == inv_id]
                        if target_row_q.empty: continue
                        target_row = target_row_q.iloc[0]
                        ev_df = bt_events_df[bt_events_df["inventory_id"] == inv_id]
                        e_res = backtest_strategy(sc["strategy"], target_row, ev_df, sc["config"])
                        evals.append(e_res)

                        # 配列を合算して平均を出す
                        import numpy as np
                        p_rates = np.array(e_res.get("predicted_rates", []))
                        a_rates = np.array(e_res.get("actual_rates", []))
                        l_days = np.array(e_res.get("lead_days", []))

                        if len(l_days) > 0:
                            if sum_pred_rates is None:
                                sum_pred_rates = p_rates.copy()
                                sum_act_rates = a_rates.copy()
                                all_lead_days = l_days.copy()
                            else:
                                min_len = min(len(sum_pred_rates), len(p_rates))
                                sum_pred_rates[:min_len] += p_rates[:min_len]
                                sum_act_rates[:min_len] += a_rates[:min_len]
                            cnt += 1

                    if cnt > 0:
                        avg_pred = sum_pred_rates / cnt
                        avg_act = sum_act_rates / cnt
                        all_actual_rates = avg_act # 実績は全てのシナリオで同じはず

                        c = colors[s_idx % len(colors)]
                        fig.add_trace(go.Scatter(
                            x=-all_lead_days, y=avg_pred * 100, mode='lines',
                            name=f"[{sc['id']}] {sc['name']}",
                            line=dict(color=c, width=3, dash='dash')
                        ))

                    # スコア平均
                    df_e = pd.DataFrame(evals)
                    avg_mape = df_e["mape"].mean() if not df_e.empty else 0
                    avg_mae = df_e["mae"].mean() if not df_e.empty else 0
                    avg_rmse = df_e["rmse"].mean() if not df_e.empty else 0
                    avg_bias = df_e["bias"].mean() if not df_e.empty else 0
                    avg_lift = df_e["revenue_lift"].mean() if not df_e.empty else 0
                    avg_spoil = df_e["spoilage_reduction"].mean() if not df_e.empty else 0
                    avg_comp = df_e["composite_score"].mean() if not df_e.empty else 0

                    # 辞書のコピーを渡す（Streamlitのバグ回避）
                    import copy
                    scenario_results.append({
                        "シナリオ": f"[{sc['id']}] {sc['name']}",
                        "アルゴリズム": "🌟ルールベース" if sc['strategy']=='rule_based' else "📈需要予測",
                        "MAPE": avg_mape,
                        "MAE": avg_mae,
                        "RMSE": avg_rmse,
                        "Bias": avg_bias,
                        "Revenue Lift": avg_lift,
                        "廃棄損低減率": avg_spoil,
                        "Composite Score": avg_comp,
                        "Ref_strategy": sc["strategy"],
                        "Ref_config": copy.deepcopy(sc["config"])
                    })

                # 実績線を追加
                if all_actual_rates is not None and all_lead_days is not None:
                    fig.add_trace(go.Scatter(
                        x=-all_lead_days, y=all_actual_rates * 100, mode='lines',
                        name='実際の販売ペース', line=dict(color=Theme.chart_actual, width=4)
                    ))

                # グラフ描画
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
                    - **Bias (偏り)**: 誤差の単純な平均。プラスなら「予測が実績より過大（強気すぎる）」、マイナスなら「予測が実績より過小（弱気すぎる）」傾向を示します。
                    - **Revenue Lift (収益リフト)**: 基準価格で販売し続けた場合と比較した収益の増加率(%)。高いほど収益性が向上します。
                    - **廃棄損低減率**: 基準設定と比較して、売れ残りによる機会損失をどれだけ減らせたか(%)。
                    - **Composite Score (総合スコア)**: これらの指標を総合勘案して算出した100点満点の独自スコア。シナリオの最終判定に使用されます。
                    """)
                    
                res_df = pd.DataFrame(scenario_results)

                # スコア降順にソート
                res_df = res_df.sort_values("Composite Score", ascending=False).reset_index(drop=True)

                # 表示用DF
                disp_df = res_df.copy()
                disp_df["MAPE"] = disp_df["MAPE"].map(lambda x: f"{x:.1f}%")
                disp_df["MAE"] = disp_df["MAE"].map(lambda x: f"{x:.1f}%")
                disp_df["RMSE"] = disp_df["RMSE"].map(lambda x: f"{x:.1f}%")
                disp_df["Bias"] = disp_df["Bias"].map(lambda x: f"{x:+.1f}%")
                disp_df["Revenue Lift"] = disp_df["Revenue Lift"].map(lambda x: f"{x:+.1f}%")
                disp_df["廃棄損低減率"] = disp_df["廃棄損低減率"].map(lambda x: f"{x:+.1f}%")
                disp_df["Composite Score"] = disp_df["Composite Score"].map(lambda x: f"{x:.1f}点")

                # スコア1位に王冠をつける
                if len(disp_df) > 0:
                    disp_df.loc[0, "シナリオ"] = "👑 " + disp_df.loc[0, "シナリオ"]

                st.dataframe(light_dataframe(disp_df.drop(columns=["Ref_strategy", "Ref_config"])), use_container_width=True, hide_index=True)

                st.markdown("### 💾 Section 4: 最適シナリオの登録")
                st.write(f"決定したシナリオを `{target_category}` に登録（永続化）します。登録されたモデル設定は全体（本日のアクション等）に波及します。")

                s_col1, s_col2 = st.columns([3, 1])
                selected_sc_name = s_col1.selectbox("📝 登録するシナリオを選択", res_df["シナリオ"].tolist(), index=0)

                st.write("")
                if s_col2.button("💾 このシナリオを登録", type="primary", use_container_width=True):
                    sc_data = res_df[res_df["シナリオ"] == selected_sc_name].iloc[0]
                    
                    save_model_setting(
                        item_type=t_item, 
                        characteristic=t_char, 
                        strategy=sc_data["Ref_strategy"], 
                        config=sc_data["Ref_config"], 
                        score=sc_data["Composite Score"], 
                        mape=sc_data["MAPE"], 
                        lift=sc_data["Revenue Lift"], 
                        spoilage=sc_data["廃棄損低減率"]
                    )
                    st.success(f"{target_category} に {selected_sc_name} の設定を登録しました！")


# ══════════════════════════════════════════════════════════════════
# Footer & Logs
# ══════════════════════════════════════════════════════════════════
last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
st.markdown(f'<p style="color:{Theme.text_muted};text-align:right;font-size:.8rem">最終更新: {last_upd}</p>', unsafe_allow_html=True)
