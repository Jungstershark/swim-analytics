/**
 * Swim Analytics API client
 *
 * Typed fetch helpers for all backend endpoints.
 * Requests are proxied by Next.js rewrites → FastAPI at :8000.
 */

const API_BASE = "/api";

/**
 * Clean display name — strip placeholder surnames like "., " from single-name swimmers.
 */
export function displayName(name: string): string {
  // "., Lineysha" → "Lineysha"
  if (name.startsWith("., ")) return name.slice(3);
  return name;
}

// ---------------------------------------------------------------------------
// Types — mirrors the FastAPI Pydantic schemas
// ---------------------------------------------------------------------------

export interface PaginationInfo {
  page: number;
  limit: number;
  total: number;
  total_pages: number;
}

export interface SwimmerBrief {
  id: number;
  name: string;
  age: number | null;
  team: string | null;
}

export interface SwimmerListItem extends SwimmerBrief {
  meet_count: number;
  result_count: number;
  latest_meet: string | null;
}

export interface PersonalBest {
  event: string;
  time: string;
  time_in_seconds: number | null;
  meet: string;
  date: string;
}

export interface SwimmerDetail extends SwimmerBrief {
  personal_bests: PersonalBest[];
  recent_results: ResultListItem[];
  stats: {
    total_meets: number;
    total_results: number;
    total_dqs: number;
    first_meet: string | null;
    latest_meet: string | null;
  };
}

export interface MeetBrief {
  id: number;
  name: string;
  date: string;
  end_date: string | null;
  location: string | null;
}

export interface MeetListItem extends MeetBrief {
  result_count: number;
  swimmer_count: number;
}

export interface EventGroup {
  name: string;
  results: ResultBrief[];
}

export interface MeetDetail extends MeetBrief {
  events: EventGroup[];
}

export interface ResultBrief {
  id: number;
  event: string;
  time: string | null;
  seed_time: string | null;
  placement: number | null;
  is_dq: boolean;
  dq_code: string | null;
  dq_description: string | null;
  is_guest: boolean;
  qualifier: string | null;
  round: string | null;
  swim_date: string | null;
  swimmer: SwimmerBrief;
}

export interface ResultListItem extends ResultBrief {
  meet: MeetBrief;
}

export interface ResultDetail extends ResultBrief {
  reaction_time: string | null;
  splits: string | null;
  meet: MeetBrief;
}

export interface PreviewResultRow {
  event: string;
  name: string;
  age: number | null;
  team: string;
  time: string | null;
  seed_time: string | null;
  round: string;
  placement: number | null;
  is_dq: boolean;
  is_guest: boolean;
  qualifier: string | null;
}

export interface ConfidenceCheck {
  name: string;
  passed: boolean;
}

export interface PreviewEventGroup {
  event: string;
  round: string;
  result_count: number;
  results: PreviewResultRow[];
}

export interface UploadPreviewResponse {
  parser_format: string;
  confidence_score: number;
  confidence_passed: boolean;
  confidence_checks: ConfidenceCheck[];
  unmatched_lines: string[];
  meet_name: string;
  meet_dates: string | null;
  session: string | null;
  events_count: number;
  results_count: number;
  swimmers_count: number;
  events: PreviewEventGroup[];
}

export interface DuplicateEntry {
  event: string;
  name: string;
  team: string | null;
  round: string | null;
  time: string | null;
}

export interface UploadResponse {
  success: boolean;
  meet: MeetBrief;
  results_count: number;
  swimmers_count: number;
  events_count: number;
  duplicates_skipped: number;
  duplicates: DuplicateEntry[];
  errors: string[];
}

export interface ProgressionDataPoint {
  date: string;
  time: string;
  time_in_seconds: number;
  meet: string;
  placement: number | null;
}

export interface ProgressionResponse {
  swimmer: SwimmerBrief;
  event: string;
  data_points: ProgressionDataPoint[];
  summary: {
    personal_best?: string;
    personal_best_date?: string;
    meet_count?: number;
    total_improvement?: string;
    improvement_percent?: number;
  };
}

