/**
 * バックエンドAPIとの通信クライアント。
 * 全APIリクエストを一元管理する。
 */

// バックエンドのベースURL（環境変数で切替）
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─────────────────────────────────────────
// 型定義
// ─────────────────────────────────────────

/** 在庫（一般ユーザー向け）*/
export interface InventoryItem {
  id: number;
  name: string;
  item_type: string;          // 「flight」「hotel」等
  total_stock: number;
  remaining_stock: number;
  dynamic_price: number;      // 動的価格（Opaque Pricing: 総額のみ）
  image_url?: string;
  description?: string;
}

/** 在庫（管理者向け: 原価情報を含む）*/
export interface InventoryAdminItem extends InventoryItem {
  base_price: number;       // 原価（元の価格）
  price_multiplier: number; // 価格倍率
}

/** 在庫追加リクエスト（管理者専用）*/
export interface InventoryCreatePayload {
  item_type: string;
  name: string;
  total_stock: number;
  remaining_stock: number;
  base_price: number;
}

/** 価格セッション */
export interface PriceSession {
  token: string;
  inventory_id: number;
  product_name: string;
  price_snapshot: number;
  expires_at: string;
  remaining_seconds: number;
}

// ─────────────────────────────────────────
// 在庫API
// ─────────────────────────────────────────

/** 在庫一覧を取得する（一般ユーザー向け） */
export async function fetchInventory(): Promise<InventoryItem[]> {
  const res = await fetch(`${API_BASE_URL}/inventory`, { cache: "no-store" });
  if (!res.ok) throw new Error("在庫一覧の取得に失敗しました");
  return res.json();
}

/** 在庫一覧を取得する（管理者向け） */
export async function fetchAdminInventory(): Promise<InventoryAdminItem[]> {
  const res = await fetch(`${API_BASE_URL}/admin/inventory`, { cache: "no-store" });
  if (!res.ok) throw new Error("管理者向け在庫一覧の取得に失敗しました");
  return res.json();
}

/** 在庫を追加する（管理者専用） */
export async function createInventory(payload: InventoryCreatePayload): Promise<InventoryAdminItem> {
  const res = await fetch(`${API_BASE_URL}/admin/inventory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("在庫追加に失敗しました");
  return res.json();
}

/** 在庫を更新する（管理者専用） */
export async function updateInventory(id: number, remaining_stock: number): Promise<InventoryAdminItem> {
  const res = await fetch(`${API_BASE_URL}/admin/inventory/${id}?remaining_stock=${remaining_stock}`, {
    method: "PATCH",
  });
  if (!res.ok) throw new Error("在庫更新に失敗しました");
  return res.json();
}

/** 在庫を削除する（管理者専用） */
export async function deleteInventory(id: number): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/admin/inventory/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("在庫削除に失敗しました");
}

// ─────────────────────────────────────────
// 価格セッションAPI
// ─────────────────────────────────────────

/** 価格セッションを開始する（「予約する」ボタン押下時） */
export async function createPriceSession(inventoryId: number): Promise<PriceSession> {
  const res = await fetch(`${API_BASE_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inventory_id: inventoryId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "予約セッションの開始に失敗しました");
  }
  return res.json();
}

/** 価格セッションの残り時間を確認する */
export async function fetchPriceSession(token: string): Promise<PriceSession> {
  const res = await fetch(`${API_BASE_URL}/sessions/${token}`, { cache: "no-store" });
  if (!res.ok) throw new Error("セッション情報の取得に失敗しました");
  return res.json();
}

// ─────────────────────────────────────────
// ユーティリティ
// ─────────────────────────────────────────

/** 金額を日本円フォーマットで表示する（例: ¥92,000） */
export function formatPrice(price: number): string {
  return new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  }).format(price);
}

/** 残り秒数を MM:SS 形式の文字列に変換する */
export function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
