/**
 * Swim Analytics API client
 *
 * Typed fetch helpers for all backend endpoints.
 * Requests are proxied by Next.js rewrites → FastAPI at :8000.
 */

const API_BASE = "/api";

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

export interface UploadResponse {
  success: boolean;
  meet: MeetBrief;
  results_count: number;
  swimmers_count: number;
  events_count: number;
  duplicates_skipped: number;
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
