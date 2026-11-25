import type { CoveredDestination } from "./types";

/**
 * Offline fallback for GET /api/destinations — the 65 guidebook cities in data/corpus.jsonl with their
 * passage counts. The live endpoint wins whenever the API is reachable.
 */
const RAW: [string, string, number][] = [
  ["London", "United Kingdom", 309], ["Hong Kong", "China", 291], ["Singapore", "Singapore", 285],
  ["New York City", "United States", 278], ["Chicago", "United States", 238], ["Shanghai", "China", 227],
  ["Mexico City", "Mexico", 217], ["Paris", "France", 216], ["Berlin", "Germany", 212], ["Sydney", "Australia", 208],
  ["San Francisco", "United States", 205], ["Bangkok", "Thailand", 201], ["Los Angeles", "United States", 193],
  ["Cape Town", "South Africa", 178], ["Istanbul", "Turkey", 176], ["Hanoi", "Vietnam", 170], ["Vienna", "Austria", 169],
  ["Rome", "Italy", 167], ["Bali", "Indonesia", 165], ["Athens", "Greece", 161], ["Mumbai", "India", 159],
  ["Toronto", "Canada", 156], ["Amsterdam", "Netherlands", 153], ["Beijing", "China", 150], ["Marrakech", "Morocco", 148],
  ["Buenos Aires", "Argentina", 143], ["Venice", "Italy", 143], ["Copenhagen", "Denmark", 138], ["Oslo", "Norway", 134],
  ["Tokyo", "Japan", 134], ["Florence", "Italy", 133], ["Stockholm", "Sweden", 132], ["Rio de Janeiro", "Brazil", 131],
  ["Zurich", "Switzerland", 130], ["Reykjavík", "Iceland", 129], ["Barcelona", "Spain", 128], ["Prague", "Czechia", 126],
  ["Jaipur", "India", 124], ["Melbourne", "Australia", 121], ["Doha", "Qatar", 113], ["Cairo", "Egypt", 110],
  ["Lisbon", "Portugal", 106], ["Abu Dhabi", "United Arab Emirates", 104], ["Bangalore", "India", 101],
  ["Edinburgh", "United Kingdom", 99], ["Dubai", "United Arab Emirates", 97], ["Delhi", "India", 96],
  ["Kuala Lumpur", "Malaysia", 92], ["Seoul", "South Korea", 90], ["Varanasi", "India", 90], ["Kochi", "India", 89],
  ["Chennai", "India", 88], ["Kyoto", "Japan", 86], ["Kolkata", "India", 85], ["Tashkent", "Uzbekistan", 82],
  ["Lima", "Peru", 81], ["Hyderabad", "India", 81], ["Amritsar", "India", 73], ["Goa", "India", 68], ["Udaipur", "India", 68],
  ["Auckland", "New Zealand", 56], ["Pondicherry", "India", 52], ["Rishikesh", "India", 50], ["Darjeeling", "India", 49],
  ["Agra", "India", 39],
];

export const COVERED_FALLBACK: CoveredDestination[] = RAW.map(([name, country, passages]) => ({ name, country, passages }));

/** Wikipedia article titles where the city name alone is ambiguous or redirects poorly. */
export const WIKI_TITLE: Record<string, string> = {
  Bali: "Ubud",
  Goa: "Panaji",
  "New York City": "New York City",
  Marrakech: "Marrakesh",
  Kochi: "Kochi",
  Pondicherry: "Puducherry",
  Bangalore: "Bangalore",
};
