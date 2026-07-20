/** Download endpoint: the full public timeseries of one ministry as JSON. */
import type { APIRoute } from "astro";
import { loadCabinet, loadIndex, loadTimeseries } from "../../lib/published";

export function getStaticPaths() {
  const index = loadIndex();
  return loadCabinet(index)
    .filter((m) => (loadTimeseries(m.slug)?.series.length ?? 0) > 0)
    .map((m) => ({ params: { ministry: m.slug } }));
}

export const GET: APIRoute = ({ params }) => {
  const timeseries = loadTimeseries(params.ministry!);
  return new Response(JSON.stringify(timeseries, null, 2), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
};
