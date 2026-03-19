"""
init_db.py  ─ Phase 16: 沖縄路線リアルデータ刷新

【設計方針】
  - 東京（羽田）→那覇 HND→OKA 路線に絞り、
    フライト5社（ANA/JAL/Solaseed/SKYMARK/Peach）、沖縄ホテル4件を商品マスタとして定義
  - 2025年1月〜2026年12月の全24ヶ月、各月10日分の出発日を動的生成
  - シーズン（繁忙期/閑散期/中間期）に応じて sold_price に倍率を反映
    ※ base_price は中間期の定価として固定（pricing_engine の基準値として使用）
  - リードタイム別価格補正を sold_price に適用
    （120〜61日前: ×0.85 / 60〜30日前: ×1.0 / 29〜15日前: ×1.10 / 14〜4日前: ×1.20 / 3〜0日前: ×0.75）
  - 購入者情報（性別/年代/同行者人数）を価格帯で差別化して生成
  - betavariate分布で商品特性に応じた「予約タイミングの偏り」を再現
  - パッケージ予約（フライト+ホテル）を PACKAGE_AFFINITY マトリクスで制御
  - random.seed(42) で再現性を確保
"""

import sqlite3
import random
import calendar
from datetime import datetime, timedelta, timezone, date

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'inventory.db')

# 再現性確保のためシードを固定
random.seed(42)

# ─── 基準日（"今日"） ────────────────────────────────────────────────
TODAY = datetime(2026, 3, 18)  # スクリプト実行時点

# ─── シーズン定義 ──────────────────────────────────────────────────
PEAK_MONTHS = {5, 7, 8}        # 繁忙期
OFF_MONTHS  = {2, 6, 11}       # 閑散期
# それ以外は中間期

def get_season(month: int) -> str:
    if month in PEAK_MONTHS:
        return "peak"
    if month in OFF_MONTHS:
        return "off"
    return "mid"

def get_season_multiplier(month: int) -> float:
    s = get_season(month)
    return {"peak": 1.5, "off": 0.8, "mid": 1.0}[s]

# ─── リードタイム別価格補正倍率 ───────────────────────────────────────
def get_leadtime_multiplier(lead_days: int) -> float:
    """購入日〜出発日の日数から sold_price 補正倍率を返す"""
    if lead_days >= 61:     # 120〜61日前: やや安い（早割）
        return 0.85
    elif lead_days >= 30:   # 60〜30日前: 定価
        return 1.00
    elif lead_days >= 15:   # 29〜15日前: やや高い
        return 1.10
    elif lead_days >= 4:    # 14〜4日前: 高い（直前プレミアム）
        return 1.20
    else:                   # 3〜0日前: 安い（見切り直前割）
        return 0.75

