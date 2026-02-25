
import sqlite3
from datetime import datetime, timezone, timedelta

DATABASE = 'inventory.db'

def inject_velocity_data():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    now_utc = datetime.now(timezone.utc).isoformat()
    
    # ターゲット商品と投入数
    # ID=1 (ハワイフライト): 期待販売 3.0/日 -> 8件投入で 約2.6x
    # ID=3 (グアムフライト): 期待販売 9.6/日 -> 15件投入で 約1.5x
    
    test_bookings = [
        (1, 8),  # Hawaii Flight -> High Velocity
        (3, 15), # Guam Flight -> Medium-High Velocity
    ]
    
    total = 0
    for inventory_id, count in test_bookings:
        # 在庫情報を取得して base_price を合わせる
        row = cursor.execute("SELECT base_price FROM inventory WHERE id=?", (inventory_id,)).fetchone()
        if not row: continue
        base_price = row[0]
        
        for _ in range(count):
            cursor.execute(
                "INSERT INTO booking_events (inventory_id, booked_at, quantity, sold_price, base_price_at_sale, is_package) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (inventory_id, now_utc, 1, int(base_price * 1.1), base_price, 0)
            )
            total += 1
            
    conn.commit()
    conn.close()
    print(f"✅ {total} 件の直近予約データを注入しました。ダッシュボードをリロードしてください。")

if __name__ == "__main__":
    inject_velocity_data()
