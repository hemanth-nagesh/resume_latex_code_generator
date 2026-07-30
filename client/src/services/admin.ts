import type { Skill, Project, Role, Certification } from '../types/admin';
import { authHeaders } from './auth';

const API = '/api/admin';

async function req(path: string, method: string, body?: unknown): Promise<unknown> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      ...authHeaders(),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.status === 204 ? null : res.json();
}

// DB Status
export const getDbStatus = () => req('/db-status', 'GET') as Promise<{
  connected: boolean;
  counts: Record<string, number>;
  message: string;
  needs_seed: boolean;
}>;

// Skills
export const listSkills = () => req('/skills', 'GET') as Promise<Skill[]>;
export const createSkill = (data: object) => req('/skills', 'POST', data) as Promise<Skill>;
export const updateSkill = (id: string, data: object) => req(`/skills/${id}`, 'PATCH', data);
export const deleteSkill = (id: string) => req(`/skills/${id}`, 'DELETE');

// Projects — parse comma-separated strings to arrays before sending
export const listProjects = () => req('/projects', 'GET') as Promise<Project[]>;
export function createProject(fields: { title: string; description: string; tech_stack: string; impact_metric: string; start_date: string; end_date: string; status: string; tags: string }) {
  return req('/projects', 'POST', {
    title: fields.title,
    description: fields.description,
    tech_stack: fields.tech_stack.split(',').map((s: string) => s.trim()).filter(Boolean),
    tags: fields.tags.split(',').map((s: string) => s.trim()).filter(Boolean),
    impact_metric: fields.impact_metric || undefined,
    start_date: fields.start_date || undefined,
    end_date: fields.end_date || undefined,
    status: fields.status,
  }) as Promise<Project>;
}
export function updateProject(id: string, fields: { title: string; description: string; tech_stack: string; impact_metric: string; start_date: string; end_date: string; status: string; tags: string }) {
  return req(`/projects/${id}`, 'PATCH', {
    title: fields.title,
    description: fields.description,
    tech_stack: fields.tech_stack.split(',').map((s: string) => s.trim()).filter(Boolean),
    tags: fields.tags.split(',').map((s: string) => s.trim()).filter(Boolean),
    impact_metric: fields.impact_metric || undefined,
    start_date: fields.start_date || undefined,
    end_date: fields.end_date || undefined,
    status: fields.status,
  }) as Promise<Project>;
}
export const deleteProject = (id: string) => req(`/projects/${id}`, 'DELETE');

// Roles — parse newline-separated responsibilities to array
export const listRoles = () => req('/roles', 'GET') as Promise<Role[]>;
export function createRole(fields: { company_name: string; role_title: string; start_date: string; end_date: string; location: string; employment_type: string; base_responsibilities: string }) {
  return req('/roles', 'POST', {
    ...fields,
    end_date: fields.end_date || undefined,
    location: fields.location || undefined,
    base_responsibilities: fields.base_responsibilities.split('\n').filter(Boolean),
  }) as Promise<Role>;
}
export function updateRole(id: string, fields: { company_name: string; role_title: string; start_date: string; end_date: string; location: string; employment_type: string; base_responsibilities: string }) {
  return req(`/roles/${id}`, 'PATCH', {
    ...fields,
    end_date: fields.end_date || undefined,
    location: fields.location || undefined,
    base_responsibilities: fields.base_responsibilities.split('\n').filter(Boolean),
  }) as Promise<Role>;
}
export const deleteRole = (id: string) => req(`/roles/${id}`, 'DELETE');

// Certifications
export const listCertifications = () => req('/certifications', 'GET') as Promise<Certification[]>;
export const createCertification = (data: object) => req('/certifications', 'POST', data) as Promise<Certification>;
export const deleteCertification = (id: string) => req(`/certifications/${id}`, 'DELETE');
