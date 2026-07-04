export type ApprovalStatus =
  | 'APPROVED'
  | 'APPROVE_WITH_CHANGES'
  | 'REJECTED'
  | 'HUMAN_REVIEW_REQUIRED';

export type RiskLevel = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type ComplianceOpinion = 'APPROVE' | 'AMEND' | 'REJECT' | 'HUMAN';
export type VerifierStatus = 'PASS' | 'FAIL' | 'PARTIAL';

export interface InferredMetadata {
  language: string;
  channel: string;
  product_type: string;
  target_audience: string;
}

export interface InputCompleteness {
  accepted: boolean;
  mode: string;
  inferred_metadata?: InferredMetadata;
  provided_metadata?: Partial<InferredMetadata>;
  inferred_fields?: Record<string, unknown>;
  provided_fields?: string[];
  missing_or_unknown_fields?: string[];
  requires_form_completion_for_production?: boolean;
  [key: string]: unknown;
}

export interface ComplianceFinding {
  id: string;
  category: string;
  finding_text: string;
  reason: string;
  suggested_revision: string;
  severity?: string;
  law_name?: string;
  article_no?: string;
  verifier_status?: VerifierStatus;
  source_text?: string;
  raw?: Record<string, unknown>;
}

export interface CitationEvidence {
  clause: string;
  verbatim: string;
  exists: boolean;
  match: boolean;
  applicable: boolean;
  confidence?: number;
  source?: string;
  finding_ids?: string[];
}

export interface RevisionItem {
  finding_id: string;
  original: string;
  revised: string;
  reason?: string;
}

export interface BoardDiagnostic {
  persona: string;
  avatar: string;
  title: string;
  opinion: ComplianceOpinion;
  comment: string;
  risk_level?: RiskLevel;
}

export interface SchemaValidation {
  schema_version: string;
  passed: boolean;
  errors: string[];
}

export interface VerifierResult {
  status: VerifierStatus;
  details?: string;
  checked_claims?: number;
  failed_claims?: number;
}

export interface RuntimeGuardFlags {
  pii_detected: boolean;
  pii_redacted_count: number;
  prompt_injection_flagged: boolean;
  dangerous_url_flagged: boolean;
}

export interface IntegrationInfo {
  backend: 'python-engine' | 'local-rule-engine' | 'seed';
  connected: boolean;
  engine: string;
  fallback_reason?: string;
  cache_hit?: boolean;
  cache_key?: string;
  cache_expires_at?: string;
  concurrency?: {
    policy: string;
    max_in_flight: number;
    active_at_start: number;
    queued_ms: number;
    queue_timeout_ms: number;
  };
}

export interface ComplianceReport {
  review_request_id: string;
  raw_content: string;
  input_completeness: InputCompleteness;
  status?: string;
  approval_status: ApprovalStatus;
  risk_level: RiskLevel;
  confidence: string;
  confidence_score: number;
  summary?: string;
  language?: string;
  channel?: string;
  product_type?: string;
  target_audience?: string;
  redacted_content?: string;
  redacted_text?: string;
  pii_findings?: Array<{ kind: string; replacement: string; start?: number; end?: number }>;
  pii_count?: number;
  llm_degraded?: boolean;
  llm_degraded_reasons?: string[];
  llm_degradation_reasons?: string[];
  findings: ComplianceFinding[];
  evidence: CitationEvidence[];
  revision_suggestions: string;
  revision_items?: RevisionItem[];
  board_diagnostics: BoardDiagnostic[];
  verifier_result: VerifierResult;
  schema_validation: SchemaValidation;
  audit_log_id: string;
  timestamp: string;
  human_review_needed?: boolean;
  guard_flags?: RuntimeGuardFlags;
  integration?: IntegrationInfo;
  workflow_publish_plan?: Record<string, unknown>;
  workflow_exports?: Record<string, unknown>;
  rag_metadata?: RagMetadata;
  marketing_rewrite?: MarketingRewrite;
  raw_report?: Record<string, unknown>;
}

export interface MarketingRewrite {
  rewritten?: string | null;
  removed_terms?: string[];
  added_notices?: string[];
  raw_response?: string;
  model?: string;
  deterministic_fallback?: boolean;
  error?: string | null;
}

