import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import math # 追加
from constants import (
    DEFAULT_COST_RATIO, FORECAST_MULTIPLIERS,
    BUNDLE_VELOCITY_BOOST, BUNDLE_THRESHOLD, BUNDLE_DISCOUNT_RATE,
    CANNIBALIZATION_RATE
)

# データベースへの相対パス
DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# 出発直前の資産減衰計算用（pricing_engineからインポート）
def _get_decay_factor(lead_days: int, total_lead_days: int) -> float:
    try:
        from pricing_engine import calculate_inventory_decay_factor
        return calculate_inventory_decay_factor(lead_days, total_lead_days)
    except ImportError:
        return 1.0 # 予備

def get_velocity_ratio(inventory_id: int, total_stock: int, remaining_stock: int, lead_days: int) -> Optional[float]:
    """直近24時間の販売ペースを期待値と比較した比率を算出する"""
    conn = get_conn()
    now = datetime.now(timezone.utc)
    one_day_ago = (now - timedelta(days=1)).isoformat()
    
    row = conn.execute(
        "SELECT SUM(quantity) as qty FROM booking_events WHERE inventory_id = ? AND booked_at >= ?",
        (inventory_id, one_day_ago)
    ).fetchone()
    conn.close()
    
    actual_24h = row["qty"] if row and row["qty"] else 0
    # 期待される24時間あたりの販売数 (単純な定速モデル)
    expected_24h = (total_stock / max(lead_days, 1)) if lead_days > 0 else 0
    
    if expected_24h == 0:
        return None
    return actual_24h / expected_24h

def hotel_urgency_score(remaining_stock: int, total_stock: int, lead_days: int) -> float:
    """ホテルの切迫度スコア (0.0 - 1.0)"""
    inv_ratio = remaining_stock / total_stock if total_stock > 0 else 0
    # 残り日数が少ないほど、在庫が多いほどスコアが高くなる
    time_factor = max(0, 1.0 - (lead_days / 30.0))
    inv_factor = inv_ratio
    return (inv_factor * 0.7 + time_factor * 0.3)

def calc_velocity_adjustment(dynamic_price: int, velocity_ratio: Optional[float]) -> tuple[int, str]:
    """販売速度に基づいた価格調整額を算出する"""
    if velocity_ratio is None:
        return 0, "分析データなし"
    
    if velocity_ratio >= 2.0:
        adj = int(dynamic_price * 0.10)
        return adj, f"売れすぎ({velocity_ratio:.1f}x) → 値上げ(+10%)"
    elif velocity_ratio >= 1.5:
        adj = int(dynamic_price * 0.05)
        return adj, f"好調({velocity_ratio:.1f}x) → 値上げ(+5%)"
    elif velocity_ratio <= 0.3:
        adj = int(dynamic_price * -0.05)
        return adj, f"鈍化({velocity_ratio:.1f}x) → 値下げ(-5%)"
    return 0, "安定"

def calculate_roi_metrics(inventory_ids: Optional[list[int]] = None) -> dict:
    """動的価格設定による収益改善効果(ROI)を算出する"""
    conn = get_conn()
    
    where_clause = ""
    params = []
    if inventory_ids:
        placeholders = ",".join(["?"] * len(inventory_ids))
        where_clause = f"WHERE inventory_id IN ({placeholders})"
        params = inventory_ids

    # 簡易的な集計: 累計の sold_price vs base_price_at_sale
    row = conn.execute(f"""
        SELECT 
            SUM(sold_price) as total_dynamic,
            SUM(base_price_at_sale) as total_fixed,
            SUM(quantity) as total_units
        FROM booking_events
        {where_clause}
    """, params).fetchone()
    
    total_dynamic = row["total_dynamic"] or 0
    total_fixed   = row["total_fixed"] or 0
    lift = total_dynamic - total_fixed
    lift_pct = (lift / total_fixed * 100) if total_fixed > 0 else 0
    
    daily_rows = conn.execute(f"""
        SELECT date(booked_at) as day, SUM(sold_price) as day_dynamic, SUM(base_price_at_sale) as day_fixed
        FROM booking_events
        {where_clause}
        GROUP BY day ORDER BY day
    """, params).fetchall()
    
    conn.close()
    
    return {
        "total_dynamic": total_dynamic,
        "total_fixed":   total_fixed,
        "lift":          lift,
        "lift_pct":      round(lift_pct, 1),
        "total_units":   row["total_units"] or 0,
        "daily_data":    [dict(r) for r in daily_rows]
    }

