import { formatDateRange, formatDuration, formatMoney, parseISODate, travellers } from "@/lib/format";
import type { TripPlan } from "@/lib/types";

/** A clean, ink-only itinerary that only exists on paper (Download PDF → window.print()). */
export function PrintView({ plan }: { plan: TripPlan }) {
  const r = plan.request;
  return (
    <div className="print-only text-[11pt] leading-snug text-black">
      <header className="border-b-2 border-black pb-3">
        <p className="text-[9pt] uppercase tracking-widest">Voyager itinerary · revision {plan.revision}</p>
        <h1 className="font-display text-[22pt] font-semibold leading-tight">{plan.title}</h1>
        <p>
          {plan.destination.name}, {plan.destination.country} · {formatDateRange(r.start_date, r.end_date)} · {travellers(r.adults, r.children)} · budget{" "}
          {formatMoney({ amount: r.budget, currency: r.currency })}
        </p>
        <p className="mt-2 text-[10pt]">{plan.summary}</p>
      </header>

      {plan.days.map((d) => (
        <section key={d.day} className="print-avoid mt-5">
          <h2 className="text-[13pt] font-bold">
            Day {d.day} — {parseISODate(d.date).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}: {d.title}
          </h2>
          {d.weather && (
            <p className="text-[9pt]">
              Weather: {d.weather.summary}, {Math.round(d.weather.t_min)}–{Math.round(d.weather.t_max)} °C ({d.weather.provenance})
            </p>
          )}
          <table className="mt-1 w-full border-collapse text-[10pt]">
            <tbody>
              {d.activities.map((a) => (
                <tr key={a.id} className="border-b border-gray-300 align-top">
                  <td className="w-14 py-1 pr-2 font-mono">{a.time}</td>
                  <td className="py-1 pr-2">
                    <strong>{a.title}</strong> <span className="text-gray-600">({formatDuration(a.duration_min)})</span>
                    <br />
                    {a.description}
                    {a.place ? <span className="text-gray-600"> — {a.place}</span> : null}
                    {a.citations.length ? <span className="text-gray-500"> [{a.citations.join(", ")}]</span> : null}
                  </td>
                  <td className="w-24 py-1 text-right">{a.cost.amount ? formatMoney(a.cost) : "Free"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      <section className="print-avoid mt-6">
        <h2 className="text-[13pt] font-bold">Where to stay</h2>
        <ul className="list-disc pl-5 text-[10pt]">
          {plan.stays.map((s, i) => (
            <li key={`${s.name}-${i}`}>
              <strong>{s.name}</strong> ({s.area}) — {formatMoney(s.price_per_night)}/night, {s.provenance}. {s.why}
            </li>
          ))}
        </ul>
      </section>
      <section className="print-avoid mt-4">
        <h2 className="text-[13pt] font-bold">Where to eat</h2>
        <ul className="list-disc pl-5 text-[10pt]">
          {plan.food.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <strong>{f.name}</strong> — {f.cuisine}. Try: {f.must_try}
            </li>
          ))}
        </ul>
      </section>
      <section className="print-avoid mt-4">
        <h2 className="text-[13pt] font-bold">Budget (estimate, {plan.budget.analyst})</h2>
        <ul className="pl-5 text-[10pt]">
          {plan.budget.lines.map((l) => (
            <li key={l.category}>
              {l.category}: {formatMoney(l.amount)} — {l.note}
            </li>
          ))}
        </ul>
        <p className="mt-1 font-bold">
          Total {formatMoney(plan.budget.total)} of {formatMoney(plan.budget.limit)} ({Math.round(plan.budget.utilisation * 100)}%)
        </p>
      </section>
      <section className="print-avoid mt-4 text-[10pt]">
        <h2 className="text-[13pt] font-bold">Before you go</h2>
        <p>
          <strong>Visa:</strong> {plan.pre_trip.visa}
        </p>
        <p>
          <strong>Money:</strong> {plan.pre_trip.currency_note}
        </p>
        <p>
          <strong>Packing:</strong> {plan.pre_trip.packing.join(" · ")}
        </p>
      </section>
      <section className="mt-4 text-[8.5pt] text-gray-600">
        <h2 className="font-bold">Sources</h2>
        {plan.citations.map((c) => (
          <p key={c.id}>
            [{c.id}] {c.title} — {c.url}
          </p>
        ))}
      </section>
    </div>
  );
}
