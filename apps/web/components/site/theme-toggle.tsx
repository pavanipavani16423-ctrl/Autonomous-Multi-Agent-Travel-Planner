"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { applyTheme, readThemeChoice, type ThemeChoice } from "@/lib/use-theme";

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<ThemeChoice, string> = { system: "System theme", light: "Light theme", dark: "Dark theme" };

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice | null>(null);

  useEffect(() => {
    // Read the persisted choice after mount (the server can't know it) and follow OS changes in "system".
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setChoice(readThemeChoice());
    const onOs = () => {
      if (readThemeChoice() === "system") applyTheme("system");
    };
    queueMicrotask(sync);
    mq.addEventListener("change", onOs);
    return () => mq.removeEventListener("change", onOs);
  }, []);

  const current = choice ?? "system";
  const Icon = current === "light" ? Sun : current === "dark" ? Moon : Monitor;
  return (
    <button
      type="button"
      onClick={() => {
        const next = NEXT[current];
        applyTheme(next);
        setChoice(next);
      }}
      className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-line-strong text-ink-2 transition hover:text-ink"
      aria-label={`${LABEL[current]} — switch to ${LABEL[NEXT[current]].toLowerCase()}`}
      title={LABEL[current]}
    >
      <Icon className="h-4 w-4" aria-hidden suppressHydrationWarning />
    </button>
  );
}
