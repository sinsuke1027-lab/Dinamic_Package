"""
model_evaluator.py

モデル性能評価（バックテスト）および商品分類・最適化選択の永続化を担うモジュール。
過去の予約データを元に、AIアルゴリズムをシミュレーションし、客観的指標（MAPE等）でスコアリングを行います。
"""

import sqlite3
import pandas as pd
import numpy as np
import json
from datetime import datetime, date, timezone, timedelta
import math
from typing import Optional

from pricing_engine import calc_inventory_adjustment, calc_time_adjustment, calculate_inventory_decay_factor
from constants import (
    CLASS_POPULAR_THRESHOLD, CLASS_NICHE_DAYS, CLASS_NICHE_RATIO,
    SCORE_WEIGHT_MAPE, SCORE_WEIGHT_LIFT, SCORE_WEIGHT_SPOILAGE, SCORE_WEIGHT_DIR_ACC
)

DB_PATH = 'inventory.db'

# ─── 商品分類と自動判定 ───────────────────────────────────────────────

def auto_classify_product(history_df: pd.DataFrame, total_stock: int, config: Optional[dict] = None) -> str:
    """
    過去の実績データ（日ごとの販売累積など）から、商品の特性を自動サジェストする。
    history_df は lead_days に対しての販売履歴。
    """
    conf = config or {}
    if history_df.empty or total_stock == 0:
        return "stable" # データ不足時は安定とする
        
    final_sales = history_df["quantity"].sum()
    final_rate = final_sales / total_stock
    
    # 最終的な販売率がしきい値以上なら「大人気」
    if final_rate >= conf.get('class_popular_threshold', CLASS_POPULAR_THRESHOLD):
        return "popular"
        
    # 直前期（残りN日以内）に売上の半分以上が集中しているなら「ニッチ」
    n_days = conf.get('class_niche_days', CLASS_NICHE_DAYS)
    n_ratio = conf.get('class_niche_ratio', CLASS_NICHE_RATIO)
    late_sales = history_df[history_df["lead_days"] <= n_days]["quantity"].sum()
    if final_sales > 0 and (late_sales / final_sales) > n_ratio:
        return "niche"
        
    return "stable"


