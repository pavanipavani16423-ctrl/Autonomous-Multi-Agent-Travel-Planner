"use client";

import { useState } from "react";
import { TripForm } from "@/components/composer/trip-form";
import { WakingNotice } from "@/components/ui/waking";
import { useCreateTrip } from "@/lib/use-create-trip";
import { defaultRequest } from "@/lib/validate";

export function PlanClient({ destination }: { destination: string }) {
  const [initial] = useState(() => defaultRequest({ destination }));
  const { state, submit } = useCreateTrip();
  return (
    <div className="card mt-8 p-5 sm:p-8">
      {state.status === "waking" && (
        <div className="mb-6">
          <WakingNotice compact elapsedMs={state.elapsedMs} />
        </div>
      )}
      {state.status === "error" && state.offline && (
        <div className="mb-6">
          <WakingNotice compact failed message={state.message} />
        </div>
      )}
      <TripForm
        initial={initial}
        onSubmit={submit}
        submitting={state.status === "submitting" || state.status === "waking"}
        serverError={state.status === "error" && !state.offline ? state.message : null}
      />
    </div>
  );
}
