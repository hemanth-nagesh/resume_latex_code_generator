import { useState, useEffect, useCallback } from 'react';
import * as api from '../services/admin';
import type {
  Skill, SkillForm, Project, ProjectForm,
  Role, RoleForm, Certification, CertificationForm,
} from '../types/admin';

const CATEGORIES = ['technical', 'domain', 'tool', 'soft'];
const STATUSES = ['completed', 'ongoing'];
const EMPLOYMENT_TYPES = ['full-time', 'contract', 'freelance'];

type Tab = 'projects' | 'skills' | 'roles' | 'certifications';

interface DbStatus {
  connected: boolean;
  counts: Record<string, number>;
  message: string;
  needs_seed: boolean;
  query_errors?: Record<string, string | null>;
}

export default function AdminPanel() {
  const [tab, setTab] = useState<Tab>('projects');
  const [dbStatus, setDbStatus] = useState<DbStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  useEffect(() => {
    api.getDbStatus()
      .then(setDbStatus)
      .catch(() => setDbStatus({ connected: false, counts: {}, message: 'Could not reach server', needs_seed: false }))
      .finally(() => setStatusLoading(false));
  }, []);

  return (
    <div className="admin-section">
      <div className="admin-title">⚙ Knowledge Graph Admin</div>

      {/* DB connection status banner */}
      {!statusLoading && dbStatus && !dbStatus.connected && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8,
          padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#991b1b',
        }}>
          <strong>Database Connection Error</strong>
          <p style={{ margin: '4px 0 0' }}>{dbStatus.message}</p>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: '#b91c1c' }}>
            Ensure <code>DATABASE_URL</code> is set correctly in your <code>.env</code> file and the database is accessible.
          </p>
        </div>
      )}

      {!statusLoading && dbStatus && dbStatus.connected && dbStatus.needs_seed && (
        <div style={{
          background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8,
          padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#92400e',
        }}>
          <strong>Database is empty — seed required</strong>
          <p style={{ margin: '4px 0 0' }}>
            The database is connected but contains no data. Run the seed script to populate it:
          </p>
          <code style={{ display: 'block', margin: '8px 0 0', padding: '6px 10px', background: '#fef3c7', borderRadius: 4, fontSize: 12 }}>
            python -m server.db.seed
          </code>
        </div>
      )}

      {!statusLoading && dbStatus && dbStatus.query_errors && Object.values(dbStatus.query_errors).some(Boolean) && (
        <div style={{
          background: '#fff7ed', border: '1px solid #fb923c', borderRadius: 8,
          padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#9a3412',
        }}>
          <strong>Query errors detected</strong>
          <p style={{ margin: '4px 0 0' }}>
            The database is connected but queries are failing:
          </p>
          <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
            {Object.entries(dbStatus.query_errors).filter(([, v]) => v).map(([key, err]) => (
              <li key={key}><strong>{key}:</strong> {err}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="tab-bar" style={{ marginBottom: 20 }}>
        {(['projects', 'skills', 'roles', 'certifications'] as Tab[]).map((t) => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'projects' && <ProjectsManager />}
      {tab === 'skills' && <SkillsManager />}
      {tab === 'roles' && <RolesManager />}
      {tab === 'certifications' && <CertificationsManager />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Projects Manager                                                   */
/* ------------------------------------------------------------------ */

function ProjectsManager() {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<ProjectForm>({
    title: '', description: '', tech_stack: '', impact_metric: '',
    start_date: '', end_date: '', status: 'completed', tags: '',
  });

  const load = useCallback(async () => {
    try { setError(null); setItems(await api.listProjects()); }
    catch (e: any) { setError(e.message || 'Failed to load projects'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const reset = () => {
    setEditId(null); setShowForm(false);
    setForm({ title: '', description: '', tech_stack: '', impact_metric: '', start_date: '', end_date: '', status: 'completed', tags: '' });
  };

  const submit = async () => {
    if (editId) await api.updateProject(editId, form);
    else await api.createProject(form);
    reset(); load();
  };

  const startEdit = (p: Project) => {
    setEditId(p.id); setShowForm(true);
    setForm({ title: p.title, description: p.description, tech_stack: p.tech_stack.join(', '), impact_metric: p.impact_metric || '', start_date: p.start_date || '', end_date: p.end_date || '', status: p.status, tags: (p.tags || []).join(', ') });
  };

  if (loading) return <div className="empty-state"><div className="empty-state-icon">⏳</div>Loading…</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <span className="badge badge-slate">{items.length} projects</span>
        <button className="btn btn-sm btn-primary" onClick={() => { reset(); setShowForm(!showForm); }}>
          {showForm ? '✕ Cancel' : '+ New Project'}
        </button>
      </div>

      {items.map((p) => (
        <div key={p.id} className="card card-accent" style={{ marginBottom: 8 }}>
          <div className="admin-card-row">
            <div>
              <strong style={{ fontSize: 15 }}>{p.title}</strong>
              <span className={`badge ${p.status === 'ongoing' ? 'badge-green' : 'badge-slate'}`} style={{ marginLeft: 8 }}>
                {p.status}
              </span>
            </div>
            <div className="admin-card-actions">
              <button className="btn btn-xs btn-ghost" onClick={() => startEdit(p)}>Edit</button>
              <button className="btn btn-xs btn-danger" onClick={async () => { await api.deleteProject(p.id); load(); }}>Delete</button>
            </div>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text2)', margin: '6px 0' }}>{p.description.slice(0, 160)}…</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(p.tech_stack || []).slice(0, 6).map((t) => <span key={t} className="tag-chip">{t}</span>)}
            {(p.tech_stack || []).length > 6 && <span className="badge badge-slate">+{p.tech_stack.length - 6}</span>}
          </div>
        </div>
      ))}

      {showForm && (
        <div className="card" style={{ background: 'var(--accent-light)', borderColor: 'var(--accent)', marginTop: 12 }}>
          <h4 style={{ marginBottom: 12, fontSize: 14 }}>{editId ? 'Edit Project' : 'New Project'}</h4>
          <input className="input-field" placeholder="Title" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} />
          <textarea className="input-field" placeholder="Description (min 50 characters)" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
          <input className="input-field" placeholder="Tech stack (comma-separated)" value={form.tech_stack} onChange={e => setForm({ ...form, tech_stack: e.target.value })} />
          <div className="form-grid">
            <input className="input-field" placeholder="Impact metric" value={form.impact_metric} onChange={e => setForm({ ...form, impact_metric: e.target.value })} />
            <input className="input-field" placeholder="Tags (comma-separated)" value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} />
            <input className="input-field" type="date" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} />
            <input className="input-field" type="date" value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} />
          </div>
          <select className="input-field" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}>
            {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={submit} disabled={!form.title || !form.description || !form.tech_stack}>
              {editId ? 'Update' : 'Create'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={reset}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Skills Manager                                                      */
/* ------------------------------------------------------------------ */

function SkillsManager() {
  const [items, setItems] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<SkillForm>({ name: '', display_name: '', category: 'technical', proficiency: 3 });

  const load = useCallback(async () => {
    try { setError(null); setItems(await api.listSkills()); }
    catch (e: any) { setError(e.message || 'Failed to load skills'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const reset = () => { setEditId(null); setShowForm(false); setForm({ name: '', display_name: '', category: 'technical', proficiency: 3 }); };
  const submit = async () => {
    if (editId) await api.updateSkill(editId, form);
    else await api.createSkill(form);
    reset(); load();
  };

  const grouped = items.reduce((acc, s) => {
    (acc[s.category] ||= []).push(s);
    return acc;
  }, {} as Record<string, Skill[]>);

  if (loading) return <div className="empty-state"><div className="empty-state-icon">⏳</div>Loading…</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <span className="badge badge-slate">{items.length} skills</span>
        <button className="btn btn-sm btn-primary" onClick={() => { reset(); setShowForm(!showForm); }}>
          {showForm ? '✕ Cancel' : '+ New Skill'}
        </button>
      </div>

      {Object.entries(grouped).map(([category, skills]) => (
        <div key={category} style={{ marginBottom: 16 }}>
          <div className="section-title">{category}</div>
          <div className="skills-grid">
            {skills.map((s) => (
              <div key={s.id} className="card" style={{ padding: '8px 12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{s.display_name}</div>
                    <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
                      {Array.from({ length: 5 }, (_, i) => (
                        <div key={i} style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: i < s.proficiency ? 'var(--accent)' : 'var(--border)',
                        }} />
                      ))}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 2 }}>
                    <button className="btn btn-xs btn-ghost" onClick={() => { setEditId(s.id); setShowForm(true); setForm({ name: s.name, display_name: s.display_name, category: s.category, proficiency: s.proficiency }); }}>✎</button>
                    <button className="btn btn-xs btn-danger" onClick={async () => { await api.deleteSkill(s.id); load(); }}>✕</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {showForm && (
        <div className="card" style={{ background: 'var(--accent-light)', borderColor: 'var(--accent)', marginTop: 12 }}>
          <h4 style={{ marginBottom: 12, fontSize: 14 }}>{editId ? 'Edit Skill' : 'New Skill'}</h4>
          <input className="input-field" placeholder="Slug name (e.g. python)" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
          <input className="input-field" placeholder="Display name (e.g. Python)" value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} />
          <div className="form-grid">
            <select className="input-field" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 4 }}>
                Proficiency: {form.proficiency}/5
              </div>
              <input type="range" min={1} max={5} value={form.proficiency}
                onChange={e => setForm({ ...form, proficiency: Number(e.target.value) })}
                style={{ width: '100%', accentColor: 'var(--accent)' }} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={submit} disabled={!form.name || !form.display_name}>
              {editId ? 'Update' : 'Create'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={reset}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Roles Manager                                                       */
/* ------------------------------------------------------------------ */

function RolesManager() {
  const [items, setItems] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<RoleForm>({
    company_name: '', role_title: '', start_date: '', end_date: '',
    location: '', employment_type: 'full-time', base_responsibilities: '',
  });

  const load = useCallback(async () => {
    try { setError(null); setItems(await api.listRoles()); }
    catch (e: any) { setError(e.message || 'Failed to load roles'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const reset = () => { setEditId(null); setShowForm(false); setForm({ company_name: '', role_title: '', start_date: '', end_date: '', location: '', employment_type: 'full-time', base_responsibilities: '' }); };
  const submit = async () => {
    if (editId) await api.updateRole(editId, form);
    else await api.createRole(form);
    reset(); load();
  };

  if (loading) return <div className="empty-state"><div className="empty-state-icon">⏳</div>Loading…</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <span className="badge badge-slate">{items.length} roles</span>
        <button className="btn btn-sm btn-primary" onClick={() => { reset(); setShowForm(!showForm); }}>
          {showForm ? '✕ Cancel' : '+ New Role'}
        </button>
      </div>

      {items.map((r) => (
        <div key={r.id} className="card card-accent" style={{ marginBottom: 8 }}>
          <div className="admin-card-row">
            <div>
              <strong style={{ fontSize: 15 }}>{r.role_title}</strong>
              <span style={{ color: 'var(--text2)', marginLeft: 8, fontSize: 13 }}>at {r.company_name}</span>
              <div className="badge badge-green" style={{ marginLeft: 8, fontSize: 11 }}>
                {r.start_date} – {r.end_date || 'Present'}
              </div>
            </div>
            <div className="admin-card-actions">
              <button className="btn btn-xs btn-ghost" onClick={() => {
                setEditId(r.id); setShowForm(true);
                setForm({ company_name: r.company_name, role_title: r.role_title, start_date: r.start_date, end_date: r.end_date || '', location: r.location || '', employment_type: r.employment_type, base_responsibilities: (r.base_responsibilities || []).join('\n') });
              }}>Edit</button>
              <button className="btn btn-xs btn-danger" onClick={async () => { await api.deleteRole(r.id); load(); }}>Delete</button>
            </div>
          </div>
          {(r.base_responsibilities || []).length > 0 && (
            <ul style={{ margin: '8px 0 0 16px', fontSize: 13, color: 'var(--text2)' }}>
              {(r.base_responsibilities || []).slice(0, 3).map((resp, i) => (
                <li key={i}>{resp.slice(0, 100)}{resp.length > 100 && '…'}</li>
              ))}
            </ul>
          )}
        </div>
      ))}

      {showForm && (
        <div className="card" style={{ background: 'var(--accent-light)', borderColor: 'var(--accent)', marginTop: 12 }}>
          <h4 style={{ marginBottom: 12, fontSize: 14 }}>{editId ? 'Edit Role' : 'New Role'}</h4>
          <div className="form-grid">
            <input className="input-field" placeholder="Company name" value={form.company_name} onChange={e => setForm({ ...form, company_name: e.target.value })} />
            <input className="input-field" placeholder="Role title" value={form.role_title} onChange={e => setForm({ ...form, role_title: e.target.value })} />
          </div>
          <div className="form-grid">
            <input className="input-field" type="date" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} />
            <input className="input-field" type="date" value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} />
          </div>
          <div className="form-grid">
            <input className="input-field" placeholder="Location" value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} />
            <select className="input-field" value={form.employment_type} onChange={e => setForm({ ...form, employment_type: e.target.value })}>
              {EMPLOYMENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <textarea className="input-field" placeholder="Responsibilities (one per line)" value={form.base_responsibilities} onChange={e => setForm({ ...form, base_responsibilities: e.target.value })} />
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={submit} disabled={!form.company_name || !form.role_title || !form.start_date}>
              {editId ? 'Update' : 'Create'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={reset}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Certifications Manager                                              */
/* ------------------------------------------------------------------ */

function CertificationsManager() {
  const [items, setItems] = useState<Certification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CertificationForm>({ title: '', year: new Date().getFullYear(), description: '', url: '' });

  const load = useCallback(async () => {
    try { setError(null); setItems(await api.listCertifications()); }
    catch (e: any) { setError(e.message || 'Failed to load certifications'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    await api.createCertification(form);
    setForm({ title: '', year: new Date().getFullYear(), description: '', url: '' });
    setShowForm(false); load();
  };

  if (loading) return <div className="empty-state"><div className="empty-state-icon">⏳</div>Loading…</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <span className="badge badge-slate">{items.length} certifications</span>
        <button className="btn btn-sm btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? '✕ Cancel' : '+ Add'}
        </button>
      </div>

      {items.map((c) => (
        <div key={c.id} className="card" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <strong style={{ fontSize: 14 }}>{c.title}</strong>
            {c.year && <span className="badge badge-slate" style={{ marginLeft: 8 }}>{c.year}</span>}
            {c.url && <span className="badge badge-green" style={{ marginLeft: 6 }}>🔗 Link</span>}
          </div>
          <button className="btn btn-xs btn-danger" onClick={async () => { await api.deleteCertification(c.id); load(); }}>Delete</button>
        </div>
      ))}

      {showForm && (
        <div className="card" style={{ background: 'var(--accent-light)', borderColor: 'var(--accent)', marginTop: 12 }}>
          <h4 style={{ marginBottom: 12, fontSize: 14 }}>Add Certification</h4>
          <div className="form-grid">
            <input className="input-field" placeholder="Title" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} />
            <input className="input-field" type="number" placeholder="Year" value={form.year} onChange={e => setForm({ ...form, year: Number(e.target.value) })} />
          </div>
          <input className="input-field" placeholder="Description" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
          <input className="input-field" placeholder="URL (optional)" value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} />
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={submit} disabled={!form.title}>Add</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
