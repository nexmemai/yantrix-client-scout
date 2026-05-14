export type ScoreBucket = "high-fit" | "mid-fit" | "low-fit";

export interface LeadListItem {
  id: string;
  name: string;
  category?: string | null;
  city?: string | null;
  website_url?: string | null;
  source: string;
  overall_score?: number | null;
  has_website?: boolean | null;
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
