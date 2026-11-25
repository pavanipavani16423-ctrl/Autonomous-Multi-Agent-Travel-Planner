import type { Metadata } from "next";
import { SiteFooter } from "@/components/site/footer";
import { TripsClient } from "./trips-client";

export const metadata: Metadata = { title: "My trips" };

export default function TripsPage() {
  return (
    <>
      <div className="mx-auto min-h-[70vh] max-w-7xl px-4 pb-24 pt-12 sm:px-6">
        <p className="eyebrow">My trips</p>
        <h1 className="mt-3 font-display text-4xl font-semibold sm:text-5xl">
          Your <span className="display-italic text-coral">travels</span>, planned.
        </h1>
        <p className="mt-3 max-w-xl text-ink-2">Trips planned from this browser. No account needed — they&apos;re tied to an anonymous id stored on this device.</p>
        <TripsClient />
      </div>
      <SiteFooter />
    </>
  );
}
