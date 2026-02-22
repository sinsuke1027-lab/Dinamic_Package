"""
FastAPI メインアプリケーション（v2: sqlite3 + pricing_engine ベース）。

inventory.db を直接 sqlite3 で操作し、pricing_engine.py のダイナミック
プライス計算と連動する。SQLAlchemy は使用しない（MVPシンプル構成）。
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# pricing_engine から計算関数をインポート
from pricing_engine import calculate_dynamic_price

# ─────────────────────────────────────────
# 定数
# ─────────────────────────────────────────
DATABASE = "inventory.db"
PRICE_SESSION_DURATION_MINUTES = 15  # 価格有効期限（分）

# ─────────────────────────────────────────
# FastAPI アプリ初期化
# ─────────────────────────────────────────
app = FastAPI(
    title="ダイナミックプライシング API",
    description="旅行代理店向けダイナミックプライシング MVP のバックエンドAPI（v2）",
    version="0.2.0",
)

# CORS 設定（フロントエンドからアクセス許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────
# DB ユーティリティ
# ─────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    """sqlite3 接続を返す（辞書形式でアクセス可）"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_sessions_table():
    """
    price_sessions テーブルが存在しない場合に作成する。
    アプリ起動時に呼び出す。
    """
    conn = get_conn()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS price_sessions (
            token         TEXT PRIMARY KEY,
            inventory_id  INTEGER NOT NULL,
            product_name  TEXT NOT NULL,
            price_snapshot INTEGER NOT NULL,
            expires_at    TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# アプリ起動時にセッションテーブルを保証する
@app.on_event("startup")
def on_startup():
    ensure_sessions_table()


# ─────────────────────────────────────────
# Pydantic スキーマ（リクエスト/レスポンス型）
# ─────────────────────────────────────────

class InventoryResponse(BaseModel):
    """一般ユーザー向けレスポンス（Opaque Pricing: 原価を含まない）"""
    id: int
    item_type: str
    name: str
    total_stock: int
    remaining_stock: int
    dynamic_price: int        # 動的価格（100円単位）
    base_price: int = None    # 管理者向けのみ返す


class InventoryCreate(BaseModel):
    """在庫追加リクエスト（管理者専用）"""
    item_type: str
    name: str
    total_stock: int
    remaining_stock: int
    base_price: int


class SessionCreate(BaseModel):
    """価格セッション開始リクエスト"""
    inventory_id: int


class SessionResponse(BaseModel):
    """価格セッションレスポンス（決済画面用）"""
    token: str
    inventory_id: int
    product_name: str
    price_snapshot: int
    expires_at: str
    remaining_seconds: int


# ─────────────────────────────────────────
# ヘルスチェック
# ─────────────────────────────────────────

@app.get("/", tags=["ヘルスチェック"])
def root():
    """APIサーバー起動確認"""
    return {"status": "ok", "message": "ダイナミックプライシングAPI v2 は正常に動作しています"}


# ─────────────────────────────────────────
# 在庫API（一般ユーザー向け）
# ─────────────────────────────────────────

@app.get("/inventory", tags=["在庫"])
def get_inventory_list():
    """
    在庫一覧取得（一般ユーザー向け）。
    - 動的価格を計算して返す
    - Opaque Pricing: base_price（原価）は返さない
    - remaining_stock が 0 の在庫は除外する
    """
    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory").fetchall()
    conn.close()

    result = []
    for row in rows:
        remaining = row["remaining_stock"]
        if remaining <= 0:
            continue  # 品切れは非表示
        dynamic_price = calculate_dynamic_price(
            row["base_price"], row["total_stock"], remaining
        )
        result.append({
            "id": row["id"],
            "item_type": row["item_type"],
            "name": row["name"],
            "total_stock": row["total_stock"],
            "remaining_stock": remaining,
            "dynamic_price": dynamic_price,
            # base_price は意図的に返さない（Opaque Pricing）
        })
    return result


@app.get("/inventory/{inventory_id}", tags=["在庫"])
def get_inventory_detail(inventory_id: int):
    """在庫詳細取得（一般ユーザー向け）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="指定された在庫が見つかりません")

    dynamic_price = calculate_dynamic_price(
        row["base_price"], row["total_stock"], row["remaining_stock"]
    )
    return {
        "id": row["id"],
        "item_type": row["item_type"],
        "name": row["name"],
        "total_stock": row["total_stock"],
        "remaining_stock": row["remaining_stock"],
        "dynamic_price": dynamic_price,
    }


# ─────────────────────────────────────────
# 在庫API（管理者向け）
# ─────────────────────────────────────────

@app.get("/admin/inventory", tags=["管理者: 在庫"])
def admin_get_inventory_list():
    """在庫一覧取得（管理者向け: 原価・全情報を含む）"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory").fetchall()
    conn.close()

    result = []
    for row in rows:
        dynamic_price = calculate_dynamic_price(
            row["base_price"], row["total_stock"], row["remaining_stock"]
        )
        multiplier = dynamic_price / row["base_price"] if row["base_price"] > 0 else 1.0
        result.append({
            "id": row["id"],
            "item_type": row["item_type"],
            "name": row["name"],
            "total_stock": row["total_stock"],
            "remaining_stock": row["remaining_stock"],
            "base_price": row["base_price"],          # 管理者のみ原価を表示
            "dynamic_price": dynamic_price,
            "price_multiplier": round(multiplier, 2),
        })
    return result


