export interface Skill {
  id: string;
  name: string;
  display_name: string;
  category: string;
  proficiency: number;
  last_used_date?: string;
}

export interface Project {
  id: string;
  title: string;
  description: string;
  tech_stack: string[];
  impact_metric?: string;
  start_date?: string;
  end_date?: string;
  status: string;
  tags: string[];
  is_active: boolean;
  skills: Skill[];
  created_at: string;
  updated_at: string;
}

export interface Role {
  id: string;
  company_name: string;
  role_title: string;
  start_date: string;
  end_date?: string;
  location?: string;
  employment_type: string;
  base_responsibilities: string[];
  is_active: boolean;
  projects: Project[];
}

export interface Certification {
  id: string;
  title: string;
  year?: number;
  description?: string;
  url?: string;
  is_active: boolean;
}

export interface SkillForm {
  name: string;
  display_name: string;
  category: string;
  proficiency: number;
}

export interface ProjectForm {
  title: string;
  description: string;
  tech_stack: string;
  impact_metric: string;
  start_date: string;
  end_date: string;
  status: string;
  tags: string;
}

export interface RoleForm {
  company_name: string;
  role_title: string;
  start_date: string;
  end_date: string;
  location: string;
  employment_type: string;
  base_responsibilities: string;
}

export interface CertificationForm {
  title: string;
  year: number;
  description: string;
  url: string;
}
