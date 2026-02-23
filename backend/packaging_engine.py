"""
packaging_engine.py

フライトとホテルを組み合わせた最適パッケージ作成エンジン（フェーズ8 統合版）。

【実装済みロジック】
  1. クロスセル・マッチング（フェーズ7）
     - ホテル緊急スコア × フライト需要スコア → 戦略スコアでペアを評価
  2. Velocity-based Pricing（フェーズ8）
     - booking_events テーブルの直近24h予約件数 vs 期待販売ペースを比較
     - 売れすぎ（割安シグナル）→ 価格を自動引き上げ
     - データなし・想定内 → 調整なし

【数理設計（ホワイトボックス）】
  フライト価格 = dynamic_price + velocity_adjustment
  ホテル価格   = dynamic_price + velocity_adjustment
  合計         = フライト調整後 + ホテル調整後
  最終価格     = 合計 + bundle_discount （クロスセル割引）

【PackagingResult 出力例】
  {
    "rank": 1,
    "flight_name": "ハワイ行きチャーター便 B席",
    "hotel_name": "ホノルル・ビジネスホテル",
    "flight_dynamic_price":        47500,
    "flight_velocity_adjustment":   4800,   # 売れすぎ(×2.1) → 自動値上げ
    "hotel_dynamic_price":          9200,
    "hotel_velocity_adjustment":       0,   # 想定内
    "sum_dynamic_price":           61500,   # velocity 込み合計
    "hotel_urgency_score":          0.53,
    "bundle_discount":             -1100,
    "final_package_price":         60400,
    "flight_velocity_ratio":         2.1,
    "hotel_velocity_ratio":          0.9,
    "strategy_score":               0.61,
    "reason": "..."
  }
"""

import sqlite3
import math
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

DATABASE = "inventory.db"

# Velocity 計算のウィンドウ（時間）
VELOCITY_WINDOW_HOURS = 24
# 出発日までに売り切る目標比率
TARGET_SELL_RATIO = 0.90


# ─────────────────────────────────────────
# DB ユーティリティ
# ─────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────
# Step 1（フェーズ7）: ホテルの緊急スコア
# ─────────────────────────────────────────────────────────────

def hotel_urgency_score(
    remaining_stock: int,
    total_stock: int,
    lead_days: Optional[int],
) -> float:
    """
    ホテルの「売り急ぎ度」を 0.0〜1.0 でスコア化する。

    urgency = 時間切迫度 × 0.6 + 余剰在庫率 × 0.4
    """
    time_urgency = max(0.0, 1.0 - lead_days / 30.0) if (lead_days is not None and lead_days >= 0) else 0.0
    surplus_ratio = remaining_stock / total_stock if total_stock > 0 else 0.0
    score = time_urgency * 0.6 + surplus_ratio * 0.4
    return round(min(score, 1.0), 4)


# ─────────────────────────────────────────────────────────────
# Step 2（フェーズ7）: クロスセル割引
# ─────────────────────────────────────────────────────────────

def calc_bundle_discount(
    hotel_base_price: int,
    hotel_dynamic_price: int,
    urgency: float,
) -> int:
    """ホテルの限界利益を原資とするクロスセル割引額（負の整数）"""
    max_discount = hotel_base_price * 0.25
    raw_discount = max_discount * urgency
    discount = round(raw_discount / 100) * 100
    cap = math.floor(hotel_dynamic_price * 0.30 / 100) * 100
    discount = min(discount, cap)
    return -int(discount)


# ─────────────────────────────────────────────────────────────
# Step 3（フェーズ7）: ペア戦略スコア
# ─────────────────────────────────────────────────────────────

def calc_strategy_score(
    urgency: float,
    flight_remaining: int,
    flight_total: int,
) -> float:
    """
    strategy_score = hotel_urgency × 0.7 + flight_demand × 0.3
    flight_demand  = 1 − (残席 / 総席)
    """
    flight_demand = 1.0 - (flight_remaining / flight_total) if flight_total > 0 else 0.0
    return round(min(urgency * 0.7 + flight_demand * 0.3, 1.0), 4)


# ─────────────────────────────────────────────────────────────
# Step 4（フェーズ8）: Velocity-based Pricing
# ─────────────────────────────────────────────────────────────

