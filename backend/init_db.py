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
    conn.row_factory = sqlite3.Row # 行データを辞書形式で扱えるように設定
    cursor = conn.cursor()

    # ─── テーブル再作成（スキーマ更新のため DROP してから CREATE） ───
    cursor.execute('DROP TABLE IF EXISTS inventory')
    cursor.execute('DROP TABLE IF EXISTS price_history')
    cursor.execute('DROP TABLE IF EXISTS booking_events')

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
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id      INTEGER NOT NULL,
            partner_id         INTEGER, -- パッケージ販売時の相手方ID
            booked_at          TEXT NOT NULL,
            quantity           INTEGER DEFAULT 1,
            sold_price         INTEGER,
            base_price_at_sale INTEGER,
            is_package         INTEGER DEFAULT 0,
            discount_amount    INTEGER DEFAULT 0,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        )
    ''')

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

def populate_booking_events(conn):
    """
    パッケージ戦略分析（ヒートマップ、相関分析）に対応した高度な予約履歴を生成する。
    """
    cursor = conn.cursor()
    rows = cursor.execute("SELECT id, item_type, name, total_stock, remaining_stock, base_price, departure_date FROM inventory").fetchall()
    inventory = [dict(r) for r in rows]
    
    flights = [i for i in inventory if i["item_type"] == "flight"]
    hotels  = [i for i in inventory if i["item_type"] == "hotel"]
    
    now_utc = datetime.now(timezone.utc)
    total_inserted = 0

    # 1. パッケージ予約（アトミックなペア予約）の生成
    # 組み合わせの相性（相性スコア）をシミュレート
    affinities = {}
    for f in flights:
        for h in hotels:
            # 基本的な相性（ランダム + 目的地の一致を想定した重み）
            score = random.uniform(0.5, 2.0)
            if f["name"].split("・")[0] == h["name"].split("・")[0]: # 目的地が同じ場合
                score *= 1.5
            affinities[(f["id"], h["id"])] = score

    # 過去30日間のパッケージ予約生成
    for days_ago in range(30, -1, -1):
        target_date = now_utc - timedelta(days=days_ago)
        
        for (f_id, h_id), affinity in affinities.items():
            f = next(i for i in flights if i["id"] == f_id)
            h = next(i for i in hotels if i["id"] == h_id)
            
            # 出発までの日数に応じたベースレート
            dep_date = datetime.strptime(f["departure_date"], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            lead_days = (dep_date - target_date).days
            if lead_days < 0 or lead_days > 60: continue
            
            # パッケージ販売ペース
            base_rate = 0.008 * affinity
            if lead_days < 7: base_rate *= 1.3 # 直前加速
            
            count = max(0, int(f["total_stock"] * base_rate + random.uniform(-0.5, 1.0)))
            
            for _ in range(count):
                offset_mins = random.uniform(0, 1440)
                booked_at = (target_date.replace(hour=0, minute=0, second=0) + timedelta(minutes=offset_mins)).isoformat()
                
                # --- フライト予約の挿入 ---
                f_price = int(f["base_price"] * random.uniform(0.9, 1.3) / 100) * 100
                cursor.execute(
                    "INSERT INTO booking_events (inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, is_package, discount_amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f["id"], h["id"], booked_at, 1, f_price, f["base_price"], 1, 0)
                )
                
                # --- ホテル予約の挿入（相棒をセット） ---
                discount = int(random.uniform(2000, 5000) / 100) * 100
                h_price = int(h["base_price"] * random.uniform(0.8, 1.1) / 100) * 100 - discount
                cursor.execute(
                    "INSERT INTO booking_events (inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, is_package, discount_amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (h["id"], f["id"], booked_at, 1, h_price, h["base_price"], 1, discount)
                )
                total_inserted += 2

    # 2. 単体予約（単品販売）の生成
    for item in inventory:
        dep_date = datetime.strptime(item["departure_date"], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        for days_ago in range(30, -1, -1):
            target_date = now_utc - timedelta(days=days_ago)
            lead_days = (dep_date - target_date).days
            if lead_days < 0 or lead_days > 60: continue
            
            count = max(0, int(item["total_stock"] * 0.01 + random.uniform(-1, 1)))
            for _ in range(count):
                offset_mins = random.uniform(0, 1440)
                booked_at = (target_date.replace(hour=0, minute=0, second=0) + timedelta(minutes=offset_mins)).isoformat()
                price = int(item["base_price"] * random.uniform(0.9, 1.5) / 100) * 100
                cursor.execute(
                    "INSERT INTO booking_events (inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, is_package, discount_amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (item["id"], None, booked_at, 1, price, item["base_price"], 0, 0)
                )
                total_inserted += 1

    conn.commit()
    print(f"✅ booking_events テーブルに {total_inserted} 件の高度なパッケージ・単品混合予約履歴を生成しました。")

if __name__ == '__main__':
    init_db()
