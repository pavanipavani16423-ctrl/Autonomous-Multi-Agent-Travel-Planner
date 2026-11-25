"use client";

import { useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "voyager.theme";

function subscribe(cb: () => void) {
  const mo = new MutationObserver(cb);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
  return () => mo.disconnect();
}

/** The theme actually on screen ("light" | "dark"), tracked from the <html> class. */
export function useResolvedTheme(): "light" | "dark" {
  return useSyncExternalStore(
    subscribe,
    () => (document.documentElement.classList.contains("dark") ? "dark" : "light"),
    () => "light",
  );
}

export function readThemeChoice(): ThemeChoice {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice) {
  const d = document.documentElement;
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    /* storage blocked */
  }
  if (choice === "system") {
    delete d.dataset.theme;
    d.classList.toggle("dark", matchMedia("(prefers-color-scheme: dark)").matches);
  } else {
    d.dataset.theme = choice;
    d.classList.toggle("dark", choice === "dark");
  }
}