def get_product_classification(name: str, item_type: str) -> dict:
    """DBから特定の商品の分類（ホテル/フライト × 特性）を取得する"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM product_classification WHERE name = ? AND item_type = ?", (name, item_type))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def save_product_classification(name: str, item_type: str, characteristic: str, 
                                target_rate_peak: float=0.95, target_rate_normal: float=0.80, target_rate_offpeak: float=0.60,
                                source: str = "manual") -> None:
    """特定商品の分類をDBに保存する"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    cur.execute('''
        INSERT INTO product_classification (name, item_type, characteristic, target_rate_peak, target_rate_normal, target_rate_offpeak, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, item_type) DO UPDATE SET 
            characteristic = excluded.characteristic,
            target_rate_peak = excluded.target_rate_peak,
            target_rate_normal = excluded.target_rate_normal,
            target_rate_offpeak = excluded.target_rate_offpeak,
            source = excluded.source,
            updated_at = excluded.updated_at
    ''', (name, item_type, characteristic, target_rate_peak, target_rate_normal, target_rate_offpeak, source, now_str))
    conn.commit()
    conn.close()

# ─── モデル設定の読み書き ─────────────────────────────────────────

def get_model_setting(item_type: str, characteristic: str) -> dict:
    """特定のカテゴリ（例: hotel × popular）の保存済みモデル設定を取得する"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('''
        SELECT strategy, config_json FROM model_settings 
        WHERE item_type = ? AND characteristic = ?
    ''', (item_type, characteristic))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "strategy": row["strategy"],
            "config": json.loads(row["config_json"]) if row["config_json"] else {}
        }
    return None

def save_model_setting(item_type: str, characteristic: str, strategy: str, config: dict, 
                       score: float=0, mape: float=0, lift: float=0, spoilage: float=0) -> None:
    """カテゴリに適用するモデルと設定フルスナップショットを保存する"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    config_json = json.dumps(config)
    
    cur.execute('''
        INSERT INTO model_settings 
        (item_type, characteristic, strategy, config_json, composite_score, mape, revenue_lift, spoilage_reduction, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_type, characteristic) DO UPDATE SET 
            strategy = excluded.strategy,
            config_json = excluded.config_json,
            composite_score = excluded.composite_score,
            mape = excluded.mape,
            revenue_lift = excluded.revenue_lift,
            spoilage_reduction = excluded.spoilage_reduction,
            updated_at = excluded.updated_at
    ''', (item_type, characteristic, strategy, config_json, score, mape, lift, spoilage, now_str))
    conn.commit()
    conn.close()

# ─── 評価指標: DTW (Dynamic Time Warping) ─────────────────────────

def calculate_dtw_distance(s1: list, s2: list, window: int = 10) -> float:
    """
    2つの時系列データの距離を動的時間伸縮法(DTW)で計算する。
    s1, s2 は 0.0〜1.0 の累積販売率のリスト。
    """
    n, m = len(s1), len(s2)
    if n == 0 or m == 0:
        return 0.0
        
    # DPテーブルの初期化 (無限大で埋める)
    dtw = np.full((n + 1, m + 1), np.inf)
    dtw[0, 0] = 0
    
    # 窓サイズ（Sakoe-Chiba Band）の制限
    w = max(window, abs(n - m))
    
    for i in range(1, n + 1):
        for j in range(max(1, i - w), min(m + 1, i + w)):
            cost = abs(s1[i-1] - s2[j-1])
            dtw[i, j] = cost + min(dtw[i-1, j], dtw[i, j-1], dtw[i-1, j-1])
            
    return dtw[n, m] / max(n, m) # 正規化

# ─── バックテスト・推論エンジン ─────────────────────────────────────────

def backtest_strategy(strategy: str, inv_row: pd.Series, booking_events: pd.DataFrame, config: dict) -> dict:
    """
    過去の完了済み商品（inv_row）に対して、指定された価格戦略（strategy）をシミュレーションし、
    結果を指標群（MAPE, Lift等）として返す。
    
    ロジック概要:
    1. 販売開始（90日前等）から出発日までの各日についてシミュレーションを行う
    2. 価格を動的に計算する（strategyに基づく）
    3. 計算された価格によって、実際の歴史データの「需要（販売数）」が弾力性に従い増減したと仮定する
    4. 結果の架空の売上高、最終販売数などを集計する
    """
    _backtest_price_cache = {}  # 価格計算キャッシュ: (inv_id, strategy, remaining, lead_day, config_key) -> price
    total_stock = inv_row["total_stock"]
    base_price = inv_row["base_price"]
    
    # 弹力性の優先順位: config > マスタ値
    elasticity_val = abs(config.get("elasticity", inv_row.get("elasticity", 1.5)))
    
    # シミュレーション期間: 120日（ユーザー要望により拡張）
    BACKTEST_WINDOW = 120
    days = list(range(BACKTEST_WINDOW, -1, -1))
    
    # booking_eventsから、リードタイムごとの実際の純粋な販売数を集計
    # （ここでは簡略化のため、booked_at と departure_date の差分をリードタイムとする）
    if booking_events.empty:
        return _empty_eval()
        
    dep_date = pd.to_datetime(inv_row["departure_date"], utc=True)
    booking_events = booking_events.copy()
    booked_dates = pd.to_datetime(booking_events["booked_at"], utc=True)
    booking_events["lead_days"] = (dep_date - booked_dates).dt.days
    
    # 日別実際の販売数
    daily_actual_sales = booking_events.groupby("lead_days")["quantity"].sum().to_dict()
    
    # シミュレーション用変数
    # 60日より前（61日〜90日等）に既に売れた実績を計算して初期値とする
    pre_window_sales = sum(v for k, v in daily_actual_sales.items() if k > BACKTEST_WINDOW)
    
    sim_remaining = total_stock - pre_window_sales
    sim_revenue = 0
    
    # 定価維持（Baseline）シミュレーション
    base_revenue = 0
    base_remaining = total_stock - pre_window_sales
    actual_sales_so_far = pre_window_sales
    predicted_rates = []
    actual_rates = []
    sim_rates = []
    tracked_days = []
    
    directional_correct = 0
    directional_count = 0
    prev_price = base_price
    prev_actual_demand = 0
    
    # ─── ポテンシャル（限界）の事前計算 ───
    def _get_seasonal_target_rate_for_potential(dep_date, c):
        if not dep_date:
            return c.get("target_sell_rate", 1.0)
        try:
            import pandas as pd
            dt = pd.to_datetime(dep_date)
            m = dt.month
            if m in {5, 7, 8}: return c.get("target_rate_peak", c.get("target_sell_rate", 0.95))
            elif m in {2, 6, 11}: return c.get("target_rate_offpeak", c.get("target_sell_rate", 0.60))
            else: return c.get("target_rate_normal", c.get("target_sell_rate", 0.80))
        except Exception:
            return c.get("target_sell_rate", 1.0)
            
    target_sr_potential = _get_seasonal_target_rate_for_potential(inv_row.get("departure_date"), config)
    # 最低でも現在の販売率、通常は目標の1.05倍を最終的な需要限界（ポテンシャルの天井）とする
    potential_limit = max(target_sr_potential * 1.05, (actual_sales_so_far / max(1, total_stock)))
    cannibalized_demand = 0.0 # 未来からの前借り需要
    
    for d in days:
        # Note: Removing the 'if sim_remaining <= 0: break' to ensure fixed-length results for averaging
            
        actual_demand_raw = daily_actual_sales.get(d, 0)
        actual_sales_so_far += actual_demand_raw
        
        # ─── [1] 新しい戦略に基づく価格計算 (実際のエンジンを呼び出し)
        from pricing_engine import calculate_pricing_result
        
        # 疑似在庫行
        # エンジン内部で lead_days を再計算するため、reference_date を適切に設定する
        
        # 価格計算キャッシュ: 同一パラメータ設定の弓を何度も呼ばないよう、結果をdictに保存
        _price_cache_key = (
            inv_row["id"], strategy,
            int(sim_remaining), d,
            tuple(sorted((k, str(v)) for k, v in config.items() if k not in ("score_weight_mape", "score_weight_dtw", "score_weight_lift", "score_weight_spoilage", "score_weight_dir_acc")))
        )
        
        if _price_cache_key in _backtest_price_cache:
            curr_price = _backtest_price_cache[_price_cache_key]
        else:
            engine_res = calculate_pricing_result(
                inventory_id=inv_row["id"],
                name=inv_row["name"],
                base_price=base_price,
                total_stock=total_stock,
                remaining_stock=sim_remaining,
                departure_date=inv_row["departure_date"],
                elasticity=elasticity_val,
                reference_date=(dep_date - timedelta(days=d)).date(),
                config=config,
                strategy=strategy
            )
            curr_price = engine_res["final_price"]
            _backtest_price_cache[_price_cache_key] = curr_price
            
        # ─── [2] 価格弾力性による仮想需要の計算とポテンシャル制御
        
        # カニバリゼーション（需要の前借り）の消化
        effective_actual = float(actual_demand_raw)
        if cannibalized_demand > 0 and effective_actual > 0:
            eat = min(cannibalized_demand, effective_actual * 0.5) # 初動実績の半分まで消化
            effective_actual -= eat
            cannibalized_demand -= eat
            
        demand_floor = 0.05 
        effective_actual = max(effective_actual, demand_floor)
        
        price_ratio = base_price / curr_price if curr_price > 0 else 1.0
        
        # 非線形弾力性（限界効用逓減）: ポテンシャル天井に近づくほど、値下げ効果が薄れる
        current_sim_rate = (total_stock - sim_remaining) / max(1, total_stock)
        room_ratio = max(0.0, (potential_limit - current_sim_rate) / potential_limit) if potential_limit > 0 else 0.0
        
        effective_elasticity = elasticity_val
        if price_ratio > 1.0:
            # 値下げによるブースト効果は、残りのポテンシャル余裕度に依存する（余裕がないと効かない）
            effective_elasticity = elasticity_val * math.sqrt(room_ratio)
            
        demand_mul = config.get("demand_multiplier", 1.0)
        sim_demand_float = effective_actual * math.pow(price_ratio, effective_elasticity) * demand_mul
        
        # 値下げにより需要が不自然に急増した場合、未来の分を前借りしたとみなす（カニバリゼーション記録）
        if price_ratio > 1.0 and sim_demand_float > actual_demand_raw:
            extra = sim_demand_float - actual_demand_raw
            cannibalized_demand += extra * 0.3 # 増加分の30%を未来の実績から削る
        
        # 整数化の際に確率的な丸め、または単純四捨五入（ここでは安定性のため四捨五入）
        sim_demand = int(round(sim_demand_float)) if actual_demand_raw > 0 or sim_demand_float > 0.5 else 0
        
        # 絶対的な天井リミッター：ポテンシャル上限件数を超過する爆発的売上をカット
        max_allowable_sales = int(total_stock * potential_limit)
        current_sales = total_stock - sim_remaining
        if current_sales + sim_demand > max_allowable_sales:
            sim_demand = max(0, max_allowable_sales - current_sales)
            
        sim_demand = min(sim_demand, sim_remaining)
        
        # ─── [3] 状態更新
        sim_remaining -= sim_demand
        sim_revenue += (sim_demand * curr_price)
        
        base_demand = min(actual_demand_raw, base_remaining)
        base_remaining -= base_demand
        base_revenue += (base_demand * base_price)
        
        # ─── [4] MAPE用の予測率 vs 実績率 記録
        def _get_seasonal_target_rate(dep_date, c):
            if not dep_date:
                return c.get("target_sell_rate", 1.0)
            try:
                import pandas as pd
                dt = pd.to_datetime(dep_date)
                m = dt.month
                if m in {5, 7, 8}: return c.get("target_rate_peak", c.get("target_sell_rate", 0.95))
                elif m in {2, 6, 11}: return c.get("target_rate_offpeak", c.get("target_sell_rate", 0.60))
                else: return c.get("target_rate_normal", c.get("target_sell_rate", 0.80))
            except Exception:
                return c.get("target_sell_rate", 1.0)
        
        target_sr = _get_seasonal_target_rate(inv_row.get("departure_date"), config)
        if strategy == "demand_forecast":
            k_p = config.get("decay_k", 20.0)
            p_p = config.get("decay_p", 0.12)
            pattern_p = config.get("decay_pattern", "standard")
            decay_for_plot = calculate_inventory_decay_factor(d, BACKTEST_WINDOW, k_p, p_p, pattern=pattern_p)
            predicted_sales = total_stock * target_sr * (1.0 - decay_for_plot)
        else:
            predicted_sales = total_stock * target_sr * (1.0 - (d / BACKTEST_WINDOW))
            
        predicted_rates.append(predicted_sales / max(1, total_stock))
        actual_rates.append(actual_sales_so_far / max(1, total_stock))
        sim_rates.append((total_stock - sim_remaining) / max(1, total_stock))
        tracked_days.append(d)
        
        # ─── [5] Directional Accuracy
        price_change = curr_price - prev_price
        demand_change = actual_demand_raw - prev_actual_demand
        if abs(price_change) > 100 and demand_change != 0:
            if (price_change > 0 and demand_change <= 0) or (price_change < 0 and demand_change >= 0):
                directional_correct += 1
            directional_count += 1
            
        prev_price = curr_price
        prev_actual_demand = actual_demand_raw

    # --- スコア算出 ---
    
    # 1. MAPE, MAE, RMSE, Bias (売れ始めの0割は分母が0になるため、除外または微小値を足す)
    mape_sum = 0
    mae_sum = 0
    rmse_sum = 0
    bias_sum = 0
    valid_days = 0
    for p, a in zip(predicted_rates, actual_rates):
        if a > 0.05: # 販売率5%を超えてからの精度をみる
            diff = p - a
            mape_sum += abs(diff) / a
            mae_sum += abs(diff)
            rmse_sum += diff ** 2
            bias_sum += diff
            valid_days += 1
            
    mape = (mape_sum / valid_days) * 100 if valid_days > 0 else 0
    mae = (mae_sum / valid_days) * 100 if valid_days > 0 else 0
    rmse = math.sqrt(rmse_sum / valid_days) * 100 if valid_days > 0 else 0
    bias = (bias_sum / valid_days) * 100 if valid_days > 0 else 0
    
    # 2. Revenue Lift
    revenue_lift = ((sim_revenue - base_revenue) / base_revenue) * 100 if base_revenue > 0 else 0
    
    # 3. Spoilage Reduction
    base_spoilage_units = base_remaining
    sim_spoilage_units = sim_remaining
    
    base_spoilage_value = base_spoilage_units * base_price
    sim_spoilage_value = sim_spoilage_units * base_price
    
    if base_spoilage_value > 0:
        spoilage_reduction = (1 - (sim_spoilage_value / base_spoilage_value)) * 100
    else:
        spoilage_reduction = 0 # 元々廃棄損ゼロ
        
    # 4. Directional Accuracy
    dir_acc = (directional_correct / directional_count) * 100 if directional_count > 0 else 0
    
    # 5. DTW Distance (Shape Similarity)
    # 累積率リストの長さが揃っている前提 (tracked_daysが共通のため)
    dtw_dist = calculate_dtw_distance(predicted_rates, actual_rates)
    
    # 6. Composite Score
    # MAPE: 0=100点, 20=0点
    score_mape = max(0, 100 - (mape * 5))
    # DTW: 0=100点, 0.2=0点 (0.1程度が許容範囲)
    score_dtw = max(0, 100 - (dtw_dist * 500))
    # Lift: 0=50点, +20%=100点
    score_lift = min(100, max(0, 50 + (revenue_lift * 2.5)))
    # Spoilage: 0=50点, +50%=100点
    score_spoilage = min(100, max(0, 50 + spoilage_reduction))
    # Dir Acc: 0-100直結
    score_dir = dir_acc
    
    # ユーザー設定の重み（なければ波形重視のデフォルト値）
    w_mape = config.get('score_weight_mape', 0.40)
    w_dtw = config.get('score_weight_dtw', 0.30)
    w_lift = config.get('score_weight_lift', 0.15)
    w_spoil = config.get('score_weight_spoilage', 0.10)
    w_dir = config.get('score_weight_dir_acc', 0.05)
    
    composite = (score_mape     * w_mape)  + \
                (score_dtw      * w_dtw)   + \
                (score_lift     * w_lift)  + \
                (score_spoilage * w_spoil) + \
                (score_dir      * w_dir)
    
    return {
        "mape": mape,
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "dtw_distance": dtw_dist,
        "revenue_lift": round(revenue_lift, 1),
        "spoilage_reduction": round(spoilage_reduction, 1),
        "directional_accuracy": dir_acc,
        "composite_score": round(composite, 1),
        "lead_days": tracked_days,
        "predicted_rates": predicted_rates,
        "actual_rates": actual_rates,
        "simulated_rates": sim_rates,
        "base_revenue": base_revenue,
        "sim_revenue": sim_revenue,
    }

def _empty_eval():
    return {
        "mape": 0,
        "mae": 0,
        "rmse": 0,
        "bias": 0,
        "revenue_lift": 0, "spoilage_reduction": 0, "directional_accuracy": 0, "composite_score": 0,
        "lead_days": [], "predicted_rates": [], "actual_rates": [],
        "simulated_rates": [], "base_revenue": 0, "sim_revenue": 0,
    }

def run_batch_evaluation(inv_df: pd.DataFrame, booking_events: pd.DataFrame, current_config: dict) -> pd.DataFrame:
    """
    完了済み商品群に対して、全自動で分類推定＆バックテストを行い、レポート用DFを返す
    """
    records = []
    
    # 出発済みの商品のみ抽出 (ここでは簡略化して全inv_dfを回す)
    for _, row in inv_df.iterrows():
        inv_id = row["id"]
        ev = booking_events[booking_events["inventory_id"] == inv_id]
        
        # 1. 特性の自動判定または取得
        item_type = row["item_type"]
        name = row["name"]
        
        cls_data = get_product_classification(name, item_type)
        if cls_data:
            char = cls_data["characteristic"]
        else:
            char = auto_classify_product(ev, row["total_stock"], config=current_config)
            
        item_type = row["item_type"]
        
        # 2. ルールベースのバックテスト
        result_rule = backtest_strategy("rule_based", row, ev, current_config)
        
        # 3. 需要予測のバックテスト
        result_demand = backtest_strategy("demand_forecast", row, ev, current_config)
        
        records.append({
            "inventory_id": inv_id,
            "name": row["name"],
            "item_type": item_type,
            "characteristic": char,
            "rule_score": result_rule["composite_score"],
            "demand_score": result_demand["composite_score"],
            "rule_metrics": result_rule,
            "demand_metrics": result_demand
        })
        
    return pd.DataFrame(records)
