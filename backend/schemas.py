"""
Pydantic スキーマ定義モジュール。
APIのリクエスト/レスポンスのデータ型を定義する。
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ─────────────────────────────────────────
# 在庫（Inventory）スキーマ
# ─────────────────────────────────────────

class InventoryCreate(BaseModel):
    """在庫追加リクエストのスキーマ（管理者用）"""
    name: str
    category: str = "ツアー"
    total_seats: int
    booked_seats: int = 0
    base_cost: float
    floor_price: float
    description: Optional[str] = None
    image_url: Optional[str] = None
    expires_at: datetime


class InventoryUpdate(BaseModel):
    """在庫更新リクエストのスキーマ（管理者用）"""
    name: Optional[str] = None
    booked_seats: Optional[int] = None
    floor_price: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class InventoryResponse(BaseModel):
    """
    在庫レスポンスのスキーマ（一般ユーザー向け）。
    - Opaque Pricing: base_cost（原価）は含めない
    - total_price のみを返す（内訳は非表示）
    """
    id: int
    name: str
    category: str
    total_seats: int
    remaining_seats: int      # 残席数（計算済み）
    total_price: float        # 動的価格（シャドープライス計算済み）
    availability_label: str   # 「空席あり」「残り少」「残りわずか」「満席」
    description: Optional[str] = None
    image_url: Optional[str] = None
    expires_at: datetime

    class Config:
        from_attributes = True


class InventoryAdminResponse(InventoryResponse):
    """
    在庫レスポンスのスキーマ（管理者向け）。
    - 原価・フロアプライスなど内部情報を含む
    """
    base_cost: float
    floor_price: float
    booked_seats: int
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# 価格セッション（PriceSession）スキーマ
# ─────────────────────────────────────────

class SessionCreate(BaseModel):
    """価格セッション開始リクエストのスキーマ"""
    inventory_id: int


class SessionResponse(BaseModel):
    """価格セッションレスポンスのスキーマ（決済画面用）"""
    token: str
    inventory_id: int
    product_name: str         # 商品名（確認表示用）
    price_snapshot: float     # セッション開始時の確定価格
    expires_at: datetime      # 価格有効期限
    remaining_seconds: int    # 残り秒数（カウントダウン用）

    class Config:
        from_attributes = True
