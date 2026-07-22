import type { GenerateRequest } from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

export async function postGenerate(body: GenerateRequest): Promise<{ session_id: string; session_key: string }> {
  const res = await fetch(`${BASE_URL}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Generate request failed');
  }
  return res.json();
}

export function openSSE(sessionId: string, onEvent: (event: unknown) => void): EventSource {
  const source = new EventSource(`${BASE_URL}/api/stream/${sessionId}`);
  
  source.addEventListener('session_ready', (e) => onEvent(parseJSON(e.data)));
  source.addEventListener('node_start', (e) => onEvent(parseJSON(e.data)));
  source.addEventListener('node_complete', (e) => onEvent(parseJSON(e.data)));
  source.addEventListener('node_error', (e) => onEvent(parseJSON(e.data)));
  source.addEventListener('complete', (e) => {
    onEvent(parseJSON(e.data));
    source.close();
  });
  source.addEventListener('pipeline_error', (e) => {
    onEvent(parseJSON(e.data));
    source.close();
  });
  source.addEventListener('heartbeat', () => { /* keepalive */ });

  source.onerror = () => {
    // Reconnection handled by EventSource automatically
  };

  return source;
}

function parseJSON(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return { raw: data };
  }
}