# ─── 商品マスタ定義 ────────────────────────────────────────────────
# フィールド説明:
#   type             : "hotel" or "flight"
#   name             : 商品名
#   base_price       : 中間期のベース価格 (¥) ※固定。シーズン補正は sold_price に反映
#   total_stock      : 在庫総数（座席数 / 客室数）
#   sell_thru_ratio  : 「理想的な販売率」
#   alpha, beta      : betavariate分布パラメータ（α<β=早期集中、α>β=直前集中）
#   elasticity       : 価格弾力性（pricing_engine用）
#   price_tier       : "budget" / "mid" / "premium" （購入者プロファイル分岐用）
PRODUCT_MASTERS = [
    # ── ホテル 4商品 ─────────────────────────────────────────
    {
        "type": "hotel",
        "name": "Southwest Grand Hotel 沖縄",
        "base_price": 100_000,
        "total_stock": 20,
        "sell_thru_ratio": 0.75,
        "alpha": 1.2, "beta": 6.0,   # 早期集中（高級層は早めに予約）
        "elasticity": -0.6,
        "price_tier": "premium",
    },
    {
        "type": "hotel",
        "name": "ハイアット リージェンシー 沖縄",
        "base_price": 60_000,
        "total_stock": 30,
        "sell_thru_ratio": 0.85,
        "alpha": 1.5, "beta": 5.0,   # 早期寄り
        "elasticity": -0.9,
        "price_tier": "premium",
    },
    {
        "type": "hotel",
        "name": "沖縄 ナハナホテル&スパ",
        "base_price": 40_000,
        "total_stock": 50,
        "sell_thru_ratio": 0.88,
        "alpha": 2.5, "beta": 2.5,   # 均等（ファミリー）
        "elasticity": -1.4,
        "price_tier": "mid",
    },
    {
        "type": "hotel",
        "name": "ホテルリブマックス那覇",
        "base_price": 30_000,
        "total_stock": 80,
        "sell_thru_ratio": 0.65,
        "alpha": 5.0, "beta": 1.5,   # 直前集中（格安層）
        "elasticity": -2.2,
        "price_tier": "budget",
    },
    # ── フライト 5商品 ─────────────────────────────────────────
    {
        "type": "flight",
        "name": "ANA HND→OKA",
        "base_price": 40_000,
        "total_stock": 180,
        "sell_thru_ratio": 0.95,
        "alpha": 1.0, "beta": 5.0,   # 早期集中（人気路線）
        "elasticity": -0.7,
        "price_tier": "premium",
    },
    {
        "type": "flight",
        "name": "JAL HND→OKA",
        "base_price": 38_000,
        "total_stock": 160,
        "sell_thru_ratio": 0.92,
        "alpha": 2.0, "beta": 4.0,   # 早期寄り
        "elasticity": -0.9,
        "price_tier": "premium",
    },
    {
        "type": "flight",
        "name": "Solaseed Air HND→OKA",
        "base_price": 22_000,
        "total_stock": 100,
        "sell_thru_ratio": 0.80,
        "alpha": 2.5, "beta": 2.5,   # 均等（ファミリー）
        "elasticity": -1.5,
        "price_tier": "mid",
    },
    {
        "type": "flight",
        "name": "SKYMARK HND→OKA",
        "base_price": 18_000,
        "total_stock": 120,
        "sell_thru_ratio": 0.72,
        "alpha": 4.0, "beta": 2.0,   # 直前集中
        "elasticity": -2.0,
        "price_tier": "budget",
    },
    {
        "type": "flight",
        "name": "Peach HND→OKA",
        "base_price": 12_000,
        "total_stock": 100,
        "sell_thru_ratio": 0.55,
        "alpha": 6.0, "beta": 1.2,   # 超直前集中（LCC）
        "elasticity": -2.8,
        "price_tier": "budget",
    },
]

# ─── パッケージ相性マトリクス ──────────────────────────────────────
# (フライト商品名, ホテル商品名) : 相性スコア（高い=組み合わせ予約が多い）
PACKAGE_AFFINITY = {
    ("ANA HND→OKA",          "Southwest Grand Hotel 沖縄"):  2.5,
    ("ANA HND→OKA",          "ハイアット リージェンシー 沖縄"): 2.2,
    ("ANA HND→OKA",          "沖縄 ナハナホテル&スパ"):        1.5,
    ("ANA HND→OKA",          "ホテルリブマックス那覇"):         0.5,
    ("JAL HND→OKA",          "Southwest Grand Hotel 沖縄"):  2.3,
    ("JAL HND→OKA",          "ハイアット リージェンシー 沖縄"): 2.0,
    ("JAL HND→OKA",          "沖縄 ナハナホテル&スパ"):        1.5,
    ("JAL HND→OKA",          "ホテルリブマックス那覇"):         0.4,
    ("Solaseed Air HND→OKA", "Southwest Grand Hotel 沖縄"):  0.5,
    ("Solaseed Air HND→OKA", "ハイアット リージェンシー 沖縄"): 0.8,
    ("Solaseed Air HND→OKA", "沖縄 ナハナホテル&スパ"):        2.0,
    ("Solaseed Air HND→OKA", "ホテルリブマックス那覇"):         1.2,
    ("SKYMARK HND→OKA",      "Southwest Grand Hotel 沖縄"):  0.3,
    ("SKYMARK HND→OKA",      "ハイアット リージェンシー 沖縄"): 0.5,
    ("SKYMARK HND→OKA",      "沖縄 ナハナホテル&スパ"):        1.0,
    ("SKYMARK HND→OKA",      "ホテルリブマックス那覇"):         1.5,
    ("Peach HND→OKA",        "Southwest Grand Hotel 沖縄"):  0.2,
    ("Peach HND→OKA",        "ハイアット リージェンシー 沖縄"): 0.3,
    ("Peach HND→OKA",        "沖縄 ナハナホテル&スパ"):        0.8,
    ("Peach HND→OKA",        "ホテルリブマックス那覇"):         1.8,
}

