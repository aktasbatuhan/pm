import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Analytics } from "@vercel/analytics/react";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

const SITE_URL = "https://heydash.dev";

export const metadata: Metadata = {
  title: {
    default: "Dash — Autonomous PM Agent",
    template: "%s | Dash PM",
  },
  description:
    "Dash watches your GitHub, Linear, PostHog, and Slack. It produces daily briefs, surfaces action items, tracks goals, monitors signals, and generates reports — so you ship the right things, fast.",
  metadataBase: new URL(SITE_URL),
  openGraph: {
    type: "website",
    siteName: "Dash PM",
    title: "Dash — Autonomous PM Agent",
    description:
      "Daily briefs, signal collection, report automation, team pulse, goal tracking. One agent that learns your workspace and gets smarter every cycle.",
    url: SITE_URL,
  },
  twitter: {
    card: "summary_large_image",
    title: "Dash — Autonomous PM Agent",
    description:
      "Ship fast. Ship the right things. Dash is the autonomous PM that watches your stack and tells you what to build, fix, and kill.",
  },
  robots: {
    index: true,
    follow: true,
  },
  alternates: {
    canonical: SITE_URL,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        {/* JSON-LD Structured Data */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "SoftwareApplication",
              name: "Dash PM",
              description:
                "Autonomous product management agent that produces daily briefs, tracks goals, monitors signals, and generates reports.",
              url: SITE_URL,
              applicationCategory: "BusinessApplication",
              operatingSystem: "Web",
              offers: {
                "@type": "Offer",
                price: "0",
                priceCurrency: "USD",
                description: "Early access for design partners",
              },
            }),
          }}
        />
      </head>
      <body className="h-full bg-background text-foreground font-sans">
        {children}
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