export interface RagMetadataLawProvenance {
  law_name?: string;
  article_no?: string;
  effective_date?: string;
  source_url?: string;
}

export interface RagMetadata {
  rag_pipeline?: string;
  law_backend?: string;
  law_count?: number;
  retrieved_law_provenance?: RagMetadataLawProvenance[];
  document_rag_count?: number;
  memory_hit_count?: number;
  rag_cache_hit?: boolean;
  qdrant_status?: Record<string, unknown>;
  ai_research_skill_patterns?: string[];
}

export interface DemoCase {
  key: string;
  title: string;
  subtitle: string;
  source: string;
  text: string;
  metadata: InferredMetadata;
}

export interface HealthStatus {
  status: string;
  app: string;
  parent_root: string;
  python_bridge: {
    enabled: boolean;
    python_bin: string;
    source_path: string;
    source_present: boolean;
  };
  python_worker?: {
    enabled: boolean;
    url: string;
    auto_start: boolean;
    status: 'disabled' | 'starting' | 'ready' | 'unavailable';
    pid?: number;
    last_error?: string;
    timeout_ms?: number;
  };
  review_cache?: {
    enabled: boolean;
    size: number;
    max: number;
    ttl_ms: number;
  };
  review_concurrency?: {
    policy: string;
    max_in_flight: number;
    active: number;
    queued: number;
    queue_timeout_ms: number;
  };
  provider_credentials?: Record<string, { present: boolean; source: string; provider?: string; purpose?: string }>;
  history_count: number;
}

export interface AdminStatus {
  parent_root: string;
  app_root: string;
  paths: Record<string, boolean>;
  model_routing: {
    shallow: string;
    standard: string;
    deep: string;
    critic: string;
    live_profile: string;
    live_effort: string;
    llm_parallelism: string;
  };
  runtime_flags: Record<string, boolean>;
  secrets: Record<string, { present: boolean; source: string }>;
  python_worker: Record<string, unknown>;
  cache: Record<string, unknown>;
  review_concurrency?: Record<string, unknown>;
}

export interface AuditLogRecord {
  audit_log_id: string;
  created_at?: string;
  final_status?: string;
  human_review_needed?: boolean;
  input_type?: string;
  redacted_text?: string;
  routing_decision?: Record<string, unknown>;
  llm_call_count?: number;
  trace_count?: number;
  model_plan?: Record<string, unknown>;
  cross_model_result?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface IngestChunk {
  id: string;
  source: string;
  text: string;
  targets: string[];
  blocked_reasons: string[];
  trust_notes: string[];
  score_by_target?: Record<string, number>;
}

export interface IngestReport {
  source: string;
  applied: boolean;
  approved_memory: boolean;
  total_chunks: number;
  blocked_chunks: number;
  target_counts: Record<string, number>;
  skill_path: string;
  rag_path: string;
  pending_path: string;
  trust_summary: Record<string, number>;
  written_skill_items: number;
  written_rag_items: number;
  written_memory_items: number;
  chunks: IngestChunk[];
}

export interface WorkflowStatus {
  mode: string;
  live_publish_enabled: boolean;
  targets: Record<string, { ready: boolean; live_supported: boolean }>;
  langgraph: Record<string, unknown>;
  hitl: Record<string, unknown>;
  observability: Record<string, unknown>;
  mcp: Record<string, unknown>;
}

export interface SettingsField {
  env: string;
  label: string;
  default?: string;
  help: string;
  required?: boolean;
  kind?: string;
  options?: string[];
  minimum?: number;
  maximum?: number;
}

export interface SecureSettingsSchema {
  secret_fields: SettingsField[];
  model_fields: SettingsField[];
  flag_fields: SettingsField[];
  routing_fields: SettingsField[];
  model_presets: string[];
}

export interface SecureSettingSecretStatus {
  present: boolean;
  source: string;
}

export interface SecureSettingsStatus {
  encrypted_settings_present: boolean;
  updated_at?: string;
  models: Record<string, string>;
  routing: Record<string, string>;
  flags: Record<string, string>;
  secrets: Record<string, SecureSettingSecretStatus>;
  schema?: SecureSettingsSchema;
  applied?: boolean;
  python_worker_restart?: string;
}
