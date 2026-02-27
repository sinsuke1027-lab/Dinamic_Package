"""
init_db.py  ─ Phase 15: リアルなハワイツアーデータ刷新

【設計方針】
  - 日本国内4都市発のハワイ行き8商品（ホテル4 + フライト4）を商品マスタとして定義
  - 「仕入日（procurement_date）」「顧客の予約日（booked_at）」「出発日（departure_date）」の
    3つの時間軸を厳密にシミュレート
  - betavariate分布で商品特性に応じた「予約タイミングの偏り」を再現
  - random.seed(42) で再現性を確保
"""

import sqlite3
import random
import math
from datetime import datetime, timedelta, timezone, date

DATABASE = 'inventory.db'

# 再現性確保のためシードを固定
random.seed(42)

# ─── 基準日（"今日"） ────────────────────────────────────────────────
TODAY = datetime(2026, 2, 25)  # ローカル時刻の「今日」

# ─── 出発日バッチ定義 ──────────────────────────────────────────────
DEPARTURE_BATCHES = [
    # 完了済み（過去）のバッチ。販売履歴の機械学習/分析用データ
    {"label": "Past-90", "offset": -90},
    {"label": "Past-60", "offset": -60},
    {"label": "Past-30", "offset": -30},
    {"label": "Past-10", "offset": -10},
    # 未来のバッチ。現在販売中
    {"label": "D-1",  "offset": 1},
    {"label": "D-3",  "offset": 3},
    {"label": "D-10", "offset": 10},
    {"label": "D-30", "offset": 30},
]

# ─── 商品マスタ定義 ────────────────────────────────────────────────
# フィールド説明:
#   type             : "hotel" or "flight"
#   name_tmpl        : 商品名テンプレート（{label}に出発日バッチが入る）
#   base_price       : ベース価格 (¥)
#   total_stock      : 在庫総数（座席数 / 客室数）
#   sell_thru_ratio  : 「理想的な販売率」(1.0=完売想定、0.5=半分売れ残りリスク)
#   procurement_days_before : 出発日の何日前に仕入れるか
#   alpha, beta      : betavariate分布のパラメータ（早期=α↓β↑, 直前=α↑β↓）
#   base_velocity    : 1日あたりの基本販売ペース（商品特性別）
PRODUCT_MASTERS = [
    # ── ホテル 4商品 ─────────────────────────────────────────
    {
        "type": "hotel",
        "name_tmpl": "ハレクラニ・ハワイ (超高級)",
        "base_price": 120_000,
        "total_stock": 20,
        "sell_thru_ratio": 0.70,  # 高単価なので70%でも優良
        "procurement_days_before": 180,
        "alpha": 1.2, "beta": 6.0,   # 早期（仕入れ直後）に集中
        "elasticity": -0.8,        # 高価格帯は価格変化に鈍感
    },
    {
        "type": "hotel",
        "name_tmpl": "シェラトン・ワイキキ (高級)",
        "base_price": 75_000,
        "total_stock": 40,
        "sell_thru_ratio": 0.88,
        "procurement_days_before": 150,
        "alpha": 2.0, "beta": 4.0,   # やや早期寄り
        "elasticity": -1.2,        # やや鈍感
    },
    {
        "type": "hotel",
        "name_tmpl": "マリオット・ワイキキ (ファミリー)",
        "base_price": 45_000,
        "total_stock": 60,
        "sell_thru_ratio": 0.85,
        "procurement_days_before": 120,
        "alpha": 2.5, "beta": 2.5,   # 均等分布
        "elasticity": -1.8,        # 標準的〜やや敏感
    },
    {
        "type": "hotel",
        "name_tmpl": "アロハ・バジェット・イン (格安)",
        "base_price": 18_000,
        "total_stock": 80,
        "sell_thru_ratio": 0.60,   # 格安でも売れ残りリスク大
        "procurement_days_before": 60,
        "alpha": 6.0, "beta": 1.2,   # 直前に集中
        "elasticity": -2.5,        # 非常に敏感（安いから買う層）
    },
    # ── フライト 4商品 ─────────────────────────────────────────
    {
        "type": "flight",
        "name_tmpl": "JAL HND→HNL (羽田発・最人気)",
        "base_price": 95_000,
        "total_stock": 120,
        "sell_thru_ratio": 0.97,   # ほぼ完売
        "procurement_days_before": 180,
        "alpha": 1.0, "beta": 5.0,   # 早期集中（人気路線）
        "elasticity": -0.5,        # 人気路線は価格に非弾力的（代えが利かない）
    },
    {
        "type": "flight",
        "name_tmpl": "ANA KIX→HNL (関空発・安定)",
        "base_price": 72_000,
        "total_stock": 90,
        "sell_thru_ratio": 0.85,
        "procurement_days_before": 150,
        "alpha": 2.0, "beta": 3.0,
        "elasticity": -1.0,
    },
    {
        "type": "flight",
        "name_tmpl": "JL FUK→HNL (福岡発・中需要)",
        "base_price": 68_000,
        "total_stock": 70,
        "sell_thru_ratio": 0.70,   # 売れ残りリスク中
        "procurement_days_before": 120,
        "alpha": 3.0, "beta": 2.5,
        "elasticity": -1.5,
    },
    {
        "type": "flight",
        "name_tmpl": "NH CTS→HNL (札幌発・ニッチ)",
        "base_price": 55_000,
        "total_stock": 50,
        "sell_thru_ratio": 0.45,   # 売れ残りリスク大
        "procurement_days_before": 90,
        "alpha": 5.0, "beta": 1.5,   # 直前集中
        "elasticity": -2.0,        # ニッチ需要、安ければ動く
    },
]

