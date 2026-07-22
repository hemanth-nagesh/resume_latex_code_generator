import { openDB, type IDBPDatabase } from 'idb';
import type { DraftData, CachedPDF } from '../types';

const DB_NAME = 'resume-builder';
const DB_VERSION = 1;

function getDB(): Promise<IDBPDatabase> {
  return openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains('drafts')) {
        db.createObjectStore('drafts');
      }
      if (!db.objectStoreNames.contains('sessions')) {
        db.createObjectStore('sessions');
      }
      if (!db.objectStoreNames.contains('pdfs')) {
        db.createObjectStore('pdfs');
      }
    },
  });
}

function isExpired(savedAt: string, ttlDays: number): boolean {
  const saved = new Date(savedAt).getTime();
  const now = Date.now();
  return now - saved > ttlDays * 24 * 60 * 60 * 1000;
}

// --- Drafts ---

export async function saveDraft(jdText: string, sections: string[]): Promise<void> {
  const db = await getDB();
  const data: DraftData = {
    jd_text: jdText,
    sections,
    saved_at: new Date().toISOString(),
    ttl_days: 7,
  };
  await db.put('drafts', data, 'current');
}

export async function loadDraft(): Promise<DraftData | null> {
  const db = await getDB();
  const data = await db.get('drafts', 'current') as DraftData | undefined;
  if (!data) return null;
  if (isExpired(data.saved_at, data.ttl_days)) {
    await db.delete('drafts', 'current');
    return null;
  }
  return data;
}

// --- Session node outputs ---

export async function saveNodeOutput(
  sessionKey: string,
  nodeId: string,
  output: unknown,
): Promise<void> {
  const db = await getDB();
  const entry = {
    output,
    saved_at: new Date().toISOString(),
    ttl_hours: 6,
  };
  await db.put('sessions', entry, `session:${sessionKey}:node:${nodeId}`);
}

export async function getNodeOutput(
  sessionKey: string,
  nodeId: string,
): Promise<unknown | null> {
  const db = await getDB();
  const entry = await db.get('sessions', `session:${sessionKey}:node:${nodeId}`) as
    | { output: unknown; saved_at: string; ttl_hours: number }
    | undefined;
  if (!entry) return null;
  if (isExpired(entry.saved_at, entry.ttl_hours / 24)) {
    await db.delete('sessions', `session:${sessionKey}:node:${nodeId}`);
    return null;
  }
  return entry.output;
}

export async function getCompletedNodes(sessionKey: string): Promise<string[]> {
  const db = await getDB();
  const keys = await db.getAllKeys('sessions');
  const prefix = `session:${sessionKey}:node:`;
  return keys
    .filter((k) => typeof k === 'string' && k.startsWith(prefix))
    .map((k) => (k as string).slice(prefix.length));
}

// --- PDF cache ---

export async function savePDF(
  sessionKey: string,
  pdfBuffer: ArrayBuffer,
  jdPreview: string,
): Promise<void> {
  const db = await getDB();
  const data: CachedPDF = {
    pdf_blob: pdfBuffer,
    generated_at: new Date().toISOString(),
    session_key: sessionKey,
    jd_preview: jdPreview,
  };
  await db.put('pdfs', data, `session:${sessionKey}:pdf`);
}

export async function getCachedPDF(sessionKey: string): Promise<CachedPDF | null> {
  const db = await getDB();
  const data = await db.get('pdfs', `session:${sessionKey}:pdf`) as CachedPDF | undefined;
  if (!data) return null;
  if (isExpired(data.generated_at, 7)) {
    await db.delete('pdfs', `session:${sessionKey}:pdf`);
    return null;
  }
  return data;
}

// --- Full cache clear ---

export async function clearAllCache(): Promise<void> {
  const db = await getDB();
  await db.clear('drafts');
  await db.clear('sessions');
  await db.clear('pdfs');
}
