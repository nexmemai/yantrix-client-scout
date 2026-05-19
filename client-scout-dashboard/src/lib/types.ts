export type ScoreBucket = "high-fit" | "mid-fit" | "low-fit";

export interface LeadListItem {
  id: string;
  name: string;
  category?: string | null;
  city?: string | null;
  website_url?: string | null;
  source: string;
  overall_score?: number | null;
  agency_fit_score?: number | null;
  agency_fit_bucket?: string | null;
  estimated_deal_value?: number | null;
  has_website?: boolean | null;
  rating?: number | null;
  review_count?: number | null;
  lead_status: string;
  follow_up_at?: string | null;
  priority_rank?: number | null;
  created_at: string;
}

export interface AuditRead {
  id: string;
  business_id: string;
  url_checked?: string | null;
  has_website: boolean;
  ssl_valid: boolean;
  mobile_friendly: boolean;
  has_forms: boolean;
  has_cta: boolean;
  has_whatsapp: boolean;
  has_booking: boolean;
  has_chatbot: boolean;
  load_time_ms?: number | null;
  page_speed_score?: number | null;
  has_title: boolean;
  has_meta_desc: boolean;
  has_h1: boolean;
  has_og_tags: boolean;
  has_facebook: boolean;
  has_instagram: boolean;
  has_linkedin: boolean;
  has_twitter: boolean;
  tech_stack?: string[] | null;
  cms_detected?: string | null;
  pain_flags?: Record<string, boolean> | null;
  screenshot_url?: string | null;
  status: string;
  error_message?: string | null;
  audited_at: string;
}

export interface ScoreRead {
  id: string;
  business_id: string;
  overall_score: number;
  website_quality?: number | null;
  online_presence?: number | null;
  conversion_readiness?: number | null;
  urgency?: number | null;
  agency_fit_score?: number | null;
  agency_fit_bucket?: string | null;
  opportunity_types?: string[] | null;
  estimated_deal_value?: number | null;
  pitch_notes?: string | null;
  recommended_services?: string[] | null;
  objection_handlers?: string | null;
  llm_provider?: string | null;
  llm_model?: string | null;
  scored_at: string;
}

export interface LeadDetail {
  id: string;
  name: string;
  category?: string | null;
  niche?: string | null;
  city?: string | null;
  website_url?: string | null;
  source: string;
  phone?: string | null;
  email?: string | null;
  rating?: number | null;
  review_count?: number | null;
  contact_name?: string | null;
  contact_title?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  contact_linkedin_url?: string | null;
  contact_confidence?: number | null;
  primary_language?: string | null;
  domain_age_years?: number | null;
  has_recent_updates?: boolean | null;
  budget_tier?: string | null;
  reliability?: string | null;
  lead_status: string;
  follow_up_at?: string | null;
  last_contacted_at?: string | null;
  contact_attempts: number;
  sales_notes?: string | null;
  priority_rank?: number | null;
  assigned_to?: string | null;
  whatsapp_link?: string | null;
  email_subject?: string | null;
  email_body?: string | null;
  created_at: string;
  updated_at: string;
  audit?: AuditRead | null;
  score?: ScoreRead | null;
}

export interface PaginatedLeads {
  total: number;
  page: number;
  limit: number;
  pages: number;
  items: LeadListItem[];
}

export interface LeadSalesUpdate {
  lead_status?: string | null;
  follow_up_at?: string | null;
  last_contacted_at?: string | null;
  increment_contact_attempts?: boolean;
  sales_notes?: string | null;
  priority_rank?: number | null;
  assigned_to?: string | null;
}

export interface LeadSalesState {
  business_id: string;
  lead_status: string;
  follow_up_at?: string | null;
  last_contacted_at?: string | null;
  contact_attempts: number;
  sales_notes?: string | null;
  priority_rank?: number | null;
  assigned_to?: string | null;
}

export interface LeadSummary {
  followups_today: number;
  new_hot_leads: number;
  stale_contacted: number;
}

export interface RunScoutPayload {
  niche: string;
  city: string;
  max_businesses: number;
}

export interface RunScoutResponse {
  job_id: string;
  status: string;
  niche: string;
  city: string;
  source: string;
  discovered: number;
  audited: number;
  scored: number;
  pitched: number;
  message: string;
  created_at: string;
  started_at: string;
  completed_at?: string | null;
  duration_seconds?: number | null;
}

export interface JobStatus {
  id: string;
  query: string;
  city?: string | null;
  source: string;
  niche?: string | null;
  status: string;
  total_discovered: number;
  total_audited: number;
  total_scored: number;
  total_pitched: number;
  error_message?: string | null;
  started_at?: string | null;
  created_at: string;
  updated_at: string;
  last_updated_at: string;
  completed_at?: string | null;
}

export interface PaginatedJobs {
  total: number;
  page: number;
  limit: number;
  pages: number;
  items: JobStatus[];
}

export interface ConfigWeights {
  weak_website: number;
  lead_capture_gap: number;
  outdated_contact: number;
  high_ticket: number;
  trust_gap: number;
  automation_gap: number;
}

export interface NicheConfig {
  id: string;
  niche: string;
  weights: ConfigWeights;
  prompt_template?: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface PitchResponse {
  id: string;
  business_id: string;
  pitch_notes: string;
  llm_provider?: string | null;
  llm_model?: string | null;
  tokens_used?: number | null;
  generated_at: string;
}
