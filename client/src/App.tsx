import { useCache } from './hooks/useCache';
import { useSSE } from './hooks/useSSE';
import { saveDraft } from './services/cache';
import { useEffect, useRef, useCallback, useState } from 'react';
import AdminPanel from './components/AdminPanel';
import LoginPage from './components/LoginPage';
import { isAuthenticated, validateToken } from './services/auth';
import './index.css';

const NODE_LABELS: Record<string, string> = {
  n1_session_validator: 'Checking session',
  n2_input_parser: 'Validating input',
  n3_jd_analyzer: 'Analyzing job description',
  n4_kg_loader: 'Loading your profile',
  n5_project_scorer: 'Scoring projects',
  n6_content_selector: 'Selecting best matches',
  n7a_summary_gen: 'Writing summary',
  n7b_experience_gen: 'Tailoring experience',
  n7c_projects_gen: 'Tailoring projects',
  n7d_skills_gen: 'Assembling skills',
  n8_latex_assembler: 'Building resume',
  n9_latex_validator: 'Validating format',
  n12_response_builder: 'Packaging output',
};

export default function App() {
  const [unlocked, setUnlocked] = useState(() => isAuthenticated());

  useEffect(() => {
    if (unlocked) {
      validateToken().then((valid) => { if (!valid) setUnlocked(false); });
    }
  }, [unlocked]);

  // Always call hooks unconditionally — React Rules of Hooks
  const {
    jdText, setJdText, sections, setSections,
    completedNodes, sessionKey,
    draftLoaded, draftTimestamp, clearDraft,
  } = useCache();

  const { isGenerating, nodeStatuses, error, latexOutput, templateFallback, startGeneration, cancelGeneration } = useSSE();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [copied, setCopied] = useState(false);

  if (!unlocked) {
    return <LoginPage onUnlock={() => setUnlocked(true)} />;
  }

  const handleJdChange = useCallback(
    (text: string) => {
      setJdText(text);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        saveDraft(text, sections.map((s) => s.name));
      }, 500);
    },
    [sections, setJdText],
  );

  const handleGenerate = () => {
    if (!jdText.trim() || sections.length === 0) return;
    startGeneration({
      jd_text: jdText, sections,
      session_key: sessionKey,
      completed_nodes: completedNodes,
    });
  };

  const handleCopy = async () => {
    if (!latexOutput) return;
    await navigator.clipboard.writeText(latexOutput);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!latexOutput) return;
    const blob = new Blob([latexOutput], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'resume.tex'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };

  const completedCount = [...nodeStatuses.values()].filter((s) => s === 'completed').length;
  const totalCount = nodeStatuses.size;

  return (
    <div className="app-container">
      {/* Header */}
      <div className="header">
        <h1>Resume AI Builder</h1>
        <p>Paste a job description → AI tailors your resume using your real experience</p>
      </div>

      {/* Draft banner */}
      {draftLoaded && (
        <div className="draft-banner">
          <span>💾 Unsaved draft from {draftTimestamp ? new Date(draftTimestamp).toLocaleString() : 'earlier'}</span>
          <button className="btn btn-sm btn-ghost" onClick={clearDraft}>Discard</button>
        </div>
      )}

      {/* JD Input */}
      <div className="section-title">Job Description</div>
      <textarea
        className="input-field"
        value={jdText}
        onChange={(e) => handleJdChange(e.target.value)}
        rows={9}
        placeholder="Paste the full job description here — the AI extracts required skills, seniority level, and domain to tailor your resume…"
        style={{ marginBottom: 12 }}
      />
      {jdText.length > 0 && jdText.length < 100 && (
        <p style={{ color: 'var(--amber)', fontSize: 13, marginBottom: 12 }}>⚠ JD is short — accuracy may be lower. Include the full description for best results.</p>
      )}
      {jdText.length > 15000 && (
        <p style={{ color: 'var(--amber)', fontSize: 13, marginBottom: 12 }}>⚠ JD is very long — the system will focus on the most relevant sections.</p>
      )}

      {/* Section selector */}
      <div className="section-title">Sections to Generate</div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="section-checkboxes">
          {(['summary', 'experience', 'projects', 'skills'] as const).map((name) => {
            const config = sections.find((s) => s.name === name);
            const checked = !!config;
            const label = name.charAt(0).toUpperCase() + name.slice(1);
            const desc: Record<string, string> = { summary: '3-sentence professional profile', experience: 'Tailored role descriptions', projects: 'Best-matching project highlights', skills: 'Categorized technical skills' };
            return (
              <label key={name} className={`section-checkbox ${checked ? 'on' : 'off'}`}>
                <input type="checkbox" checked={checked} onChange={() => {
                  if (checked) setSections(sections.filter((s) => s.name !== name));
                  else setSections([...sections, { name }]);
                }} />
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
                  <div style={{ fontSize: 12, color: 'var(--text3)' }}>{desc[name]}</div>
                  {name === 'projects' && checked && (
                    <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className="badge badge-slate">Max {config?.max_count ?? 4}</span>
                      <input type="range" min={2} max={6} value={config?.max_count ?? 4}
                        onChange={(e) => setSections(sections.map((s) => s.name === 'projects' ? { ...s, max_count: Number(e.target.value) } : s))}
                        style={{ width: 80 }} />
                    </div>
                  )}
                  {name === 'experience' && checked && (
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 12 }}>
                      <input type="checkbox" checked={config?.matched_only ?? true}
                        onChange={(e) => setSections(sections.map((s) => s.name === 'experience' ? { ...s, matched_only: e.target.checked } : s))} />
                      Matched roles only
                    </label>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="actions">
        <button className="btn btn-primary btn-generate" onClick={handleGenerate}
          disabled={!jdText.trim() || sections.length === 0 || isGenerating}>
          {isGenerating ? '⟳ Generating…' : '✨ Generate Resume'}
        </button>
        {isGenerating && (
          <button className="btn btn-danger btn-sm" onClick={cancelGeneration}>Cancel</button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="card" style={{ borderColor: 'var(--red)', background: 'var(--red-light)', marginBottom: 16 }}>
          <strong style={{ color: 'var(--red)' }}>Error</strong>
          <p style={{ fontSize: 13, marginTop: 4, color: 'var(--red)' }}>{error}</p>
        </div>
      )}

      {/* Progress */}
      {isGenerating && totalCount > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>Building your resume</span>
            <span className="badge" style={{ background: 'var(--accent-light)', color: 'var(--accent)' }}>
              {completedCount}/{totalCount} steps
            </span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${totalCount > 0 ? (completedCount / totalCount) * 100 : 0}%` }} />
          </div>
          <div className="node-track">
            {[...nodeStatuses.entries()].map(([node, status]) => (
              <div key={node} className={`node-row ${status}`}>
                <div className={`node-dot ${status}`} />
                <span style={{ flex: 1 }}>{NODE_LABELS[node] || node}</span>
                <span style={{ fontSize: 11, color: 'var(--text3)' }}>
                  {status === 'running' ? 'Running' : status === 'completed' ? 'Done' : status === 'failed' ? 'Failed' : 'Waiting'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LaTeX Output */}
      {latexOutput && !isGenerating && (
        <div className="latex-output">
          {templateFallback && (
            <div className="draft-banner" style={{ background: '#fef3c7', borderColor: '#f59e0b' }}>
              <span>⚠️ Using local fallback template — Blob Storage is unavailable. Upload template to Azure for production use.</span>
            </div>
          )}
          <div className="latex-toolbar">
            <span style={{ fontWeight: 600 }}>📄 Generated LaTeX</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn btn-sm btn-ghost" onClick={handleCopy}>
                {copied ? '✓ Copied' : '📋 Copy'}
              </button>
              <button className="btn btn-sm btn-primary" onClick={handleDownload}>
                ⬇ Download .tex
              </button>
            </div>
          </div>
          <div className="latex-viewer">
            <div className="latex-viewer-header">
              <span>resume.tex</span>
              <span style={{ fontSize: 11, opacity: .6 }}>{latexOutput.split('\n').length} lines</span>
            </div>
            <textarea readOnly value={latexOutput} rows={24} />
          </div>
          <p style={{ fontSize: 12, color: 'var(--text3)', marginTop: 6 }}>
            Copy this into <strong>Overleaf</strong> or compile locally with <code>pdflatex resume.tex</code>
          </p>
        </div>
      )}

      {/* Admin */}
      <AdminPanel />
    </div>
  );
}
