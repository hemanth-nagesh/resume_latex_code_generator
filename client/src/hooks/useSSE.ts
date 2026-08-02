import { useState, useCallback, useRef } from 'react';
import { openSSE, postGenerate, postApprove } from '../services/api';
import { saveNodeOutput } from '../services/cache';
import type {
  NodeId, SSEEvent, NodeStartEvent, NodeCompleteEvent,
  NodeErrorEvent, CompleteEvent, ReviewPendingEvent, PipelineErrorEvent, GenerateRequest,
} from '../types';

interface UseSSEReturn {
  isGenerating: boolean;
  nodeStatuses: Map<NodeId, 'pending' | 'running' | 'completed' | 'failed'>;
  error: string | null;
  latexOutput: string | null;
  pdfBase64: string | null;
  isInReview: boolean;
  reviewLatex: string | null;
  currentSessionKey: string | null;
  startGeneration: (request: GenerateRequest) => void;
  cancelGeneration: () => void;
  approveLatex: (latex: string) => void;
  resetReview: () => void;
}

export function useSSE(): UseSSEReturn {
  const [isGenerating, setIsGenerating] = useState(false);
  const [nodeStatuses, setNodeStatuses] = useState<
    Map<NodeId, 'pending' | 'running' | 'completed' | 'failed'>
  >(new Map());
  const [error, setError] = useState<string | null>(null);
  const [latexOutput, setLatexOutput] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [isInReview, setIsInReview] = useState(false);
  const [reviewLatex, setReviewLatex] = useState<string | null>(null);
  const [currentSessionKey, setCurrentSessionKey] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const startGeneration = useCallback(async (request: GenerateRequest) => {
    setIsGenerating(true);
    setError(null);
    setLatexOutput(null);
    setPdfBase64(null);
    setIsInReview(false);
    setReviewLatex(null);
    const newStatuses = new Map<NodeId, 'pending' | 'running' | 'completed' | 'failed'>();
    setNodeStatuses(newStatuses);

    try {
      const { session_id, session_key } = await postGenerate(request);
      setCurrentSessionKey(session_key);

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
        } else if (event.event === 'review_pending') {
          const e = rawEvent as ReviewPendingEvent;
          setReviewLatex(e.latex_source);
          setIsInReview(true);
          setLatexOutput(e.latex_source);
          setIsGenerating(false);
        } else if (event.event === 'complete') {
          const e = rawEvent as CompleteEvent;
          if (!e.latex_source) {
            setError('Pipeline completed but no LaTeX was generated');
            setIsGenerating(false);
            return;
          }
          setLatexOutput(e.latex_source);
          setPdfBase64(e.pdf_base64 || null);
          setIsInReview(false);
          setIsGenerating(false);
        } else if (event.event === 'pipeline_error') {
          const e = rawEvent as PipelineErrorEvent;
          setError(`Pipeline failed at ${e.failed_node}: ${e.error}`);
          setIsGenerating(false);
          setIsInReview(false);
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
    setIsInReview(false);
  }, []);

  const approveLatex = useCallback(async (latex: string) => {
    if (!currentSessionKey) return;
    setIsGenerating(true);
    setError(null);
    setIsInReview(false);

    try {
      await postApprove(currentSessionKey, latex);
      // SSE connection stays open — complete event will arrive
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF compilation failed');
      setIsGenerating(false);
    }
  }, [currentSessionKey]);

  const resetReview = useCallback(() => {
    setIsInReview(false);
    setReviewLatex(null);
    setLatexOutput(null);
    setPdfBase64(null);
  }, []);

  return {
    isGenerating, nodeStatuses, error, latexOutput, pdfBase64,
    isInReview, reviewLatex, currentSessionKey,
    startGeneration, cancelGeneration, approveLatex, resetReview,
  };
}

