import re

file_path = "backend/dashboard/app.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Sidebar slicer removal
slicer_code = """    # ─── 過去の実績スライサー追加 ───
    st.markdown("---")
    st.markdown("### 🗓️ 販売実績期間フィルタ")
    st.caption("ROI・売上推移グラフの集計対象期間")
    
    # booking_events の最小・最大日付を概算で取得
    min_date_val = datetime.now(timezone.utc).date() - timedelta(days=180) # デフォルト安全値
    max_date_val = datetime.now(timezone.utc).date()
    # 実際はクエリで最小値をとるのが正確ですが、デモでは固定範囲でUI提供します
    
    selected_hist_dates = st.date_input(
        "集計対象期間を選択",
        value=(min_date_val, max_date_val),
        help="この期間内に発生した予約データのみがROIグラフの対象になります。"
    )

    if isinstance(selected_hist_dates, tuple) and len(selected_hist_dates) == 2:
        hist_start, hist_end = selected_hist_dates
    elif isinstance(selected_hist_dates, tuple) and len(selected_hist_dates) == 1:
        hist_start = hist_end = selected_hist_dates[0]
    else:
        hist_start, hist_end = min_date_val, max_date_val"""
content = content.replace(slicer_code, "")

# 2. Tabs rename
content = content.replace('"🎯 本日のアクション",', '"🎯 Today\'s Action",')

# 3. Extract the two chunks:
# Chunk A: with tab2: (Lines ~258 to ~364)
# Chunk B: with tab1: (Lines ~366 to ~507)
# We will just split by "# ══════════════════════════════════════════════════════════════════"

sections = content.split("# ══════════════════════════════════════════════════════════════════")
# Section map:
# sections[0] -> before tabs
# sections[1] -> Tab 2 header
# sections[2] -> Tab 2 content
# sections[3] -> Tab 1 header
# sections[4] -> Tab 1 content
# sections[5] -> Tab 3 header ...

# Wait, let's just use regex to accurately find the blocks
tab2_pattern = re.compile(r"(# ══════════════════════════════════════════════════════════════════\n# Tab 2: 【アクション】本日のアクション \(Action\)\n# ══════════════════════════════════════════════════════════════════\nwith tab2:.*?)(?=# ══════════════════════════════════════════════════════════════════\n# Tab 1)", re.DOTALL)
tab1_pattern = re.compile(r"(# ══════════════════════════════════════════════════════════════════\n# Tab 1: 【観察】エグゼクティブ・サマリ \(Observe\)\n# ══════════════════════════════════════════════════════════════════\nwith tab1:.*?)(?=# ══════════════════════════════════════════════════════════════════\n# Tab 3)", re.DOTALL)

tab2_match = tab2_pattern.search(content)
tab1_match = tab1_pattern.search(content)

if not tab2_match or not tab1_match:
    print("Failed to match tabs")
    exit(1)

tab2_code = tab2_match.group(1)
tab1_code = tab1_match.group(1)

# Modify tab1_code: inject slicer at the beginning, calculate roi_metrics.
# Then remove the roi_metrics calculation and KPI cards from the bottom of tab1, because we move them to tab2!
# But wait, roi_metrics is calculated at the bottom of tab1 and used by the chart. We should keep the calculation in tab1 (after the slicer) so both tabs can use it.
roi_metric_calc_str = """    roi_metrics = calculate_roi_metrics(
        inventory_ids=target_ids,
        target_start_date=hist_start.isoformat(),
        target_end_date=hist_end.isoformat()
    )"""

kpi_cards_str = """    # ROI KPI
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f\"\"\"
        <div class="metric-card-roi">
            <div class="metric-label">合計純利益リフト</div>
            <div class="roi-value">+¥{roi_metrics['lift']:,}</div>
            <div class="metric-sub">固定価格比 <b>+{roi_metrics['lift_pct']:.1f}%</b></div>
        </div>
        \"\"\", unsafe_allow_html=True)
    with c2:
        st.markdown(f\"\"\"
        <div class="metric-card-roi">
            <div class="metric-label">回避した廃棄損失額</div>
            <div class="roi-value" style="color:#38bdf8;">+¥{roi_metrics.get('avoided_waste_loss', 0):,}</div>
            <div class="metric-sub">値引き/パッケージによる救済額</div>
        </div>
        \"\"\", unsafe_allow_html=True)
    with c3:
        st.markdown(f\"\"\"
        <div class="metric-card-roi">
            <div class="metric-label">値上げによる純増益</div>
            <div class="roi-value" style="color:#f472b6;">+¥{roi_metrics.get('surge_profit', 0):,}</div>
            <div class="metric-sub">需要高騰時の自動価格調整効果</div>
        </div>
        \"\"\", unsafe_allow_html=True)

    st.markdown("---")"""

