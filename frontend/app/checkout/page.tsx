"use client";

/**
 * 決済確認ページ（Checkout）。
 * カウントダウンタイマーで価格の有効期限を表示する。
 * タイムアウト時は一覧ページへリダイレクトする。
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { fetchPriceSession, formatPrice, formatCountdown, PriceSession } from "@/lib/api";

export default function CheckoutPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [session, setSession] = useState<PriceSession | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expired, setExpired] = useState(false);

  // セッション情報を取得する
  useEffect(() => {
    if (!token) {
      router.replace("/");
      return;
    }
    fetchPriceSession(token)
      .then((s) => {
        setSession(s);
        setRemainingSeconds(s.remaining_seconds);
        if (s.remaining_seconds <= 0) setExpired(true);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token, router]);

  // カウントダウンタイマー（1秒ごとにデクリメント）
  useEffect(() => {
    if (remainingSeconds <= 0 || expired) return;
    const timer = setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          setExpired(true);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [remainingSeconds, expired]);

  // 期限切れ時に3秒後にリダイレクト
  const handleExpired = useCallback(() => {
    setTimeout(() => router.replace("/"), 3000);
  }, [router]);

  useEffect(() => {
    if (expired) handleExpired();
  }, [expired, handleExpired]);

  // タイマーが残り60秒以下かどうかで警告色を出す
  const isWarning = remainingSeconds <= 60;

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <div className="w-10 h-10 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <p className="text-red-400 text-lg">⚠ {error}</p>
        <button className="btn-primary" onClick={() => router.replace("/")}>
          一覧へ戻る
        </button>
      </div>
    );
  }

  // 価格期限切れ画面
  if (expired) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 animate-fade-in-up">
        <div
          className="glass-card p-10 text-center"
          style={{ maxWidth: "440px", width: "100%" }}
        >
          <div className="text-5xl mb-4">⏰</div>
          <h2 className="text-xl font-bold text-red-400 mb-2">価格の有効期限が切れました</h2>
          <p className="text-gray-400 text-sm">
            この価格は有効期限が切れています。<br />
            最新の価格で改めてご確認ください。
          </p>
          <p className="text-gray-600 text-xs mt-4">3秒後に一覧へ戻ります...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div
        className="glass-card p-8 animate-fade-in-up w-full"
        style={{ maxWidth: "480px" }}
      >
        {/* ヘッダー */}
        <div className="text-center mb-8">
          <p className="text-indigo-400 text-xs font-bold tracking-widest uppercase mb-2">
            ✦ Order Confirmation
          </p>
          <h1 className="text-2xl font-black text-white">ご予約の確認</h1>
        </div>

        {/* 商品名 */}
        <div
          className="rounded-xl p-4 mb-6"
          style={{ background: "rgba(99, 102, 241, 0.08)", border: "1px solid rgba(99, 102, 241, 0.2)" }}
        >
          <p className="text-gray-400 text-xs uppercase tracking-widest mb-1">旅行パッケージ</p>
          <p className="text-white font-bold text-lg">{session?.product_name}</p>
        </div>

        {/* ─── カウントダウンタイマー ─── */}
        <div
          className="rounded-xl p-5 mb-6 text-center"
          style={{
            background: isWarning
              ? "rgba(239, 68, 68, 0.08)"
              : "rgba(255, 255, 255, 0.03)",
            border: `1px solid ${isWarning ? "rgba(239,68,68,0.3)" : "rgba(255,255,255,0.08)"}`,
            transition: "all 0.3s ease",
          }}
        >
          <p
            className="text-xs uppercase tracking-widest mb-2"
            style={{ color: isWarning ? "#f87171" : "#9ca3af" }}
          >
            🕐 この価格の有効期限
          </p>
          <p
            className={`countdown-timer text-5xl font-black ${isWarning ? "countdown-warning" : "text-white"}`}
          >
            {formatCountdown(remainingSeconds)}
          </p>
          {isWarning && (
            <p className="text-red-400 text-xs mt-2 animate-pulse">
              ⚠ まもなく期限切れになります
            </p>
          )}
        </div>

        {/* ─── Opaque Pricing: 総額のみ表示 ─── */}
        <div
          className="rounded-xl p-5 mb-6"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
        >
          <p className="text-gray-500 text-xs uppercase tracking-widest mb-2">お支払い総額（税込・全込み）</p>
          <p className="price-display">{formatPrice(session?.price_snapshot ?? 0)}</p>
          <p className="text-gray-600 text-xs mt-2">
            ※ 宿泊・交通・現地費用・旅行保険をすべて含みます
          </p>
        </div>

        {/* 注意書き */}
        <p className="text-gray-600 text-xs text-center mb-6">
          上記の価格はこのセッション中のみ有効です。<br />
          期限後は市場価格に戻ります。
        </p>

        {/* 決済ボタン（MVP: UI表示のみでダミー処理） */}
        <button className="btn-primary w-full text-base mb-3">
          💳 決済に進む
        </button>
        <button
          className="w-full py-3 text-sm text-gray-500 hover:text-gray-300 transition-colors"
          onClick={() => router.replace("/")}
        >
          キャンセルして戻る
        </button>
      </div>
    </div>
  );
}