// ---------------------------------------------------------------------------
// Paginated response wrappers
// ---------------------------------------------------------------------------

export interface PaginatedResponse<T> {
  data: T[];
  pagination: PaginationInfo;
}

// ---------------------------------------------------------------------------
// API fetch helper
// ---------------------------------------------------------------------------

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(body.detail || body.error || res.statusText, res.status);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Browser read models — Slice 3 longitudinal browser foundation
// ---------------------------------------------------------------------------

export interface BrowserWarning {
  type: string;
  severity: "info" | "warning" | "error" | string;
  entity_kind?: string;
  entity_id?: number;
  message: string;
  count?: number;
  sample_rows?: Record<string, unknown>[];
  source_fields?: string[];
}

export interface BrowserSourceInfo {
  document_sha256: string | null;
  parse_job_id: number | null;
  source_scope: "result" | "parent_relay_result" | string;
}

export interface BrowserMeetBrief {
  id: number;
  name: string;
  date: string | null;
  end_date: string | null;
  location: string | null;
}

export interface BrowserSwimmerBrief {
  id: number;
  name: string;
  age: number | null;
  team: string | null;
}

export interface BrowserEventGroup {
  event_key: string;
  meet_id: number;
  source_event_number: string | null;
  event_label: string;
  normalization_status: string;
  derived: boolean;
  rounds: string[];
  swim_dates: string[];
  individual_count: number;
  relay_count: number;
  total_rows: number;
}

export interface BrowserOverview {
  counts: {
    meets: number;
    swimmers: number;
    individual_results: number;
    relay_results: number;
    raw_documents: number;
    source_references: number;
  };
  latest_meets: BrowserMeetBrief[];
  top_events: { event_label: string; individual_count: number }[];
  source_summary: {
    missing_individual_result_source_count: number;
    missing_relay_result_source_count: number;
  };
}

export interface BrowserSwimmerListItem extends BrowserSwimmerBrief {
  individual_result_count: number;
  relay_result_count: number;
  meet_count: number;
  event_count: number;
  latest_meet: BrowserMeetBrief | null;
  warning_count: number;
  warnings: BrowserWarning[];
}

export interface BrowserSwimmerListParams {
  page?: number;
  limit?: number;
  q?: string;
  team?: string;
  min_results?: number;
  has_warnings?: boolean;
  sort?: "name" | "team" | "result_count" | "latest_meet";
  order?: "asc" | "desc";
}

export interface BrowserPersonalBest {
  event: string;
  time: string | null;
  time_in_seconds: number;
  meet: BrowserMeetBrief | null;
  date: string | null;
  round: string | null;
}

export interface BrowserIndividualRow {
  row_type: "individual";
  id: number;
  event_key: string;
  event_label: string;
  round: string | null;
  swim_date: string | null;
  placement: number | null;
  time: string | null;
  seed_time: string | null;
  is_dq: boolean;
  dq_code: string | null;
  dq_description: string | null;
  is_guest: boolean;
  qualifier: string | null;
  swimmer: BrowserSwimmerBrief | null;
  meet: BrowserMeetBrief | null;
  source: BrowserSourceInfo;
  warnings: BrowserWarning[];
}

export interface BrowserRelayLeg {
  leg_number: number;
  swimmer_id: number | null;
  swimmer_name: string;
  age: number | null;
  gender: string | null;
  split_time: string | null;
  reaction_time: string | null;
  matched_by: string;
  identity_match_confidence: string;
}

export interface BrowserRelayRow {
  row_type: "relay";
  id: number;
  event_key: string;
  event_label: string;
  round: string | null;
  swim_date: string | null;
  placement: number | null;
  time: string | null;
  seed_time: string | null;
  is_dq: boolean;
  team_name: string;
  relay_letter: string | null;
  is_exhibition: boolean;
  legs: BrowserRelayLeg[];
  meet: BrowserMeetBrief | null;
  source: BrowserSourceInfo;
  warnings: BrowserWarning[];
}

