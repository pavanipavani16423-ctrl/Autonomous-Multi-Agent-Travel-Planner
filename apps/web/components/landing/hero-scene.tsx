"use client";

import { AnimatePresence, motion, useMotionValue, useSpring, useTransform, type MotionValue } from "motion/react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { Globe, type GlobeCity } from "./globe";

const CITIES: GlobeCity[] = [
  { name: "Kyoto", lat: 35.01, lon: 135.77 },
  { name: "Bengaluru", lat: 12.97, lon: 77.59 },
  { name: "Delhi", lat: 28.61, lon: 77.21 },
  { name: "Mumbai", lat: 19.08, lon: 72.88 },
  { name: "Lisbon", lat: 38.72, lon: -9.14 },
  { name: "Marrakech", lat: 31.63, lon: -8.0 },
  { name: "Reykjavík", lat: 64.15, lon: -21.94 },
  { name: "Istanbul", lat: 41.01, lon: 28.95 },
  { name: "Bali", lat: -8.34, lon: 115.09 },
];
const ROUTES: [string, string][] = [
  ["Bengaluru", "Kyoto"],
  ["Mumbai", "Lisbon"],
  ["Delhi", "Reykjavík"],
  ["Bengaluru", "Bali"],
  ["Delhi", "Istanbul"],
  ["Mumbai", "Marrakech"],
];

const W = "https://thumb.wikimedia.org/wikipedia/commons/thumb";
const CARDS = [
  { city: "Kyoto", meta: "4 days · temples & tea", src: `${W}/a/ae/Kiyomizu-dera%2C_Kyoto%2C_November_2016_-02.jpg/500px-Kiyomizu-dera%2C_Kyoto%2C_November_2016_-02.jpg`, pos: "left-[-4%] top-[6%]", depth: 1.4, rot: -6, dur: 6.5 },
  { city: "Lisbon", meta: "3 days · trams & tiles", src: `${W}/4/41/Lisbon_%2836831596786%29_%28cropped%29.jpg/500px-Lisbon_%2836831596786%29_%28cropped%29.jpg`, pos: "right-[-2%] top-[2%]", depth: 0.8, rot: 5, dur: 7.5 },
  { city: "Jaipur", meta: "5 days · palaces", src: `${W}/4/41/East_facade_Hawa_Mahal_Jaipur_from_ground_level_%28July_2022%29_-_img_01.jpg/500px-East_facade_Hawa_Mahal_Jaipur_from_ground_level_%28July_2022%29_-_img_01.jpg`, pos: "right-[-6%] top-[52%]", depth: 1.8, rot: -4, dur: 8 },
  { city: "Reykjavík", meta: "4 days · aurora", src: `${W}/0/04/Reykjav%C3%ADk%2C_view_from_Hallgr%C3%ADmskirkja_%282%29.jpg/500px-Reykjav%C3%ADk%2C_view_from_Hallgr%C3%ADmskirkja_%282%29.jpg`, pos: "left-[2%] bottom-[4%]", depth: 1.1, rot: 4, dur: 7 },
];

const TICKER = [
  { k: "MCP", v: "weather.forecast", p: "live", c: "var(--p-live)" },
  { k: "RAG", v: "12 guidebook hits · 0.88", p: "guidebook", c: "var(--p-guide)" },
  { k: "MCP", v: "places.search_pois · 54", p: "live", c: "var(--p-live)" },
  { k: "A2A", v: "Budget Analyst · 88% of limit", p: "received", c: "var(--coral)" },
  { k: "Critic", v: "8/8 checks passed", p: "done", c: "var(--p-live)" },
];

function FloatingCard({ card, mx, my, index }: { card: (typeof CARDS)[number]; mx: MotionValue<number>; my: MotionValue<number>; index: number }) {
  const x = useTransform(mx, (v) => v * card.depth * 18);
  const y = useTransform(my, (v) => v * card.depth * 14);
  return (
    <motion.div className={`absolute ${card.pos} z-10 w-[34%] max-w-[190px]`} style={{ x, y }}>
      <motion.figure
        initial={{ opacity: 0, y: 30, rotate: 0 }}
        animate={{ opacity: 1, y: [0, -9, 0], rotate: card.rot }}
        transition={{
          opacity: { duration: 0.6, delay: 0.5 + index * 0.15 },
          rotate: { duration: 0.8, delay: 0.5 + index * 0.15 },
          y: { duration: card.dur, repeat: Infinity, ease: "easeInOut", delay: index * 0.4 },
        }}
        className="overflow-hidden rounded-[1.1rem] border border-white/40 bg-surface p-1.5 shadow-float"
      >
        <div className="relative aspect-[4/3] overflow-hidden rounded-[0.8rem]">
          <Image src={card.src} alt={card.city} fill sizes="190px" className="object-cover" priority={index < 2} />
        </div>
        <figcaption className="px-1.5 pb-1 pt-2">
          <span className="block font-display text-[0.95rem] font-semibold leading-tight">{card.city}</span>
          <span className="block text-[0.7rem] text-ink-3">{card.meta}</span>
        </figcaption>
      </motion.figure>
    </motion.div>
  );
}

function Ticker() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % TICKER.length), 2400);
    return () => clearInterval(t);
  }, []);
  const item = TICKER[i];
  return (
    <div className="absolute bottom-[-2%] left-1/2 z-20 -translate-x-1/2" aria-hidden>
      <div className="flex h-10 min-w-[17rem] items-center gap-2 overflow-hidden rounded-full border border-line bg-surface/90 px-3 font-mono text-[11px] shadow-float backdrop-blur">
        <span className="relative flex h-2 w-2">
          <span className="pulse-ring absolute inset-0 rounded-full" style={{ background: item.c }} />
          <span className="relative h-2 w-2 rounded-full" style={{ background: item.c }} />
        </span>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={i}
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -12, opacity: 0, transition: { duration: 0.15 } }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            className="flex items-center gap-2 whitespace-nowrap"
          >
            <span className="font-semibold text-ink">{item.k}</span>
            <span className="text-ink-2">{item.v}</span>
            <span className="rounded-full px-1.5 py-0.5 uppercase" style={{ color: item.c, background: "var(--bg-2)" }}>
              {item.p}
            </span>
          </motion.span>
        </AnimatePresence>
      </div>
    </div>
  );
}

/** The animated hero: dotted globe with drawing route arcs, parallax photo cards, live agent ticker. */
export function HeroScene() {
  const rawX = useMotionValue(0);
  const rawY = useMotionValue(0);
  const mx = useSpring(rawX, { stiffness: 60, damping: 18 });
  const my = useSpring(rawY, { stiffness: 60, damping: 18 });

  return (
    <div
      className="relative mx-auto aspect-square w-full max-w-[600px]"
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        rawX.set(((e.clientX - r.left) / r.width - 0.5) * 2);
        rawY.set(((e.clientY - r.top) / r.height - 0.5) * 2);
      }}
      onPointerLeave={() => {
        rawX.set(0);
        rawY.set(0);
      }}
    >
      <motion.div
        className="absolute inset-[8%]"
        initial={{ opacity: 0, scale: 0.92 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
      >
        <Globe cities={CITIES} routes={ROUTES} className="h-full w-full" />
      </motion.div>
      {CARDS.map((c, i) => (
        <FloatingCard key={c.city} card={c} mx={mx} my={my} index={i} />
      ))}
      <Ticker />
    </div>
  );
}
