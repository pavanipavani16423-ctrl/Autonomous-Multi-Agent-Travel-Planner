import type { Metadata } from "next";
import { TripClient } from "@/components/trip/trip-client";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: id === "demo" ? "Sample trip · Kyoto" : "Your trip" };
}

export default async function TripPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Keyed so navigating between trips starts from a clean stream state.
  return <TripClient key={id} id={decodeURIComponent(id)} />;
}