# ─── 購入者プロファイル定義 ────────────────────────────────────────
# price_tier ごとの分布を定義
BUYER_PROFILES = {
    "budget": {
        "companion_weights": {0: 0.65, 1: 0.20, 2: 0.10, 3: 0.05},
        "age_weights": {
            "10代": 0.15, "20代": 0.40, "30代": 0.25,
            "40代": 0.10, "50代": 0.05, "60代": 0.03, "70代以上": 0.02
        },
    },
    "mid": {
        "companion_weights": {0: 0.15, 1: 0.25, 2: 0.30, 3: 0.20, 4: 0.10},
        "age_weights": {
            "10代": 0.02, "20代": 0.10, "30代": 0.30,
            "40代": 0.35, "50代": 0.15, "60代": 0.06, "70代以上": 0.02
        },
    },
    "premium": {
        "companion_weights": {0: 0.10, 1: 0.55, 2: 0.20, 3: 0.10, 4: 0.05},
        "age_weights": {
            "10代": 0.01, "20代": 0.05, "30代": 0.15,
            "40代": 0.30, "50代": 0.28, "60代": 0.15, "70代以上": 0.06
        },
    },
}

def weighted_choice(choices: dict):
    """重み付き選択 (キー: 値, 値: 重み)"""
    keys = list(choices.keys())
    weights = list(choices.values())
    return random.choices(keys, weights=weights, k=1)[0]

def generate_buyer_profile(price_tier: str) -> tuple[str, str, int]:
    """(gender, age_group, companion_count) を返す"""
    profile = BUYER_PROFILES.get(price_tier, BUYER_PROFILES["mid"])
    gender = random.choice(["M", "F"])
    age_group = weighted_choice(profile["age_weights"])
    companion_count = weighted_choice(profile["companion_weights"])
    return gender, age_group, companion_count