# ─── パッケージ相性マトリクス ──────────────────────────────────────
# (フライトindex, ホテルindex) : 相性スコア（高いほど組み合わせ予約が多い）
PACKAGE_AFFINITY = {
    (4, 0): 2.5,   # JAL HND + ハレクラニ（最高級パッケージ）
    (4, 1): 2.0,   # JAL HND + シェラトン
    (4, 2): 1.5,   # JAL HND + マリオット
    (4, 3): 0.8,   # JAL HND + バジェット（不釣り合い）
    (5, 0): 1.2,   # ANA KIX + ハレクラニ
    (5, 1): 1.8,   # ANA KIX + シェラトン（関西人気）
    (5, 2): 2.0,   # ANA KIX + マリオット（ファミリー）
    (5, 3): 1.0,   # ANA KIX + バジェット
    (6, 0): 0.6,   # FUK + ハレクラニ（少ない）
    (6, 1): 0.8,   # FUK + シェラトン
    (6, 2): 1.2,   # FUK + マリオット（ファミリー出張）
    (6, 3): 1.5,   # FUK + バジェット（バックパッカー風）
    (7, 0): 0.3,   # CTS + ハレクラニ（ほぼなし）
    (7, 1): 0.5,   # CTS + シェラトン
    (7, 2): 0.7,   # CTS + マリオット
    (7, 3): 1.2,   # CTS + バジェット（北海道発バックパック）
}


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ─── テーブル再作成 ──────────────────────────────────────────
    cursor.execute('DROP TABLE IF EXISTS inventory')
    cursor.execute('DROP TABLE IF EXISTS price_history')
    cursor.execute('DROP TABLE IF EXISTS booking_events')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type         TEXT NOT NULL,
            name              TEXT NOT NULL,
            total_stock       INTEGER NOT NULL,
            remaining_stock   INTEGER NOT NULL,
            base_price        INTEGER NOT NULL,
            departure_date    TEXT,
            procurement_date  TEXT,
            elasticity        REAL NOT NULL DEFAULT -1.5
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
            inventory_id       INTEGER NOT NULL,
            partner_id         INTEGER,
            booked_at          TEXT NOT NULL,
            quantity           INTEGER DEFAULT 1,
            sold_price         INTEGER,
            base_price_at_sale INTEGER,
            is_package         INTEGER DEFAULT 0,
            discount_amount    INTEGER DEFAULT 0,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        )
    ''')

    # ─── 在庫レコードの生成 ─────────────────────────────────────
    inv_records = []
    product_inv_map = []  # (inventory_id, product_master, batch) の対応

    for batch in DEPARTURE_BATCHES:
        dep_day = TODAY + timedelta(days=batch["offset"])
        dep_str = dep_day.strftime('%Y-%m-%d')

        for pm in PRODUCT_MASTERS:
            proc_day = dep_day - timedelta(days=pm["procurement_days_before"])
            proc_str = proc_day.strftime('%Y-%m-%d')

            # 出発日に応じた「残在庫」を算出
            # D-1 は出発直前 → より多くが売れていると想定
            days_until_dep = batch["offset"]
            procurement_window = pm["procurement_days_before"]
            elapsed_ratio = max(0.0, min(1.0, 1.0 - (days_until_dep / procurement_window)))
            sold_so_far = int(pm["total_stock"] * pm["sell_thru_ratio"] * elapsed_ratio)
            remaining = max(0, pm["total_stock"] - sold_so_far)

            inv_records.append((
                pm["type"],
                pm["name_tmpl"],
                pm["total_stock"],
                remaining,
                pm["base_price"],
                dep_str,
                proc_str,
                pm.get("elasticity", -1.5)
            ))

    cursor.executemany('''
        INSERT INTO inventory
            (item_type, name, total_stock, remaining_stock, base_price, departure_date, procurement_date, elasticity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', inv_records)
    conn.commit()
    print(f"✅ inventory テーブルに {len(inv_records)} 件の在庫レコードを生成しました。")

    # IDマッピングを取得
    all_inv = [dict(r) for r in cursor.execute("SELECT * FROM inventory").fetchall()]

    # ─── 予約履歴の生成 ────────────────────────────────────────────
    populate_booking_events(conn, all_inv)
    conn.close()
    print("✅ データベースの初期化が完了しました。")


def populate_booking_events(conn, all_inv: list[dict]):
    """
    betavariate分布で商品特性に応じた「予約タイミングの偏り」を再現しながら
    数千件の予約履歴（単品 + パッケージ混在）を生成する。
    """
    cursor = conn.cursor()
    total_inserted = 0

    hotels  = [i for i in all_inv if i["item_type"] == "hotel"]
    flights = [i for i in all_inv if i["item_type"] == "flight"]

    # 商品名 → オリジナルのPRODUCT_MASTERS参照
    def get_pm(name: str):
        for p in PRODUCT_MASTERS:
            if p["name_tmpl"] == name:
                return p
        return PRODUCT_MASTERS[0]

    def random_booking_date(procurement_date_str: str, departure_date_str: str, alpha: float, beta: float) -> str:
        """betavariate分布を使って予約日をランダムに生成する"""
        try:
            proc_dt = datetime.strptime(procurement_date_str, '%Y-%m-%d')
            dep_dt  = datetime.strptime(departure_date_str,  '%Y-%m-%d')
        except Exception:
            proc_dt = TODAY - timedelta(days=180)
            dep_dt  = TODAY + timedelta(days=30)

        window_days = max(1, (dep_dt - proc_dt).days)
        # betavariate: 0〜1の値で予約タイミングを決定
        t = random.betavariate(alpha, beta)
        booking_dt = proc_dt + timedelta(days=int(t * window_days))

        # 仕入日より前、出発日より後にはならないようにクリップ
        booking_dt = max(proc_dt, min(dep_dt - timedelta(days=1), booking_dt))
        # まだ来ていない未来の予約は生成しない
        booking_dt = min(booking_dt, TODAY)

        # 時刻をランダムにずらす（HH:MM:SS）
        booking_dt = booking_dt.replace(
            hour=random.randint(6, 23),
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
            tzinfo=timezone.utc
        )
        return booking_dt.isoformat()

    # ── 1. パッケージ予約の生成 ────────────────────────────────────
    # 出発日バッチごとに処理
    for batch in DEPARTURE_BATCHES:
        dep_str = (TODAY + timedelta(days=batch["offset"])).strftime('%Y-%m-%d')

        batch_flights = [i for i in flights if i["departure_date"] == dep_str]
        batch_hotels  = [i for i in hotels  if i["departure_date"] == dep_str]

        for f_inv in batch_flights:
            f_pm = get_pm(f_inv["name"])
            # フライトのPRODUCT_MASTERリストでのインデックス（4〜7）
            f_idx = PRODUCT_MASTERS.index(f_pm)

            for h_inv in batch_hotels:
                h_pm = get_pm(h_inv["name"])
                h_idx = PRODUCT_MASTERS.index(h_pm)

                affinity = PACKAGE_AFFINITY.get((f_idx, h_idx), 0.5)

                # 相性スコアに基づいて生成件数を決定
                # 相性2.5 → 最大50件、相性0.3 → 最大5件程度
                n_bookings = int(affinity * 20 * random.uniform(0.7, 1.3))
                # 過去バッチは1.0、未来は期間に応じて減衰
                window_bonus = {1: 0.3, 3: 0.5, 10: 0.8, 30: 1.0}
                if batch["offset"] <= 0:
                    n_bookings = int(n_bookings * 1.0)
                else:
                    n_bookings = int(n_bookings * window_bonus.get(batch["offset"], 1.0))

                for _ in range(n_bookings):
                    # フライトと相性の平均alpha/betaでランダム予約日を生成
                    alpha = (f_pm["alpha"] + h_pm["alpha"]) / 2
                    beta  = (f_pm["beta"]  + h_pm["beta"])  / 2

                    booked_at = random_booking_date(
                        f_inv["procurement_date"],
                        f_inv["departure_date"],
                        alpha, beta
                    )

                    # フライト価格（基本価格 ±10%）
                    f_price = int(f_inv["base_price"] * random.uniform(0.9, 1.1) / 100) * 100

                    # ホテル価格（パッケージ割引 5〜12%）
                    discount_rate = random.uniform(0.05, 0.12)
                    discount = int(h_inv["base_price"] * discount_rate / 100) * 100
                    h_price = int(h_inv["base_price"] * random.uniform(0.9, 1.05) / 100) * 100 - discount
                    h_price = max(0, h_price)

                    # フライトのパッケージ予約
                    cursor.execute(
                        "INSERT INTO booking_events "
                        "(inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, is_package, discount_amount) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (f_inv["id"], h_inv["id"], booked_at, 1, f_price, f_inv["base_price"], 1, 0)
                    )
                    # ホテルのパッケージ予約（割引あり）
                    cursor.execute(
                        "INSERT INTO booking_events "
                        "(inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, is_package, discount_amount) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (h_inv["id"], f_inv["id"], booked_at, 1, h_price, h_inv["base_price"], 1, discount)
                    )
                    total_inserted += 2

    # ── 2. 単品予約の生成 ──────────────────────────────────────────
    for inv in all_inv:
        pm = get_pm(inv["name"])
        # 単品予約件数 = 総在庫の（販売率 × 50%）を単品予約と想定
        n_solo = int(inv["total_stock"] * pm["sell_thru_ratio"] * 0.5 * random.uniform(0.8, 1.2))
        n_solo = max(3, n_solo)  # 最低3件

        for _ in range(n_solo):
            booked_at = random_booking_date(
                inv["procurement_date"],
                inv["departure_date"],
                pm["alpha"], pm["beta"]
            )
            # 価格（基本価格 ±20% のダイナミックレンジ）
            price = int(inv["base_price"] * random.uniform(0.85, 1.25) / 100) * 100

            cursor.execute(
                "INSERT INTO booking_events "
                "(inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, is_package, discount_amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (inv["id"], None, booked_at, 1, price, inv["base_price"], 0, 0)
            )
            total_inserted += 1

    conn.commit()
    print(f"✅ booking_events テーブルに {total_inserted} 件の予約履歴（単品 + パッケージ混在）を生成しました。")


if __name__ == '__main__':
    init_db()
