/** RSS feed of every published report (иронично задължително). */
import type { APIRoute } from "astro";
import {
  allPublications,
  loadCabinet,
  loadIndex,
  ministryName,
  TYPE_LABELS,
} from "../lib/published";

const SITE = "https://aigov.bg";

function escapeXml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export const GET: APIRoute = () => {
  const index = loadIndex();
  const slugs = new Set([
    ...loadCabinet(index).map((m) => m.slug),
    ...Object.keys(index.ministries),
  ]);
  const items = [...slugs]
    .flatMap((slug) => allPublications(index, slug))
    .filter((p) => p.report)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 50)
    .map((p) => {
      const link = `${SITE}/${p.slug}/${p.date}/`;
      const title = `${ministryName(index, p.slug)}: ${p.report!.title}`;
      const label = TYPE_LABELS[p.type] ?? p.type;
      return `    <item>
      <title>${escapeXml(title)}</title>
      <link>${link}</link>
      <guid isPermaLink="false">${p.slug}/${p.date}/${p.type}</guid>
      <pubDate>${new Date(`${p.date}T08:00:00Z`).toUTCString()}</pubDate>
      <category>${escapeXml(label)}</category>
      <description>${escapeXml(p.report!.summary)}</description>
    </item>`;
    })
    .join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>aigov.bg — публикации на AI кабинета</title>
    <link>${SITE}/</link>
    <description>Независим граждански AI експеримент: цитирани анализи върху публични данни за България. Не е свързан с правителството.</description>
    <language>bg</language>
${items}
  </channel>
</rss>
`;
  return new Response(xml, {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" },
  });
};