# ─── 出発日バッチを動的生成 ───────────────────────────────────────
def generate_departure_dates() -> list[dict]:
    """
    2025年1月〜2026年12月の全24ヶ月について、
    各月から均等に10日分の出発日を生成する。
    """
    batches = []
    # 月内の10日分を均等に選ぶオフセット（1〜28日の範囲、月末日も含む）
    day_positions = [3, 6, 9, 12, 15, 18, 21, 24, 27, 0]  # 0=月末日

    for year in [2025, 2026]:
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            for pos in day_positions:
                day = last_day if pos == 0 else min(pos, last_day)
                dep_date = date(year, month, day)
                season = get_season(month)
                batches.append({
                    "dep_date": dep_date,
                    "dep_str": dep_date.strftime('%Y-%m-%d'),
                    "month": month,
                    "season": season,
                    "season_mult": get_season_multiplier(month),
                })

    return batches


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ─── テーブル再作成 ──────────────────────────────────────────
    cursor.execute('DROP TABLE IF EXISTS inventory')
    cursor.execute('DROP TABLE IF EXISTS price_history')
    cursor.execute('DROP TABLE IF EXISTS booking_events')
    cursor.execute('DROP TABLE IF EXISTS model_settings')
    cursor.execute('DROP TABLE IF EXISTS product_classification')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type         TEXT NOT NULL,
            name              TEXT NOT NULL,
            total_stock       INTEGER NOT NULL,
            remaining_stock   INTEGER NOT NULL,
            base_price        INTEGER NOT NULL,
            cost              INTEGER NOT NULL,
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
            gender             TEXT,
            age_group          TEXT,
            companion_count    INTEGER DEFAULT 0,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_settings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type       TEXT NOT NULL,
            characteristic  TEXT NOT NULL,
            strategy        TEXT NOT NULL,
            config_json     TEXT NOT NULL,
            composite_score REAL,
            mape            REAL,
            revenue_lift    REAL,
            spoilage_reduction REAL,
            updated_at      TEXT NOT NULL,
            UNIQUE(item_type, characteristic)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_classification (
            name            TEXT NOT NULL,
            item_type       TEXT NOT NULL,
            characteristic  TEXT NOT NULL,
            target_rate_peak REAL DEFAULT 0.95,
            target_rate_normal REAL DEFAULT 0.80,
            target_rate_offpeak REAL DEFAULT 0.60,
            source          TEXT,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY (name, item_type)
        )
    ''')

    # ─── 出発日バッチ生成 ────────────────────────────────────────
    departure_batches = generate_departure_dates()

    # ─── 在庫レコードの生成 ─────────────────────────────────────
    inv_records = []

    for batch in departure_batches:
        dep_date = batch["dep_date"]
        dep_str  = batch["dep_str"]

        for pm in PRODUCT_MASTERS:
            # 販売開始日: 出発日の 110〜130 日前（120日前 ±ランダム）
            actual_proc_days = random.randint(110, 130)
            proc_day = dep_date - timedelta(days=actual_proc_days)
            proc_str = proc_day.strftime('%Y-%m-%d')

            # 出発日に応じた「残在庫」を算出
            today_date = TODAY.date()
            days_until_dep = (dep_date - today_date).days
            procurement_window = actual_proc_days
            elapsed_ratio = max(0.0, min(1.0, 1.0 - (days_until_dep / procurement_window) if days_until_dep > 0 else 1.0))
            sold_so_far = int(pm["total_stock"] * pm["sell_thru_ratio"] * elapsed_ratio)
            remaining = max(0, pm["total_stock"] - sold_so_far)

            # 原価を base_price の 70〜80%で設定
            cost_rate = random.uniform(0.70, 0.80)
            cost = int(pm["base_price"] * cost_rate)

            inv_records.append((
                pm["type"],
                pm["name"],
                pm["total_stock"],
                remaining,
                pm["base_price"],   # ← 中間期の定価（固定）
                cost,
                dep_str,
                proc_str,
                pm.get("elasticity", -1.5)
            ))

    cursor.executemany('''
        INSERT INTO inventory
            (item_type, name, total_stock, remaining_stock, base_price, cost, departure_date, procurement_date, elasticity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', inv_records)
    conn.commit()
    print(f"✅ inventory テーブルに {len(inv_records)} 件の在庫レコードを生成しました。")

    # IDマッピングを取得
    all_inv = [dict(r) for r in cursor.execute("SELECT * FROM inventory").fetchall()]

    # ─── 予約履歴の生成 ────────────────────────────────────────────
    populate_booking_events(conn, all_inv, departure_batches)
    conn.close()
    print("✅ データベースの初期化が完了しました。")


def populate_booking_events(conn, all_inv: list[dict], departure_batches: list[dict]):
    """
    betavariate分布で商品特性に応じた「予約タイミングの偏り」を再現しながら
    数万件の予約履歴（単品 + パッケージ混在）を生成する。
    - sold_price にシーズン倍率 × リードタイム補正を反映
    - 購入者情報（性別/年代/同行者人数）を商品価格帯に応じて生成
    """
    cursor = conn.cursor()
    total_inserted = 0

    hotels  = [i for i in all_inv if i["item_type"] == "hotel"]
    flights = [i for i in all_inv if i["item_type"] == "flight"]

    # 出発日文字列 → シーズン乗数のマップ
    dep_season_map = {b["dep_str"]: b["season_mult"] for b in departure_batches}

    # 商品名 → PRODUCT_MASTERS 参照
    def get_pm(name: str):
        for p in PRODUCT_MASTERS:
            if p["name"] == name:
                return p
        return PRODUCT_MASTERS[0]

    def random_booking_date(procurement_date_str: str, departure_date_str: str,
                            alpha: float, beta: float) -> tuple[str, int]:
        """
        betavariate分布を使って予約日をランダムに生成する。
        Returns: (ISO形式日時文字列, 購入時点のリードタイム日数)
        """
        try:
            proc_dt = datetime.strptime(procurement_date_str, '%Y-%m-%d')
            dep_dt  = datetime.strptime(departure_date_str,  '%Y-%m-%d')
        except Exception:
            proc_dt = TODAY - timedelta(days=120)
            dep_dt  = TODAY + timedelta(days=30)

        # 販売開始〜今日 or 出発日 の範囲で予約日を決定
        end_dt = min(dep_dt, TODAY)
        total_seconds = (end_dt - proc_dt).total_seconds()

        if total_seconds <= 0:
            booking_dt = proc_dt
        else:
            random_fraction = random.betavariate(alpha, beta)
            booking_dt = proc_dt + timedelta(seconds=total_seconds * random_fraction)

        # 時刻をランダムにずらす
        booking_dt = booking_dt.replace(
            hour=random.randint(6, 23),
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
            tzinfo=timezone.utc
        )

        # リードタイム計算（予約日から出発日まで）
        lead_days = (dep_dt.date() - booking_dt.date()).days

        return booking_dt.isoformat(), max(0, lead_days)

    # ── 在庫上限管理 ──
    remaining_stocks = {inv["id"]: inv["total_stock"] for inv in all_inv}

    # ── 1. パッケージ予約の生成 ────────────────────────────────────
    for batch in departure_batches:
        dep_str = batch["dep_str"]
        season_mult = batch["season_mult"]

        batch_flights = [i for i in flights if i["departure_date"] == dep_str]
        batch_hotels  = [i for i in hotels  if i["departure_date"] == dep_str]

        for f_inv in batch_flights:
            f_pm  = get_pm(f_inv["name"])
            for h_inv in batch_hotels:
                h_pm  = get_pm(h_inv["name"])

                affinity = PACKAGE_AFFINITY.get((f_inv["name"], h_inv["name"]), 0.3)
                # パッケージ需要もシーズン倍率の影響を強く受けるようにする
                base_demand = int(affinity * 15 * season_mult * random.uniform(0.7, 1.3))

                max_pkg_alloc = min(
                    remaining_stocks[f_inv["id"]],
                    remaining_stocks[h_inv["id"]],
                    int(f_inv["total_stock"] * 0.25),   # フライト: 25%まで
                    int(h_inv["total_stock"] * 0.20),   # ホテル: 20%まで（単品枠を確保）
                )

                n_bookings = min(base_demand, max_pkg_alloc)
                if n_bookings <= 0:
                    continue

                alpha = (f_pm["alpha"] + h_pm["alpha"]) / 2
                beta  = (f_pm["beta"]  + h_pm["beta"])  / 2

                for _ in range(n_bookings):
                    if remaining_stocks[f_inv["id"]] <= 0 or remaining_stocks[h_inv["id"]] <= 0:
                        break

                    booked_at, lead_days = random_booking_date(
                        f_inv["procurement_date"],
                        f_inv["departure_date"],
                        alpha, beta
                    )

                    lt_mult = get_leadtime_multiplier(lead_days)

                    # フライト価格: base_price × シーズン倍率 × リードタイム補正 × ±5%
                    f_price = int(
                        f_inv["base_price"] * season_mult * lt_mult
                        * random.uniform(0.95, 1.05) / 100
                    ) * 100
                    f_price = max(f_price, 1000)

                    # ホテル価格: パッケージ割引 5〜12%
                    discount_rate = random.uniform(0.05, 0.12)
                    discount = int(h_inv["base_price"] * season_mult * discount_rate / 100) * 100
                    h_price = int(
                        h_inv["base_price"] * season_mult * lt_mult
                        * random.uniform(0.95, 1.05) / 100
                    ) * 100 - discount
                    h_price = max(h_price, 1000)

                    # 購入者プロファイル（フライトとホテルで高い方の price_tier を使用）
                    tier_rank = {"budget": 0, "mid": 1, "premium": 2}
                    dominant_tier = max(
                        [f_pm["price_tier"], h_pm["price_tier"]],
                        key=lambda t: tier_rank.get(t, 1)
                    )
                    gender, age_group, companion_count = generate_buyer_profile(dominant_tier)

                    cursor.execute(
                        "INSERT INTO booking_events "
                        "(inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, "
                        "is_package, discount_amount, gender, age_group, companion_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (f_inv["id"], h_inv["id"], booked_at, 1, f_price, f_inv["base_price"],
                         1, 0, gender, age_group, companion_count)
                    )
                    cursor.execute(
                        "INSERT INTO booking_events "
                        "(inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, "
                        "is_package, discount_amount, gender, age_group, companion_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (h_inv["id"], f_inv["id"], booked_at, 1, h_price, h_inv["base_price"],
                         1, discount, gender, age_group, companion_count)
                    )

                    remaining_stocks[f_inv["id"]] -= 1
                    remaining_stocks[h_inv["id"]] -= 1
                    total_inserted += 2

    # ── 2. 単品予約の生成 ──────────────────────────────────────────
    for inv in all_inv:
        pm = get_pm(inv["name"])
        season_mult = dep_season_map.get(inv["departure_date"], 1.0)
        
        # 最終到達点（販売率）がシーズンによって明確に変動するようにする
        adjusted_sell_thru = min(1.0, pm["sell_thru_ratio"] * season_mult)
        target_qty = int(inv["total_stock"] * adjusted_sell_thru * random.uniform(0.85, 1.15))
        already_sold = inv["total_stock"] - remaining_stocks[inv["id"]]
        solo_target = max(1, target_qty - already_sold)
        n_solo = min(solo_target, remaining_stocks[inv["id"]])

        for _ in range(n_solo):
            booked_at, lead_days = random_booking_date(
                inv["procurement_date"],
                inv["departure_date"],
                pm["alpha"], pm["beta"]
            )

            lt_mult = get_leadtime_multiplier(lead_days)

            # 価格: base_price × シーズン × リードタイム × ±10%
            price = int(
                inv["base_price"] * season_mult * lt_mult
                * random.uniform(0.90, 1.10) / 100
            ) * 100
            price = max(price, 1000)

            gender, age_group, companion_count = generate_buyer_profile(pm["price_tier"])

            cursor.execute(
                "INSERT INTO booking_events "
                "(inventory_id, partner_id, booked_at, quantity, sold_price, base_price_at_sale, "
                "is_package, discount_amount, gender, age_group, companion_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (inv["id"], None, booked_at, 1, price, inv["base_price"],
                 0, 0, gender, age_group, companion_count)
            )
            total_inserted += 1

    conn.commit()
    print(f"✅ booking_events テーブルに {total_inserted:,} 件の予約履歴（単品 + パッケージ混在）を生成しました。")


if __name__ == '__main__':
    init_db()