def calculate_demand_forecast(inventory_id: int, lead_days: int, remaining_stock: int, total_stock: int, base_price: int, cost: int) -> dict:
    """特定商品の需要予測を行い、3つのシナリオを返す。"""
    conn = get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    row = conn.execute(
        "SELECT SUM(quantity) as qty FROM booking_events WHERE inventory_id = ? AND booked_at >= ?",
        (inventory_id, cutoff)
    ).fetchone()
    conn.close()

    actual_14d = row["qty"] if row and row["qty"] else 0
    base_velocity = actual_14d / 14.0
    if base_velocity < 0.05:
        base_velocity = (total_stock * 0.7 / max(lead_days, 30))

    scenarios = {
        "pessimistic": {"multiplier": FORECAST_MULTIPLIERS["pessimistic"], "label": "悲観"},
        "base":        {"multiplier": FORECAST_MULTIPLIERS["base"], "label": "ベース"},
        "optimistic":  {"multiplier": FORECAST_MULTIPLIERS["optimistic"], "label": "楽観"}
    }
    
    forecast_results = {}
    for key, sc in scenarios.items():
        daily_pace = base_velocity * sc["multiplier"]
        predicted_total_sales = min(remaining_stock, daily_pace * max(0, lead_days))
        unsold_stock = remaining_stock - predicted_total_sales
        # 修正①: 粗利 = 売価(base_price) - 原価(cost)  ← 以前は base_price * 0.2 で誤差大
        gross_profit = predicted_total_sales * (base_price - cost)
        waste_loss = unsold_stock * cost
        net_profit = gross_profit - waste_loss
        
        forecast_results[key] = {
            "daily_pace": round(daily_pace, 2),
            "predicted_sales": round(predicted_total_sales, 1),
            "unsold_stock": round(unsold_stock, 1),
            "expected_profit": int(net_profit),
            "label": sc["label"]
        }
    return forecast_results

def calculate_inventory_rescue_metrics(inventory_ids: Optional[list[int]] = None) -> dict:
    """切迫在庫の救済率を算出する"""
    conn = get_conn()
    
    where_clause = ""
    params = []
    if inventory_ids:
        placeholders = ",".join(["?"] * len(inventory_ids))
        where_clause = f"WHERE inventory_id IN ({placeholders})"
        params = inventory_ids

    rescue_row = conn.execute(f"""
        SELECT 
            SUM(CASE WHEN is_package = 1 THEN quantity ELSE 0 END) AS rescued_units,
            SUM(quantity) AS total_units
        FROM booking_events
        {where_clause}
    """, params).fetchone()
    
    rescued_units = rescue_row["rescued_units"] or 0
    total_units   = rescue_row["total_units"] or 1
    
    # ホテル救済率の算出 (パッケージにより販売されたホテルの割合)
    # 実際には booking_events からホテルに限定して集計
    h_rescue_row = conn.execute(f"""
        SELECT 
            SUM(CASE WHEN be.is_package = 1 THEN be.quantity ELSE 0 END) AS h_rescued_units,
            SUM(be.quantity) AS h_total_units
        FROM booking_events be
        JOIN inventory i ON be.inventory_id = i.id
        WHERE i.item_type = 'hotel'
        {where_clause.replace("WHERE ", "AND ")}
    """, params).fetchone()
    
    conn.close()
    
    h_rescued = h_rescue_row["h_rescued_units"] or 0
    h_total   = h_rescue_row["h_total_units"] or 1
    h_rescue_rate = (h_rescued / h_total * 100)

    return {
        "overall_rescue_rate": round(rescued_units / total_units * 100, 1),
        "rescued_units": rescued_units,
        "total_units": total_units,
        "hotel_rescue_rate": round(h_rescue_rate, 1)
    }