def get_velocity_ratio(
    inventory_id: int,
    total_stock: int,
    remaining_stock: int,
    lead_days: Optional[int],
    window_hours: int = VELOCITY_WINDOW_HOURS,
) -> Optional[float]:
    """
    販売速度比率（velocity_ratio）を算出する。

    velocity_ratio = actual_daily_qty / expected_daily_qty
      actual_daily_qty  = 直近 window_hours の booking_events 合計 × (24 / window_hours)
      expected_daily_qty = total_stock × TARGET_SELL_RATIO / max(lead_days, 1)

    Returns:
        velocity_ratio（float）または None（データなし / 計算不能）
    """
    # 実績ペースの計算
    conn = get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM booking_events "
        "WHERE inventory_id = ? AND booked_at >= ?",
        (inventory_id, cutoff),
    ).fetchone()
    conn.close()

    actual_in_window = row["qty"] if row else 0

    if actual_in_window == 0:
        return None   # データなし → 調整しない

    # 日換算
    actual_daily = actual_in_window * (24.0 / window_hours)

    # 期待ペースの計算
    if lead_days is None or lead_days <= 0:
        # 出発済み / 未設定 → 計算不能
        return None

    target_sell_qty = total_stock * TARGET_SELL_RATIO
    expected_daily = target_sell_qty / lead_days

    if expected_daily <= 0:
        return None

    return round(actual_daily / expected_daily, 3)


def calc_velocity_adjustment(
    dynamic_price: int,
    velocity_ratio: Optional[float],
) -> tuple[int, str]:
    """
    velocity_ratio を価格調整額（円）と理由テキストに変換する。

    Returns:
        (調整額（正=値上げ/負=値下げ）, 理由テキスト)
    """
    if velocity_ratio is None:
        return 0, "販売データなし（velocity調整なし）"

    if velocity_ratio >= 2.0:
        mult = 0.10
        label = f"想定比{velocity_ratio:.1f}倍で売れすぎ → 強く値上げ(+10%)"
    elif velocity_ratio >= 1.5:
        mult = 0.05
        label = f"想定比{velocity_ratio:.1f}倍で売れすぎ → 緩く値上げ(+5%)"
    elif velocity_ratio >= 0.7:
        mult = 0.0
        label = f"想定比{velocity_ratio:.1f}倍（想定内）→ 調整なし"
    elif velocity_ratio >= 0.3:
        mult = -0.02
        label = f"想定比{velocity_ratio:.1f}倍（鈍化シグナル）→ 微小値下げ(-2%)"
    else:
        mult = 0.0
        label = f"想定比{velocity_ratio:.1f}倍（データ不足）→ 調整なし"

    adj = round(dynamic_price * mult / 100) * 100
    return int(adj), label


# ─────────────────────────────────────────────────────────────
# 理由文の生成（拡張版）
# ─────────────────────────────────────────────────────────────

def build_reason(
    flight_name: str, hotel_name: str,
    flight_inv_pct: int, hotel_inv_pct: int,
    hotel_lead_days: Optional[int], urgency: float,
    discount: int, hotel_base_price: int,
    flight_velocity_note: str, hotel_velocity_note: str,
    flight_velocity_adj: int, hotel_velocity_adj: int,
) -> str:
    lead_str = f"出発まで{hotel_lead_days}日" if hotel_lead_days is not None else "出発日未設定"
    disc_pct = round(abs(discount) / hotel_base_price * 100, 1) if hotel_base_price > 0 else 0
    urgency_label = (
        "極めて高い(緊急)" if urgency >= 0.80 else
        "高い" if urgency >= 0.60 else
        "中程度" if urgency >= 0.40 else "低い"
    )

    velocity_parts = []
    if flight_velocity_adj != 0:
        sign = "+" if flight_velocity_adj > 0 else ""
        velocity_parts.append(f"フライト: {flight_velocity_note}({sign}¥{flight_velocity_adj:,})")
    if hotel_velocity_adj != 0:
        sign = "+" if hotel_velocity_adj > 0 else ""
        velocity_parts.append(f"ホテル: {hotel_velocity_note}({sign}¥{hotel_velocity_adj:,})")
    velocity_str = " / ".join(velocity_parts) if velocity_parts else "velocity調整なし"

    return (
        f"ホテル「{hotel_name}」は残在庫{hotel_inv_pct}%・{lead_str}（売り逃しリスク: {urgency_label}）。"
        f"人気フライト「{flight_name}」（残席{flight_inv_pct}%）と組み合わせ、"
        f"ホテル原価の{disc_pct}%（¥{abs(discount):,}）をクロスセル割引として適用。"
        f"【販売速度調整】{velocity_str}。"
    )


# ─────────────────────────────────────────────────────────────
# メイン: 全フライト×ホテルのパッケージを生成
# ─────────────────────────────────────────────────────────────

