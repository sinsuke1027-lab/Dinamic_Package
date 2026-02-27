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

# 自動価格ブレーキ関連 (pricing_engine)
BRAKE_THRESHOLD       = 1.5    # 販売速度が期待値の1.5倍を超えたら発動
BRAKE_STRENGTH_PCT    = 0.05   # 5% の価格ブレーキ
MAX_DISCOUNT_PCT      = 0.30   # 最大割引率 (30%)
MAX_MARKUP_PCT        = 0.50   # 最大値上げ率 (50%)
