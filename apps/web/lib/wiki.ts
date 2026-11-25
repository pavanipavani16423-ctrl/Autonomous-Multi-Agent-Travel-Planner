"use client";

import { useEffect, useState } from "react";

/** Wikimedia only serves a fixed ladder of thumbnail widths; anything else is a 400. */
const STEPS = [330, 500, 960, 1280, 1920];

export function wikiThumb(url: string | undefined, width = 960): string | undefined {
  if (!url) return undefined;
  const w = STEPS.find((s) => s >= width) ?? 1920;
  const clean = url.split("?")[0];
  return /\/\d+px-/.test(clean) ? clean.replace(/\/\d+px-/, `/${w}px-`) : clean;
}

const ALLOWED_HOSTS = new Set(["upload.wikimedia.org", "thumb.wikimedia.org"]);
/** next/image only optimises hosts listed in next.config; anything else renders unoptimised. */
export function isOptimizable(src: string) {
  try {
    return ALLOWED_HOSTS.has(new URL(src).hostname);
  } catch {
    return false;
  }
}

const memory = new Map<string, string | null>();
const inflight = new Map<string, Promise<string | null>>();
const LS_PREFIX = "voyager.wiki.";
const TTL = 7 * 24 * 3600 * 1000;

export function fetchWikiImage(title: string, width = 960): Promise<string | null> {
  const key = `${title.toLowerCase()}@${width}`;
  if (memory.has(key)) return Promise.resolve(memory.get(key) ?? null);
  try {
    const raw = localStorage.getItem(LS_PREFIX + key);
    if (raw) {
      const { url, at } = JSON.parse(raw) as { url: string | null; at: number };
      if (Date.now() - at < TTL) {
        memory.set(key, url);
        return Promise.resolve(url);
      }
    }
  } catch {
    /* ignore */
  }
  const existing = inflight.get(key);
  if (existing) return existing;
  const p = fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title.replace(/ /g, "_"))}`)
    .then((r) => (r.ok ? r.json() : null))
    .then((d: { thumbnail?: { source?: string }; type?: string } | null) => {
      const url = d && d.type !== "disambiguation" ? wikiThumb(d.thumbnail?.source, width) ?? null : null;
      memory.set(key, url);
      try {
        localStorage.setItem(LS_PREFIX + key, JSON.stringify({ url, at: Date.now() }));
      } catch {
        /* ignore */
      }
      return url;
    })
    .catch(() => null)
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

/** Destination photo by Wikipedia title; `initial` short-circuits the lookup. */
export function useWikiImage(title: string | undefined, initial?: string, width = 960) {
  const [fetched, setFetched] = useState<{ title: string; url: string | null } | null>(null);
  useEffect(() => {
    if (initial || !title) return;
    let alive = true;
    fetchWikiImage(title, width).then((url) => {
      if (alive) setFetched({ title, url });
    });
    return () => {
      alive = false;
    };
  }, [title, initial, width]);
  if (initial) return wikiThumb(initial, width) ?? initial;
  return fetched && fetched.title === title ? fetched.url ?? undefined : undefined;
}