def generate_packages(reference_date: Optional[date] = None) -> list[dict]:
    """
    全フライト×ホテルの PackagingResult リストを strategy_score 降順で返す。
    Velocity-based Pricing を統合済み。
    """
    from pricing_engine import calculate_pricing_result

    today = reference_date or date.today()

    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory").fetchall()
    conn.close()

    flights = [dict(r) for r in rows if r["item_type"] == "flight"]
    hotels  = [dict(r) for r in rows if r["item_type"] == "hotel"]

    if not flights or not hotels:
        print("⚠️  フライトまたはホテルのデータがありません。")
        return []

    packages = []

    for flight in flights:
        f_result = calculate_pricing_result(
            inventory_id    = flight["id"],
            name            = flight["name"],
            base_price      = flight["base_price"],
            total_stock     = flight["total_stock"],
            remaining_stock = flight["remaining_stock"],
            departure_date  = flight.get("departure_date"),
            reference_date  = today,
        )

        # ── フライトの velocity 取得（pricing_engine側ですでに加算済み） ──
        f_vel_ratio = f_result["velocity_ratio"]
        f_vel_adj   = f_result["velocity_adjustment"]
        _, f_vel_note = calc_velocity_adjustment(f_result["base_price"], f_vel_ratio)
        f_adjusted_price = f_result["final_price"]

        for hotel in hotels:
            h_result = calculate_pricing_result(
                inventory_id    = hotel["id"],
                name            = hotel["name"],
                base_price      = hotel["base_price"],
                total_stock     = hotel["total_stock"],
                remaining_stock = hotel["remaining_stock"],
                departure_date  = hotel.get("departure_date"),
                reference_date  = today,
            )

            # ── ホテルの velocity 取得 ────────────────────────────
            h_vel_ratio = h_result["velocity_ratio"]
            h_vel_adj   = h_result["velocity_adjustment"]
            _, h_vel_note = calc_velocity_adjustment(h_result["base_price"], h_vel_ratio)
            h_adjusted_price = h_result["final_price"]

            # ── クロスセル割引（ホテルの velocity 調整後価格を基準）──
            urgency = hotel_urgency_score(
                remaining_stock = hotel["remaining_stock"],
                total_stock     = hotel["total_stock"],
                lead_days       = h_result["lead_days"],
            )
            discount = calc_bundle_discount(
                hotel_base_price    = hotel["base_price"],
                hotel_dynamic_price = h_adjusted_price,
                urgency             = urgency,
            )

            sum_price   = f_adjusted_price + h_adjusted_price
            final_price = sum_price + discount

            strategy = calc_strategy_score(
                urgency          = urgency,
                flight_remaining = flight["remaining_stock"],
                flight_total     = flight["total_stock"],
            )

            f_inv_pct = int(flight["remaining_stock"] / flight["total_stock"] * 100) if flight["total_stock"] > 0 else 0
            h_inv_pct = int(hotel["remaining_stock"]  / hotel["total_stock"]  * 100) if hotel["total_stock"]  > 0 else 0

            reason = build_reason(
                flight_name          = flight["name"],
                hotel_name           = hotel["name"],
                flight_inv_pct       = f_inv_pct,
                hotel_inv_pct        = h_inv_pct,
                hotel_lead_days      = h_result["lead_days"],
                urgency              = urgency,
                discount             = discount,
                hotel_base_price     = hotel["base_price"],
                flight_velocity_note = f_vel_note,
                hotel_velocity_note  = h_vel_note,
                flight_velocity_adj  = f_vel_adj,
                hotel_velocity_adj   = h_vel_adj,
            )

            packages.append({
                "rank":                     0,   # ソート後に付与
                "flight_id":                flight["id"],
                "flight_name":              flight["name"],
                "flight_base":              flight["base_price"],
                "hotel_id":                 hotel["id"],
                "hotel_name":               hotel["name"],
                "hotel_base":               hotel["base_price"],
                # 各価格の内訳（加算モデル / ホワイトボックス）
                "flight_dynamic_price":     f_result["final_price"],
                "flight_velocity_ratio":    f_vel_ratio,
                "flight_velocity_adjustment": f_vel_adj,
                "hotel_dynamic_price":      h_result["final_price"],
                "hotel_velocity_ratio":     h_vel_ratio,
                "hotel_velocity_adjustment": h_vel_adj,
                "sum_dynamic_price":        sum_price,
                "hotel_urgency_score":      urgency,
                "bundle_discount":          discount,
                "final_package_price":      final_price,
                "strategy_score":           strategy,
                "reason":                   reason,
            })

    # strategy_score 降順でソートし rank を付与
    packages.sort(key=lambda x: x["strategy_score"], reverse=True)
    for i, pkg in enumerate(packages):
        pkg["rank"] = i + 1

    return packages


