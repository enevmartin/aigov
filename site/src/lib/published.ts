/**
 * The site's ONLY data access layer: build-time reads of ../published/.
 * No APIs, no databases, no core imports — invariant #2 of the constitution.
 *
 * Layout: published/{ministry}/{date}/{type}/report.md|indicators.json|...
 *         published/{ministry}/indicators.json (latest tier-1 values, чл. 8)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import matter from "gray-matter";
import { Marked } from "marked";

const PUBLISHED_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../published",
);

export interface IndexEntry {
  date: string;
  types: Record<string, string[]>;
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
  /** event_analysis only: the tier-2 official document */
  document?: {
    url: string;
    title: string;
    publisher: string;
    kind: string;
    retrieved: string;
    sha256: string;
  };
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

export interface SignalStats {
  ministry: string;
  date: string;
  total: number;
  categories: { category: string; count: number }[];
  note?: string | null;
}

/** One publication = one task's public artifacts (ministry/date/type). */
export interface Publication {
  slug: string;
  date: string;
  type: string;
  report: ReportMeta | null;
  reportHtml: string | null;
  indicators: IndicatorSummary[];
  signals: SignalStats | null;
  correctedBy: CorrectionLink[];
}

/** One tier-1 indicator as computed by the Python collectors (чл. 8). */
export interface IndicatorSummary {
  id: string;
  name: string;
  unit: string;
  frequency: string;
  period: string;
  value: number;
  previous_period: string | null;
  previous: number | null;
  change: number | null;
  change_pct: number | null;
  year_ago: number | null;
  yoy_change: number | null;
  trend: { period: string; value: number }[];
  stale: boolean;
  source_url: string;
  source_page: string;
  publisher: string;
  collected_at: string;
}

export interface TimeseriesPoint {
  label: string;
  value: number;
  published: string;
}

export interface TimeseriesEntry {
  name: string;
  unit: string;
  points: TimeseriesPoint[];
  source: Source;
}