export type BrowserEventRow = BrowserIndividualRow | BrowserRelayRow;

export interface BrowserSwimmerDetail {
  swimmer: BrowserSwimmerBrief;
  stats: {
    individual_result_count: number;
    relay_result_count: number;
    meet_count: number;
    event_count: number;
    warning_count: number;
  };
  personal_bests: BrowserPersonalBest[];
  event_history: {
    event: string;
    event_key: string;
    derived: boolean;
    normalization_status: string;
    result_count: number;
    results: BrowserIndividualRow[];
  }[];
  relay_history: BrowserRelayRow[];
  warnings: BrowserWarning[];
}

export interface BrowserMeetDetail {
  meet: BrowserMeetBrief;
  event_groups: BrowserEventGroup[];
  summary: {
    event_group_count: number;
    individual_result_count: number;
    relay_result_count: number;
    total_rows: number;
  };
  source_summary: { missing_source_count: number };
  warnings: BrowserWarning[];
}

export interface BrowserEventDetail {
  event_group: BrowserEventGroup | null;
  data: BrowserEventRow[];
  pagination: PaginationInfo;
  warnings: BrowserWarning[];
}

export interface BrowserEventParams {
  meet_id: number;
  event_key: string;
  page?: number;
  limit?: number;
  round?: string;
  row_type?: "all" | "individual" | "relay";
  order?: "place" | "time" | "name";
}

export interface BrowserDataQualityResponse {
  summary: Record<string, number>;
  data: BrowserWarning[];
  pagination: PaginationInfo;
}

export async function getBrowserOverview(): Promise<BrowserOverview> {
  return apiFetch("/browser/overview");
}

export async function listBrowserSwimmers(
  params: BrowserSwimmerListParams = {}
): Promise<PaginatedResponse<BrowserSwimmerListItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.q) q.set("q", params.q);
  if (params.team) q.set("team", params.team);
  if (params.min_results !== undefined) q.set("min_results", String(params.min_results));
  if (params.has_warnings !== undefined) q.set("has_warnings", String(params.has_warnings));
  if (params.sort) q.set("sort", params.sort);
  if (params.order) q.set("order", params.order);
  return apiFetch(`/browser/swimmers?${q}`);
}

export async function getBrowserSwimmer(id: number): Promise<BrowserSwimmerDetail> {
  return apiFetch(`/browser/swimmers/${id}`);
}

export async function getBrowserMeet(id: number): Promise<BrowserMeetDetail> {
  return apiFetch(`/browser/meets/${id}`);
}

export async function getBrowserEvent(params: BrowserEventParams): Promise<BrowserEventDetail> {
  const q = new URLSearchParams({
    meet_id: String(params.meet_id),
    event_key: params.event_key,
  });
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.round) q.set("round", params.round);
  if (params.row_type) q.set("row_type", params.row_type);
  if (params.order) q.set("order", params.order);
  return apiFetch(`/browser/events?${q}`);
}

export async function getBrowserDataQuality(
  params: { page?: number; limit?: number } = {}
): Promise<BrowserDataQualityResponse> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  return apiFetch(`/browser/data-quality?${q}`);
}

// ---------------------------------------------------------------------------
// Meets
// ---------------------------------------------------------------------------

export interface ListMeetsParams {
  page?: number;
  limit?: number;
  search?: string;
  sort?: "date" | "name";
  order?: "asc" | "desc";
}

export async function listMeets(
  params: ListMeetsParams = {}
): Promise<PaginatedResponse<MeetListItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.search) q.set("search", params.search);
  if (params.sort) q.set("sort", params.sort);
  if (params.order) q.set("order", params.order);
  return apiFetch(`/meets?${q}`);
}

export async function getMeet(id: number): Promise<MeetDetail> {
  return apiFetch(`/meets/${id}`);
}

// ---------------------------------------------------------------------------
// Swimmers
// ---------------------------------------------------------------------------

