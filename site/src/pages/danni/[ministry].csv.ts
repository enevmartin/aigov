/** Download endpoint: the full public timeseries of one ministry as CSV. */
import type { APIRoute } from "astro";
import { loadCabinet, loadIndex, loadTimeseries } from "../../lib/published";

export function getStaticPaths() {
  const index = loadIndex();
  return loadCabinet(index)
    .filter((m) => (loadTimeseries(m.slug)?.series.length ?? 0) > 0)
    .map((m) => ({ params: { ministry: m.slug } }));
}

function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

export const GET: APIRoute = ({ params }) => {
  const timeseries = loadTimeseries(params.ministry!);
  const rows = [
    ["ministry", "metric", "unit", "label", "value", "published", "source_url"],
  ];
  for (const series of timeseries?.series ?? []) {
    for (const point of series.points) {
      rows.push([
        timeseries!.ministry,
        series.name,
        series.unit,
        point.label,
        String(point.value),
        point.published,
        series.source.url,
      ]);
    }
  }
  const body = rows.map((row) => row.map(csvCell).join(",")).join("\n") + "\n";
  return new Response("﻿" + body, {
    headers: { "Content-Type": "text/csv; charset=utf-8" },
  });
};
