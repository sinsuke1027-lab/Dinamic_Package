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

def save_product_classification(name: str, item_type: str, characteristic: str, source: str = "manual") -> None:
    """特定商品の分類をDBに保存する"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    cur.execute('''
        INSERT INTO product_classification (name, item_type, characteristic, source, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name, item_type) DO UPDATE SET 
            characteristic = excluded.characteristic,
            source = excluded.source,
            updated_at = excluded.updated_at
    ''', (name, item_type, characteristic, source, now_str))
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
    total_stock = inv_row["total_stock"]
    base_price = inv_row["base_price"]
    
    # 弾力性の優先順位: config > マスタ値
    elasticity_val = abs(config.get("elasticity", inv_row.get("elasticity", 1.5)))
    
    # 経過日数の配列を作る (過去90日から0日まで)
    days = list(range(90, -1, -1))
    
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
    sim_remaining = total_stock
    sim_revenue = 0
    
    # 定価維持（Baseline）シミュレーション
    base_revenue = 0
    base_remaining = total_stock
    actual_sales_so_far = 0
    predicted_rates = []
    actual_rates = []
    tracked_days = []
    
    directional_correct = 0
    directional_count = 0
    prev_price = base_price
    prev_actual_demand = 0
    
    for d in days:
        # Note: Removing the 'if sim_remaining <= 0: break' to ensure fixed-length results for averaging
            
        actual_demand = daily_actual_sales.get(d, 0)
        actual_sales_so_far += actual_demand
        
        # ─── [1] 新しい戦略に基づく価格計算 (実際のエンジンを呼び出し)
        from pricing_engine import calculate_pricing_result
        
        # 疑似在庫行
        # エンジン内部で lead_days を再計算するため、reference_date を適切に設定する
        
        # エンジン実行 (キーワード引数で安全に呼び出し)
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
            
        # ─── [2] 価格弾力性による仮想需要の計算
        # 潜在需要の底上げ (Demand Smoothing): 
        # 実績が0の日でも、価格を下げれば売れる可能性があるため、微小な値をベースにする
        demand_floor = 0.05 
        effective_actual = max(actual_demand, demand_floor)
        
        price_ratio = base_price / curr_price if curr_price > 0 else 1.0
        demand_mul = config.get("demand_multiplier", 1.0)
        
        # 弾力性による増減を、底上げしたベースに対して計算
        sim_demand_float = effective_actual * math.pow(price_ratio, elasticity_val) * demand_mul
        
        # 整数化の際に確率的な丸め、または単純四捨五入
        # ここではシミュレーションの安定性のため四捨五入（0.5以上で1件）
        sim_demand = int(round(sim_demand_float)) if actual_demand > 0 or sim_demand_float > 0.5 else 0
        sim_demand = min(sim_demand, sim_remaining)
        
        # ─── [3] 状態更新
        sim_remaining -= sim_demand
        sim_revenue += (sim_demand * curr_price)
        
        base_demand = min(actual_demand, base_remaining)
        base_remaining -= base_demand
        base_revenue += (base_demand * base_price)
        
        # ─── [4] MAPE用の予測率 vs 実績率 記録
        target_sr = config.get("target_sell_rate", 1.0)
        if strategy == "demand_forecast":
            k_p = config.get("decay_k", 20.0)
            p_p = config.get("decay_p", 0.12)
            pattern_p = config.get("decay_pattern", "standard")
            decay_for_plot = calculate_inventory_decay_factor(d, 90, k_p, p_p, pattern=pattern_p)
            predicted_sales = total_stock * target_sr * (1.0 - decay_for_plot)
        else:
            predicted_sales = total_stock * target_sr * (1.0 - (d / 90))
            
        predicted_rates.append(predicted_sales / max(1, total_stock))
        actual_rates.append(actual_sales_so_far / max(1, total_stock))
        tracked_days.append(d)
        
        # ─── [5] Directional Accuracy
        price_change = curr_price - prev_price
        demand_change = actual_demand - prev_actual_demand
        if abs(price_change) > 100 and demand_change != 0:
            if (price_change > 0 and demand_change <= 0) or (price_change < 0 and demand_change >= 0):
                directional_correct += 1
            directional_count += 1
            
        prev_price = curr_price
        prev_actual_demand = actual_demand

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
        "dtw_distance": round(dtw_dist, 4),
        "revenue_lift": round(revenue_lift, 1),
        "spoilage_reduction": round(spoilage_reduction, 1),
        "directional_accuracy": round(dir_acc, 1),
        "composite_score": round(composite, 1),
        "lead_days": tracked_days,
        "predicted_rates": predicted_rates,
        "actual_rates": actual_rates
    }

def _empty_eval():
    return {
        "mape": 0,
        "mae": 0,
        "rmse": 0,
        "bias": 0,
        "revenue_lift": 0, "spoilage_reduction": 0, "directional_accuracy": 0, "composite_score": 0,
        "lead_days": [], "predicted_rates": [], "actual_rates": []
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
