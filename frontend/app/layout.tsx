import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/Navbar";

const inter = Inter({ subsets: ["latin"] });

// SEO メタデータ
export const metadata: Metadata = {
  title: "TravelDeal | 旅行パッケージ特別価格",
  description: "限定旅行パッケージをお得な価格でご提供。残席わずかのスペシャルディールをお見逃しなく。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja" suppressHydrationWarning>
      <body className={inter.className} suppressHydrationWarning>
        {/* ナビゲーションバー */}
        <Navbar />
        {/* メインコンテンツ */}
        <main className="min-h-screen bg-gray-950 pt-16">
          {children}
        </main>
      </body>
    </html>
  );
}
