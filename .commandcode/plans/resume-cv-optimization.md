# Resume Update — Target Computer Vision Engineer Role

## Goal
Update ONLY three sections of `E_Hemanth_Nagesh.tex` (Professional Summary, Experience, Projects) to be ATS-optimized for the Computer Vision Engineer JD. Leave all other sections (Heading, Technical Skills, Education, Certifications) and LaTeX preamble unchanged.

## JD Keywords to incorporate
Computer vision models, object detection, image segmentation, image classification, deep learning frameworks (PyTorch, TensorFlow), OpenCV, image processing, feature extraction, data preprocessing, NumPy, Pandas, annotation tools (LabelImg), model training, evaluation, fine-tuning, optimization, end-to-end data pipeline (collection, cleaning, curation), C++, cross-functional collaboration, deployment, integration.

## File to modify
`/Users/hemanth/Coding & Staff/Resume/E_Hemanth_Nagesh.tex`

---

## Change 1 — PROFESSIONAL SUMMARY (replace existing `\section{PROFESSIONAL SUMMARY}` block)

```latex
\section{PROFESSIONAL SUMMARY}
\small
Computer Vision \& Deep Learning Engineer with an MCA (Master of Computer Applications) and 2.5+ years of experience developing, training, and deploying computer vision models for real-world applications such as object detection, image segmentation, and image classification. Proficient in deep learning frameworks PyTorch and TensorFlow, with hands-on expertise in OpenCV for image processing and feature extraction. Experienced in building end-to-end data pipelines — data collection, preprocessing, annotation, and curation — using Python libraries NumPy and Pandas. Skilled in model training, evaluation, fine-tuning, and optimization, with production deployment via Docker-containerized microservices on Azure. Strong problem-solving and analytical skills with a proven ability to collaborate with cross-functional teams for deployment and integration.
\vspace{-6pt}
```

## Change 2 — EXPERIENCE (replace both `\resumeSubheading` blocks under `\section{EXPERIENCE}`)

```latex
    \resumeSubheading
      {Tata Consultancy Services}{Dec. 2023 -- Present}
      {AI/ML Engineer — Computer Vision \& Deep Learning}{Bangalore, India}
      \resumeItemListStart
        \resumeItem{Developed and deployed computer vision models using PyTorch and TensorFlow for image classification and document verification — building object detection and image segmentation pipelines for real-world applications.}
        \resumeItem{Built end-to-end data pipelines covering data collection, cleaning, preprocessing, and curation using Python libraries NumPy and Pandas; prepared annotated datasets with tools such as LabelImg to ensure high-quality training data.}
        \resumeItem{Applied OpenCV for image processing and feature extraction, performing data augmentation and normalization to improve model robustness across diverse input conditions.}
        \resumeItem{Trained, evaluated, and fine-tuned deep learning models — optimizing hyperparameters and architectures to maximize accuracy and inference performance while reducing latency.}
        \resumeItem{Deployed models as production Python (FastAPI) APIs within a Docker-containerized microservices architecture on Azure, collaborating with cross-functional frontend (Next.js, React) and backend (NestJS) teams for deployment and integration.}
        \resumeItem{Established MLOps practices with CI/CD, automated testing, and model evaluation pipelines; mentored junior engineers on model governance and reproducible experiment tracking.}
      \resumeItemListEnd
    \resumeSubheading
      {BOTSIO Chatbot LLP}{Mar. 2023 -- May. 2023}
      {AI Engineer Intern — ML \& Data Pipelines}{Bangalore, India}
      \resumeItemListStart
        \resumeItem{Built end-to-end ML data pipelines handling data ingestion, preprocessing, and vector indexing (FAISS) — generating accurate, intent-driven outputs using Python (NumPy, Pandas).}
        \resumeItem{Developed scalable Python (FastAPI) RESTful APIs to operationalize ML models into PostgreSQL-backed environments — applying version control and automated testing.}
        \resumeItem{Performed data analysis and model evaluation, diagnosing edge cases and latency issues to support continuous model improvement.}
      \resumeItemListEnd
```

## Change 3 — PROJECTS (replace entire `\section{PROJECTS}` block; reordered to lead with the most CV-relevant project)

