"use client";

/**
 * 商品一覧ページ（メインページ）。
 * Opaque Pricing UI: 総額のみを表示し、内訳は一切表示しない。
 * ダイナミックプライシングによる残席コントロールバーも表示する。
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  fetchInventory,
  createPriceSession,
  formatPrice,
  InventoryItem,
} from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 予約ボタンの処理中状態（ID管理）
  const [bookingId, setBookingId] = useState<number | null>(null);

  // 在庫一覧を取得する
  useEffect(() => {
    fetchInventory()
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // 「予約する」ボタン押下時の処理
  const handleBook = async (item: InventoryItem) => {
    setBookingId(item.id);
    try {
      const session = await createPriceSession(item.id);
      // 決済ページへ遷移（セッショントークンをクエリパラメータに渡す）
      router.push(`/checkout?token=${session.token}`);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "エラーが発生しました");
      setBookingId(null);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* ヒーローセクション */}
      <div className="text-center mb-14 animate-fade-in-up">
        <p className="text-indigo-400 text-sm font-bold tracking-widest uppercase mb-3">
          ✦ Limited Time Deals
        </p>
        <h1 className="text-5xl font-black tracking-tighter mb-4">
          <span className="gradient-text">秘密の優待価格</span>で<br />旅行パッケージを
        </h1>
        <p className="text-gray-400 text-lg max-w-xl mx-auto">
          残席が少なくなるほど価格が上昇します。今すぐ確保してください。
        </p>
      </div>

      {/* ローディング */}
      {loading && (
        <div className="flex justify-center items-center py-24">
          <div
            className="w-10 h-10 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin"
          />
        </div>
      )}

      {/* エラー */}
      {error && (
        <div className="text-center py-12">
          <p className="text-red-400">⚠ {error}</p>
          <p className="text-gray-500 text-sm mt-2">バックエンドが起動しているか確認してください</p>
        </div>
      )}

      {/* 在庫カードグリッド */}
      {!loading && !error && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {items.length === 0 && (
            <div className="col-span-3 text-center py-16 text-gray-500">
              現在、利用可能なパッケージがありません
            </div>
          )}
          {items.map((item, idx) => (
            <InventoryCard
              key={item.id}
              item={item}
              delay={idx * 80}
              onBook={handleBook}
              isBooking={bookingId === item.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────
// 在庫カードコンポーネント
// ─────────────────────────────────────────

interface CardProps {
  item: InventoryItem;
  delay: number;
  onBook: (item: InventoryItem) => void;
  isBooking: boolean;
}

function InventoryCard({ item, delay, onBook, isBooking }: CardProps) {
  // 残在庫率（0.0〜1.0）
  const remainingRatio = item.remaining_stock / item.total_stock;

  // 残在庫率からステータスラベルとバッジ色を決定
  const { label, badgeClass } =
    remainingRatio <= 0.1
      ? { label: "🔥 残りわずか", badgeClass: "badge-danger" }
      : remainingRatio <= 0.3
      ? { label: "残り少", badgeClass: "badge-warning" }
      : remainingRatio < 0.5
      ? { label: "まもなく終了", badgeClass: "badge-warning" }
      : { label: "空席あり", badgeClass: "badge-success" };

  return (
    <div
      className="glass-card overflow-hidden animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
    >
      {/* サムネイル画像 */}
      <div
        className="relative h-44 overflow-hidden"
        style={{
          background: item.image_url
            ? `url(${item.image_url}) center/cover`
            : "linear-gradient(135deg, #1e1b4b, #312e81)",
        }}
      >
        {/* カテゴリバッジ */}
        <div className="absolute top-3 left-3">
          <span className="badge badge-success text-xs">{item.item_type}</span>
        </div>
        {/* 在庫ステータスバッジ */}
        <div className="absolute top-3 right-3">
          <span className={`badge ${badgeClass}`}>{label}</span>
        </div>
        {/* 画像がない場合の絵文字表示 */}
        {!item.image_url && (
          <div className="absolute inset-0 flex items-center justify-center text-6xl opacity-30">
            🏝
          </div>
        )}
      </div>

      {/* カードコンテンツ */}
      <div className="p-5">
        <h2 className="text-lg font-bold text-white mb-1 leading-snug">{item.name}</h2>

        {/* 残席プログレスバー */}
        <div className="mb-4">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>残在庫 {item.remaining_stock} / {item.total_stock}</span>
            <span>{Math.round(remainingRatio * 100)}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${remainingRatio * 100}%`,
                background:
                  remainingRatio <= 0.1
                    ? "#ef4444"
                    : remainingRatio <= 0.3
                    ? "#f59e0b"
                    : "#6366f1",
              }}
            />
          </div>
        </div>

        {/* ─── Opaque Pricing: 総額のみ表示（内訳は意図的に非表示）─── */}
        <div className="mb-5">
          <p className="text-gray-500 text-xs mb-1 uppercase tracking-widest">パッケージ料金（全込み）</p>
          <p className="price-display">{formatPrice(item.dynamic_price)}</p>
          <p className="text-gray-600 text-xs mt-1">※ 宿泊・交通・諸費用すべて含む</p>
        </div>

        {/* 予約ボタン */}
        <button
          className="btn-primary w-full text-sm"
          onClick={() => onBook(item)}
          disabled={isBooking}
        >
          {isBooking ? "処理中..." : "今すぐ予約する →"}
        </button>
      </div>
    </div>
  );
}
