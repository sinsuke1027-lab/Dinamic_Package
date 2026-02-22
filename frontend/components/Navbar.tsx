"use client";

/**
 * ナビゲーションバーコンポーネント。
 * 全ページで共通表示される。
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50"
      style={{
        background: "rgba(3, 7, 18, 0.85)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
      }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* ロゴ */}
          <Link href="/" className="flex items-center gap-2">
            <span className="text-2xl">✈️</span>
            <span
              className="font-black text-lg tracking-tight"
              style={{
                background: "linear-gradient(135deg, #818cf8, #c084fc)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              TravelDeal
            </span>
          </Link>

          {/* ナビリンク */}
          <div className="flex items-center gap-1">
            <NavLink href="/" label="旅行パッケージ" active={pathname === "/"} />
            <NavLink href="/admin" label="⚙ 管理" active={pathname === "/admin"} />
          </div>
        </div>
      </div>
    </nav>
  );
}

/** ナビゲーションリンクの共通コンポーネント */
function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className="px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200"
      style={{
        color: active ? "#818cf8" : "rgba(255,255,255,0.6)",
        background: active ? "rgba(99, 102, 241, 0.12)" : "transparent",
      }}
    >
      {label}
    </Link>
  );
}
