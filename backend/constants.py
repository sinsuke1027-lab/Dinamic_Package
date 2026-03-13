"""
constants.py
システム全体で使用する共通定数とマジックナンバーを管理。
"""

# 原価計算関連
DEFAULT_COST_RATIO = 0.90  # 標準的な原価率 (90%)

# 需要予測係数 (calculate_demand_forecast)
FORECAST_MULTIPLIERS = {
    "pessimistic": 0.7,  # 悲観シナリオ (70%)
    "base":        1.0,  # ベースシナリオ (100%)
    "optimistic":  1.3   # 楽観シナリオ (130%)
}

# パッケージ最適化関連 (calculate_optimal_strategy)
BUNDLE_VELOCITY_BOOST = 1.5    # パッケージ化による販売速度向上係数
BUNDLE_THRESHOLD      = 5000   # バンドル推奨の最低利益改善基準（円）
BUNDLE_DISCOUNT_RATE  = 0.08   # パッケージ割引率（合計額の8%）
CANNIBALIZATION_RATE  = 0.15   # カニバリゼーション控除率の基本値

# キャンセル・変動率
BASE_CANCELLATION_RATE = 0.05
PRICE_ELASTICITY = -1.5

# 自動割引探索パラメータ
AUTO_DISCOUNT_MIN_RATE = 0.02
AUTO_DISCOUNT_MAX_RATE = 0.20
AUTO_DISCOUNT_GRID_STEPS = 5

# 自動価格ブレーキ関連 (pricing_engine)
BRAKE_THRESHOLD       = 1.5    # 販売速度が期待値の1.5倍を超えたら発動
BRAKE_STRENGTH_PCT    = 0.05   # 5% の価格ブレーキ
MAX_DISCOUNT_PCT      = 0.30   # 最大割引率 (30%)
MAX_MARKUP_PCT        = 0.50   # AI Command Center / ロジック用デフォルト値
DEFAULT_RULE_INV_PREMIUM_PCT = 30
DEFAULT_RULE_INV_HIGH_PCT = 10
DEFAULT_RULE_INV_DISCOUNT_PCT = -15

DEFAULT_RULE_TIME_LAST_MIN_PCT = -15
DEFAULT_RULE_TIME_PEAK_PCT = 10
DEFAULT_RULE_TIME_EARLY_PCT = -10

DEFAULT_DECAY_K = 20.0
DEFAULT_DECAY_P = 0.12

# --- 追加分: ハードコーディングされていた係数群 ---

# 1. 在庫・時期の判定しきい値 (判定境界)
INV_THRESHOLD_PREMIUM = 0.20
INV_THRESHOLD_HIGH    = 0.50
INV_THRESHOLD_NORMAL  = 0.70

TIME_THRESHOLD_LAST_MIN = 7
TIME_THRESHOLD_PEAK     = 30
TIME_THRESHOLD_NORMAL   = 90

# 2. 価格の丸め
PRICE_ROUNDING_UNIT = 100

# 3. 商品分類基準 (model_evaluator.py)
CLASS_POPULAR_THRESHOLD = 0.75
CLASS_NICHE_DAYS        = 14
CLASS_NICHE_RATIO       = 0.5

# 4. バックテスト評価重み (model_evaluator.py)
SCORE_WEIGHT_MAPE     = 0.3
SCORE_WEIGHT_LIFT     = 0.4
SCORE_WEIGHT_SPOILAGE = 0.2
SCORE_WEIGHT_DIR_ACC  = 0.1

# 5. ホテル切迫度スコア重み (packaging_engine.py)
HOTEL_URGENCY_TIME_WEIGHT = 0.3
HOTEL_URGENCY_INV_WEIGHT  = 0.7
HOTEL_URGENCY_MAX_DAYS    = 30.0

# 6. 販売速度自動調整の判定 (packaging_engine.py)
VELOCITY_ADJ_HIGH_2_THRESHOLD = 2.0
VELOCITY_ADJ_HIGH_1_THRESHOLD = 1.5
VELOCITY_ADJ_LOW_THRESHOLD    = 0.3
VELOCITY_ADJ_HIGH_2_RATE      = 0.10
VELOCITY_ADJ_HIGH_1_RATE      = 0.05
VELOCITY_ADJ_LOW_RATE         = -0.05
