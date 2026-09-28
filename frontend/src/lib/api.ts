export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, `Can't reach the API at ${API_URL}. Is the backend running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------- types

export type Stage = "new" | "contacted" | "qualified" | "proposal" | "negotiation" | "won" | "lost";
export type IssueType = "duplicate" | "stale" | "missing_field";
export type ActionType = "outreach" | "merge" | "stage_change";
export type ActionStatus = "pending" | "approved" | "rejected" | "executed";

export const STAGES: Stage[] = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"];

export interface Health {
  status: string;
  leads: number;
  as_of: string;
  llm: string | null;
  mode: "full" | "offline";
}

export interface LeadRow {
  lead_id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  title: string | null;
  seniority: string;
  stage: Stage;
  owner: string;
  source: string;
  deal_value: number | null;
  created_at: string;
  last_contacted_at: string | null;
  updated_at: string;
  company_id: string;
  company: string;
  industry: string;
  employees: number;
  country: string;
  score: number;
  fit: number;
  intent: number;
  recency: number;
  issues: IssueType[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Overview {
  as_of: string;
  totals: {
    leads: number;
    open_leads: number;
    companies: number;
    activities: number;
    open_pipeline: number;
    avg_score: number;
    leads_with_issues: number;
    pending_actions: number;
    clean_pct: number;
  };
  issues: { issue_type: IssueType; count: number }[];
  stages: { stage: Stage; count: number; avg_score: number }[];
  score_histogram: { bucket: number; count: number }[];
  top_leads: (Pick<LeadRow, "lead_id" | "stage" | "owner" | "score" | "fit" | "intent" | "recency" | "company"> & {
    name: string;
  })[];
}

export interface Contribution {
  source: "lead" | "company" | "activity";
  ref: string;
  field: string;
  value: string;
  points: number;
}

export interface Component {
  points: number;
  max_points: number;
  summary: string;
  contributions: Contribution[];
}

export interface Breakdown {
  lead_id: string;
  score: number;
  fit: Component;
  intent: Component;
  recency: Component;
}

export interface Action {
  action_id: string;
  type: ActionType;
  lead_ids: string[];
  payload: Record<string, unknown>;
  status: ActionStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  note: string | null;
  audit: { id: number; action_id: string; event: string; at: string; actor: string }[];
}

export interface LeadDetail {
  lead: LeadRow;
  breakdown: Breakdown;
  citations: string[];
  activities: { activity_id: string; type: string; occurred_at: string }[];
  issues: { issue_id: string; issue_type: IssueType; details: string; related_lead_id: string | null }[];
  actions: Action[];
}

export interface Explanation {
  lead_id: string;
  why_now: string;
  citations: string[];
  valid: boolean;
  source: "llm" | "template";
  provider: string | null;
  notes: string[];
}

export interface AskResult {
  question: string;
  answer: string;
  sql: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  citations: string[];
  valid: boolean;
  source: "llm" | "rules" | "none";
  provider: string | null;
  attempts: number;
  notes: string[];
}

export interface SourceRow {
  id: string;
  table: string;
  row: Record<string, unknown>;
}

export interface EvalReport {
  run_at: string;
  mode: "full" | "offline";
  model: string | null;
  summary: {
    total: number;
    passed: number;
    accuracy: number;
    answered: number;
    citation_valid_rate: number;
    hallucinated_citations: number;
    avg_latency_ms: number;
    by_category: Record<string, { passed: number; total: number }>;
    by_source: Record<string, number>;
  };
  cleaning: Record<string, { precision: number; recall: number; f1: number; found: number; expected: number }>;
  results: {
    id: string;
    category: string;
    kind: string;
    question: string;
    passed: boolean;
    valid: boolean;
    source: string;
    latency_ms: number;
    sql: string | null;
    answer: string;
    citations: string[];
    expected: unknown;
    got: unknown;
  }[];
}

export interface LeadQuery {
  q?: string;
  stage?: string;
  owner?: string;
  industry?: string;
  issue?: string;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

// ---------------------------------------------------------------- calls

function qs(params: object): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "" && v !== null) s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  overview: () => request<Overview>("/overview"),
  leads: (q: LeadQuery) => request<Page<LeadRow>>(`/leads${qs(q)}`),
  lead: (id: string) => request<LeadDetail>(`/leads/${id}`),
  explain: (id: string) => request<Explanation>(`/leads/${id}/explain`, { method: "POST" }),
  row: (id: string) => request<SourceRow>(`/rows/${id}`),
  ask: (question: string) => request<AskResult>("/ask", { method: "POST", body: JSON.stringify({ question }) }),
  actions: (status?: ActionStatus) => request<Action[]>(`/actions${qs({ status })}`),
  createAction: (body: { type: ActionType; lead_ids: string[]; payload?: Record<string, unknown>; note?: string; actor?: string }) =>
    request<Action>("/actions", { method: "POST", body: JSON.stringify(body) }),
  decide: (id: string, decision: "approve" | "reject", body: { actor: string; note?: string }) =>
    request<Action>(`/actions/${id}/${decision}`, { method: "POST", body: JSON.stringify(body) }),
  evals: () => request<EvalReport>("/evals/latest"),
};