export interface ListSwimmersParams {
  page?: number;
  limit?: number;
  search?: string;
  team?: string;
  sort?: "name" | "team" | "age";
  order?: "asc" | "desc";
}

export async function listSwimmers(
  params: ListSwimmersParams = {}
): Promise<PaginatedResponse<SwimmerListItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.search) q.set("search", params.search);
  if (params.team) q.set("team", params.team);
  if (params.sort) q.set("sort", params.sort);
  if (params.order) q.set("order", params.order);
  return apiFetch(`/swimmers?${q}`);
}

export async function getSwimmer(id: number): Promise<SwimmerDetail> {
  return apiFetch(`/swimmers/${id}`);
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

export interface ListResultsParams {
  page?: number;
  limit?: number;
  swimmer?: string;
  swimmer_id?: number;
  meet_id?: number;
  event?: string;
  team?: string;
  is_dq?: boolean;
  sort?: "time" | "date" | "placement" | "event";
  order?: "asc" | "desc";
}

export async function listResults(
  params: ListResultsParams = {}
): Promise<PaginatedResponse<ResultListItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.swimmer) q.set("swimmer", params.swimmer);
  if (params.swimmer_id) q.set("swimmer_id", String(params.swimmer_id));
  if (params.meet_id) q.set("meet_id", String(params.meet_id));
  if (params.event) q.set("event", params.event);
  if (params.team) q.set("team", params.team);
  if (params.is_dq !== undefined) q.set("is_dq", String(params.is_dq));
  if (params.sort) q.set("sort", params.sort);
  if (params.order) q.set("order", params.order);
  return apiFetch(`/results?${q}`);
}

// Relay types
export interface RelayLegBrief {
  leg_number: number;
  swimmer: SwimmerBrief;
  split_time: string | null;
  reaction_time: string | null;
  splits: string | null;
  is_guest: boolean;
  gender: string | null;
}

export interface RelayResultBrief {
  id: number;
  event: string;
  team_name: string;
  relay_letter: string | null;
  time: string | null;
  seed_time: string | null;
  placement: number | null;
  is_dq: boolean;
  is_exhibition: boolean;
  round: string | null;
  swim_date: string | null;
  legs: RelayLegBrief[];
  meet: MeetBrief;
}

export interface CombinedResultItem {
  type: "individual" | "relay";
  id: number;
  event: string;
  time: string | null;
  seed_time: string | null;
  placement: number | null;
  is_dq: boolean;
  round: string | null;
  swim_date: string | null;
  qualifier: string | null;
  swimmer: SwimmerBrief | null;
  is_guest: boolean;
  team_name: string | null;
  relay_letter: string | null;
  is_exhibition: boolean;
  legs: RelayLegBrief[];
  meet: MeetBrief;
}

export async function getSwimmerRelays(id: number): Promise<{ data: RelayResultBrief[] }> {
  return apiFetch(`/swimmers/${id}/relays`);
}

export async function listAllResults(
  params: ListResultsParams = {}
): Promise<PaginatedResponse<CombinedResultItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.swimmer) q.set("swimmer", params.swimmer);
  if (params.swimmer_id) q.set("swimmer_id", String(params.swimmer_id));
  if (params.meet_id) q.set("meet_id", String(params.meet_id));
  if (params.event) q.set("event", params.event);
  if (params.is_dq !== undefined) q.set("is_dq", String(params.is_dq));
  return apiFetch(`/results/all?${q}`);
}

export async function listEvents(meetId?: number): Promise<{ events: string[] }> {
  const q = new URLSearchParams();
  if (meetId) q.set("meet_id", String(meetId));
  return apiFetch(`/events?${q}`);
}

export async function getResult(id: number): Promise<ResultDetail> {
  return apiFetch(`/results/${id}`);
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

export async function previewUpload(file: File): Promise<UploadPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch("/upload/preview", { method: "POST", body: formData });
}

