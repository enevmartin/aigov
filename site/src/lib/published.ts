/**
 * The site's ONLY data access layer: build-time reads of ../published/.
 * No APIs, no databases, no core imports — invariant #2 of the constitution.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import matter from "gray-matter";
import { marked } from "marked";

const PUBLISHED_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../published",
);

export interface IndexEntry {
  date: string;
  artifacts: string[];
}

export interface PublishedIndex {
  ministries: Record<string, IndexEntry[]>;
  names: Record<string, string>;
}

export interface Source {
  url: string;
  title: string;
  retrieved: string;
}

export interface ReportMeta {
  ministry: string;
  date: string;
  title: string;
  summary: string;
  sources: Source[];
}

export interface Series {
  name: string;
  unit: string;
  labels: string[];
  values: number[];
  source: Source;
}

export interface Aggregates {
  ministry: string;
  date: string;
  series: Series[];
}

export interface NewsItem {
  title: string;
  summary: string;
  source: Source;
  published?: string | null;
}

export interface NewsDigest {
  ministry: string;
  date: string;
  items: NewsItem[];
}

export interface PublishedDay {
  slug: string;
  date: string;
  report: ReportMeta;
  reportHtml: string;
  aggregates: Aggregates;
  news: NewsDigest | null;
}

/** Read published/index.json — the table of contents. */
export function loadIndex(): PublishedIndex {
  const indexPath = path.join(PUBLISHED_ROOT, "index.json");
  if (!fs.existsSync(indexPath)) {
    return { ministries: {}, names: {} };
  }
  return JSON.parse(fs.readFileSync(indexPath, "utf-8")) as PublishedIndex;
}

/** Display name for a ministry slug (falls back to the slug). */
export function ministryName(index: PublishedIndex, slug: string): string {
  return index.names[slug] ?? slug;
}

/** Sorted dates (newest first) with published artifacts for a ministry. */
export function datesFor(index: PublishedIndex, slug: string): string[] {
  return (index.ministries[slug] ?? [])
    .map((entry) => entry.date)
    .sort()
    .reverse();
}

/** Load one published day of one ministry (report + aggregates + news). */
export function loadDay(slug: string, date: string): PublishedDay {
  const dayDir = path.join(PUBLISHED_ROOT, slug, date);
  const raw = fs.readFileSync(path.join(dayDir, "report.md"), "utf-8");
  const parsed = matter(raw);
  const aggregates = JSON.parse(
    fs.readFileSync(path.join(dayDir, "aggregates.json"), "utf-8"),
  ) as Aggregates;

  const newsPath = path.join(dayDir, "news.json");
  const news = fs.existsSync(newsPath)
    ? (JSON.parse(fs.readFileSync(newsPath, "utf-8")) as NewsDigest)
    : null;

  return {
    slug,
    date,
    report: parsed.data as ReportMeta,
    reportHtml: marked.parse(parsed.content, { async: false }) as string,
    aggregates,
    news,
  };
}

/** Latest published day for a ministry, or null if nothing published yet. */
export function loadLatest(index: PublishedIndex, slug: string): PublishedDay | null {
  const [latest] = datesFor(index, slug);
  return latest ? loadDay(slug, latest) : null;
}

/** Initials for the avatar placeholder, e.g. "Министерство на финансите" -> "МФ". */
export function initials(name: string): string {
  const stop = new Set(["на", "и", "по", "за"]);
  const words = name.split(/\s+/).filter((w) => w && !stop.has(w.toLowerCase()));
  return words
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}