```latex
\section{PROJECTS}
    \resumeSubHeadingListStart
      \resumeProjectHeading
         {\textbf{Automated Document Verification Engine}}{2023 -- 2024}
          \resumeItemListStart
            \resumeItem{Designed a computer vision pipeline combining PyTorch image classification with scikit-learn models for automated document verification, deployed as microservices on Azure App Services.}
            \resumeItem{Built end-to-end data pipelines for data collection, cleaning, and annotation (LabelImg), applying OpenCV-based image preprocessing and feature extraction to improve classification accuracy.}
            \resumeItem{Trained, evaluated, and fine-tuned deep learning models with real-time logging and human-in-the-loop feedback — reducing manual verification effort by 70\% and validating model accuracy for critical decision support.}
            \resumeItem{\textbf{Tech Stack}: Python, PyTorch, TensorFlow, scikit-learn, OpenCV, NumPy, Pandas, Azure App Services, FastAPI, REST APIs}
          \resumeItemListEnd
      \resumeProjectHeading
          {\textbf{AI Copilot for Accessible Image \& Code Generation}} {2024 -- 2025}
          \resumeItemListStart
            \resumeItem{Built an AI copilot for automated accessibility testing, using computer vision and multimodal LLMs (Gemini/GPT) to analyze images and generate context-aware alt-text ensuring comprehensive WCAG coverage.}
            \resumeItem{Engineered prompt designs and image-processing workflows to extract visual features and produce high-relevance descriptions for accessible content generation.}
            \resumeItem{\textbf{Tech Stack}: Python, PyTorch, OpenCV, Gemini AI, LangChain, OpenAI, FastAPI, REST APIs}
          \resumeItemListEnd
      \resumeProjectHeading
          {\textbf{Enterprise AI Copilot \& Multi-Agent Orchestration Platform}} {2025 -- present}
          \resumeItemListStart
            \resumeItem{Designed a multi-agent workflow platform with a supervisor agent, domain-specific agents (research, database, document), and a Temporal-based workflow executor — enabling retry policies and human-in-the-loop oversight.}
            \resumeItem{Architected dual-layer memory (Redis short-term + pgvector long-term); deployed observability with tracing, LLM-as-judge evaluation, and prompt versioning to troubleshoot edge cases.}
            \resumeItem{Wrapped agent capabilities in production APIs with GitLab CI pipelines for automated testing and distributed execution — natively containerized via Docker.}
            \resumeItem{\textbf{Tech Stack}: Python, FastAPI, LangChain, LangGraph, OpenAI/Mistral APIs, Temporal, Redis, pgvector, Docker, GitLab CI}
          \resumeItemListEnd
      \resumeProjectHeading
         {\textbf{GenAI Internal Automation \& Dialogue Systems}}{2023 -- 2024}
          \resumeItemListStart
            \resumeItem{Developed an AI automation tool utilizing fine-tuned open-source LLMs (LLaMA via HuggingFace) to power contextual email drafting and automated responses.}
            \resumeItem{Structured evaluation frameworks to monitor generated text for accuracy, enabling structured learning and measurable progress tracking.}
            \resumeItem{\textbf{Tech Stack}: Python, PyTorch, Hugging Face, LLaMA, FastAPI, REST APIs}
          \resumeItemListEnd
    \resumeSubHeadingListEnd
```

## Notes
- Sections NOT changed: Heading, Technical Skills, Education, Certifications & Publications, and the LaTeX preamble/macros.
- The TCS role title is reframed from "AI/ML & Prompt Engineer — Gen AI & MLOps" to "AI/ML Engineer — Computer Vision & Deep Learning" to align with the target role.
- Projects reordered so the CV-relevant "Automated Document Verification Engine" leads.
- ATS keywords from the JD are woven naturally into all three sections.

## Verification
- Compile with `pdflatex E_Hemanth_Nagesh.tex` (or the project's build command) and confirm the PDF renders with no LaTeX errors.
- Visually confirm only the three target sections changed.
- Optionally scan the output text for JD keywords (PyTorch, TensorFlow, OpenCV, object detection, segmentation, NumPy, Pandas, LabelImg, fine-tuning, data pipeline).
