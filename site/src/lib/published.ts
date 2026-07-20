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

export interface CabinetMember {
  slug: string;
  name: string;
  persona: string;
  persona_style: string;
  enabled: boolean;
}

export interface PublishedIndex {
  ministries: Record<string, IndexEntry[]>;
  names: Record<string, string>;
  cabinet: CabinetMember[];
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
  reviewed?: boolean;
  reviewer?: string | null;
  /** crisis_brief only */
  confidence?: "low" | "medium" | "high";
  trigger_keywords?: string[];
  /** joint_report only */
  contributors?: string[];
  /** correction only */
  corrects?: { ministry: string; date: string; type?: string | null };
}

export interface CorrectionLink {
  ministry: string;
  date: string;
  title: string;
  summary: string;
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

export interface SignalStats {
  ministry: string;
  date: string;
  total: number;
  categories: { category: string; count: number }[];
  note?: string | null;
}

export interface PublishedDay {
  slug: string;
  date: string;
  report: ReportMeta | null;
  reportHtml: string | null;
  aggregates: Aggregates | null;
  news: NewsDigest | null;
  signals: SignalStats | null;
  /** set when a later correction publication amends this day */
  correctedBy: CorrectionLink[];
}

export interface SourceHealth {
  ministry: string;
  name: string;
  url: string;
  status: "ok" | "degraded";
  consecutive_failures?: number;
  last_ok?: string | null;
  note?: string | null;
}

export interface HealthEvent {
  timestamp: string;
  kind: string;
  ministry?: string | null;
  message: string;
}

export interface SystemHealth {
  generated: string;
  sources: SourceHealth[];
  events: HealthEvent[];
  last_session?: {
    timestamp?: string;
    done?: number;
    failed?: number;
    failed_ids?: string[];
  } | null;
}

function readJson<T>(file: string): T | null {
  return fs.existsSync(file)
    ? (JSON.parse(fs.readFileSync(file, "utf-8")) as T)
    : null;
}

/** Read published/index.json — the table of contents. */
export function loadIndex(): PublishedIndex {
  const index = readJson<Partial<PublishedIndex>>(path.join(PUBLISHED_ROOT, "index.json"));
  return {
    ministries: index?.ministries ?? {},
    names: index?.names ?? {},
    cabinet: index?.cabinet ?? [],
  };
}

/** The full cabinet; falls back to published slugs when no roster exists. */
export function loadCabinet(index: PublishedIndex): CabinetMember[] {
  if (index.cabinet.length > 0) return index.cabinet;
  return Object.keys(index.ministries).map((slug) => ({
    slug,
    name: index.names[slug] ?? slug,
    persona: "",
    persona_style: "",
    enabled: true,
  }));
}

/** Display name for a ministry slug (falls back to the slug). */
export function ministryName(index: PublishedIndex, slug: string): string {
  return (
    index.names[slug] ??
    index.cabinet.find((m) => m.slug === slug)?.name ??
    slug
  );
}

/** Sorted dates (newest first) with published artifacts for a ministry. */
export function datesFor(index: PublishedIndex, slug: string): string[] {
  return (index.ministries[slug] ?? [])
    .map((entry) => entry.date)
    .sort()
    .reverse();
}

/** Load one published day of one ministry (whatever artifacts it has). */
export function loadDay(slug: string, date: string): PublishedDay {
  const dayDir = path.join(PUBLISHED_ROOT, slug, date);

  let report: ReportMeta | null = null;
  let reportHtml: string | null = null;
  const reportPath = path.join(dayDir, "report.md");
  if (fs.existsSync(reportPath)) {
    const parsed = matter(fs.readFileSync(reportPath, "utf-8"));
    report = parsed.data as ReportMeta;
    reportHtml = marked.parse(parsed.content, { async: false }) as string;
  }

  const correctedBy =
    readJson<{ corrections: CorrectionLink[] }>(
      path.join(dayDir, "corrected_by.json"),
    )?.corrections ?? [];

  return {
    slug,
    date,
    report,
    reportHtml,
    aggregates: readJson<Aggregates>(path.join(dayDir, "aggregates.json")),
    news: readJson<NewsDigest>(path.join(dayDir, "news.json")),
    signals: readJson<SignalStats>(path.join(dayDir, "signals.json")),
    correctedBy,
  };
}

/** Latest published day for a ministry, or null if nothing published yet. */
export function loadLatest(index: PublishedIndex, slug: string): PublishedDay | null {
  const [latest] = datesFor(index, slug);
  return latest ? loadDay(slug, latest) : null;
}

/** published/system/health.json, or null before the first ingest/session. */
export function loadHealth(): SystemHealth | null {
  return readJson<SystemHealth>(path.join(PUBLISHED_ROOT, "system", "health.json"));
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
