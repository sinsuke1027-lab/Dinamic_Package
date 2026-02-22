"""
シャドープライス価格計算エンジン（コアモジュール）。
残席数に基づいてダイナミックな販売価格を算出する。
"""

from models import Inventory


def calculate_dynamic_price(inventory: Inventory) -> float:
    """
    シャドープライスを活用したダイナミックプライシング計算。

    【アルゴリズム】
    - 残席率（remaining_ratio）= 残席数 / 総席数（0.0〜1.0）
    - シャドープライス乗数 = 1 + (1 - 残席率)^2（最大で2倍まで上昇）
    - 最終価格 = 原価 × 乗数
    - ただし、フロアプライス（最低販売価格）を下回らないよう保証

    【価格変動例（原価10万円の場合）】
    - 残席率 100%  → ×1.00 → 100,000円
    - 残席率  50%  → ×1.25 → 125,000円
    - 残席率  20%  → ×1.64 → 164,000円
    - 残席率   5%  → ×1.90 → 190,000円

    Args:
        inventory: 計算対象の在庫オブジェクト

    Returns:
        算出された販売価格（円）
    """
    # 残席数の計算
    remaining = inventory.total_seats - inventory.booked_seats

    # エッジケース：総席数が0の場合はフロアプライスを返す
    if inventory.total_seats <= 0:
        return inventory.floor_price

    # 残席率（0.0 = 満席, 1.0 = 空席）
    remaining_ratio = remaining / inventory.total_seats

    # シャドープライス乗数（2次関数で残席率が低いほど急激に上昇）
    shadow_price_multiplier = 1.0 + (1.0 - remaining_ratio) ** 2

    # 動的価格の計算
    dynamic_price = inventory.base_cost * shadow_price_multiplier

    # フロアプライス（最低価格）を保証
    return max(dynamic_price, inventory.floor_price)


def get_remaining_seats(inventory: Inventory) -> int:
    """残席数を返す"""
    return inventory.total_seats - inventory.booked_seats


def get_availability_label(inventory: Inventory) -> str:
    """
    残席数に応じた在庫ステータスラベルを返す。
    フロントエンドでのバッジ表示に使用する。
    """
    remaining = get_remaining_seats(inventory)
    ratio = remaining / inventory.total_seats if inventory.total_seats > 0 else 0

    if remaining == 0:
        return "満席"
    elif ratio <= 0.1:
        return "残りわずか"  # 残席10%以下
    elif ratio <= 0.3:
        return "残り少"     # 残席30%以下
    else:
        return "空席あり"
