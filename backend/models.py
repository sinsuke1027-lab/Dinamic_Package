"""
データベースモデル定義モジュール。
SQLAlchemy ORM を使用してテーブル構造を定義する。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Inventory(Base):
    """
    リスク在庫テーブル。
    旅行代理店が自社保有する「限界費用ゼロの在庫」を管理する。
    """
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, comment="商品名（例：沖縄3泊4日パック）")
    category = Column(String, nullable=False, default="ツアー", comment="カテゴリ（ホテル/航空券/ツアー）")
    total_seats = Column(Integer, nullable=False, comment="総席数")
    booked_seats = Column(Integer, nullable=False, default=0, comment="予約済み席数")
    base_cost = Column(Float, nullable=False, comment="原価（仕入れコスト、円）")
    floor_price = Column(Float, nullable=False, comment="最低販売価格（原価以下にしない下限、円）")
    description = Column(String, nullable=True, comment="商品説明文")
    image_url = Column(String, nullable=True, comment="サムネイル画像URL")
    expires_at = Column(DateTime, nullable=False, comment="在庫の期限（この日を過ぎると収益ゼロ）")
    created_at = Column(DateTime, default=datetime.utcnow, comment="作成日時")

    # リレーション：この在庫に紐づく価格セッション一覧
    sessions = relationship("PriceSession", back_populates="inventory")


class PriceSession(Base):
    """
    価格セッションテーブル。
    ユーザーが「予約する」を押した瞬間の価格スナップショットと有効期限を管理する。
    - 有効期限（15分）内にのみ、その価格で決済可能。
    """
    __tablename__ = "price_sessions"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, nullable=False, index=True, comment="セッションの一意トークン")
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    price_snapshot = Column(Float, nullable=False, comment="セッション開始時点の価格スナップショット（円）")
    expires_at = Column(DateTime, nullable=False, comment="価格有効期限（開始から15分後）")
    created_at = Column(DateTime, default=datetime.utcnow, comment="セッション開始日時")

    # リレーション：紐づく在庫
    inventory = relationship("Inventory", back_populates="sessions")
