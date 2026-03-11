import os

with open('dashboard/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if "### 🏷️ Section 0: 商品分類マスタ設定" in line:
        start_idx = i - 1
    elif 'st.success(f"{save_cat} に {save_strat} と現在のパラメータを保存しました！")' in line:
        end_idx = i

if start_idx != -1 and end_idx != -1:
    new_code = """    # === Section 0: 商品分類マスタ設定 ===
    st.markdown("### 🏷️ Section 0: 商品分類マスタ設定")
    st.write("各商品を「ホテル/フライト」×「大人気/安定/ニッチ」のマトリクスに分類します。ここでの設定はすべての推論のベースとなります。")

    # nameとitem_typeの組み合わせで重複排除
    unique_products_df = bt_inv_df.drop_duplicates(subset=["name", "item_type"])

    # 現在の分類をロード
    cls_records = []
    for _, row in unique_products_df.iterrows():
        it_type = row["item_type"]
        p_name = row["name"]
        c_data = get_product_classification(p_name, it_type)
        if c_data:
            char = c_data["characteristic"]
            src = c_data["source"]
        else:
            char = "stable" # デフォルト
            src = "auto"
        cls_records.append({
            "商品種別": it_type,
            "商品名": p_name,
            "特性 (クリックで変更)": char,
            "設定元": src
        })
    cls_df = pd.DataFrame(cls_records)

    edited_cls_df = st.data_editor(
        cls_df,
        column_config={
            "特性 (クリックで変更)": st.column_config.SelectboxColumn(
                "特性", help="商品の販売特性", options=["popular", "stable", "niche"], required=True
            ),
            "商品種別": st.column_config.TextColumn(disabled=True),
            "商品名": st.column_config.TextColumn(disabled=True),
            "設定元": st.column_config.TextColumn(disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        key="cls_editor"
    )

    if st.button("💾 分類マスタを保存", type="primary"):
        with st.spinner("DBに分類を保存中..."):
            for _, row in edited_cls_df.iterrows():
                save_product_classification(row["商品名"], row["商品種別"], row["特性 (クリックで変更)"], "manual")
        st.success("分類を保存しました！バックテストを実行するには下のシナリオ設定へお進みください。")
        import time
        time.sleep(1)
        st.rerun()

    st.markdown("---")

    # === Section 1: 評価シナリオ設定 ===
    st.markdown("### 🛠️ Section 1: 評価シナリオ・パラメータ設定")
    st.write("特定のカテゴリに対して、複数のアルゴリズムやパラメータを組み合わせた「シナリオ」を定義し、比較テストを行います。")

    cat_options = edited_cls_df["商品種別"] + "---" + edited_cls_df["特性 (クリックで変更)"]
    cat_options = sorted(list(cat_options.unique()))

    if not cat_options:
        st.warning("商品データが存在しません。")
        st.stop()

    target_category = st.selectbox("🎯 バックテスト対象のカテゴリ", cat_options, help="このカテゴリに属する商品群に対して複数のシナリオをテストします。")
    t_item, t_char = target_category.split("---")

    if "eval_scenarios" not in st.session_state:
        st.session_state["eval_scenarios"] = [
            {"id": "A", "name": "現行ルールベース", "strategy": "rule_based", "config": ai_config.copy()},
            {"id": "B", "name": "標準・需要予測", "strategy": "demand_forecast", "config": ai_config.copy()}
        ]

    def add_scenario():
        new_id = chr(65 + len(st.session_state["eval_scenarios"]))
        st.session_state["eval_scenarios"].append({
            "id": new_id, "name": f"シナリオ {new_id}", "strategy": "demand_forecast", "config": ai_config.copy()
        })
    def clear_scenarios():
        st.session_state["eval_scenarios"] = []
        add_scenario()

    sc_col1, sc_col2, _ = st.columns([2, 2, 4])
    sc_col1.button("➕ 新しいシナリオを追加", on_click=add_scenario)
    sc_col2.button("🗑️ シナリオをリセット", on_click=clear_scenarios)

    scenarios = st.session_state["eval_scenarios"]

    # シナリオ入力UI
    for i, sc in enumerate(scenarios):
        with st.expander(f"シナリオ {sc['id']}: {sc['name']} ({'ルールベース' if sc['strategy']=='rule_based' else '需要予測'})", expanded=(i==0)):
            c1, c2 = st.columns(2)
            sc["name"] = c1.text_input("シナリオ名", value=sc["name"], key=f"sc_name_{i}")
            sc["strategy"] = c2.selectbox("アルゴリズム", ["rule_based", "demand_forecast"], 
                                          index=0 if sc["strategy"]=="rule_based" else 1,
                                          format_func=lambda x: "ルールベース" if x=="rule_based" else "需要予測ベース",
                                          key=f"sc_strat_{i}")

            cfg = sc["config"]
            pc1, pc2, pc3, pc4 = st.columns(4)
            if sc["strategy"] == "rule_based":
                rp = pc1.slider("希少割増(%)", 0, 100, int(cfg.get("rare_premium", 1.4)*100-100), 5, key=f"rp_{i}")
                pd = pc2.slider("ピーク割増(%)", 0, 50, int(cfg.get("peak_markup", 1.15)*100-100), 5, key=f"pd_{i}")
                ad = pc3.slider("余裕割引(%)", 0, 50, int(100-cfg.get("abundant_discount", 0.9)*100), 5, key=f"ad_{i}")
                lm = pc4.slider("見切り割引(%)", 0, 50, int(100-cfg.get("last_minute_discount", 0.8)*100), 5, key=f"lm_{i}")
                cfg["rare_premium"] = 1.0 + rp/100
                cfg["peak_markup"] = 1.0 + pd/100
                cfg["abundant_discount"] = 1.0 - ad/100
                cfg["last_minute_discount"] = 1.0 - lm/100
            else:
                ptn = pc1.selectbox("減衰パターン", ["standard", "early_rush", "last_minute_rush"],
                                   index=["standard", "early_rush", "last_minute_rush"].index(cfg.get("decay_pattern", "standard")),
                                   key=f"ptn_{i}")
                dek = pc2.slider("鋭さ (k)", 5.0, 50.0, float(cfg.get("decay_k", 15.0)), 1.0, key=f"dek_{i}")
                dep = pc3.slider("柔軟性 (p)", 0.05, 0.50, float(cfg.get("decay_p", 0.15)), 0.05, key=f"dep_{i}")
                cfg["decay_pattern"] = ptn
                cfg["decay_k"] = dek
                cfg["decay_p"] = dep

    st.markdown("---")

    # === Section 2: バックテスト実行と推移グラフ ===
    import plotly.graph_objects as go

    st.markdown("### 📊 Section 2: バックテスト実行と推移グラフ")
    st.write(f"**対象カテゴリ:** `{target_category}` に対して、全シナリオのシミュレーションを実行します。")

    if st.button("▶ 全シナリオのバックテストを実行", type="primary", use_container_width=True):
        with st.spinner("各シナリオのシミュレーション中..."):

            # 対象カテゴリの商品だけ抽出
            cat_products = edited_cls_df[(edited_cls_df["商品種別"] == t_item) & (edited_cls_df["特性 (クリックで変更)"] == t_char)]
            target_inv_ids = bt_inv_df[bt_inv_df["name"].isin(cat_products["商品名"]) & (bt_inv_df["item_type"] == t_item)]["id"].tolist()

            if not target_inv_ids:
                st.warning("このカテゴリに属する商品実績がありません。")
            else:
                # 分析結果を格納
                scenario_results = []
                from model_evaluator import backtest_strategy, _empty_eval

                # シナリオごとのグラフ用データ
                fig = go.Figure()
                colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#8b5cf6"]

                # 実績線の加算用
                all_actual_rates = None
                all_lead_days = None

                for s_idx, sc in enumerate(scenarios):
                    evals = []
                    sum_pred_rates = None
                    sum_act_rates = None
                    cnt = 0

                    for inv_id in target_inv_ids:
                        target_row_q = bt_inv_df[bt_inv_df["id"] == inv_id]
                        if target_row_q.empty: continue
                        target_row = target_row_q.iloc[0]
                        ev_df = bt_events_df[bt_events_df["inventory_id"] == inv_id]
                        e_res = backtest_strategy(sc["strategy"], target_row, ev_df, sc["config"])
                        evals.append(e_res)

                        # 配列を合算して平均を出す
                        p_rates = np.array(e_res.get("predicted_rates", []))
                        a_rates = np.array(e_res.get("actual_rates", []))
                        l_days = np.array(e_res.get("lead_days", []))

                        if len(l_days) > 0:
                            if sum_pred_rates is None:
                                sum_pred_rates = p_rates.copy()
                                sum_act_rates = a_rates.copy()
                                all_lead_days = l_days.copy()
                            else:
                                min_len = min(len(sum_pred_rates), len(p_rates))
                                sum_pred_rates[:min_len] += p_rates[:min_len]
                                sum_act_rates[:min_len] += a_rates[:min_len]
                            cnt += 1

                    if cnt > 0:
                        avg_pred = sum_pred_rates / cnt
                        avg_act = sum_act_rates / cnt
                        all_actual_rates = avg_act # 実績は全てのシナリオで同じはず

                        c = colors[s_idx % len(colors)]
                        fig.add_trace(go.Scatter(
                            x=-all_lead_days, y=avg_pred * 100, mode='lines',
                            name=f"[{sc['id']}] {sc['name']}",
                            line=dict(color=c, width=3, dash='dash')
                        ))

                    # スコア平均
                    df_e = pd.DataFrame(evals)
                    avg_mape = df_e["mape"].mean() if not df_e.empty else 0
                    avg_lift = df_e["revenue_lift"].mean() if not df_e.empty else 0
                    avg_spoil = df_e["spoilage_reduction"].mean() if not df_e.empty else 0
                    avg_comp = df_e["composite_score"].mean() if not df_e.empty else 0

                    # 辞書のコピーを渡す（Streamlitのバグ回避）
                    import copy
                    scenario_results.append({
                        "シナリオ": f"[{sc['id']}] {sc['name']}",
                        "アルゴリズム": "🌟ルールベース" if sc['strategy']=='rule_based' else "📈需要予測",
                        "MAPE": avg_mape,
                        "Revenue Lift": avg_lift,
                        "廃棄損低減率": avg_spoil,
                        "Composite Score": avg_comp,
                        "Ref_strategy": sc["strategy"],
                        "Ref_config": copy.deepcopy(sc["config"])
                    })

                # 実績線を追加
                if all_actual_rates is not None and all_lead_days is not None:
                    fig.add_trace(go.Scatter(
                        x=-all_lead_days, y=all_actual_rates * 100, mode='lines',
                        name='実際の販売ペース', line=dict(color='rgba(150, 150, 150, 0.7)', width=4)
                    ))

                # グラフ描画
                st.write("")
                fig.update_layout(
                    title=f"`{target_category}` カテゴリの仮想販売推移シミュレーション",
                    xaxis_title="リードタイム (日前)",
                    yaxis_title="累計販売率 (%)",
                    yaxis=dict(range=[0, 100]),
                    template="plotly_white",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("---")
                # === Section 3-4: 比較表と登録 ===
                st.markdown("### 🏆 Section 3: シナリオ評価スコア・マトリクス")
                res_df = pd.DataFrame(scenario_results)

                # スコア降順にソート
                res_df = res_df.sort_values("Composite Score", ascending=False).reset_index(drop=True)

                # 表示用DF
                disp_df = res_df.copy()
                disp_df["MAPE"] = disp_df["MAPE"].map(lambda x: f"{x:.1f}%")
                disp_df["Revenue Lift"] = disp_df["Revenue Lift"].map(lambda x: f"{x:+.1f}%")
                disp_df["廃棄損低減率"] = disp_df["廃棄損低減率"].map(lambda x: f"{x:+.1f}%")
                disp_df["Composite Score"] = disp_df["Composite Score"].map(lambda x: f"{x:.1f}点")

                # スコア1位に王冠をつける
                if len(disp_df) > 0:
                    disp_df.loc[0, "シナリオ"] = "👑 " + disp_df.loc[0, "シナリオ"]

                st.dataframe(disp_df.drop(columns=["Ref_strategy", "Ref_config"]), use_container_width=True, hide_index=True)

                st.markdown("### 💾 Section 4: 最適シナリオの登録")
                st.write(f"決定したシナリオを `{target_category}` に登録（永続化）します。登録されたモデル設定は全体（本日のアクション等）に波及します。")

                s_col1, s_col2 = st.columns([3, 1])
                selected_sc_name = s_col1.selectbox("📝 登録するシナリオを選択", res_df["シナリオ"].tolist(), index=0)

                st.write("")
                if s_col2.button("💾 このシナリオを登録", type="primary", use_container_width=True):
                    sc_data = res_df[res_df["シナリオ"] == selected_sc_name].iloc[0]
                    
                    save_model_setting(
                        item_type=t_item, 
                        characteristic=t_char, 
                        strategy=sc_data["Ref_strategy"], 
                        config=sc_data["Ref_config"], 
                        score=sc_data["Composite Score"], 
                        mape=sc_data["MAPE"], 
                        lift=sc_data["Revenue Lift"], 
                        spoilage=sc_data["廃棄損低減率"]
                    )
                    st.success(f"{target_category} に {selected_sc_name} の設定を登録しました！")
"""
    
    modified_lines = lines[:start_idx] + [new_code + "\n"] + lines[end_idx+1:]
    with open('dashboard/app.py', 'w', encoding='utf-8') as f:
        f.writelines(modified_lines)
    print("app.py updated successfully.")
else:
    print(f"Could not find target boundaries. start: {start_idx}, end: {end_idx}")
