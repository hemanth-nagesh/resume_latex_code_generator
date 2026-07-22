import { useState, useCallback, useEffect } from 'react';
import { loadDraft, saveDraft, getCachedPDF, getCompletedNodes } from '../services/cache';
import { computeSessionKey } from '../services/sessionKey';
import type { DraftData, CachedPDF, SectionConfig } from '../types';

interface UseCacheReturn {
  jdText: string;
  setJdText: (text: string) => void;
  sections: SectionConfig[];
  setSections: (sections: SectionConfig[]) => void;
  cachedPDF: CachedPDF | null;
  completedNodes: string[];
  sessionKey: string;
  draftLoaded: boolean;
  draftTimestamp: string | null;
  clearDraft: () => void;
}

export function useCache(): UseCacheReturn {
  const [jdText, setJdTextRaw] = useState('');
  const [sections, setSectionsRaw] = useState<SectionConfig[]>([
    { name: 'summary' },
    { name: 'experience', matched_only: true },
    { name: 'projects', max_count: 4 },
    { name: 'skills' },
  ]);
  const [sessionKey, setSessionKey] = useState('');
  const [cachedPDF, setCachedPDF] = useState<CachedPDF | null>(null);
  const [completedNodes, setCompletedNodes] = useState<string[]>([]);
  const [draftLoaded, setDraftLoaded] = useState(false);
  const [draftTimestamp, setDraftTimestamp] = useState<string | null>(null);

  // Load draft on mount
  useEffect(() => {
    (async () => {
      const draft: DraftData | null = await loadDraft();
      if (draft) {
        setJdTextRaw(draft.jd_text);
        setDraftLoaded(true);
        setDraftTimestamp(draft.saved_at);
      }
    })();
  }, []);

  const setJdText = useCallback((text: string) => {
    setJdTextRaw(text);
    // Debounced save to IndexedDB (called from component with useRef timer)
  }, []);

  const setSections = useCallback((newSections: SectionConfig[]) => {
    setSectionsRaw(newSections);
  }, []);

  // Recompute session key whenever jdText or sections change
  useEffect(() => {
    if (!jdText.trim()) return;
    let cancelled = false;
    (async () => {
      const sectionNames = sections.map((s) => s.name);
      const key = await computeSessionKey(jdText, sectionNames);
      if (cancelled) return;
      setSessionKey(key);

      // Check for cached PDF
      const pdf = await getCachedPDF(key);
      setCachedPDF(pdf);

      // Check completed nodes
      const nodes = await getCompletedNodes(key);
      setCompletedNodes(nodes);
    })();
    return () => { cancelled = true; };
  }, [jdText, sections]);

  const clearDraft = useCallback(async () => {
    await saveDraft('', []);
    setDraftLoaded(false);
    setDraftTimestamp(null);
  }, []);

  return {
    jdText,
    setJdText,
    sections,
    setSections,
    cachedPDF,
    completedNodes,
    sessionKey,
    draftLoaded,
    draftTimestamp,
    clearDraft,
  };
}
