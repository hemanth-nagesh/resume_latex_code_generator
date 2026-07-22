# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# latex
- When tailoring a resume for a specific company, create a separate file with a meaningful name (e.g., `{FullName}_{Company}_{Role}.tex`) rather than editing the original in-place. Confidence: 0.65
- Use a locked master .tex template in Azure Blob Storage with strictly typed content slots (plain text for summary, custom command calls for experience/projects/skills); template is read-only and manually verified. Confidence: 0.85
- N8 (latex_assembler) performs pure string substitution (`str.replace`) into the locked template; never let Gemini generate LaTeX structural commands. Confidence: 0.85
- N9 (latex_validator) must validate custom template command signatures and argument counts via a hardcoded `CUSTOM_COMMAND_SCHEMA` dict (e.g., `\resumeItem{1 arg}`, `\resumeSubheading{4 args}`). Confidence: 0.85
- Use raw .tex template file + string substitution, not PyLaTeX, for fixed-structure documents like resumes. Confidence: 0.85

# architecture
- Follow SOLID principles, KISS (Keep It Simple, Stupid), and DRY (Don't Repeat Yourself) across all phases with patterns like Abstract Factory, factory pattern, and cross-cutting concerns for robust architecture. Confidence: 0.75

# api
- Distribute LLM calls across multiple API keys (already in env) to avoid free-tier rate limits; rotate keys per call in the pipeline. Confidence: 0.75
- On Gemini 503/UNAVAILABLE and 429/RESOURCE_EXHAUSTED errors, fall back to `GEMINI_MODEL_FALLBACK` env var model instead of retrying the same model or waiting on backoff. Confidence: 0.75

# ai-prompts
- Section generator prompts (N7a–N7d) must include verbatim output format examples showing exact LaTeX commands Gemini must use (e.g., `\resumeItem{}`, `\resumeSubheading{}`) and explicitly forbid structural commands like `\begin{}`, `\end{}`, `\section{}`. Confidence: 0.85
- N7a (summary) prompt instructs Gemini to return plain text only, since the summary content slot takes no LaTeX commands. Confidence: 0.85