def simulate_sales_scenario(
    h_item: dict, 
    f_item: dict, 
    discount: int, 
    lead_days: int, 
    market_condition: str = "base"
) -> dict:
    """
    30日間（またはリードタイム分）の販売シミュレーションを行い、
    単品維持(Scenario A) vs ハイブリッド(Scenario B) の収益差分を計算する。
    app.py（シミュレーター）とロジックを100%統一。
    """
    # 1. 基礎データ (AI時価基準)
    h_unit_profit_standalone = h_item["current_price"] - h_item["cost"]
    f_unit_profit_standalone = f_item["current_price"] - f_item["cost"]
    
    # 需要予測
    h_forecasts = calculate_demand_forecast(
        h_item["id"], lead_days, h_item["remaining_stock"], 
        h_item["total_stock"], h_item["base_price"], h_item["cost"]
    )
    vel_a_base = h_forecasts.get(market_condition, h_forecasts["base"])["daily_pace"]
    
    # パッケージ速度（シミュレーターと同期）
    vel_b_base = 2.5 
    lift_factor = 1.0 + (discount / 10000.0)
    vel_b_boosted = vel_b_base * lift_factor
    
    # 動的カニバリゼーション（シミュレーターと同期）
    dynamic_cannibal_rate = min(1.0, max(0.0, f_item.get("velocity_ratio", 1.0) - 1.0))
    
    # 2. タイムライン計算
    curr_a_h_stock = h_item["remaining_stock"]
    curr_b_h_stock = h_item["remaining_stock"]
    flight_stock_a = f_item["remaining_stock"]
    flight_stock_b = f_item["remaining_stock"]
    
    total_profit_a = 0
    total_profit_b = 0
    total_sold_pkg = 0
    history = []

    days_t = list(range(max(1, lead_days), -1, -1))
    
    for t in days_t:
        # --- シナリオ A (単品) ---
        sold_h_a = min(curr_a_h_stock, vel_a_base)
        curr_a_h_stock -= sold_h_a
        total_profit_a += sold_h_a * h_unit_profit_standalone

        sold_f_a = min(flight_stock_a, vel_b_base)
        flight_stock_a -= sold_f_a
        total_profit_a += sold_f_a * f_unit_profit_standalone

        # --- シナリオ B (パッケージ + 切替) ---
        # パッケージ販売
        stock_cap_b = min(curr_b_h_stock, flight_stock_b)
        sold_pkg = min(stock_cap_b, vel_b_boosted)
        total_sold_pkg += sold_pkg
        curr_b_h_stock -= sold_pkg
        flight_stock_b -= sold_pkg
        
        # パッケージ利益
        pkg_unit_profit = (h_unit_profit_standalone + f_unit_profit_standalone) - discount
        total_profit_b += sold_pkg * pkg_unit_profit - (sold_pkg * f_unit_profit_standalone * dynamic_cannibal_rate)

        # 在庫が偏った場合の単品切替
        if curr_b_h_stock > 0 and flight_stock_b == 0:
            sold_h_solo = min(curr_b_h_stock, vel_a_base)
            curr_b_h_stock -= sold_h_solo
            total_profit_b += sold_h_solo * h_unit_profit_standalone
        elif flight_stock_b > 0 and curr_b_h_stock == 0:
            sold_f_solo = min(flight_stock_b, vel_b_base)
            flight_stock_b -= sold_f_solo
            total_profit_b += sold_f_solo * f_unit_profit_standalone

        # 履歴記録 (グラフ用)
        history.append({
            "day_idx": t,
            "day_label": f"D-{t}",
            "profit_a": int(total_profit_a),
            "profit_b": int(total_profit_b),
            "h_stock_b": int(curr_b_h_stock),
            "f_stock_b": int(flight_stock_b),
            "decay_factor": _get_decay_factor(t, lead_days)
        })

    # 30日目の廃棄損 (Day 0)
    waste_a = (curr_a_h_stock * h_item["cost"] + flight_stock_a * f_item["cost"])
    waste_b = (curr_b_h_stock * h_item["cost"] + flight_stock_b * f_item["cost"])
    total_profit_a -= waste_a
    total_profit_b -= waste_b
    
    # 最終日の履歴を廃棄損考慮後に更新 (任意だが、グラフの末端を合わせるため)
    if history:
        history[-1]["profit_a"] = int(total_profit_a)
        history[-1]["profit_b"] = int(total_profit_b)

    return {
        "profit_a": int(total_profit_a),
        "profit_b": int(total_profit_b),
        "gain": int(total_profit_b - total_profit_a),
        "max_sets": int(h_item["remaining_stock"]), # 目安
        "packages_sold": int(total_sold_pkg),
        "history": history
    }



