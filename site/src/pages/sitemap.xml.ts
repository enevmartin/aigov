/** Sitemap over every static route the build produces. */
import type { APIRoute } from "astro";
import { datesFor, loadCabinet, loadIndex } from "../lib/published";

const SITE = "https://aigov.bg";

export const GET: APIRoute = () => {
  const index = loadIndex();
  const slugs = new Set([
    ...loadCabinet(index).map((m) => m.slug),
    ...Object.keys(index.ministries),
  ]);

  const urls: string[] = [
    "/",
    "/analizi/",
    "/planove/",
    "/danni/",
    "/system/",
    "/za-proekta/",
    "/arhiv/",
  ];
  for (const slug of slugs) {
    urls.push(`/${slug}/`);
    for (const date of datesFor(index, slug)) {
      urls.push(`/${slug}/${date}/`);
    }
  }

  const body = urls
    .map((u) => `  <url><loc>${SITE}${u}</loc></url>`)
    .join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${body}
</urlset>
`;
  return new Response(xml, {
    headers: { "Content-Type": "application/xml; charset=utf-8" },
  });
};
