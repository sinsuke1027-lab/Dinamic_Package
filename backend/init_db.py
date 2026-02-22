"""
init_db.py

inventory.db を初期化し、高度なシミュレーション用ダミーデータを投入する。
- 目的地別（ハワイ、グアム、沖縄、札幌）
- ランク別（高級、標準、格安）
- 時間軸別（直前、近場、未来）
- 販売速度（Velocity）テスト用の予約履歴生成
"""

import sqlite3
import random
from datetime import datetime, timedelta, timezone

DATABASE = 'inventory.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # ─── テーブル作成 ───────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type       TEXT NOT NULL,
            name            TEXT NOT NULL,
            total_stock     INTEGER NOT NULL,
            remaining_stock INTEGER NOT NULL,
            base_price      INTEGER NOT NULL,
            departure_date  TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id    INTEGER NOT NULL,
            recorded_at     TEXT NOT NULL,
            remaining_stock INTEGER NOT NULL,
            dynamic_price   INTEGER NOT NULL,
            lead_days       INTEGER,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS booking_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER NOT NULL,
            booked_at    TEXT NOT NULL,
            quantity     INTEGER DEFAULT 1,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        )
    ''')

    # 既存データをクリア
    cursor.execute('DELETE FROM inventory')
    cursor.execute('DELETE FROM price_history')
    cursor.execute('DELETE FROM booking_events')

    # ─── 高度なダミーデータ投入 ───────────────────────────────────
    # (item_type, name, total_stock, remaining_stock, base_price, departure_date)
    # 本日: 2026-02-22
    now = datetime(2026, 2, 22)
    
    dummy_data = [
        # --- ハワイ (人気・1ヶ月後) ---
        ('flight', 'ハワイ・プレミアム空路 (L)', 100, 30, 80000, (now + timedelta(days=30)).strftime('%Y-%m-%d')),
        ('hotel',  'トランプ・ワイキキ・ラグジュアリー', 50, 45, 60000, (now + timedelta(days=30)).strftime('%Y-%m-%d')),
        
        # --- グアム (標準・2週間後) ---
        ('flight', 'グアム・定期便 (M)', 150, 80, 40000, (now + timedelta(days=14)).strftime('%Y-%m-%d')),
        ('hotel',  'グアム・プラザ・リゾート', 80, 40, 15000, (now + timedelta(days=14)).strftime('%Y-%m-%d')),
        
        # --- 沖縄 (直近・売れすぎ/不人気の極端な例) ---
        ('flight', '那覇行き LCC便 (S)', 180, 20, 15000, (now + timedelta(days=3)).strftime('%Y-%m-%d')),
        ('hotel',  '那覇ビジネス・スタンダード', 100, 95, 8000, (now + timedelta(days=3)).strftime('%Y-%m-%d')),
        
        # --- 札幌 (未来・3ヶ月後) ---
        ('flight', '新千歳行き 特急空路', 200, 180, 25000, (now + timedelta(days=90)).strftime('%Y-%m-%d')),
        ('hotel',  '札幌ステーション・ホテル', 120, 110, 12000, (now + timedelta(days=90)).strftime('%Y-%m-%d')),
    ]

    cursor.executemany('''
        INSERT INTO inventory (item_type, name, total_stock, remaining_stock, base_price, departure_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', dummy_data)
    
    conn.commit()
    print(f"✅ inventory テーブルに {len(dummy_data)} 件の高度なダミーデータを投入しました。")

    # ─── 販売履歴（booking_events）の生成 ───────────────────────
    populate_booking_events(conn)

    conn.close()
    print("✅ データベースの高度な初期化が完了しました。")

def populate_booking_events(conn):
    """
    販売速度テスト用の予約履歴を生成する。
    
    シナリオ:
    1. ハワイ・プレミアム空路 (id=1): 直近24hで想定の3倍売れている (High Velocity)
    2. トランプ・ワイキキ (id=2): 直近24hで全く売れていない (Zero Velocity)
    3. 那覇行き LCC (id=5): 直近24hで想定の5倍売れている (Extreme Velocity - Price Brake)
    4. 那覇ビジネス (id=6): 全く売れていない (Zero Velocity - Near Expiry)
    """
    cursor = conn.cursor()
    rows = cursor.execute("SELECT id, name, total_stock, remaining_stock, departure_date FROM inventory").fetchall()
    
    now_utc = datetime.now(timezone.utc)
    target_sell_ratio = 0.9
    total_inserted = 0

    for row in rows:
        inv_id, name, total, remaining, dep_date_str = row
        dep_date = datetime.strptime(dep_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        lead_days = (dep_date - now_utc).days
        lead_days = max(1, lead_days)
        
        expected_daily = (total * target_sell_ratio) / lead_days
        
        # シナリオ別の件数設定
        if "ハワイ・プレミアム空路" in name:
            recent_count = int(expected_daily * 3) # 売れすぎ
        elif "那覇行き LCC" in name:
            recent_count = int(expected_daily * 5) # 激しく売れすぎ
        elif "トランプ・ワイキキ" in name or "那覇ビジネス" in name:
            recent_count = 0 # 全く売れていない
        else:
            recent_count = int(expected_daily) # 標準
            
        # 直近24時間の予約を生成
        for _ in range(recent_count):
            # 0〜24時間前のランダムな時間
            offset = random.uniform(0, 24)
            booked_at = (now_utc - timedelta(hours=offset)).isoformat()
            cursor.execute(
                "INSERT INTO booking_events (inventory_id, booked_at, quantity) VALUES (?, ?, ?)",
                (inv_id, booked_at, 1)
            )
            total_inserted += 1

    conn.commit()
    print(f"✅ booking_events テーブルに {total_inserted} 件の予約履歴を生成しました。")

if __name__ == '__main__':
    init_db()
