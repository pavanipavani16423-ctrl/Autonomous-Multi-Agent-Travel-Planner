"use client";

import { ArrowUpRight, BookOpenCheck } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Photo } from "@/components/ui/photo";
import { api } from "@/lib/api";
import { COVERED_FALLBACK, WIKI_TITLE } from "@/lib/covered";
import type { CoveredDestination } from "@/lib/types";

// One 2×2 hero tile + eight singles fills a 4-column grid exactly (and a 2-column one on phones).
const FEATURED = ["Kyoto", "Lisbon", "Marrakech", "Udaipur", "Reykjavík", "Cape Town", "Hanoi", "Venice", "Jaipur"];

/** Covered guidebook cities (GET /api/destinations, offline fallback), photography-led. */
export function Gallery() {
  const [list, setList] = useState<CoveredDestination[]>(COVERED_FALLBACK);
  const [live, setLive] = useState(false);
  useEffect(() => {
    let alive = true;
    api
      .destinations()
      .then((d) => {
        if (alive && d.length) {
          setList(d);
          setLive(true);
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const byName = new Map(list.map((d) => [d.name.toLowerCase(), d]));
  const featured = FEATURED.map((n) => byName.get(n.toLowerCase()) ?? COVERED_FALLBACK.find((c) => c.name === n)).filter(
    (d): d is CoveredDestination => !!d,
  );
  const rest = list
    .filter((d) => !FEATURED.some((f) => f.toLowerCase() === d.name.toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <section className="py-24 sm:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <p className="eyebrow">In the guidebook</p>
            <h2 className="mt-3 font-display text-4xl font-semibold leading-[1.05] sm:text-5xl">
              {list.length} cities ready to go<span className="text-coral">.</span>
            </h2>
            <p className="mt-3 max-w-xl text-ink-2">
              Indexed from Wikivoyage{live ? "" : " (offline list)"}. Anywhere else? The brief agent fetches and indexes the city on the fly.
            </p>
          </div>
          <Link href="/plan" className="btn btn-ghost self-start sm:self-auto">
            Plan anywhere <ArrowUpRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>

        <ul className="mt-10 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {featured.map((d, i) => (
            <motion.li
              key={d.name}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-5%" }}
              transition={{ duration: 0.55, delay: (i % 4) * 0.07, ease: [0.16, 1, 0.3, 1] }}
              className={i === 0 ? "col-span-2 lg:row-span-2" : ""}
            >
              <Link
                href={`/plan?destination=${encodeURIComponent(d.name)}`}
                className="group relative block h-full min-h-48 overflow-hidden rounded-[1.25rem] sm:min-h-60"
              >
                <Photo
                  title={WIKI_TITLE[d.name] ?? d.name}
                  alt={`${d.name}, ${d.country}`}
                  className="absolute inset-0 transition-transform duration-700 group-hover:scale-[1.04]"
                  sizes="(max-width: 1024px) 50vw, 25vw"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-transparent" />
                <div className="absolute inset-x-0 bottom-0 p-4 text-white">
                  <p className="font-display text-2xl font-semibold leading-tight">{d.name}</p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-xs text-white/85">
                    {d.country} · <BookOpenCheck className="h-3 w-3" aria-hidden /> {d.passages} passages
                  </p>
                </div>
                <span className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-white/90 text-[#0f2430] opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100">
                  <ArrowUpRight className="h-4 w-4" aria-hidden />
                </span>
              </Link>
            </motion.li>
          ))}
        </ul>

        <ul className="mt-8 flex flex-wrap gap-2" aria-label="All guidebook cities">
          {rest.map((d) => (
            <li key={d.name}>
              <Link href={`/plan?destination=${encodeURIComponent(d.name)}`} className="chip !py-1.5 !text-[0.8rem]">
                {d.name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