def calculate_optimal_strategy(scenario: str = "base", inventory_ids: Optional[list[int]] = None, current_prices: Optional[Dict[int, int]] = None) -> dict:
    """
    全商品に対して「単品維持」vs「パッケージ化」の最適販売戦略を計算する。
    Prescriptive Analytics の中核ロジック。

    Args:
        scenario: "base" / "pessimistic" / "optimistic"
        inventory_ids: フィルタリング対象のIDリスト

    Returns:
        {
            "recommendations": list[dict],  # 商品ごとのアクションプラン
            "total_standalone_profit": int,  # 全単品での予測総利益
            "total_optimized_profit": int,   # AI推奨戦略実行時の予測総利益
            "ai_impact": int,               # 利益改善インパクト
        }
    """
    # ---------- Step 1: 全商品の単品着地点を算出 ----------

    conn = get_conn()

    where_clause = ""
    params = []
    if inventory_ids:
        placeholders = ",".join(["?"] * len(inventory_ids))
        where_clause = f"WHERE id IN ({placeholders})"
        params = inventory_ids

    # 全在庫を取得
    rows = conn.execute(f"""
        SELECT id, name, item_type, base_price, total_stock, remaining_stock, departure_date 
        FROM inventory
        {where_clause}
    """, params).fetchall()
    conn.close()

    if not rows:
        return {
            "recommendations": [],
            "total_standalone_profit": 0,
            "total_optimized_profit": 0,
            "ai_impact": 0,
        }

    now = datetime.now(timezone.utc).date()

    # ---------- Step 1: 全商品の単品着地点を算出 ----------
    items = []
    for row in rows:
        dep_date = None
        if row["departure_date"]:
            try:
                dep_date = datetime.fromisoformat(str(row["departure_date"])).date()
            except Exception:
                dep_date = None

        lead_days = (dep_date - now).days if dep_date else 90
        cost = int(row["base_price"] * DEFAULT_COST_RATIO)

        # フライトの販売速度比率を取得（カニバリゼーション率の動的算出に使用）
        vr = get_velocity_ratio(row["id"], row["total_stock"], row["remaining_stock"], max(lead_days, 1))

        forecast = calculate_demand_forecast(
            inventory_id    = row["id"],
            lead_days       = lead_days,
            remaining_stock = row["remaining_stock"],
            total_stock     = row["total_stock"],
            base_price      = row["base_price"],
            cost            = cost,
        )
        sc = forecast.get(scenario, forecast["base"])

        items.append({
            "id":               row["id"],
            "name":             row["name"],
            "item_type":        row["item_type"],  # "hotel" or "flight"
            "base_price":       row["base_price"],
            "current_price":    current_prices.get(row["id"], row["base_price"]) if current_prices else row["base_price"],
            "total_stock":      row["total_stock"],
            "remaining_stock":  row["remaining_stock"],
            "lead_days":        lead_days,
            "cost":             cost,
            "departure_date":   str(row["departure_date"]) if row["departure_date"] else "---",
            "velocity_ratio":   vr if vr is not None else 1.0,  # 動的カニバリゼーション向け
            "standalone_profit": sc["expected_profit"], # 互換用(単独予測)
            "unsold_stock":     sc["unsold_stock"],
            "daily_pace":       sc["daily_pace"],
        })

    hotels  = [i for i in items if i["item_type"] == "hotel"]
    flights = [i for i in items if i["item_type"] == "flight"]

    # ---------- Step 2: 最良の組み合わせを探索 (O(n×m)) ----------
    # ホテルの「パッケージ最適割引率」を 8% と仮定して全フライトを試算
    # (シミュレーターの動的ループを用いるため、以前の簡易的な組合せロジックを置換)
    hotel_best_bundle = {}
    for h in hotels:
        best_gain = -999_999_999
        best_result = None
        # 提案割引額 (サマリ用): (合計価格の8% または 固定8000円など)
        proposed_discount = int((h["current_price"] + (h["current_price"]*0.5)) * 0.08) # 目安

        for f in flights:
            if f["departure_date"] != h["departure_date"]:
                continue

            # シミュレーション実行 (不整合解消の核)
            sim = simulate_sales_scenario(h, f, proposed_discount, h["lead_days"], scenario)
            gain = sim["gain"]

            if gain > best_gain:
                best_gain = gain
                bundle_price = int(h["current_price"] + f["current_price"] - proposed_discount)
                best_result = {
                    "flight": f,
                    "gain": gain,
                    "bundle_price": bundle_price,
                    "max_sets": sim["max_sets"],
                    "sim_data": sim # 詳細が必要な場合用
                }
        hotel_best_bundle[h["id"]] = best_result

    # ホテルに対し「最良のフライト相棒」を探す
    # (Step 2の結果 hotel_best_bundle をそのまま使用)

    # フライトが複数のホテルに「最良相棒」として使われていた場合は、最も利益改善が大きいホテルに割り当てる
    sorted_hotels = sorted(hotels, key=lambda h: (hotel_best_bundle.get(h["id"]) or {}).get("gain", -999_999_999), reverse=True)

    # ---------- Step 3: 推奨アクションリスト生成 ----------
    recommendations = []
    bundled_hotel_ids  = set()
    bundled_flight_ids = set()

    # まずバンドル推奨を確定する（利益の大きい順）
    for h in sorted_hotels:
        best = hotel_best_bundle.get(h["id"])
        if not best or best["gain"] <= BUNDLE_THRESHOLD:
            continue
        f = best["flight"]
        if f["id"] in bundled_flight_ids:
            continue

        bundled_hotel_ids.add(h["id"])
        bundled_flight_ids.add(f["id"])

        recs_reason = (
            f"廃棄損を ¥{int(h['unsold_stock'] * h['cost']):,} から削減。"
            f"「{f['name']}」と組むことで全体利益が ¥{best['gain']:,} 改善。"
        )
        recommendations.append({
            "item_id":       h["id"],
            "departure_date": h["departure_date"],
            "item_name":     h["name"],
            "item_type":     "hotel",
            "strategy":      "bundle",
            "partner_name":  f["name"],
            "optimal_price": best["bundle_price"],
            "max_sets":      best["max_sets"],
            "gain":          best["gain"],
            "reason":        recs_reason,
        })

    # 単品維持の商品
    for it in items:
        if it["id"] in bundled_hotel_ids or it["id"] in bundled_flight_ids:
            continue
        
        if it["item_type"] == "flight":
            reason = "現在のペースで売り切れる見込みが強く、パッケージ化より単品販売が有利です。"
        else:
            reason = "切迫リスクは低く、現行価格での単品維持が最適です。"
        
        recommendations.append({
            "item_id":       it["id"],
            "departure_date": it["departure_date"],
            "item_name":     it["name"],
            "item_type":     it["item_type"],
            "strategy":      "standalone",
            "partner_name":  None,
            "optimal_price": it["current_price"], # 時価
            "max_sets":      None,
            "gain":          0,
            "reason":        reason,
        })

    # バンドル側のフライトレコードも追加
    for it in items:
        if it["id"] in bundled_flight_ids:
            recommendations.append({
                "item_id":       it["id"],
                "item_name":     it["name"],
                "item_type":     "flight",
                "strategy":      "bundle_partner",
                "partner_name":  None,
                "optimal_price": it["current_price"],
                "max_sets":      None,
                "gain":          0,
                "reason":        "ホテルとのパッケージ提供に組み込まれています。",
            })

    # ---------- Step 4: 合計利益の算出 (厳密なシミュレーションベース) ----------
    total_standalone = 0
    total_optimized  = 0
    processed_h = set()
    processed_f = set()

    # 1. バンドル組
    for h_id in bundled_hotel_ids:
        best = hotel_best_bundle[h_id]
        total_standalone += best["sim_data"]["profit_a"]
        total_optimized  += best["sim_data"]["profit_b"]
        processed_h.add(h_id)
        processed_f.add(best["flight"]["id"])

    # 2. その他単品
    for it in items:
        if it["id"] not in processed_h and it["id"] not in processed_f:
            # 単品シミュレーションを実行して利益を計上
            dummy_f = {"id": -1, "remaining_stock": 0, "cost": 0, "current_price": 0, "velocity_ratio": 0, "base_price": 0}
            sim_a = simulate_sales_scenario(it, dummy_f, 0, it["lead_days"], scenario)
            total_standalone += sim_a["profit_a"]
            total_optimized  += sim_a["profit_a"]

    ai_impact = total_optimized - total_standalone

    return {
        "recommendations": recommendations,
        "total_standalone_profit": int(total_standalone),
        "total_optimized_profit":  int(total_optimized),
        "ai_impact":               int(ai_impact),
    }
