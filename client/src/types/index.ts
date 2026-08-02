export interface JDProfile {
  required_skills: { skill: string; is_technical: boolean; ats_exact_phrase: string }[];
  preferred_skills: { skill: string; is_technical: boolean }[];
  seniority_level: 'junior' | 'mid' | 'senior' | 'lead' | 'staff';
  domain: string;
  industry: string;
  role_type: string;
  ats_keywords: string[];
  company_values: string[];
  red_flags_to_avoid: string[];
}

export interface Project {
  id: string;
  title: string;
  description: string;
  impact_metric?: string;
  start_date?: string;
  end_date?: string;
  status: 'completed' | 'ongoing';
  tech_stack: string[];
  tags: string[];
  is_active: boolean;
  skills: string[];
}

export interface Skill {
  id: string;
  name: string;
  display_name: string;
  category: 'technical' | 'domain' | 'tool' | 'soft';
  proficiency: number;
  last_used_date?: string;
}

export interface Role {
  id: string;
  company_name: string;
  role_title: string;
  start_date: string;
  end_date?: string;
  location?: string;
  employment_type: 'full-time' | 'contract' | 'freelance';
  base_responsibilities: string[];
  project_ids: string[];
}

export interface SectionConfig {
  name: 'summary' | 'experience' | 'projects' | 'skills';
}

export interface GenerateRequest {
  jd_text: string;
  sections: SectionConfig[];
  session_key?: string;
  completed_nodes?: string[];
}

export type NodeId =
  | 'n1_session_validator'
  | 'n2_input_parser'
  | 'n3_jd_analyzer'
  | 'n4_kg_loader'
  | 'n5_project_scorer'
  | 'n6_content_selector'
  | 'n7a_summary_gen'
  | 'n7b_experience_gen'
  | 'n7c_projects_gen'
  | 'n7d_skills_gen'
  | 'n8_latex_assembler'
  | 'n9_latex_validator'
  | 'n9r_latex_fixer'
  | 'n10_pdf_compiler'
  | 'n10f_fallback_handler'
  | 'n11_state_persister'
  | 'n12_response_builder';

export type SSEEventType =
  | 'session_ready'
  | 'node_start'
  | 'node_complete'
  | 'node_error'
  | 'complete'
  | 'pipeline_error'
  | 'review_pending'
  | 'heartbeat';

export interface SSEEvent {
  event: SSEEventType;
  session_key: string;
  timestamp: string;
}

export interface NodeStartEvent extends SSEEvent {
  node: NodeId;
}

export interface NodeCompleteEvent extends SSEEvent {
  node: NodeId;
  duration_ms: number;
}

export interface NodeErrorEvent extends SSEEvent {
  node: NodeId;
  error: string;
  will_retry: boolean;
}

export interface CompleteEvent extends SSEEvent {
  latex_source: string;
  filename: string;
  pdf_base64?: string;
  warnings: string[];
}

export interface ReviewPendingEvent extends SSEEvent {
  latex_source: string;
  warnings: string[];
}

export interface PipelineErrorEvent extends SSEEvent {
  error: string;
  failed_node: NodeId;
}

export interface DraftData {
  jd_text: string;
  sections: string[];
  saved_at: string;
  ttl_days: number;
}

export interface CachedPDF {
  pdf_blob: ArrayBuffer;
  generated_at: string;
  session_key: string;
  jd_preview: string;
}
