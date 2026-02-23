"""
pricing_engine.py

Explainable Pricing Engine（説明可能な価格設定エンジン）。

【フェーズ6 アップデート】
  - 2軸モデル: 在庫要因（inventory_factor）× リードタイム要因（time_factor）
  - 設計思想: 加算モデル（Additive Model）
      最終価格 = 原価 + 在庫調整額 + 時期調整額
    → 各要因の影響を円単位で明示し、誰でも追跡・検証できる
  - PricingResult 辞書を出力することで、外部システムへの組み込みが容易

【出力例】
  {
    "inventory_id": 2,
    "name": "ハワイ行きチャーター便 B席",
    "base_price": 50000,
    "inventory_adjustment": 5000,   # +¥5,000（在庫残20%: 希少プレミアム）
    "time_adjustment": -7500,       # -¥7,500（出発まで3日: 直前割引）
    "final_price": 47500,
    "inv_ratio": 0.20,
    "lead_days": 3,
    "reason": "在庫残20%のため希少プレミアム(+¥5,000)。出発まで3日のため直前割引(-¥7,500)。"
  }
"""

import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

DATABASE = 'inventory.db'


# ─────────────────────────────────────────
# 在庫要因の計算
# ─────────────────────────────────────────

def calc_inventory_adjustment(base_price: int, inv_ratio: float) -> tuple[int, str]:
    """
    残在庫率に基づく価格調整額を計算する。

    Args:
        base_price: 原価（円）
        inv_ratio:  残在庫率（0.0〜1.0）

    Returns:
        (調整額（円）, 理由テキスト)
    """
    if inv_ratio < 0.20:
        # 残20%未満: 希少プレミアム
        adj = round(base_price * 0.30)
        reason = f"在庫残{int(inv_ratio*100)}%のため希少プレミアム(+¥{adj:,})"
    elif inv_ratio < 0.50:
        # 残20〜50%: 軽微な需要圧
        adj = round(base_price * 0.10)
        reason = f"在庫残{int(inv_ratio*100)}%のため需要増加調整(+¥{adj:,})"
    elif inv_ratio < 0.70:
        # 残50〜70%: 標準（調整なし）
        adj = 0
        reason = f"在庫残{int(inv_ratio*100)}%のため標準価格（調整なし）"
    else:
        # 残70%以上: 余裕割引
        adj = round(base_price * -0.15)
        reason = f"在庫残{int(inv_ratio*100)}%のため余裕割引(-¥{abs(adj):,})"

    return adj, reason


# ─────────────────────────────────────────
# リードタイム要因の計算
# ─────────────────────────────────────────

def calc_time_adjustment(base_price: int, lead_days: int) -> tuple[int, str]:
    """
    出発日までの残り日数（リードタイム）に基づく価格調整額を計算する。

    Args:
        base_price: 原価（円）
        lead_days:  出発日まで何日か（負 = 既に出発済み）

    Returns:
        (調整額（円）, 理由テキスト)
    """
    if lead_days < 0:
        # 出発済み → 価格無効
        return 0, "出発済み（価格計算対象外）"
    elif lead_days <= 7:
        # 0〜7日: 直前割引（最終在庫の取りこぼし防止）
        adj = round(base_price * -0.15)
        reason = f"出発まで{lead_days}日のため直前割引(-¥{abs(adj):,})"
    elif lead_days <= 30:
        # 8〜30日: 需要ピーク・決断促進
        adj = round(base_price * 0.10)
        reason = f"出発まで{lead_days}日のため需要ピーク調整(+¥{adj:,})"
    elif lead_days <= 90:
        # 31〜90日: 標準
        adj = 0
        reason = f"出発まで{lead_days}日のため標準価格（調整なし）"
    else:
        # 90日超: 早期予約割引
        adj = round(base_price * -0.10)
        reason = f"出発まで{lead_days}日のため早期予約割引(-¥{abs(adj):,})"

    return adj, reason


# ─────────────────────────────────────────
# メイン: PricingResult を生成する
# ─────────────────────────────────────────