# Remove from tab1_code
tab1_code = tab1_code.replace(roi_metric_calc_str, "")
tab1_code = tab1_code.replace(kpi_cards_str, "")
# Remove the old header for ROI summary in dict
tab1_code = tab1_code.replace('st.markdown("### 💰 導入効果・ROIサマリ (純利益ベース)")', '')
tab1_code = tab1_code.replace('# =========================================================\n    # 💰 7. 導入効果・ROIサマリ (純利益ベース) + 在庫救済状況\n    # =========================================================\n    st.markdown("---")', '')

# Inject Slicer and calculation at the top of tab1_code
slicer_injection = f"""    {slicer_code.strip()}

{roi_metric_calc_str}
"""
tab1_code = tab1_code.replace("with tab1:\n", "with tab1:\n" + slicer_injection + "\n")

# Inject KPI cards into tab2_code
new_tab2_header = """# ══════════════════════════════════════════════════════════════════
# Tab 2: 【アクション】Today's Action
# ══════════════════════════════════════════════════════════════════
with tab2:"""

tab2_code = tab2_code.replace("""# ══════════════════════════════════════════════════════════════════
# Tab 2: 【アクション】本日のアクション (Action)
# ══════════════════════════════════════════════════════════════════
with tab2:""", new_tab2_header)

# Create highly visible cards
highlighted_kpi = f"""
    st.markdown(\"\"\"
    <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%); border:1px solid rgba(56,189,248,0.4); border-radius:20px; padding:24px; margin-top:20px; margin-bottom:20px; box-shadow:0 0 30px rgba(56,189,248,0.15);">
        <div style="font-size:1.1rem; color:#bae6fd; font-weight:800; letter-spacing:0.1em; margin-bottom:12px;">
            ✨ これまでのAI導入効果・ROIサマリ (純利益ベース)
        </div>
        <div style="font-size:0.8rem; color:#94a3b8; margin-bottom:16px;">設定した「販売実績期間」内での実績を示します。</div>
    \"\"\", unsafe_allow_html=True)
{kpi_cards_str.replace('    st.markdown("---")', '')}
    st.markdown("</div>", unsafe_allow_html=True)
"""
# Insert after render_alerts, which is around line 262
tab2_code = tab2_code.replace("render_alerts(results, filtered_inv_df, [], get_velocity_ratio)\n", "render_alerts(results, filtered_inv_df, [], get_velocity_ratio)\n" + highlighted_kpi + "\n")


# 4. Tab 3 modifications: move table down
tab3_pattern = re.compile(r"(# ══════════════════════════════════════════════════════════════════\n# Tab 3: Analysis & Tracking \(旧ドリルダウン \+ ライブ動向\)\n# ══════════════════════════════════════════════════════════════════\nwith tab3:.*?)(?=# 🪟 Tab 4: Strategy Map)", re.DOTALL)
tab3_match = tab3_pattern.search(content)

tab3_code = tab3_match.group(1)

table_render_code = """    st.dataframe(table_df, use_container_width=True, hide_index=True)
    st.markdown("---")"""
tab3_code = tab3_code.replace(table_render_code, '    st.markdown("---")')

tab3_code = tab3_code.replace('st.markdown("#### 🚚 商品一覧 & 異常検知")', 'st.markdown("#### 🎯 対象商品の詳細分析")')

# Append table code to bottom
table_bottom_code = """
    st.markdown("---")
    st.markdown("#### 🚚 商品一覧 & 異常検知")
    st.dataframe(table_df, use_container_width=True, hide_index=True)
"""
tab3_code = tab3_code.rstrip() + table_bottom_code + "\n"

# Replace all chunks in main content!
# Note that we are SWAPPING tab1 and tab2 physically!
# So we replace the combined chunk of tab2+tab1 with tab1+tab2_modified
original_combined = content[tab2_match.start(1):tab1_match.end(1)]
new_combined = tab1_code + tab2_code

content = content.replace(original_combined, new_combined)
content = content.replace(tab3_match.group(1), tab3_code)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Modification complete!")
