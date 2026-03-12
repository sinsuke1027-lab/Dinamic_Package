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
            font=dict(family="'Outfit', 'Inter', 'Segoe UI', 'Roboto', sans-serif", color=cls.chart_text, size=13),
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
    
    # ─── セマンティック・アクション ───
    color_pos = "#16a34a"       # ポジティブ（成功、改善）
    color_pos_light = "#f0fdf4" # ポジティブ背景
    color_neg = "#dc2626"       # ネガティブ（損失、悪化）
    color_neg_light = "#fff1f2" # ネガティブ背景
    
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
    
    chart_actual = "rgba(150, 150, 150, 0.7)"
    chart_h_alpha = "rgba(16, 185, 129, 0.9)"
    chart_f_alpha = "rgba(20, 184, 166, 0.9)"
    chart_line_muted = "rgba(148, 163, 184, 0.5)"
    
    chart_fill_alpha = "rgba(167,139,250,0.18)"
    chart_fill_alpha2 = "rgba(167,139,250,0.1)"
    
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
    
    alert_info_text = "#3730a3"

    # ─── UI 特殊効果 ───
    tooltip_bg = "#1e293b"      # ツールチップ背景
    tooltip_text = "#ffffff"    # ツールチップ文字
    shadow_sm = "0 1px 3px rgba(0,0,0,0.05)"
    shadow_md = "0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03)"
    shadow_lg = "0 10px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.05)"
    shadow_info = "0 4px 12px rgba(99, 102, 241, 0.1)"

    # ─── 汎用パレット ───
    palette = ["#6366f1", "#10b981", "#f59e0b", "#0284c7", "#8b5cf6", "#ec4899", "#ef4444"]

    # ─── フォントサイズ ───
    size_xs = "0.7rem"     # 極小 (キャプション等)
    size_sm = "0.75rem"    # 小 (バッジ等)
    size_md = "0.85rem"    # 中 (標準的な補助テキスト)
    size_base = "1rem"     # 基本 (段落等)
    size_lg = "1.2rem"     # 大 (アイコン、強調、小見出し)
    size_xl = "1.5rem"     # 特大 (カード内の主要数値)
    size_2xl = "2rem"      # 巨大 (メインメトリック)
    size_3xl = "2.4rem"    # 最大 (インパクト強調)

# 各ファイルで `from dashboard.theme import Theme` として利用する
Theme = ThemeColors()
