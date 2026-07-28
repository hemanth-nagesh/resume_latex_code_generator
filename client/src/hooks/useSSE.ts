import { useState, useCallback, useRef } from 'react';
import { openSSE, postGenerate } from '../services/api';
import { saveNodeOutput } from '../services/cache';
import type {
  NodeId, SSEEvent, NodeStartEvent, NodeCompleteEvent,
  NodeErrorEvent, CompleteEvent, PipelineErrorEvent, GenerateRequest,
} from '../types';

interface UseSSEReturn {
  isGenerating: boolean;
  nodeStatuses: Map<NodeId, 'pending' | 'running' | 'completed' | 'failed'>;
  error: string | null;
  latexOutput: string | null;
  pdfBase64: string | null;
  startGeneration: (request: GenerateRequest) => void;
  cancelGeneration: () => void;
}

export function useSSE(): UseSSEReturn {
  const [isGenerating, setIsGenerating] = useState(false);
  const [nodeStatuses, setNodeStatuses] = useState<
    Map<NodeId, 'pending' | 'running' | 'completed' | 'failed'>
  >(new Map());
  const [error, setError] = useState<string | null>(null);
  const [latexOutput, setLatexOutput] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const startGeneration = useCallback(async (request: GenerateRequest) => {
    setIsGenerating(true);
    setError(null);
    setLatexOutput(null);
    setPdfBase64(null);
    const newStatuses = new Map<NodeId, 'pending' | 'running' | 'completed' | 'failed'>();
    setNodeStatuses(newStatuses);

    try {
      const { session_id, session_key } = await postGenerate(request);

      const source = openSSE(session_id, (rawEvent) => {
        const event = rawEvent as SSEEvent;

        if (event.event === 'node_start') {
          const e = rawEvent as NodeStartEvent;
          newStatuses.set(e.node, 'running');
          setNodeStatuses(new Map(newStatuses));
        } else if (event.event === 'node_complete') {
          const e = rawEvent as NodeCompleteEvent;
          newStatuses.set(e.node, 'completed');
          setNodeStatuses(new Map(newStatuses));
          saveNodeOutput(session_key, e.node, { duration_ms: e.duration_ms });
        } else if (event.event === 'node_error') {
          const e = rawEvent as NodeErrorEvent;
          newStatuses.set(e.node, 'failed');
          setNodeStatuses(new Map(newStatuses));
          setError(`${e.node}: ${e.error}`);
        } else if (event.event === 'complete') {
          const e = rawEvent as CompleteEvent;
          if (!e.latex_source) {
            setError('Pipeline completed but no LaTeX was generated');
            setIsGenerating(false);
            return;
          }
          setLatexOutput(e.latex_source);
          setPdfBase64(e.pdf_base64 || null);
          setIsGenerating(false);
        } else if (event.event === 'pipeline_error') {
          const e = rawEvent as PipelineErrorEvent;
          setError(`Pipeline failed at ${e.failed_node}: ${e.error}`);
          setIsGenerating(false);
        }
      });

      sourceRef.current = source;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
      setIsGenerating(false);
    }
  }, []);

  const cancelGeneration = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    setIsGenerating(false);
  }, []);

  return { isGenerating, nodeStatuses, error, latexOutput, pdfBase64, startGeneration, cancelGeneration };
}

