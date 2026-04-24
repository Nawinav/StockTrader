import type { Metadata } from "next";
import Link from "next/link";
import { PortfolioPill } from "@/components/PortfolioPill";
import { TokenStatusBanner } from "@/components/TokenStatusBanner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Suggestion Dashboard",
  description:
    "Top 10 intraday and long-term stock ideas refreshed every 10 minutes, blended from technical + fundamental factors.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 backdrop-blur sticky top-0 z-10">
          <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-brand-500 text-white flex items-center justify-center font-bold">
                S
              </div>
              <span className="font-semibold">Stock Suggestions</span>
            </Link>
            <nav className="flex items-center gap-4 text-sm">
              <Link href="/" className="hover:text-brand-600">
                Dashboard
              </Link>
              <Link href="/trading" className="hover:text-brand-600">
                Trading
              </Link>
              <Link href="/watchlist" className="hover:text-brand-600">
                Watchlist
              </Link>
              <PortfolioPill />
            </nav>
          </div>
        </header>
        <TokenStatusBanner />
        <main className="max-w-6xl mx-auto px-4 py-6">{children}</main>
        <footer className="max-w-6xl mx-auto px-4 py-8 text-xs text-slate-500">
          MVP scaffold &middot; Scores are illustrative. Not investment advice.
          Upstox live trading integration is planned — paper trading only today.
        </footer>
      </body>
    </html>
  );
}
