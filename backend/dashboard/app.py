"""
dashboard/app.py  ― フェーズ1 ホワイトボックス化（タブ型 SaaS レイアウト）

【3タブ構成】
  🏠 ライブ概況       : KPI カード / パッケージランキング / 販売速度
  🔍 価格の内訳分析   : 単品5ステップ WF / パッケージ7ステップ WF
  🃏 商品カルテ       : 5軸レーダーチャート / 特性バッジ / 数値サマリー

【起動方法】
  cd backend
  source venv/bin/activate
  streamlit run dashboard/app.py
"""

import os
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── 設定 ────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "inventory.db")

st.set_page_config(
    page_title="Explainable Pricing Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── カスタム CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: #0a0a0f; color: #e2e8f0; }
h1 { color: #a78bfa !important; font-weight: 900 !important; font-size: 2rem !important; }
h2, h3, h4 { color: #c4b5fd !important; }

/* タブ */
button[data-baseweb="tab"] {
    font-size: 1rem !important; font-weight: 600 !important;
    color: #64748b !important; border-radius: 10px 10px 0 0 !important;
    padding: 10px 24px !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #a78bfa !important;
    border-bottom: 3px solid #a78bfa !important;
    background: rgba(167,139,250,.08) !important;
}

/* KPI カード */
.metric-card {
    background: linear-gradient(135deg,#1e1b4b 0%,#312e81 100%);
    border:1px solid #4338ca; border-radius:16px;
    padding:20px; text-align:center; margin:6px; height:100%;
}
.metric-value { font-size:2rem; font-weight:900; color:#a78bfa; margin:8px 0; }
.metric-label { font-size:.75rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.1em; }
.metric-sub   { font-size:.9rem; color:#c4b5fd; }

/* バッジ */
.badge-up   { display:inline-block; background:rgba(248,113,113,.2); color:#f87171;
              border-radius:999px; padding:2px 10px; font-size:.8rem; font-weight:700; }
.badge-down { display:inline-block; background:rgba(74,222,128,.2);  color:#4ade80;
              border-radius:999px; padding:2px 10px; font-size:.8rem; font-weight:700; }
.badge-high { display:inline-block; background:rgba(248,113,113,.15); color:#f87171;
              border:1px solid rgba(248,113,113,.4);
              border-radius:999px; padding:3px 14px; font-size:.8rem; font-weight:700; margin:2px; }
.badge-med  { display:inline-block; background:rgba(251,191,36,.15); color:#fbbf24;
              border:1px solid rgba(251,191,36,.4);
              border-radius:999px; padding:3px 14px; font-size:.8rem; font-weight:700; margin:2px; }
.badge-low  { display:inline-block; background:rgba(74,222,128,.15); color:#4ade80;
              border:1px solid rgba(74,222,128,.4);
              border-radius:999px; padding:3px 14px; font-size:.8rem; font-weight:700; margin:2px; }

/* テキストボックス */
.reason-box {
    background:rgba(99,102,241,.08); border:1px solid rgba(99,102,241,.3);
    border-radius:10px; padding:12px 16px; font-size:.9rem;
    color:#c4b5fd; margin:6px 0;
}

/* カルテカード */
.karte-card {
    background: rgba(30,27,75,.6);
    border: 1px solid rgba(99,102,241,.4);
    border-radius: 16px; padding: 24px; margin: 8px 0;
    backdrop-filter: blur(8px);
    box-shadow: 0 0 24px rgba(99,102,241,.12);
}
hr { border-color: #1e293b; }
</style>
""", unsafe_allow_html=True)

# ─── データ取得 ───────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_inventory() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM inventory", conn)
    conn.close()
    return df

@st.cache_data(ttl=60)
def load_history() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT h.inventory_id, i.name, i.total_stock, i.base_price,
               i.departure_date,
               h.recorded_at, h.remaining_stock, h.dynamic_price, h.lead_days
        FROM price_history h
        JOIN inventory i ON h.inventory_id = i.id
        ORDER BY h.recorded_at ASC
    """, conn)
    conn.close()
    if not df.empty:
        df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
        df["recorded_at"] = df["recorded_at"].dt.tz_convert("Asia/Tokyo")
    return df

def get_pricing_results(inv_df: pd.DataFrame) -> list[dict]:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from pricing_engine import calculate_pricing_result
    results = []
    for _, row in inv_df.iterrows():
        r = calculate_pricing_result(
            inventory_id    = int(row["id"]),
            name            = row["name"],
            base_price      = int(row["base_price"]),
            total_stock     = int(row["total_stock"]),
            remaining_stock = int(row["remaining_stock"]),
            departure_date  = row.get("departure_date"),
        )
        results.append(r)
    return results

# ─── Plotly 共通スタイル ──────────────────────────────────────────
PLOT_BG    = "#0d0d1a"
PAPER_BG   = "#0d0d1a"
FONT_COLOR = "#94a3b8"
GRID_COLOR = "#1e293b"
COLORS     = ["#a78bfa","#f472b6","#34d399","#fbbf24","#60a5fa","#fb923c","#38bdf8","#a3e635"]

def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB 形式のヘックスカラーを rgba(r, g, b, a) 形式に変換する"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    return hex_color

def dark_layout(fig: go.Figure, title: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(color="#c4b5fd", size=15)),
        paper_bgcolor=PAPER_BG, plot_bgcolor=PLOT_BG,
        font=dict(color=FONT_COLOR, family="Inter"),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_COLOR,
                    font=dict(color=FONT_COLOR)),
        xaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        yaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        margin=dict(l=16, r=16, t=48, b=16),
        hovermode="x unified",
    )
    return fig

# ─── ヘッダー ──────────────────────────────────────────────────────
st.markdown("""
<h1>🔍 Explainable Pricing Dashboard</h1>
<p style='color:#64748b; margin-top:-12px; margin-bottom:20px;'>
  価格の根拠を可視化し、アルゴリズムのブラックボックス化を防ぐ —
  <span style='color:#a78bfa'>White-box Pricing Engine</span>
</p>
""", unsafe_allow_html=True)

# ─── データロード ─────────────────────────────────────────────────
inv_df     = load_inventory()
history_df = load_history()

if inv_df.empty:
    st.error("⚠️ 在庫データが見つかりません。`python init_db.py` を先に実行してください。")
    st.stop()

results = get_pricing_results(inv_df)

# ─── パッケージエンジン読み込み（全タブ共通） ─────────────────────
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from packaging_engine import (
        generate_packages, get_velocity_ratio, calc_velocity_adjustment,
        hotel_urgency_score,
    )
    packages = generate_packages()
except Exception as _e:
    packages = []
    _pkg_err = str(_e)

# ─── 3タブ ────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "🏠  ライブ概況",
    "🔍  価格の内訳分析",
    "🃏  商品カルテ",
])


# ══════════════════════════════════════════════════════════════════
# Tab 1: ライブ概況
# ══════════════════════════════════════════════════════════════════
with tab1:
    # ── KPI カード ────────────────────────────────────────────────
    st.markdown("### 📦 現在の在庫 & 動的価格")
    n_cols = min(len(results), 4)
    col_groups = [results[i:i+n_cols] for i in range(0, len(results), n_cols)]
    for group in col_groups:
        cols = st.columns(len(group))
        for ci, r in enumerate(group):
            idx = results.index(r)
            diff        = r["final_price"] - r["base_price"]
            badge_class = "badge-up" if diff >= 0 else "badge-down"
            badge_text  = f"↑ ¥{diff:,}" if diff >= 0 else f"↓ ¥{abs(diff):,}"
            lead_str    = f"{r['lead_days']}日後" if r["lead_days"] is not None else "未設定"
            ratio_pct   = int(r["inv_ratio"] * 100)
            row_item    = inv_df.iloc[idx]
            with cols[ci]:
                st.markdown(f"""
<div class="metric-card">
  <div class="metric-label">{row_item['item_type'].upper()} #{r['inventory_id']}</div>
  <div class="metric-sub">{r['name']}</div>
  <div class="metric-value">¥{r['final_price']:,}</div>
  <div><span class="{badge_class}">{badge_text}</span></div>
  <div class="metric-sub" style="margin-top:8px">
    残在庫 {row_item['remaining_stock']}/{row_item['total_stock']} ({ratio_pct}%)<br>
    出発まで <b>{lead_str}</b>
  </div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── パッケージ推奨 ─────────────────────────────────────────────
    st.markdown("### 🎁 クロスセル パッケージ推奨")
    st.markdown("<p style='color:#64748b;font-size:.9rem'>「売り逃しリスクの高いホテル」×「人気フライト」を組み合わせて全体収益を最大化</p>",
                unsafe_allow_html=True)

    if packages:
        pkg_rows = []
        for pkg in packages:
            disc_str = f"-¥{abs(pkg['bundle_discount']):,}" if pkg["bundle_discount"] < 0 else "¥0"
            saving   = pkg["sum_dynamic_price"] - pkg["final_package_price"]
            pkg_rows.append({
                "Rank":         f"🏅 {pkg['rank']}",
                "フライト":     pkg["flight_name"],
                "ホテル":       pkg["hotel_name"],
                "単純合計":     f"¥{pkg['sum_dynamic_price']:,}",
                "割引":         disc_str,
                "最終価格":     f"¥{pkg['final_package_price']:,}",
                "お得額":       f"¥{saving:,}",
                "戦略スコア":   f"{pkg['strategy_score']:.2f}",
            })
        st.dataframe(pd.DataFrame(pkg_rows), use_container_width=True, hide_index=True)

        best = packages[0]
        st.markdown(f"#### 🥇 最優先推奨: {best['flight_name']} ＋ {best['hotel_name']}")
        st.markdown(f'<div class="reason-box">{best["reason"]}</div>', unsafe_allow_html=True)
    else:
        st.info("パッケージデータが取得できませんでした。")

    st.markdown("---")

    # ── 販売速度 ──────────────────────────────────────────────────
    st.markdown("### ⚡ 販売ペース指標（Velocity-based Pricing）")
    st.markdown("<p style='color:#64748b;font-size:.9rem'>直近24hの実際の予約ペース vs 期待ペース</p>",
                unsafe_allow_html=True)
    try:
        vel_rows = []
        for _, item in inv_df.iterrows():
            r = next((x for x in results if x["inventory_id"] == item["id"]), None)
            if r is None:
                continue
            vr = get_velocity_ratio(int(item["id"]), int(item["total_stock"]),
                                    int(item["remaining_stock"]), r["lead_days"])
            adj, note = calc_velocity_adjustment(r["final_price"], vr)
            if vr is None:    sig = "⚪ データなし"
            elif vr >= 2.0:   sig = f"🔴 強く値上げ（×{vr:.1f}）"
            elif vr >= 1.5:   sig = f"🟠 緩く値上げ（×{vr:.1f}）"
            elif vr >= 0.7:   sig = f"🟢 想定内（×{vr:.1f}）"
            else:             sig = f"🔵 鈍化（×{vr:.1f}）"
            adj_str = f"+¥{adj:,}" if adj > 0 else (f"-¥{abs(adj):,}" if adj < 0 else "±¥0")
            vel_rows.append({"商品名": item["name"], "種別": item["item_type"],
                             "velocity_ratio": f"{vr:.2f}" if vr else "N/A",
                             "シグナル": sig, "価格調整額": adj_str})

        if vel_rows:
            st.dataframe(pd.DataFrame(vel_rows), use_container_width=True, hide_index=True)
            vr_vals  = [float(r["velocity_ratio"]) if r["velocity_ratio"] != "N/A" else 0.0
                        for r in vel_rows]
            vr_names = [r["商品名"] for r in vel_rows]
            vr_clrs  = ["#f87171" if v>=2.0 else "#fb923c" if v>=1.5 else "#4ade80" if v>=0.7
                        else "#60a5fa" for v in vr_vals]
            fig_vel = go.Figure(go.Bar(x=vr_names, y=vr_vals, marker_color=vr_clrs,
                                       text=[f"×{v:.2f}" for v in vr_vals],
                                       textposition="outside",
                                       textfont=dict(color="#e2e8f0")))
            fig_vel.add_hline(y=1.0, line_dash="dash", line_color="#a78bfa",
                              annotation_text="想定ペース ×1.0", annotation_position="top right",
                              annotation_font_color="#a78bfa")
            fig_vel.add_hline(y=1.5, line_dash="dot", line_color="#fb923c",
                              annotation_text="値上げ閾値 ×1.5", annotation_position="top right",
                              annotation_font_color="#fb923c")
            dark_layout(fig_vel, "販売速度比率（velocity_ratio）")
            fig_vel.update_yaxes(rangemode="tozero", title="velocity_ratio")
            st.plotly_chart(fig_vel, use_container_width=True)
    except Exception as e:
        st.warning(f"⚠️ Velocity データ取得失敗: {e}")

    # ── 価格/在庫 時系列（既存）────────────────────────────────────
    if not history_df.empty:
        st.markdown("---")
        st.markdown("### 📈 価格推移（時系列）")
        fig_p = go.Figure()
        for idx, name in enumerate(history_df["name"].unique()):
            sub = history_df[history_df["name"] == name]
            c = COLORS[idx % len(COLORS)]
            fig_p.add_trace(go.Scatter(
                x=sub["recorded_at"], y=sub["dynamic_price"], name=name,
                mode="lines+markers", line=dict(color=c, width=2.5), marker=dict(size=5),
                hovertemplate=f"<b>{name}</b><br>%{{x|%H:%M}}<br>¥%{{y:,}}<extra></extra>",
            ))
        dark_layout(fig_p, "動的価格の推移")
        fig_p.update_yaxes(tickprefix="¥", tickformat=",")
        st.plotly_chart(fig_p, use_container_width=True)

    st.markdown("---")
    last_upd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.markdown(f'<p style="color:#475569;text-align:right;font-size:.8rem">最終更新: {last_upd}</p>',
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# Tab 2: 価格の内訳分析
# ══════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 🌊 単品 価格内訳ウォーターフォール")
    st.markdown("<p style='color:#64748b;font-size:.9rem'>原価から各調整額がどのように積み上がって最終価格になるかを可視化</p>",
                unsafe_allow_html=True)

    # ── 単品: 5ステップ ────────────────────────────────────────────
    # velocity 調整込みで5ステップにする
    item_names = [r["name"] for r in results]
    selected_item = st.selectbox("🔎 商品を選択", item_names, key="tab2_single")
    r_sel = next(r for r in results if r["name"] == selected_item)
    inv_sel = inv_df[inv_df["name"] == selected_item].iloc[0]

    # velocity 調整額を取得
    try:
        vr_sel = get_velocity_ratio(int(inv_sel["id"]), int(inv_sel["total_stock"]),
                                    int(inv_sel["remaining_stock"]), r_sel["lead_days"])
        vel_adj_sel, vel_note_sel = calc_velocity_adjustment(r_sel["final_price"], vr_sel)
    except Exception:
        vr_sel, vel_adj_sel, vel_note_sel = None, 0, "取得不可"

    # 最終価格をvelocity込みで再計算
    final_with_vel = r_sel["final_price"] + vel_adj_sel

    wf_labels   = ["基本価格", "在庫調整", "時期調整", "Velocity調整", "最終価格"]
    wf_measures = ["absolute", "relative", "relative", "relative", "total"]
    wf_values   = [
        r_sel["base_price"],
        r_sel["inventory_adjustment"],
        r_sel["time_adjustment"],
        vel_adj_sel,
        final_with_vel,
    ]

    def fmt_wf(v, measure):
        if measure == "absolute": return f"¥{v:,}"
        if measure == "total":    return f"¥{v:,}"
        sign = "+" if v >= 0 else ""
        return f"{sign}¥{v:,}"

    fig_single_wf = go.Figure(go.Waterfall(
        orientation="v",
        measure=wf_measures,
        x=wf_labels,
        y=wf_values,
        connector=dict(line=dict(color="#4338ca", width=1.5, dash="dot")),
        increasing=dict(marker=dict(color="#f87171", line=dict(color="#ef4444", width=1))),
        decreasing=dict(marker=dict(color="#4ade80", line=dict(color="#22c55e", width=1))),
        totals=dict(marker=dict(color="#a78bfa", line=dict(color="#7c3aed", width=1))),
        text=[fmt_wf(v, m) for v, m in zip(wf_values, wf_measures)],
        textposition="outside",
        textfont=dict(color="#e2e8f0", size=14, family="Inter"),
    ))
    dark_layout(fig_single_wf, f"{selected_item} — 価格構成の内訳（5ステップ）")
    fig_single_wf.update_yaxes(tickprefix="¥", tickformat=",", title="価格（円）")
    fig_single_wf.update_layout(height=430)
    st.plotly_chart(fig_single_wf, use_container_width=True)

    # 根拠テキスト
    vel_txt = f"【Velocity調整】{vel_note_sel}（{'+' if vel_adj_sel>=0 else ''}¥{vel_adj_sel:,}）"
    st.markdown(f'<div class="reason-box"><b>{selected_item}</b><br>{r_sel["reason"]}<br>{vel_txt}</div>',
                unsafe_allow_html=True)

    # ── 明細テーブル ──────────────────────────────────────────────
    detail_data = [
        {"要素": "🏷 基本価格",     "金額": f"¥{r_sel['base_price']:,}",             "種別": "—"},
        {"要素": "📦 在庫調整",     "金額": fmt_wf(r_sel['inventory_adjustment'],'relative'), "種別": "relative"},
        {"要素": "⏱ 時期調整",     "金額": fmt_wf(r_sel['time_adjustment'],'relative'),      "種別": "relative"},
        {"要素": "⚡ Velocity調整", "金額": fmt_wf(vel_adj_sel,'relative'),                   "種別": "relative"},
        {"要素": "✅ 最終価格",     "金額": f"¥{final_with_vel:,}",                           "種別": "total"},
    ]
    st.dataframe(pd.DataFrame(detail_data), use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── パッケージ: 7ステップ ─────────────────────────────────────
    st.markdown("### 📦 パッケージ 価格内訳ウォーターフォール")
    st.markdown("<p style='color:#64748b;font-size:.9rem'>フライト＋ホテルの各調整とクロスセル割引が最終パッケージ価格に与える影響</p>",
                unsafe_allow_html=True)

    if packages:
        pkg_opts = [f"Rank {p['rank']}: {p['flight_name']} ＋ {p['hotel_name']}" for p in packages]
        selected_pkg_label = st.selectbox("📦 パッケージを選択", pkg_opts, key="tab2_pkg")
        sel_rank = int(selected_pkg_label.split(":")[0].replace("Rank", "").strip())
        pkg = next(p for p in packages if p["rank"] == sel_rank)

        f_adj_total = pkg["flight_velocity_adjustment"]
        h_adj_total = pkg["hotel_velocity_adjustment"]

        pkg_labels   = ["フライト原価", "フライト調整", "ホテル原価", "ホテル調整",
                        "小計", "クロスセル割引", "最終価格"]
        pkg_measures = ["absolute", "relative", "absolute", "relative",
                        "total", "relative", "total"]
        # 小計のtotal値 = フライト調整後 + ホテル調整後
        f_adjusted = pkg["flight_dynamic_price"] + f_adj_total
        h_adjusted = pkg["hotel_dynamic_price"]  + h_adj_total
        subtotal   = f_adjusted + h_adjusted

        pkg_values = [
            pkg["flight_dynamic_price"],
            f_adj_total,
            pkg["hotel_dynamic_price"],
            h_adj_total,
            subtotal,
            pkg["bundle_discount"],
            pkg["final_package_price"],
        ]

        fig_pkg_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=pkg_measures,
            x=pkg_labels,
            y=pkg_values,
            connector=dict(line=dict(color="#4338ca", width=1.5, dash="dot")),
            increasing=dict(marker=dict(color="#f87171", line=dict(color="#ef4444", width=1))),
            decreasing=dict(marker=dict(color="#4ade80", line=dict(color="#22c55e", width=1))),
            totals=dict(marker=dict(color="#a78bfa", line=dict(color="#7c3aed", width=1))),
            text=[fmt_wf(v, m) for v, m in zip(pkg_values, pkg_measures)],
            textposition="outside",
            textfont=dict(color="#e2e8f0", size=13, family="Inter"),
        ))
        dark_layout(fig_pkg_wf, f"パッケージ価格の内訳（7ステップ）— Rank {sel_rank}")
        fig_pkg_wf.update_yaxes(tickprefix="¥", tickformat=",", title="価格（円）")
        fig_pkg_wf.update_layout(height=430)
        st.plotly_chart(fig_pkg_wf, use_container_width=True)
        st.markdown(f'<div class="reason-box">{pkg["reason"]}</div>', unsafe_allow_html=True)

        # パッケージ明細テーブル
        saving = pkg["sum_dynamic_price"] - pkg["final_package_price"]
        pkg_detail = [
            {"要素": f"✈ フライト動的価格 ({pkg['flight_name']})", "金額": f"¥{pkg['flight_dynamic_price']:,}"},
            {"要素": "  └ Velocity調整",                          "金額": fmt_wf(f_adj_total,'relative')},
            {"要素": f"🏨 ホテル動的価格 ({pkg['hotel_name']})",   "金額": f"¥{pkg['hotel_dynamic_price']:,}"},
            {"要素": "  └ Velocity調整",                          "金額": fmt_wf(h_adj_total,'relative')},
            {"要素": "📊 小計（velocity込み）",                    "金額": f"¥{subtotal:,}"},
            {"要素": "🎁 クロスセル割引",                          "金額": fmt_wf(pkg['bundle_discount'],'relative')},
            {"要素": "✅ パッケージ最終価格",                      "金額": f"¥{pkg['final_package_price']:,}"},
            {"要素": "💰 お得額",                                  "金額": f"-¥{saving:,}"},
        ]
        st.dataframe(pd.DataFrame(pkg_detail), use_container_width=True, hide_index=True)
    else:
        st.info("パッケージデータがありません。")


# ══════════════════════════════════════════════════════════════════
# Tab 3: 商品カルテ
# ══════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🃏 商品カルテ — 価格特性プロファイル")
    st.markdown("<p style='color:#64748b;font-size:.9rem'>5軸レーダーチャートで商品の「性格」を一目で把握。バッジで高/中/低を評価。</p>",
                unsafe_allow_html=True)

    # 商品選択（ラジオボタン横並び）
    karte_names = [r["name"] for r in results]
    selected_karte = st.radio("商品を選択", karte_names, horizontal=True, key="tab3_item")
    r_k   = next(r for r in results if r["name"] == selected_karte)
    inv_k = inv_df[inv_df["name"] == selected_karte].iloc[0]

    # ── 5軸の特性スコア計算 ──────────────────────────────────────
    inv_urgency   = 1.0 - r_k["inv_ratio"]                             # 在庫切迫度
    time_urgency  = max(0.0, 1.0 - (r_k["lead_days"] or 90) / 60.0)   # 時間切迫度
    price_elast   = abs(r_k["final_price"] - r_k["base_price"]) / r_k["base_price"] if r_k["base_price"] > 0 else 0.0
    price_elast   = min(price_elast, 1.0)

    try:
        vr_k = get_velocity_ratio(int(inv_k["id"]), int(inv_k["total_stock"]),
                                  int(inv_k["remaining_stock"]), r_k["lead_days"])
        vel_score = min((vr_k or 0.0) / 3.0, 1.0)
    except Exception:
        vr_k, vel_score = None, 0.0

    # バンドル適性 (ホテルのみ urgency_score; フライトは inv_urgency を代用)
    try:
        bundle_score = hotel_urgency_score(
            int(inv_k["remaining_stock"]), int(inv_k["total_stock"]), r_k["lead_days"]
        )
    except Exception:
        bundle_score = inv_urgency * 0.6 + time_urgency * 0.4

    radar_labels = ["在庫切迫度", "時間切迫度", "販売速度", "価格弾力性", "バンドル適性"]
    radar_scores = [inv_urgency, time_urgency, vel_score, price_elast, bundle_score]

    # ── バッジ判定 ────────────────────────────────────────────────
    def badge(label: str, score: float, thres_h: float, thres_m: float) -> str:
        pct = int(score * 100)
        if score >= thres_h:
            return f'<span class="badge-high">{label}: HIGH ({pct}%)</span>'
        elif score >= thres_m:
            return f'<span class="badge-med">{label}: MEDIUM ({pct}%)</span>'
        else:
            return f'<span class="badge-low">{label}: LOW ({pct}%)</span>'

    badges_html = (
        badge("在庫切迫度", inv_urgency,  0.70, 0.30) +
        badge("時間切迫度", time_urgency, 0.70, 0.30) +
        badge("販売速度",   vel_score,    0.67, 0.23) +  # ratio 2.0/3=0.67, 0.7/3=0.23
        badge("価格弾力性", price_elast,  0.15, 0.05) +
        badge("バンドル適性", bundle_score, 0.70, 0.30)
    )

    # ── 2カラムレイアウト ─────────────────────────────────────────
    col_radar, col_info = st.columns([1.3, 1], gap="large")

    with col_radar:
        # レーダーチャート
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=radar_scores + [radar_scores[0]],
            theta=radar_labels + [radar_labels[0]],
            fill="toself",
            fillcolor="rgba(167,139,250,0.18)",
            line=dict(color="#a78bfa", width=2.5),
            name=selected_karte,
            hovertemplate="%{theta}: %{r:.0%}<extra></extra>",
        ))
        fig_radar.update_layout(
            polar=dict(
                bgcolor="#0d0d1a",
                radialaxis=dict(visible=True, range=[0, 1], tickformat=".0%",
                                gridcolor="#1e293b", tickfont=dict(color="#475569", size=10)),
                angularaxis=dict(gridcolor="#1e293b", tickfont=dict(color="#94a3b8", size=12)),
            ),
            paper_bgcolor=PAPER_BG,
            font=dict(color=FONT_COLOR, family="Inter"),
            showlegend=False,
            title=dict(text=f"{selected_karte}", font=dict(color="#c4b5fd", size=13)),
            margin=dict(l=40, r=40, t=60, b=40),
            height=380,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    with col_info:
        st.markdown(f'<div class="karte-card">', unsafe_allow_html=True)

        # 商品種別タグ
        item_type_badge = (
            '<span style="background:rgba(96,165,250,.15);color:#60a5fa;border:1px solid rgba(96,165,250,.4);'
            'border-radius:999px;padding:2px 10px;font-size:.75rem;font-weight:700;">✈ FLIGHT</span>'
            if inv_k["item_type"] == "flight" else
            '<span style="background:rgba(52,211,153,.15);color:#34d399;border:1px solid rgba(52,211,153,.4);'
            'border-radius:999px;padding:2px 10px;font-size:.75rem;font-weight:700;">🏨 HOTEL</span>'
        )
        dep_str = inv_k.get("departure_date", "—") or "—"
        lead_display = f"{r_k['lead_days']}日後" if r_k["lead_days"] is not None else "未設定"

        st.markdown(f"""
<div style='margin-bottom:16px'>
  {item_type_badge}
  <span style='color:#94a3b8; font-size:.85rem; margin-left:8px'>出発: {dep_str}（{lead_display}）</span>
</div>
<div style='font-size:1.1rem;font-weight:700;color:#e2e8f0;margin-bottom:8px'>{selected_karte}</div>
<div style='margin-bottom:16px'>{badges_html}</div>
""", unsafe_allow_html=True)

        # 数値サマリーテーブル
        summary_rows = [
            {"項目": "🏷 基本価格",     "値": f"¥{r_k['base_price']:,}"},
            {"項目": "📦 在庫調整額",   "値": f"{'+' if r_k['inventory_adjustment']>=0 else ''}¥{r_k['inventory_adjustment']:,}"},
            {"項目": "⏱ 時期調整額",   "値": f"{'+' if r_k['time_adjustment']>=0 else ''}¥{r_k['time_adjustment']:,}"},
            {"項目": "✅ 最終価格",     "値": f"¥{r_k['final_price']:,}"},
            {"項目": "📊 残在庫率",     "値": f"{int(r_k['inv_ratio']*100)}%  ({inv_k['remaining_stock']}/{inv_k['total_stock']})"},
            {"項目": "⚡ Velocity",    "値": f"×{vr_k:.2f}" if vr_k else "データなし"},
        ]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # 理由テキスト
    st.markdown(f'<div class="reason-box" style="margin-top:12px"><b>💬 算出根拠</b><br>{r_k["reason"]}</div>',
                unsafe_allow_html=True)

    # ── 全商品比較レーダー ────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📊 全商品 特性スコア比較")

    def compute_scores(r: dict, inv_row) -> list[float]:
        i_urg  = 1.0 - r["inv_ratio"]
        t_urg  = max(0.0, 1.0 - (r["lead_days"] or 90) / 60.0)
        p_el   = min(abs(r["final_price"] - r["base_price"]) / r["base_price"], 1.0) if r["base_price"] > 0 else 0.0
        try:
            vr_ = get_velocity_ratio(int(inv_row["id"]), int(inv_row["total_stock"]),
                                     int(inv_row["remaining_stock"]), r["lead_days"])
            v_sc = min((vr_ or 0.0) / 3.0, 1.0)
        except Exception:
            v_sc = 0.0
        try:
            b_sc = hotel_urgency_score(int(inv_row["remaining_stock"]),
                                       int(inv_row["total_stock"]), r["lead_days"])
        except Exception:
            b_sc = i_urg * 0.6 + t_urg * 0.4
        return [i_urg, t_urg, v_sc, p_el, b_sc]

    fig_all = go.Figure()
    for idx, r_a in enumerate(results):
        inv_a  = inv_df[inv_df["name"] == r_a["name"]].iloc[0]
        scores = compute_scores(r_a, inv_a)
        c = COLORS[idx % len(COLORS)]
        fig_all.add_trace(go.Scatterpolar(
            r=scores + [scores[0]],
            theta=radar_labels + [radar_labels[0]],
            fill="toself",
            fillcolor=hex_to_rgba(c, 0.07) if c.startswith("#") else c,
            line=dict(color=c, width=1.8),
            name=r_a["name"],
            hovertemplate="%{theta}: %{r:.0%}<extra>" + r_a["name"] + "</extra>",
        ))
    fig_all.update_layout(
        polar=dict(
            bgcolor="#0d0d1a",
            radialaxis=dict(visible=True, range=[0, 1], tickformat=".0%",
                            gridcolor="#1e293b", tickfont=dict(color="#475569", size=9)),
            angularaxis=dict(gridcolor="#1e293b", tickfont=dict(color="#94a3b8", size=11)),
        ),
        paper_bgcolor=PAPER_BG,
        font=dict(color=FONT_COLOR, family="Inter"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8", size=11)),
        title=dict(text="全商品 特性スコア比較", font=dict(color="#c4b5fd", size=14)),
        margin=dict(l=40, r=40, t=60, b=40),
        height=450,
    )
    st.plotly_chart(fig_all, use_container_width=True)