@app.post("/admin/inventory", status_code=status.HTTP_201_CREATED, tags=["管理者: 在庫"])
def admin_create_inventory(payload: InventoryCreate):
    """在庫追加（管理者専用）"""
    conn = get_conn()
    cursor = conn.execute(
        """INSERT INTO inventory (item_type, name, total_stock, remaining_stock, base_price)
           VALUES (?, ?, ?, ?, ?)""",
        (payload.item_type, payload.name, payload.total_stock,
         payload.remaining_stock, payload.base_price),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": new_id, "message": "在庫を追加しました"}


@app.patch("/admin/inventory/{inventory_id}", tags=["管理者: 在庫"])
def admin_update_inventory(inventory_id: int, remaining_stock: int):
    """残在庫を更新（管理者専用）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="指定された在庫が見つかりません")

    conn.execute(
        "UPDATE inventory SET remaining_stock = ? WHERE id = ?",
        (remaining_stock, inventory_id),
    )
    conn.commit()
    conn.close()
    return {"id": inventory_id, "remaining_stock": remaining_stock, "message": "更新しました"}


@app.delete("/admin/inventory/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["管理者: 在庫"])
def admin_delete_inventory(inventory_id: int):
    """在庫削除（管理者専用）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="指定された在庫が見つかりません")
    conn.execute("DELETE FROM inventory WHERE id = ?", (inventory_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# 価格セッションAPI（カウントダウンタイマー）
# ─────────────────────────────────────────

@app.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, tags=["価格セッション"])
def create_price_session(payload: SessionCreate):
    """
    価格セッション開始。
    「予約する」ボタン押下時に呼び出す。
    - 現時点の動的価格をスナップショットとして保存する
    - 有効期限は PRICE_SESSION_DURATION_MINUTES 分後
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM inventory WHERE id = ?", (payload.inventory_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="指定された在庫が見つかりません")
    if row["remaining_stock"] <= 0:
        conn.close()
        raise HTTPException(status_code=409, detail="この商品は品切れです")

    # 現時点の動的価格をスナップショット
    price_snapshot = calculate_dynamic_price(
        row["base_price"], row["total_stock"], row["remaining_stock"]
    )
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=PRICE_SESSION_DURATION_MINUTES)
    token = str(uuid.uuid4())

    conn.execute(
        """INSERT INTO price_sessions (token, inventory_id, product_name, price_snapshot, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (token, row["id"], row["name"], price_snapshot,
         expires_at.isoformat(), now.isoformat()),
    )
    conn.commit()
    conn.close()

    remaining_seconds = int((expires_at - now).total_seconds())
    return SessionResponse(
        token=token,
        inventory_id=row["id"],
        product_name=row["name"],
        price_snapshot=price_snapshot,
        expires_at=expires_at.isoformat(),
        remaining_seconds=remaining_seconds,
    )


@app.get("/sessions/{token}", response_model=SessionResponse, tags=["価格セッション"])
def get_price_session(token: str):
    """
    価格セッション状態確認。
    決済画面でのカウントダウン表示・タイムアウト判定に使用する。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM price_sessions WHERE token = ?", (token,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    expires_at = datetime.fromisoformat(row["expires_at"])
    now = datetime.now(timezone.utc)
    remaining_seconds = max(0, int((expires_at - now).total_seconds()))

    return SessionResponse(
        token=row["token"],
        inventory_id=row["inventory_id"],
        product_name=row["product_name"],
        price_snapshot=row["price_snapshot"],
        expires_at=row["expires_at"],
        remaining_seconds=remaining_seconds,
    )
