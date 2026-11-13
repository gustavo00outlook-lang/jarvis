import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "J.A.R.V.I.S.",
  description: "Just A Rather Very Intelligent System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" suppressHydrationWarning style={{ background: "#050505" }}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Montserrat:wght@200;300;400;500;600;700&family=Orbitron:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        className="bg-black text-white overflow-hidden jarvis-app-body"
        style={{
          background: "#050505",
          color: "#ffffff",
          margin: 0,
          width: "100%",
          height: "100dvh",
          minHeight: "100dvh",
          overflow: "hidden",
        }}
      >
        {children}
      </body>
    </html>
  );
}
