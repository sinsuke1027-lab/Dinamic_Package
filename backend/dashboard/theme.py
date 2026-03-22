class ThemeColors:
    """UIカラーの一括管理用クラス"""
    
    # ─── テキスト色 ───
    text_main = "#1e293b"       # 基本の文字色
    text_dark = "#0f172a"       # 強調する文字色・見出し
    text_sec = "#334155"        # セカンダリ文字色
    text_muted = "#64748b"      # 補助的な文字色（キャプションなど）
    
    # ─── グラフ用テキスト色 ───
    chart_text = "#000000"      # グラフの凡例や軸の文字色（完全な黒）
    chart_grid = "#94a3b8"      # グラフの枠線・グリッド（少し濃いめに）
    
    # ─── グラフ用レイアウト関数 ───
    @classmethod
    def apply_chart_theme(cls, fig):
        """PlotlyのFigureに共通カラースキーム（軸色、凡例色、背景色など）を適用する"""
        fig.update_layout(
            paper_bgcolor=cls.bg_transparent,
            plot_bgcolor=cls.bg_transparent,
            font=dict(family="'Outfit', 'Inter', 'Segoe UI', 'Roboto', sans-serif", color=cls.chart_text, size=14),
            legend=dict(
                font=dict(color=cls.chart_text, size=14)
            ),
            xaxis=dict(
                color=cls.chart_text,
                gridcolor=cls.chart_grid,
                zerolinecolor=cls.chart_grid,
                tickfont=dict(color=cls.chart_text, size=13),
                title_font=dict(color=cls.chart_text, size=15, weight="bold")
            ),
            yaxis=dict(
                color=cls.chart_text,
                gridcolor=cls.chart_grid,
                zerolinecolor=cls.chart_grid,
                tickfont=dict(color=cls.chart_text, size=13),
                title_font=dict(color=cls.chart_text, size=15, weight="bold")
            ),
            polar=dict(
                radialaxis=dict(
                    color=cls.chart_text,
                    gridcolor=cls.chart_grid,
                    tickfont=dict(color=cls.chart_text, size=12)
                ),
                angularaxis=dict(
                    color=cls.chart_text,
                    gridcolor=cls.chart_grid,
                    tickfont=dict(color=cls.chart_text, size=12)
                ),
                bgcolor=cls.bg_transparent
            ),
        )
        return fig
    
    # ─── 背景色 ───
    bg_main = "#f8fafc"         # アプリ全体の背景色
    bg_card = "#ffffff"         # カードやウィジェットの背景色
    white = "#ffffff"           # 汎用的な白色
    bg_hover = "#f1f5f9"        # ホバー時の背景色
    bg_glass = "rgba(255, 255, 255, 0.85)"  # 透過カード背景
    bg_tab_list = "rgba(241, 245, 249, 0.8)" # タブリスト背景
    
    # ─── 枠線・区切り線 ───
    border_light = "#e2e8f0"    # 基本の枠線カラー
    border_dark = "#cbd5e1"     # 入力フォーム等の枠線カラー
    
    # ─── ブランド・アクセントカラー ───
    primary = "#0ea5e9"         # ボタンや主要なUI（Sky Blue）
    primary_hover = "#0284c7"
    primary_alpha = "rgba(14, 165, 233, 0.1)"  # 透過性のある青（背景用）
    primary_border = "rgba(14, 165, 233, 0.3)" # 透過性のある青（枠線用）
    chart_accent = "#38bdf8"    # グラフのメイン強調色（Light Blue）
    
    # ─── ステータスカラー ───
    success = "#10b981"         # 利益改善、成功など
    success_light = "#4ade80"   # 明るいサクセスカラー
    danger = "#f87171"          # 損失、警告など
    warning = "#f59e0b"         # 注意
    info = "#0284c7"            # 情報、ハイライトテキスト
    info_light = "#38bdf8"
    
    # ─── セマンティック・アクション ───
    color_pos = "#16a34a"       # ポジティブ（成功、改善）
    color_pos_light = "#f0fdf4" # ポジティブ背景
    color_pos_light_alpha = "rgba(22, 163, 74, 0.1)"
    color_neg = "#dc2626"       # ネガティブ（損失、悪化）
    color_neg_light = "#fff1f2" # ネガティブ背景
    
    # ─── グラデーション・透過色 ───
    grad_info = "linear-gradient(135deg,#e0f2fe 0%,#bae6fd 100%)"
    border_info_alpha = "rgba(14, 165, 233, 0.3)"
    shadow_info_alpha = "rgba(14, 165, 233, 0.1)"
    bg_info_light_alpha = "rgba(56, 189, 248, 0.2)"
    
    grad_ai = "linear-gradient(135deg,#f0f9ff 0%,#e0f2fe 100%)"
    border_ai_alpha = "rgba(14, 165, 233, 0.3)"
    shadow_ai_alpha = "rgba(14, 165, 233, 0.1)"
    
    bg_success_alpha = "rgba(16, 185, 129, 0.1)"
    border_success_alpha = "rgba(16, 185, 129, 0.3)"
    
    chart_actual = "rgba(150, 150, 150, 0.7)"
    chart_h_alpha = "rgba(16, 185, 129, 0.9)"
    chart_f_alpha = "rgba(20, 184, 166, 0.9)"
    chart_line_muted = "rgba(148, 163, 184, 0.5)"
    
    chart_fill_alpha = "rgba(56, 189, 248, 0.18)"
    chart_fill_alpha2 = "rgba(56, 189, 248, 0.1)"
    
    bg_transparent = "rgba(0,0,0,0)"  # 透明背景用
    
    # ─── DataFrame, 通知バッジ用特定色 ───
    badge_green_bg = "#dcfce7"
    badge_green_text = "#166534"
    badge_red_bg = "#fee2e2"
    badge_red_text = "#991b1b"
    
    alert_warning_bg = "#fef3c7"
    alert_warning_border = "#fde68a"
    alert_warning_text = "#92400e"
    
    alert_danger_bg = "#fee2e2"
    alert_danger_border = "#fecaca"
    alert_danger_text = "#991b1b"
    
    alert_info_bg = "#f0f9ff"
    alert_info_border = "#bae6fd"
    alert_info_text = "#0369a1"

    # ─── UI 特殊効果 ───
    tooltip_bg = "#0f172a"      # ツールチップ背景
    tooltip_text = "#ffffff"    # ツールチップ文字
    shadow_sm = "0 1px 3px rgba(0,0,0,0.05)"
    shadow_md = "0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03)"
    shadow_lg = "0 10px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.05)"
    shadow_info = "0 4px 12px rgba(14, 165, 233, 0.15)"

    # ─── 汎用パレット ───
    palette = ["#0ea5e9", "#10b981", "#f59e0b", "#0284c7", "#8b5cf6", "#ec4899", "#ef4444"]

    # ─── フォントサイズ ───
    size_xs = "0.75rem"    # 極小 (キャプション等)
    size_sm = "0.875rem"   # 小 (バッジ等)
    size_md = "1.0rem"     # 中 (標準的な補助テキスト)
    size_base = "1.1rem"   # 基本 (段落等)
    size_lg = "1.35rem"    # 大 (アイコン、強調、小見出し)
    size_xl = "1.75rem"    # 特大 (カード内の主要数値)
    size_2xl = "2.5rem"    # 巨大 (メインメトリック)
    size_3xl = "3.2rem"    # 最大 (インパクト強調)

    # ─── セマンティック・フォントサイズ ───
    font_size_h1 = "2.2rem"
    font_size_h2 = "1.8rem"
    font_size_h3 = "1.4rem"
    font_size_card_title = "1rem"
    font_size_metric = "2.4rem"
    font_size_metric_label = "0.85rem"
    font_size_body = "0.95rem"
    font_size_caption = "0.75rem"

    # ─── 余白・角丸 ───
    radius_sm = "8px"
    radius_md = "12px"
    radius_lg = "20px"
    
    spacing_xs = "4px"
    spacing_sm = "12px"
    spacing_md = "20px"
    spacing_lg = "32px"

    # ─── UD（ユニバーサルデザイン）カラーパレット ───
    ud_categorical = [
        "#56B4E9",  # Sky Blue
        "#D55E00",  # Vermilion
        "#009E73",  # Blue Green
        "#E69F00",  # Orange
        "#0072B2",  # Blue
        "#CC79A7",  # Reddish Purple
        "#F0E442",  # Yellow
        "#000000"   # Black
    ]
    
    ud_sequential_age = {
        "10代": "#c6dbef", 
        "20代": "#9ecae1", 
        "30代": "#6baed6", 
        "40代": "#4292c6", 
        "50代": "#2171b5", 
        "60代": "#08519c", 
        "70代以上": "#08306b",
        "不明": "#999999"
    }
    
    ud_sequential_comp = {
        "ソロ (1名)": "#c7e9c0", 
        "ペア (2名)": "#74c476", 
        "トリオ (3名)": "#238b45", 
        "グループ (4名)": "#00441b",
        "不明": "#999999"
    }
    
    ud_gender = {
        "M": "#56B4E9",     # 男性 (Sky Blue)
        "F": "#E69F00",     # 女性 (Orange)
        "不明": "#999999",  # 不明 (Gray)
        "男性": "#56B4E9",
        "女性": "#E69F00"
    }

# 各ファイルで `from dashboard.theme import Theme` として利用する
Theme = ThemeColors()