def calculate_pricing_result(
    inventory_id: int,
    name: str,
    base_price: int,
    total_stock: int,
    remaining_stock: int,
    departure_date: Optional[str],
    reference_date: Optional[date] = None,
    config: Optional[dict] = None,
) -> dict:
    """
    2軸加算モデルによる価格計算を行い、計算根拠付きの PricingResult を返す。

    Args:
        inventory_id:   在庫ID
        name:           商品名
        base_price:     原価（円）
        total_stock:    総在庫数
        remaining_stock: 残在庫数
        departure_date: 出発日（YYYY-MM-DD文字列、または None）
        reference_date: 比較基準日（テスト用; None なら今日）

    Returns:
        PricingResult 辞書
    """
    today = reference_date or date.today()

    # ── 在庫要因 ──────────────────────────────────────────────────
    inv_ratio = remaining_stock / total_stock if total_stock > 0 else 0.0
    inv_adj, inv_reason = calc_inventory_adjustment(base_price, inv_ratio)

    # ── リードタイム要因 ─────────────────────────────────────────
    if departure_date:
        dep_d = date.fromisoformat(departure_date)
        lead_days = (dep_d - today).days
    else:
        lead_days = None

    if lead_days is not None:
        time_adj, time_reason = calc_time_adjustment(base_price, lead_days)
    else:
        time_adj, time_reason = 0, "出発日未設定のため時期調整なし"

    # ── 設定パラメータの取得 ───────────────────────────────────────
    conf = config or {}
    max_discount = conf.get("max_discount_pct", 30) / 100.0   # 既定 30%
    max_markup   = conf.get("max_markup_pct", 50) / 100.0     # 既定 50%
    brake_threshold = conf.get("brake_threshold", 1.5)        # 既定 1.5x
    brake_strength  = conf.get("brake_strength_pct", 5) / 100.0 # 既定 5%

    # ── Velocity 自動ブレーキ ──────────────────────────────────────
    vel_adj = 0
    is_brake_active = False
    vr = None
    try:
        from packaging_engine import get_velocity_ratio
        vr = get_velocity_ratio(inventory_id, total_stock, remaining_stock, lead_days)
        if vr and vr >= brake_threshold:
            vel_adj = round(base_price * brake_strength)
            vel_reason = f"販売ペース異常({vr:.1f}x)を検知。自動価格ブレーキを発動(+¥{vel_adj:,})"
            is_brake_active = True
        elif vr:
            vel_reason = f"販売ペースは正常({vr:.1f}x)です"
        else:
            vel_reason = "販売速度データ不足"
    except Exception:
        vel_reason = "速度解析エラー"

    # ── 最終価格（上下限: config に基づくクランプ）────────────
    theoretical = base_price + inv_adj + time_adj + vel_adj
    final_price  = round(theoretical / 100) * 100          # 100円単位

    min_p = round(base_price * (1.0 - max_discount) / 100) * 100
    max_p = round(base_price * (1.0 + max_markup) / 100) * 100
    
    final_price = max(final_price, min_p)
    final_price = min(final_price, max_p)

    # ── 理由文の合成 ─────────────────────────────────────────────
    reason = f"{inv_reason}。{time_reason}。{vel_reason}。"

    # ウォーターフォールチャート用の構造化データ
    waterfall = [
        {"label": "基本価格", "value": base_price,  "measure": "absolute"},
        {"label": "在庫調整", "value": inv_adj,      "measure": "relative"},
        {"label": "時期調整", "value": time_adj,     "measure": "relative"},
        {"label": "速度調整", "value": vel_adj,      "measure": "relative"},
        {"label": "最終価格", "value": final_price,  "measure": "total"},
    ]

    return {
        "inventory_id":          inventory_id,
        "name":                  name,
        "base_price":            base_price,
        "inventory_adjustment":  inv_adj,
        "time_adjustment":       time_adj,
        "velocity_adjustment":   vel_adj,
        "velocity_ratio":        vr,
        "final_price":           final_price,
        "inv_ratio":             round(inv_ratio, 3),
        "lead_days":             lead_days,
        "departure_date":        departure_date,
        "reason":                reason,
        "waterfall":             waterfall,
        "is_brake_active":       is_brake_active,
    }


# ─────────────────────────────────────────
# DB から在庫を読み込んで一括計算
# ─────────────────────────────────────────

def calculate_all() -> list[dict]:
    """全在庫の PricingResult リストを返す"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM inventory').fetchall()
    conn.close()

    results = []
    for row in rows:
        row_dict = dict(row)  # sqlite3.Row は .get() 非対応のため dict に変換
        result = calculate_pricing_result(
            inventory_id    = row_dict['id'],
            name            = row_dict['name'],
            base_price      = row_dict['base_price'],
            total_stock     = row_dict['total_stock'],
            remaining_stock = row_dict['remaining_stock'],
            departure_date  = row_dict.get('departure_date'),
        )
        results.append(result)
    return results


# ─────────────────────────────────────────
# 旧 API との互換ラッパー（他モジュールから呼べるよう残す）
# ─────────────────────────────────────────

def calculate_dynamic_price(
    base_price: int,
    total_stock: int,
    remaining_stock: int,
    departure_date: Optional[str] = None,
) -> int:
    """最終価格のみを返すシンプルなラッパー（後方互換用）"""
    result = calculate_pricing_result(
        inventory_id    = 0,
        name            = "",
        base_price      = base_price,
        total_stock     = total_stock,
        remaining_stock = remaining_stock,
        departure_date  = departure_date,
    )
    return result['final_price']


# ─────────────────────────────────────────
# CLI 実行: 結果を見やすくターミナルに表示
# ─────────────────────────────────────────

def run():
    results = calculate_all()
    if not results:
        print("⚠️  在庫データがありません。python init_db.py を先に実行してください。")
        return

    sep = "═" * 90
    print(f"\n{sep}")
    print("  📊 Explainable Pricing Engine — 計算結果（価格根拠付き）")
    print(sep)

    for r in results:
        inv_sign  = "+" if r['inventory_adjustment'] >= 0 else ""
        time_sign = "+" if r['time_adjustment'] >= 0 else ""
        lead_str  = f"{r['lead_days']}日後" if r['lead_days'] is not None else "出発日未設定"

        print(f"\n  🔹 [{r['inventory_id']}] {r['name']}")
        print(f"     出発日: {r['departure_date'] or '未設定'} ({lead_str})")
        print(f"     残在庫率: {int(r['inv_ratio']*100)}%")
        print(f"     ─────────────────────────────────────────────────────")
        print(f"     原価                          ¥{r['base_price']:>10,}")
        print(f"     在庫調整  ({inv_sign}{r['inventory_adjustment']:,})    {inv_sign}¥{abs(r['inventory_adjustment']):>9,}")
        print(f"     時期調整  ({time_sign}{r['time_adjustment']:,})   {time_sign}¥{abs(r['time_adjustment']):>9,}")
        print(f"     ─────────────────────────────────────────────────────")
        print(f"     最終価格                      ¥{r['final_price']:>10,}")
        print(f"     理由: {r['reason']}")

    print(f"\n{sep}")
    print(f"  合計 {len(results)} 件を処理しました。\n")


if __name__ == '__main__':
    run()
