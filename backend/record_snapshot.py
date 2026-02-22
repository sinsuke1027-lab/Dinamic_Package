"""
record_snapshot.py

現在の在庫状況と Explainable Pricing Engine の計算結果を
price_history テーブルにスナップショットとして記録するスクリプト。

【フェーズ6 更新】
  - departure_date を読み込んでリードタイム（lead_days）を計算して記録
  - pricing_engine.py の calculate_pricing_result() を使用

【使い方】
  python record_snapshot.py           # 現時点のスナップショットを記録
  python record_snapshot.py --demo    # デモ用：時系列ダミーデータを一括投入
"""

import sqlite3
import argparse
import random
from datetime import datetime, timedelta, date, timezone

DATABASE = 'inventory.db'


def get_conn() -> sqlite3.Connection:
    """sqlite3 接続を返す（辞書形式でアクセス可）"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def record_now():
    """現時点の全在庫スナップショットを price_history に記録する"""
    # pricing_engine から計算関数をインポート
    from pricing_engine import calculate_pricing_result

    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory").fetchall()
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for row in rows:
        result = calculate_pricing_result(
            inventory_id    = row['id'],
            name            = row['name'],
            base_price      = row['base_price'],
            total_stock     = row['total_stock'],
            remaining_stock = row['remaining_stock'],
            departure_date  = row['departure_date'],
        )
        conn.execute(
            """INSERT INTO price_history
               (inventory_id, recorded_at, remaining_stock, dynamic_price, lead_days)
               VALUES (?, ?, ?, ?, ?)""",
            (row['id'], now, row['remaining_stock'],
             result['final_price'], result['lead_days']),
        )
        count += 1
    conn.commit()
    conn.close()
    print(f"✅ スナップショットを記録しました（{count}件, {now}）")


def insert_demo_data():
    """
    デモ用：過去24時間分（1時間ごと）のダミー時系列データを生成して投入する。
    在庫が時間経過とともに徐々に売れていく様子をシミュレート。
    """
    from pricing_engine import calculate_pricing_result

    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory").fetchall()

    if not rows:
        conn.close()
        print("⚠️  在庫データがありません。先に python init_db.py を実行してください。")
        return

    # 既存のデモデータをクリア
    conn.execute("DELETE FROM price_history")
    conn.commit()

    now   = datetime.now(timezone.utc)
    hours = 24   # 過去24時間分
    total_inserted = 0

    for item in rows:
        start_remaining = item['total_stock']
        end_remaining   = item['remaining_stock']
        dep_date        = item['departure_date']

        for i in range(hours, -1, -1):
            recorded_at = (now - timedelta(hours=i)).isoformat()
            ref_date    = (now - timedelta(hours=i)).date()

            # 時間経過とともに線形に在庫が減少するシミュレーション
            progress  = (hours - i) / hours      # 0.0 → 1.0
            noise     = random.randint(-2, 2)
            remaining = max(
                0,
                min(
                    item['total_stock'],
                    int(start_remaining - (start_remaining - end_remaining) * progress + noise),
                ),
            )

            result = calculate_pricing_result(
                inventory_id    = item['id'],
                name            = item['name'],
                base_price      = item['base_price'],
                total_stock     = item['total_stock'],
                remaining_stock = remaining,
                departure_date  = dep_date,
                reference_date  = ref_date,
            )
            conn.execute(
                """INSERT INTO price_history
                   (inventory_id, recorded_at, remaining_stock, dynamic_price, lead_days)
                   VALUES (?, ?, ?, ?, ?)""",
                (item['id'], recorded_at, remaining,
                 result['final_price'], result['lead_days']),
            )
            total_inserted += 1

    conn.commit()
    conn.close()
    print(f"✅ デモ用データを投入しました（{total_inserted}件 / 過去{hours}時間 / {len(rows)}商品）")


def insert_demo_booking_events():
    """
    デモ用：過去48時間分のダミー予約イベントを booking_events に投入する。
    Velocity-based Pricing のテスト用。

    シナリオ:
      - フライトB席（ID=2）: 直近24hに14件 → 「売れすぎ」シミュレーション
      - ホテルA（リゾート）: 直近24hに2件 → 「想定内」
      - その他: 0件 → データなし
    """
    conn = get_conn()
    rows = conn.execute("SELECT id, name, total_stock, remaining_stock FROM inventory").fetchall()

    if not rows:
        conn.close()
        print("⚠️  在庫データがありません。先に python init_db.py を実行してください。")
        return

    conn.execute("DELETE FROM booking_events")
    conn.commit()

    now = datetime.now(timezone.utc)
    total_inserted = 0

    booking_scenarios = {
        1: {"total_48h": 3,  "recent_24h": 1},
        2: {"total_48h": 20, "recent_24h": 14},
        3: {"total_48h": 4,  "recent_24h": 2},
        4: {"total_48h": 2,  "recent_24h": 1},
    }

    for row in rows:
        inv_id   = row["id"]
        scenario = booking_scenarios.get(inv_id, {"total_48h": 1, "recent_24h": 1})
        total    = scenario["total_48h"]
        recent   = scenario["recent_24h"]
        old      = total - recent

        for _ in range(old):
            offset_h = random.uniform(24.5, 47.5)
            booked_at = (now - timedelta(hours=offset_h)).isoformat()
            conn.execute(
                "INSERT INTO booking_events (inventory_id, booked_at, quantity) VALUES (?, ?, ?)",
                (inv_id, booked_at, 1),
            )
            total_inserted += 1

        for _ in range(recent):
            offset_h = random.uniform(0.5, 23.5)
            booked_at = (now - timedelta(hours=offset_h)).isoformat()
            conn.execute(
                "INSERT INTO booking_events (inventory_id, booked_at, quantity) VALUES (?, ?, ?)",
                (inv_id, booked_at, 1),
            )
            total_inserted += 1

    conn.commit()
    conn.close()
    print(f"✅ ダミー予約イベントを投入しました（{total_inserted}件）")
    print(f"   フライトB席: 直近24h = {booking_scenarios[2]['recent_24h']}件（高velocity シミュレーション）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="価格・在庫スナップショット記録ツール")
    parser.add_argument("--demo", action="store_true",
                        help="デモ用：過去24時間分のダミーデータを投入する")
    parser.add_argument("--demo-booking", action="store_true",
                        help="デモ用：過去48時間分のダミー予約イベントを投入する（Velocity-based Pricing テスト用）")
    args = parser.parse_args()

    if args.demo:
        insert_demo_data()
    elif args.demo_booking:
        insert_demo_booking_events()
    else:
        record_now()