export interface Timeseries {
  ministry: string;
  generated: string;
  series: TimeseriesEntry[];
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

export interface SessionTaskRecord {
  id: string;
  ministry?: string | null;
  type?: string | null;
  brain?: string | null;
  duration_s: number;
  tokens?: Record<string, number> | null;
  outcome: string;
}

export interface SessionRecord {
  timestamp: string;
  tasks: SessionTaskRecord[];
}

/** Bulgarian labels for publication types, shared by every page. */
export const TYPE_LABELS: Record<string, string> = {
  analysis: "Анализ",
  event_analysis: "Анализ на официален документ",
  weekly_report: "Седмичен отчет",
  crisis_brief: "Извънреден брифинг",
  joint_report: "Съвместен доклад",
  signal_triage: "Сигнали (агрегирано)",
  correction: "Поправка",
  plan: "Тримесечен план",
};

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

/** Load one publication (ministry/date/type). */
export function loadPublication(slug: string, date: string, type: string): Publication {
  const dir = path.join(PUBLISHED_ROOT, slug, date, type);

  let report: ReportMeta | null = null;
  let reportHtml: string | null = null;
  const reportPath = path.join(dir, "report.md");
  if (fs.existsSync(reportPath)) {
    const parsed = matter(fs.readFileSync(reportPath, "utf-8"));
    report = parsed.data as ReportMeta;
    reportHtml = renderMarkdown(parsed.content);
  }

  const correctedBy = [
    ...(readJson<{ corrections: CorrectionLink[] }>(path.join(dir, "corrected_by.json"))
      ?.corrections ?? []),
    // date-level sidecar (corrections without a type reference)
    ...(readJson<{ corrections: CorrectionLink[] }>(
      path.join(PUBLISHED_ROOT, slug, date, "corrected_by.json"),
    )?.corrections ?? []),
  ];

  return {
    slug,
    date,
    type,
    report,
    reportHtml,
    indicators: readJson<IndicatorSummary[]>(path.join(dir, "indicators.json")) ?? [],
    signals: readJson<SignalStats>(path.join(dir, "signals.json")),
    correctedBy,
  };
}

/** All publications of one ministry on one date (newest types first is moot). */
export function loadDay(index: PublishedIndex, slug: string, date: string): Publication[] {
  const entry = (index.ministries[slug] ?? []).find((e) => e.date === date);
  if (!entry) return [];
  return Object.keys(entry.types).map((type) => loadPublication(slug, date, type));
}

/** Every publication of a ministry, newest date first. */
export function allPublications(index: PublishedIndex, slug: string): Publication[] {
  return datesFor(index, slug).flatMap((date) => loadDay(index, slug, date));
}

const LATEST_PREFERENCE = [
  "analysis",
  "weekly_report",
  "joint_report",
  "event_analysis",
  "crisis_brief",
  "plan",
  "correction",
  "signal_triage",
];

/** The ministry's most recent "lead" publication for cards and heros. */
export function loadLatest(index: PublishedIndex, slug: string): Publication | null {
  const [latest] = datesFor(index, slug);
  if (!latest) return null;
  const day = loadDay(index, slug, latest);
  if (day.length === 0) return null;
  const withReport = day.filter((p) => p.report);
  const pool = withReport.length > 0 ? withReport : day;
  pool.sort(
    (a, b) => LATEST_PREFERENCE.indexOf(a.type) - LATEST_PREFERENCE.indexOf(b.type),
  );
  return pool[0]!;
}

/** Latest tier-1 values of one ministry (published/{slug}/indicators.json). */
export function loadIndicators(slug: string): IndicatorSummary[] {
  return readJson<IndicatorSummary[]>(path.join(PUBLISHED_ROOT, slug, "indicators.json")) ?? [];
}

/** Every publication of a type across the cabinet, newest first. */
export function publicationsOfType(index: PublishedIndex, type: string): Publication[] {
  return Object.keys(index.ministries)
    .flatMap((slug) => allPublications(index, slug))
    .filter((p) => p.type === type && p.report)
    .sort((a, b) => b.date.localeCompare(a.date));
}

/**
 * Markdown from a model is UNTRUSTED (AUDIT-2026-11 F-01): raw HTML is
 * escaped, never rendered; links/images keep only http(s), relative or
 * anchor targets.
 */
const SAFE_URL = /^(https?:\/\/|\/|#)/i;
const safeMarked = new Marked({
  renderer: {
    html(html: string): string {
      return escapeHtml(html);
    },
  },
  walkTokens(token) {
    if ((token.type === "link" || token.type === "image") && !SAFE_URL.test(token.href)) {
      token.href = "#";
    }
  },
});

export function renderMarkdown(markdown: string): string {
  return safeMarked.parse(markdown, { async: false }) as string;
}

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** JSON safe inside <script> (no "</script>" breakout, AUDIT F-01). */
export function safeJson(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}

/** Bulgarian number format: 1234.5 -> "1 234,5". */
export function fmtNumber(v: number): string {
  return v.toLocaleString("bg-BG", { maximumFractionDigits: 2 });
}

/** Full historical series for the interactive charts. */
export function loadTimeseries(slug: string): Timeseries | null {
  return readJson<Timeseries>(path.join(PUBLISHED_ROOT, slug, "timeseries.json"));
}

/** published/system/health.json, or null before the first ingest/session. */
export function loadHealth(): SystemHealth | null {
  return readJson<SystemHealth>(path.join(PUBLISHED_ROOT, "system", "health.json"));
}

/** published/system/sessions.json — the cabinet's работен дневник. */
export function loadSessions(): SessionRecord[] {
  return (
    readJson<{ sessions: SessionRecord[] }>(
      path.join(PUBLISHED_ROOT, "system", "sessions.json"),
    )?.sessions ?? []
  );
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
