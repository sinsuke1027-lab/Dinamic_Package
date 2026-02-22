"use client";

/**
 * 在庫管理画面（管理者専用）。
 * 在庫の追加・残在庫更新・削除が可能。
 * 動的価格・シャドープライス乗数もここで確認できる。
 * 商品名からダッシュボードへのリンクを追加。
 */

import { useEffect, useState } from "react";
import {
  fetchAdminInventory,
  createInventory,
  updateInventory,
  deleteInventory,
  formatPrice,
  InventoryAdminItem,
  InventoryCreatePayload,
} from "@/lib/api";

// Streamlit ダッシュボードの URL（環境変数 or デフォルト）
const DASHBOARD_URL =
  process.env.NEXT_PUBLIC_DASHBOARD_URL || "http://localhost:8502";

export default function AdminPage() {
  const [items, setItems] = useState<InventoryAdminItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  // 在庫一覧を読み込む
  const loadInventory = () => {
    setLoading(true);
    fetchAdminInventory()
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadInventory();
  }, []);

  // 在庫削除の処理
  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`「${name}」を削除しますか？`)) return;
    try {
      await deleteInventory(id);
      loadInventory();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  // 残在庫数を即座に更新する（インライン編集）
  const handleUpdateStock = async (id: number, currentRemaining: number, totalStock: number) => {
    const input = prompt(
      `残在庫数を入力してください（0〜${totalStock}）:`,
      String(currentRemaining),
    );
    if (input === null) return;
    const newRemaining = parseInt(input, 10);
    if (isNaN(newRemaining) || newRemaining < 0 || newRemaining > totalStock) {
      alert("有効な数値を入力してください");
      return;
    }
    try {
      await updateInventory(id, newRemaining);
      loadInventory();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "更新に失敗しました");
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* ページヘッダー */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-black text-white mb-1">在庫管理</h1>
          <p className="text-gray-500 text-sm">リスク在庫の追加・編集・価格確認</p>
        </div>
        <div className="flex gap-3">
          {/* ダッシュボードへのリンクボタン */}
          <a
            href={DASHBOARD_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm px-4 py-2 rounded-lg font-medium transition-all"
            style={{
              background: "rgba(167,139,250,0.15)",
              border: "1px solid rgba(167,139,250,0.4)",
              color: "#a78bfa",
            }}
          >
            📊 ダッシュボードを開く ↗
          </a>
          <button
            className="btn-primary text-sm"
            onClick={() => setShowForm(!showForm)}
          >
            {showForm ? "✕ キャンセル" : "+ 在庫を追加"}
          </button>
        </div>
      </div>

      {/* 在庫追加フォーム */}
      {showForm && (
        <AddInventoryForm
          onCreated={() => {
            setShowForm(false);
            loadInventory();
          }}
        />
      )}

      {/* エラー */}
      {error && <p className="text-red-400 mb-4">⚠ {error}</p>}

      {/* ローディング */}
      {loading && (
        <div className="flex justify-center py-16">
          <div className="w-8 h-8 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
        </div>
      )}

      {/* 在庫テーブル */}
      {!loading && (
        <div
          className="glass-card overflow-hidden"
          style={{ borderRadius: "1rem" }}
        >
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>商品名</th>
                  <th>種別</th>
                  <th>残在庫</th>
                  <th>原価</th>
                  <th>動的価格</th>
                  <th>ステータス</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center text-gray-600 py-10">
                      在庫がありません。「在庫を追加」ボタンから追加してください。
                    </td>
                  </tr>
                )}
                {items.map((item) => (
                  <AdminRow
                    key={item.id}
                    item={item}
                    dashboardUrl={DASHBOARD_URL}
                    onDelete={() => handleDelete(item.id, item.name)}
                    onUpdateStock={() =>
                      handleUpdateStock(item.id, item.remaining_stock, item.total_stock)
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 価格計算の説明 */}
      <div
        className="mt-8 glass-card p-6"
        style={{ borderColor: "rgba(99, 102, 241, 0.2)" }}
      >
        <h3 className="text-white font-bold mb-3">⚡ シャドープライス計算式</h3>
        <div className="text-gray-400 text-sm font-mono space-y-1">
          <p>残在庫率 = 残在庫数 ÷ 総在庫数</p>
          <p>残在庫率 &lt; 50% → 乗数 = 1.0 + (0.5 - 残在庫率) × 1.0　（最大×1.5）</p>
          <p>残在庫率 ≥ 50% → 乗数 = 1.0 - (残在庫率 - 0.5) × 0.6　（最小×0.7）</p>
          <p>動的価格 = 原価 × 乗数　→ 100円単位に丸める</p>
        </div>
        <div className="mt-4 grid grid-cols-4 gap-3 text-xs text-center">
          {[
            { ratio: "10%", mult: "×1.40", desc: "品薄↑ 最大近く" },
            { ratio: "30%", mult: "×1.20", desc: "20%増" },
            { ratio: "70%", mult: "×0.88", desc: "12%引き" },
            { ratio: "100%", mult: "×0.70", desc: "余裕あり 最安" },
          ].map((r) => (
            <div
              key={r.ratio}
              className="rounded-lg p-3"
              style={{ background: "rgba(255,255,255,0.04)" }}
            >
              <p className="text-indigo-400 font-bold text-base">{r.mult}</p>
              <p className="text-gray-500 mt-0.5">残在庫率 {r.ratio}</p>
              <p className="text-gray-600">{r.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────
// 管理者テーブル行コンポーネント
// ─────────────────────────────────────────

function AdminRow({
  item,
  dashboardUrl,
  onDelete,
  onUpdateStock,
}: {
  item: InventoryAdminItem;
  dashboardUrl: string;
  onDelete: () => void;
  onUpdateStock: () => void;
}) {
  // 残在庫率から状態ラベルを決定
  const ratio = item.total_stock > 0 ? item.remaining_stock / item.total_stock : 0;
  const { label, badgeClass } =
    ratio <= 0.1
      ? { label: "🔥 残りわずか", badgeClass: "badge-danger" }
      : ratio <= 0.3
      ? { label: "残り少", badgeClass: "badge-warning" }
      : ratio < 0.5
      ? { label: "まもなく終了", badgeClass: "badge-warning" }
      : { label: "空席あり", badgeClass: "badge-success" };

  // 価格倍率（小数2桁）
  const multiplier = item.base_price > 0 ? item.dynamic_price / item.base_price : 1;

  return (
    <tr>
      <td>
        {/* 商品名 → ダッシュボードへのリンク */}
        <a
          href={dashboardUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-white hover:text-indigo-400 transition-colors underline-offset-2 hover:underline"
          title="ダッシュボードで価格推移を確認"
        >
          {item.name}
          <span className="ml-1 text-xs text-indigo-500 opacity-60">↗</span>
        </a>
      </td>
      <td className="text-gray-400">{item.item_type}</td>
      <td>
        {/* 残在庫数をクリックで編集 */}
        <button
          onClick={onUpdateStock}
          className="text-left hover:text-indigo-400 transition-colors"
          title="クリックして残在庫数を更新"
        >
          <span className="text-white">{item.remaining_stock}</span>
          <span className="text-gray-600"> / {item.total_stock}</span>
          <span className="text-gray-600 text-xs ml-1">✏</span>
        </button>
      </td>
      <td className="text-gray-400">{formatPrice(item.base_price)}</td>
      <td>
        <p className="text-white font-bold">{formatPrice(item.dynamic_price)}</p>
        <p
          className="text-xs"
          style={{ color: multiplier >= 1.0 ? "#f87171" : "#4ade80" }}
        >
          ×{multiplier.toFixed(2)}
        </p>
      </td>
      <td>
        <span className={`badge ${badgeClass}`}>{label}</span>
      </td>
      <td>
        <button
          onClick={onDelete}
          className="text-xs text-red-500 hover:text-red-400 transition-colors px-2 py-1 rounded"
          style={{ border: "1px solid rgba(239,68,68,0.3)" }}
        >
          削除
        </button>
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────
// 在庫追加フォームコンポーネント
// ─────────────────────────────────────────

function AddInventoryForm({ onCreated }: { onCreated: () => void }) {
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    const form = e.currentTarget;
    const data = new FormData(form);
    // 新APIのフィールド名（item_type, total_stock, remaining_stock, base_price）
    const payload: InventoryCreatePayload = {
      item_type: data.get("item_type") as string,
      name: data.get("name") as string,
      total_stock: parseInt(data.get("total_stock") as string, 10),
      remaining_stock: parseInt(data.get("total_stock") as string, 10), // 初期は満在庫
      base_price: parseInt(data.get("base_price") as string, 10),
    };
    try {
      await createInventory(payload);
      form.reset();
      onCreated();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "追加に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="glass-card p-6 mb-8 animate-fade-in-up"
      style={{ borderColor: "rgba(99, 102, 241, 0.3)" }}
    >
      <h2 className="text-lg font-bold text-white mb-5">新規在庫を追加</h2>
      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 商品名 */}
        <div className="md:col-span-2">
          <label className="block text-xs text-gray-500 mb-1 uppercase tracking-wider">商品名 *</label>
          <input name="name" required placeholder="例: ハワイ5泊7日パック" className="input-field" />
        </div>
        {/* 種別 */}
        <div>
          <label className="block text-xs text-gray-500 mb-1 uppercase tracking-wider">種別</label>
          <select name="item_type" className="input-field" style={{ appearance: "none" }}>
            <option value="tour">tour（ツアー）</option>
            <option value="hotel">hotel（ホテル）</option>
            <option value="flight">flight（フライト）</option>
          </select>
        </div>
        {/* 総在庫数 */}
        <div>
          <label className="block text-xs text-gray-500 mb-1 uppercase tracking-wider">総在庫数 *</label>
          <input name="total_stock" type="number" required min={1} placeholder="50" className="input-field" />
        </div>
        {/* 原価 */}
        <div>
          <label className="block text-xs text-gray-500 mb-1 uppercase tracking-wider">原価（円）*</label>
          <input name="base_price" type="number" required min={0} placeholder="80000" className="input-field" />
        </div>
        {/* 送信ボタン */}
        <div className="md:col-span-2">
          <button type="submit" className="btn-primary w-full" disabled={submitting}>
            {submitting ? "追加中..." : "在庫を追加する"}
          </button>
        </div>
      </form>
    </div>
  );
}