def calculate_roi_metrics() -> dict:
    """収益リフト（動的価格 vs 固定価格）を集計する"""
    conn = get_conn()
    cursor = conn.cursor()
    
    # 全販売データの集計
    row = cursor.execute("""
        SELECT 
            SUM(quantity * sold_price) AS total_dynamic,
            SUM(quantity * base_price_at_sale) AS total_fixed,
            SUM(quantity) AS total_units
        FROM booking_events
    """).fetchone()
    
    total_dynamic = row["total_dynamic"] or 0
    total_fixed   = row["total_fixed"] or 0
    lift          = total_dynamic - total_fixed
    lift_pct      = (lift / total_fixed * 100) if total_fixed > 0 else 0
    
    # 日別の推移データ（直近7日間）
    daily_rows = cursor.execute("""
        SELECT 
            date(booked_at) AS day,
            SUM(quantity * sold_price) AS day_dynamic,
            SUM(quantity * base_price_at_sale) AS day_fixed
        FROM booking_events
        GROUP BY day
        ORDER BY day ASC
    """).fetchall()
    
    conn.close()
    
    return {
        "total_dynamic": total_dynamic,
        "total_fixed":   total_fixed,
        "lift":          lift,
        "lift_pct":      round(lift_pct, 1),
        "total_units":   row["total_units"] or 0,
        "daily_data":    [dict(r) for r in daily_rows]
    }


def calculate_inventory_rescue_metrics() -> dict:
    """切迫在庫の救済率を算出する"""
    conn = get_conn()
    cursor = conn.cursor()
    
    # 全体のパッケージ寄与率（救済の代理指標）
    rescue_row = cursor.execute("""
        SELECT 
            SUM(CASE WHEN is_package = 1 THEN quantity ELSE 0 END) AS rescued_units,
            SUM(quantity) AS total_units
        FROM booking_events
    """).fetchone()
    
    rescued_units = rescue_row["rescued_units"] or 0
    total_units   = rescue_row["total_units"] or 1
    
    # 特にホテル（在庫リスクが高い傾向）に絞った集計
    hotel_rescue = cursor.execute("""
        SELECT 
            SUM(CASE WHEN is_package = 1 THEN b.quantity ELSE 0 END) AS rescued,
            SUM(b.quantity) AS total
        FROM booking_events b
        JOIN inventory i ON b.inventory_id = i.id
        WHERE i.item_type = 'hotel'
    """).fetchone()
    
    conn.close()
    
    return {
        "overall_rescue_rate": round((rescued_units / total_units * 100), 1),
        "rescued_units":       rescued_units,
        "hotel_rescue_rate":   round((hotel_rescue["rescued"] / (hotel_rescue["total"] or 1) * 100), 1),
        "total_units":         total_units
    }


# ─────────────────────────────────────────────────────────────
# CLI 実行
# ─────────────────────────────────────────────────────────────

def run():
    packages = generate_packages()
    if not packages:
        return

    sep = "═" * 105
    print(f"\n{sep}")
    print("  📦 Package Bundling Engine（Velocity統合版） — クロスセル戦略パッケージ 推奨一覧")
    print(sep)

    for pkg in packages:
        disc_str = f"-¥{abs(pkg['bundle_discount']):,}" if pkg["bundle_discount"] < 0 else "¥0"

        def vel_str(adj, ratio):
            if adj == 0:
                return f"±¥0 (ratio={ratio:.2f})" if ratio is not None else "±¥0 (データなし)"
            sign = "+" if adj > 0 else ""
            return f"{sign}¥{adj:,} (ratio={ratio:.2f})"

        print(f"""
  🏅 Rank {pkg['rank']}  （戦略スコア: {pkg['strategy_score']:.2f}）
  ─────────────────────────────────────────────────────────────────────────────
  ✈  フライト  : {pkg['flight_name']}
  🏨 ホテル    : {pkg['hotel_name']}
  ─────────────────────────────────────────────────────────────────────────────
  フライト 動的価格           ¥{pkg['flight_dynamic_price']:>10,}
    └ velocity調整            {vel_str(pkg['flight_velocity_adjustment'], pkg['flight_velocity_ratio']):>22}
  ホテル   動的価格           ¥{pkg['hotel_dynamic_price']:>10,}
    └ velocity調整            {vel_str(pkg['hotel_velocity_adjustment'], pkg['hotel_velocity_ratio']):>22}
  ──────────────────────────────────────
  合計（velocity調整後）     ¥{pkg['sum_dynamic_price']:>10,}
  クロスセル割引                       {disc_str:>11}  (ホテル緊急スコア: {pkg['hotel_urgency_score']:.2f})
  ──────────────────────────────────────
  パッケージ最終価格          ¥{pkg['final_package_price']:>10,}
  理由: {pkg['reason']}""")

    print(f"\n{sep}")
    print(f"  合計 {len(packages)} パッケージを評価しました。\n")


if __name__ == "__main__":
    run()
