"use client";

import {
  BadgeCheck,
  BedDouble,
  BookOpen,
  CalendarDays,
  Check,
  ClipboardList,
  Download,
  Gauge,
  Link2,
  Map as MapIcon,
  RotateCcw,
  Route,
  Sparkles,
  UtensilsCrossed,
  Users,
  Wallet,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { Photo } from "@/components/ui/photo";
import { Tabs, TabPanel, type TabDef } from "@/components/ui/tabs";
import { CATEGORY } from "@/lib/categories";
import { cn, formatDateRange, formatMoney, travellers } from "@/lib/format";
import type { StreamState } from "@/lib/stream-state";
import type { TripPlan } from "@/lib/types";
import { useMediaQuery } from "@/lib/use-reduced-motion";
import { BudgetPanel } from "./budget-panel";
import { CitationsProvider } from "./citations";
import { DayTabs, DayView } from "./itinerary";
import { FoodPanel, StaysPanel } from "./places";
import { PreTripPanel } from "./pretrip-panel";
import { PrintView } from "./print-view";
import { QualityPanel } from "./quality-panel";
import { RefineDock } from "./refine-dock";
import { SourcesPanel } from "./sources-panel";
import type { MapPin } from "./trip-map";
import { WeatherStrip } from "./weather-strip";

const TripMap = dynamic(() => import("./trip-map"), {
  ssr: false,
  loading: () => <div className="skeleton h-full w-full rounded-[1.25rem]" />,
});

type Tab = "itinerary" | "stays" | "food" | "budget" | "pretrip" | "sources" | "quality";
const MAP_TABS: Tab[] = ["itinerary", "stays", "food"];

/** Activities whose content changed between two revisions — those cards animate and get a badge. */
function diffActivities(prev: TripPlan, next: TripPlan) {
  const old = new Map<string, string>();
  prev.days.forEach((d) => d.activities.forEach((a) => old.set(a.id, JSON.stringify(a))));
  const changed = new Set<string>();
  next.days.forEach((d) => d.activities.forEach((a) => old.get(a.id) !== JSON.stringify(a) && changed.add(a.id)));
  return changed;
}

export function Workspace({
  plan,
  stream,
  refining,
  refineError,
  demo,
  onRefine,
  onReplay,
}: {
  plan: TripPlan;
  stream: StreamState;
  refining: boolean;
  refineError?: string | null;
  demo?: boolean;
  onRefine: (message: string) => void;
  onReplay: () => void;
}) {
  const [tab, setTab] = useState<Tab>("itinerary");
  const [dayIdx, setDayIdx] = useState(0);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [layers, setLayers] = useState({ stays: false, food: false });
  const [mapOpen, setMapOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  // Track revisions to highlight what a refinement changed (derived-state-from-props pattern).
  const [seen, setSeen] = useState(plan);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  if (seen !== plan) {
    // The same revision can arrive twice (live `plan` event, then a refetch): keep the badges then.
    const diff = seen.revision !== plan.revision ? diffActivities(seen, plan) : changed;
    setSeen(plan);
    setChanged(diff);
    if (seen.revision !== plan.revision) {
      setToast(`Revision ${plan.revision} ready${diff.size ? ` · ${diff.size} stop${diff.size === 1 ? "" : "s"} changed` : ""}`);
      const firstChangedDay = plan.days.findIndex((d) => d.activities.some((a) => diff.has(a.id)));
      if (firstChangedDay >= 0) setDayIdx(firstChangedDay);
    }
  }

  const day = plan.days[Math.min(dayIdx, plan.days.length - 1)];
  const r = plan.request;
  const pax = r.adults + r.children;
  const nights = Math.max(1, plan.days.length - 1);

  const { pins, route } = useMemo(() => {
    const out: MapPin[] = [];
    let line: [number, number][] = [];
    if (tab === "itinerary" && day) {
      day.activities.forEach((a, i) => {
        if (a.location) out.push({ id: a.id, kind: "activity", lat: a.location.lat, lon: a.location.lon, title: a.title, subtitle: `${a.time} · ${a.place ?? ""}`, n: i + 1, color: CATEGORY[a.category]?.color });
      });
      line = day.activities.filter((a) => a.location).map((a) => [a.location!.lon, a.location!.lat]);
    }
    if (tab === "stays" || (tab === "itinerary" && layers.stays)) {
      plan.stays.forEach((s, i) => s.location && out.push({ id: `stay-${i}`, kind: "stay", lat: s.location.lat, lon: s.location.lon, title: s.name, subtitle: `${s.area} · ${formatMoney(s.price_per_night)}/night` }));
    }
    if (tab === "food" || (tab === "itinerary" && layers.food)) {
      plan.food.forEach((f, i) => f.location && out.push({ id: `food-${i}`, kind: "food", lat: f.location.lat, lon: f.location.lon, title: f.name, subtitle: f.cuisine }));
    }
    return { pins: out, route: line };
  }, [tab, day, plan, layers]);

  const tabs: TabDef<Tab>[] = [
    { id: "itinerary", label: "Itinerary", icon: <Route className="h-4 w-4" aria-hidden /> },
    { id: "stays", label: "Stays", icon: <BedDouble className="h-4 w-4" aria-hidden /> },
    { id: "food", label: "Food", icon: <UtensilsCrossed className="h-4 w-4" aria-hidden /> },
    { id: "budget", label: "Budget", icon: <Wallet className="h-4 w-4" aria-hidden /> },
    { id: "pretrip", label: "Pre-trip", icon: <ClipboardList className="h-4 w-4" aria-hidden /> },
    { id: "sources", label: "Sources", icon: <BookOpen className="h-4 w-4" aria-hidden />, badge: <span className="font-mono text-[10px] opacity-60">{plan.citations.length}</span> },
    { id: "quality", label: "Quality", icon: <Gauge className="h-4 w-4" aria-hidden /> },
  ];
  const showMap = MAP_TABS.includes(tab);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setToast("Share link copied");
    } catch {
      setToast("Couldn't copy — use the address bar");
    }
  };

  const mapEl = (
    <div className="relative h-full w-full overflow-hidden rounded-[1.25rem] border border-line bg-bg-2 shadow-card">
      <TripMap
        center={plan.destination.location}
        pins={pins}
        route={tab === "itinerary" ? route : []}
        focusId={focusId}
        onPinClick={(id) => {
          setFocusId(id);
          document.querySelector(`[data-pin-target="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }}
        className="absolute inset-0"
      />
      {tab === "itinerary" && (
        <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
          <span className="inline-flex items-center gap-1 rounded-full bg-surface/95 px-2.5 py-1.5 text-xs font-bold shadow-card backdrop-blur">
            <Route className="h-3.5 w-3.5 text-coral" aria-hidden /> Day {day.day}
          </span>
          {(["stays", "food"] as const).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={layers[k]}
              onClick={() => setLayers((l) => ({ ...l, [k]: !l[k] }))}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-bold shadow-card backdrop-blur transition",
                layers[k] ? "bg-ink text-bg" : "bg-surface/95 text-ink-2 hover:text-ink",
              )}
            >
              {k === "stays" ? <BedDouble className="h-3.5 w-3.5" aria-hidden /> : <UtensilsCrossed className="h-3.5 w-3.5" aria-hidden />}
              {k === "stays" ? "Stays" : "Food"}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <CitationsProvider citations={plan.citations} onShowAll={() => setTab("sources")}>
      <div className="no-print mx-auto max-w-7xl px-4 pb-40 pt-5 sm:px-6">
        {/* header */}
        <motion.header initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }} className="relative overflow-hidden rounded-[1.75rem]">
          <Photo title={plan.destination.name} src={plan.destination.image} alt={`${plan.destination.name}, ${plan.destination.country}`} className="absolute inset-0" sizes="100vw" priority width={1280} />
          <div className="absolute inset-0 bg-gradient-to-t from-[#061217]/90 via-[#061217]/45 to-[#061217]/10" />
          <div className="relative flex min-h-[15rem] flex-col justify-end p-5 text-white sm:min-h-[16.5rem] sm:p-7">
            <div className="mb-auto flex flex-wrap gap-2 pb-4 sm:absolute sm:right-6 sm:top-6 sm:justify-end sm:pb-0">
              {demo && <span className="rounded-full bg-sun px-3 py-1.5 text-xs font-bold text-[#0f2430]">Sample trip</span>}
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 text-xs font-bold backdrop-blur" title="Overall confidence from the critic and quality scores">
                <BadgeCheck className="h-3.5 w-3.5" aria-hidden /> {Math.round(plan.quality.confidence * 100)}% confidence
              </span>
              <span className="rounded-full bg-white/15 px-3 py-1.5 font-mono text-xs backdrop-blur">v{plan.revision}</span>
            </div>
            <p className="text-sm font-semibold text-white/80">
              {plan.destination.name}, {plan.destination.country}
            </p>
            <h1 className="mt-1 max-w-3xl font-display text-3xl font-semibold leading-[1.05] sm:text-[2.75rem]">{plan.title}</h1>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs font-semibold">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 backdrop-blur">
                <CalendarDays className="h-3.5 w-3.5" aria-hidden /> {formatDateRange(r.start_date, r.end_date)} · {plan.days.length} days
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 backdrop-blur">
                <Users className="h-3.5 w-3.5" aria-hidden /> {travellers(r.adults, r.children)}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 backdrop-blur">
                <Wallet className="h-3.5 w-3.5" aria-hidden /> {formatMoney(plan.budget.total)} of {formatMoney(plan.budget.limit)}
              </span>
              <span className="rounded-full bg-white/15 px-3 py-1.5 capitalize backdrop-blur">
                {r.pace} · {r.stay_style}
              </span>
            </div>
          </div>
        </motion.header>

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
          <div>
            <p className="text-[1rem] leading-relaxed text-ink-2">{plan.summary}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={() => window.print()}>
                <Download className="h-4 w-4" aria-hidden /> Download PDF
              </button>
              <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={copyLink}>
                <Link2 className="h-4 w-4" aria-hidden /> Copy share link
              </button>
              <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={onReplay} title="Replay the agents' run in mission control">
                <RotateCcw className="h-4 w-4" aria-hidden /> Replay run
              </button>
            </div>
          </div>
          {plan.days.some((d) => d.weather) && (
            <div className="min-w-0">
              <WeatherStrip days={plan.days.flatMap((d) => (d.weather ? [d.weather] : []))} compact />
              {plan.weather_overview && <p className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-ink-3" title={plan.weather_overview}>{plan.weather_overview}</p>}
            </div>
          )}
        </div>

        {/* tabs */}
        <div className="sticky top-16 z-20 -mx-4 mt-6 border-b border-line bg-bg/85 px-4 py-2.5 backdrop-blur-xl sm:-mx-6 sm:px-6">
          <Tabs tabs={tabs} value={tab} onChange={setTab} label="Trip sections" idPrefix="trip" />
        </div>

        <div className={cn("mt-6", showMap && "lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] lg:gap-6")}>
          <div className="min-w-0">
            <TabPanel id="itinerary" prefix="trip" active={tab === "itinerary"}>
              <DayTabs days={plan.days} value={dayIdx} onChange={(i) => { setDayIdx(i); setFocusId(null); }} />
              {day && <DayView day={day} focusId={focusId} changedIds={changed} onFocus={setFocusId} />}
            </TabPanel>
            <TabPanel id="stays" prefix="trip" active={tab === "stays"}>
              <StaysPanel stays={plan.stays} nights={nights} focusId={focusId} onFocus={setFocusId} />
            </TabPanel>
            <TabPanel id="food" prefix="trip" active={tab === "food"}>
              <FoodPanel food={plan.food} diet={r.diet} currency={r.currency} focusId={focusId} onFocus={setFocusId} />
            </TabPanel>
            <TabPanel id="budget" prefix="trip" active={tab === "budget"}>
              <BudgetPanel budget={plan.budget} travellers={pax} />
            </TabPanel>
            <TabPanel id="pretrip" prefix="trip" active={tab === "pretrip"}>
              <PreTripPanel pre={plan.pre_trip} tripId={plan.trip_id} />
            </TabPanel>
            <TabPanel id="sources" prefix="trip" active={tab === "sources"}>
              <SourcesPanel plan={plan} />
            </TabPanel>
            <TabPanel id="quality" prefix="trip" active={tab === "quality"}>
              <QualityPanel plan={plan} />
            </TabPanel>
          </div>
          {showMap && isDesktop && <aside className="sticky top-[8.5rem] hidden h-[calc(100dvh-10.5rem)] min-h-[28rem] lg:block">{mapEl}</aside>}
        </div>
      </div>

      {/* phone / tablet: the map is a toggleable sheet */}
      {showMap && !isDesktop && (
        <>
          <button
            type="button"
            onClick={() => setMapOpen(true)}
            className="no-print fixed bottom-24 right-4 z-30 inline-flex items-center gap-2 rounded-full bg-ink px-4 py-3 text-sm font-bold text-bg shadow-float"
            aria-haspopup="dialog"
            aria-label="Show map"
          >
            <MapIcon className="h-4 w-4" aria-hidden /> Map
          </button>
          <AnimatePresence>
            {mapOpen && (
              <motion.div
                role="dialog"
                aria-modal="true"
                aria-label="Trip map"
                className="no-print fixed inset-x-0 bottom-0 z-50 h-[78dvh] rounded-t-[1.75rem] border-t border-line bg-bg p-3 shadow-float"
                initial={{ y: "100%" }}
                animate={{ y: 0 }}
                exit={{ y: "100%" }}
                transition={{ type: "spring", stiffness: 300, damping: 34 }}
                onKeyDown={(e) => e.key === "Escape" && setMapOpen(false)}
              >
                <div className="mb-2 flex items-center justify-between px-1">
                  <p className="text-sm font-bold">{tab === "itinerary" ? `Day ${day.day} route` : tab === "stays" ? "Stays" : "Food"}</p>
                  <button type="button" autoFocus onClick={() => setMapOpen(false)} className="rounded-full p-2 hover:bg-bg-2" aria-label="Close map">
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <div className="h-[calc(100%-3rem)]">{mapEl}</div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}

      <RefineDock
        revision={plan.revision}
        busy={refining}
        state={stream}
        error={refineError}
        onSubmit={onRefine}
        suggestions={[`Make day ${Math.min(2, plan.days.length)} more relaxed`, "Swap the hotel for something cheaper", "Add more vegetarian street food"]}
      />

      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast}
            role="status"
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            onAnimationComplete={() => setTimeout(() => setToast((t) => (t === toast ? null : t)), 2600)}
            className="no-print fixed left-1/2 top-20 z-50 -translate-x-1/2 rounded-full bg-ink px-4 py-2.5 text-sm font-semibold text-bg shadow-float"
          >
            <span className="inline-flex items-center gap-2">
              {toast.startsWith("Revision") ? <Sparkles className="h-4 w-4 text-sun" aria-hidden /> : <Check className="h-4 w-4 text-sun" aria-hidden />}
              {toast}
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      <PrintView plan={plan} />
    </CitationsProvider>
  );
}
