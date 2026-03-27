import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CaucasHub — Биржа грузов Кавказа",
  description: "Первая биржа грузов и транспорта Кавказа. Грузия, Армения, Азербайджан.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
