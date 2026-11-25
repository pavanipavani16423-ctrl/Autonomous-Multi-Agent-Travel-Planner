import type { Metadata, Viewport } from "next";
import { Fraunces, JetBrains_Mono, Manrope } from "next/font/google";
import { Assistant } from "@/components/assistant/assistant";
import { SiteNav } from "@/components/site/nav";
import { Providers } from "@/components/site/providers";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  axes: ["SOFT", "WONK", "opsz"],
  style: ["normal", "italic"],
});
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap", weight: ["400", "500"] });

export const metadata: Metadata = {
  metadataBase: new URL("https://voyager.local"),
  title: { default: "Voyager — trips planned by a team of AI agents", template: "%s · Voyager" },
  description:
    "Describe a trip in one sentence. Eleven specialist agents research weather, stays, food and costs in parallel with live data and guidebook citations, then hand you a day-by-day plan with a map.",
  openGraph: { title: "Voyager", description: "A multi-agent AI travel planner with live data, citations and quality scores." },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#061217" },
    { media: "(prefers-color-scheme: light)", color: "#f6f2ea" },
  ],
};

// Apply a stored theme before first paint (no flash); otherwise follow the OS.
const themeScript = `try{var t=localStorage.getItem("voyager.theme"),d=document.documentElement;if(t==="light"||t==="dark"){d.dataset.theme=t;d.classList.toggle("dark",t==="dark")}else if(matchMedia("(prefers-color-scheme: dark)").matches){d.classList.add("dark")}}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${manrope.variable} ${jetbrains.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-dvh">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-bg"
        >
          Skip to content
        </a>
        <Providers>
          <SiteNav />
          <main id="main">{children}</main>
          <Assistant />
        </Providers>
      </body>
    </html>
  );
}
