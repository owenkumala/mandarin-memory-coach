import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SpeakHan",
  description: "Mandarin memory coach powered by Qwen",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-ink/10 bg-white/85 backdrop-blur">
          <nav className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
            <Link className="text-lg font-semibold tracking-normal text-ink" href="/practice">
              SpeakHan
            </Link>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Link className="rounded-md px-3 py-2 text-ink/75 hover:bg-ink/5" href="/practice">
                Practice
              </Link>
              <Link className="rounded-md px-3 py-2 text-ink/75 hover:bg-ink/5" href="/memory">
                Memory
              </Link>
            </div>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
