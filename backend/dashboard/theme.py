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
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=cls.chart_text, size=13),
            legend=dict(
                font=dict(color=cls.chart_text, size=13)
            ),
            xaxis=dict(
                color=cls.chart_text,
                gridcolor=cls.chart_grid,
                zerolinecolor=cls.chart_grid,
                tickfont=dict(color=cls.chart_text, size=12),
                title_font=dict(color=cls.chart_text, size=14, weight="bold")
            ),
            yaxis=dict(
                color=cls.chart_text,
                gridcolor=cls.chart_grid,
                zerolinecolor=cls.chart_grid,
                tickfont=dict(color=cls.chart_text, size=12),
                title_font=dict(color=cls.chart_text, size=14, weight="bold")
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
                bgcolor="rgba(0,0,0,0)"
            ),
        )
        return fig
    
    # ─── 背景色 ───
    bg_main = "#f8fafc"         # アプリ全体の背景色
    bg_card = "#ffffff"         # カードやウィジェットの背景色
    white = "#ffffff"           # 汎用的な白色
    bg_hover = "#f1f5f9"        # ホバー時の背景色
    
    # ─── 枠線・区切り線 ───
    border_light = "#e2e8f0"    # 基本の枠線カラー
    border_dark = "#cbd5e1"     # 入力フォーム等の枠線カラー
    
    # ─── ブランド・アクセントカラー ───
    primary = "#6366f1"         # ボタンや主要なUI（Indigo）
    primary_hover = "#4f46e5"
    chart_accent = "#a78bfa"    # グラフのメイン強調色（Purple）
    
    # ─── ステータスカラー ───
    success = "#10b981"         # 利益改善、成功など
    success_light = "#4ade80"   # 明るいサクセスカラー
    danger = "#f87171"          # 損失、警告など
    warning = "#f59e0b"         # 注意
    info = "#0284c7"            # 情報、ハイライトテキスト
    info_light = "#38bdf8"
    
    # ─── グラデーション・透過色 ───
    grad_info = "linear-gradient(135deg,#e0f2fe 0%,#bae6fd 100%)"
    border_info_alpha = "rgba(2,132,199,0.3)"
    shadow_info_alpha = "rgba(2,132,199,0.1)"
    bg_info_light_alpha = "rgba(56,189,248,0.2)"
    
    grad_ai = "linear-gradient(135deg,#f3e8ff 0%,#e9d5ff 100%)"
    border_ai_alpha = "rgba(139,92,246,0.3)"
    shadow_ai_alpha = "rgba(139,92,246,0.1)"
    
    bg_success_alpha = "rgba(16,185,129,0.1)"
    border_success_alpha = "rgba(16,185,129,0.3)"
    
    chart_fill_alpha = "rgba(167,139,250,0.18)"
    chart_fill_alpha2 = "rgba(167,139,250,0.1)"
    
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
    
    alert_info_bg = "#e0e7ff"
    alert_info_border = "#c7d2fe"
    alert_info_text = "#3730a3"

# 各ファイルで `from dashboard.theme import Theme` として利用する
Theme = ThemeColors()