export async function uploadResults(
  file: File,
  options: { replace?: boolean } = {}
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const q = new URLSearchParams();
  if (options.replace) q.set("replace", "true");
  const qs = q.toString();
  return apiFetch(`/upload${qs ? `?${qs}` : ""}`, { method: "POST", body: formData });
}

/** @deprecated Use uploadResults instead */
export const uploadPdf = uploadResults;

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

export async function getProgression(
  swimmerId: number,
  event: string
): Promise<ProgressionResponse> {
  const q = new URLSearchParams({
    swimmer_id: String(swimmerId),
    event,
  });
  return apiFetch(`/analytics/progression?${q}`);
}

// ---------------------------------------------------------------------------
// Admin source monitoring
// ---------------------------------------------------------------------------

export interface AdminMonitorRun {
  id: number;
  sourceRuleId: number;
  triggerType: string;
  triggeredBy: string | null;
  adapterVersion: string | null;
  status: string;
  startedAt: string;
  finishedAt: string | null;
  eventsDiscovered: number;
  eventsWithResults: number;
  addedEvents: number;
  updatedEvents: number;
  unchangedEvents: number;
  absentFromIndexEvents: number;
  addedDocuments: number;
  updatedDocuments: number;
  unchangedDocuments: number;
  actionRequiredCount: number;
  errorMessage: string | null;
  summary: Record<string, unknown>;
}

export interface AdminSourceRule {
  id: number;
  name: string;
  indexUrl: string;
  enabled: boolean;
  adapterType: string | null;
  scheduleLabel: string;
  lastTriggerLabel: string;
  autoImportPolicy: string;
  autoImportLabel: string;
  policyLabels: string[];
  lastRun: AdminMonitorRun | null;
  lastStatus: string | null;
  lastFinishedAt: string | null;
  eventsDiscovered: number;
  eventsWithResults: number;
  actionRequiredCount: number;
  categoriesToArchive: string[];
  categoriesToPreview: string[];
  categoriesAllowedForImport: string[];
}

export interface AdminSourceSite {
  id: number;
  name: string;
  baseUrl: string;
  adapterType: string;
  isEnabled: boolean;
  rules: AdminSourceRule[];
}

export interface AdminSourceEvent {
  id: number;
  sourceRuleId: number;
  title: string;
  pageTitle: string | null;
  url: string;
  sourceYear: string | null;
  readinessStatus: string;
  isCurrentlyListed: boolean;
  pdfCount: number;
  resultPdfCount: number;
  categoryCounts: Record<string, number>;
  documentCount: number;
  firstSeenAt: string;
  lastSeenInIndexAt: string | null;
  lastCheckedAt: string | null;
  lastChangedAt: string | null;
}

export async function listAdminSources(): Promise<{ data: AdminSourceSite[] }> {
  return apiFetch("/admin/sources");
}

export async function listAdminSourceEvents(): Promise<{ data: AdminSourceEvent[] }> {
  return apiFetch("/admin/source-events");
}

export async function listAdminMonitorRuns(): Promise<{ data: AdminMonitorRun[] }> {
  return apiFetch("/admin/monitor-runs");
}

export async function runSourceDiscoveryPreview(ruleId: number): Promise<{ data: AdminMonitorRun }> {
  return apiFetch(`/admin/source-rules/${ruleId}/run-discovery-preview`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Dashboard stats (convenience)
// ---------------------------------------------------------------------------

export interface DashboardStats {
  totalSwimmers: number;
  totalMeets: number;
  totalResults: number;
  recentMeets: MeetListItem[];
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const [meetsRes, swimmersRes] = await Promise.all([
    listMeets({ limit: 5, sort: "date", order: "desc" }),
    listSwimmers({ limit: 1 }),
  ]);

  const totalResults = meetsRes.data.reduce((sum, m) => sum + m.result_count, 0);

  return {
    totalSwimmers: swimmersRes.pagination.total,
    totalMeets: meetsRes.pagination.total,
    totalResults,
    recentMeets: meetsRes.data,
  };
}
