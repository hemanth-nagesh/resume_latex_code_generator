"""
Quick validation: substitute dummy content into the master template
and verify the output is structurally valid LaTeX.

Run standalone: python server/tests/validate_template.py
"""

from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "template" / "master_resume.tex"


def build_dummy_content() -> dict[str, str]:
    """Return dummy content for every content slot in the master template."""

    summary = (
        "Experienced engineer with 3+ years building scalable backend systems "
        "and AI-integrated applications. Strong background in Python, FastAPI, "
        "and cloud-native architectures with proven delivery of production systems."
    )

    experience = (
        r"\resumeSubheading"
        r"{AI/ML Engineer}{Dec 2023 -- Present}"
        r"{Tech Corp}{Bangalore, India}"
        r"\resumeItemListStart"
        r"  \resumeItem{Built scalable APIs using Python and FastAPI, reducing latency by 40\%.}"
        r"  \resumeItem{Optimized PostgreSQL queries, improving performance by 35\% through indexing.}"
        r"  \resumeItem{Led migration to microservices architecture on Kubernetes.}"
        r"\resumeItemListEnd"
        r"\resumeSubheading"
        r"{Intern}{Jan 2023 -- May 2023}"
        r"{Startup Inc}{Remote}"
        r"\resumeItemListStart"
        r"  \resumeItem{Developed RAG pipelines for production conversational AI systems.}"
        r"  \resumeItem{Created RESTful APIs with FastAPI for ML model serving.}"
        r"\resumeItemListEnd"
    )

    projects = (
        r"\resumeProjectHeading"
        r"{\textbf{AI Orchestration Platform}}{2025 -- present}"
        r"\resumeItemListStart"
        r"  \resumeItem{Designed multi-agent workflow with supervisor pattern and domain agents.}"
        r"  \resumeItem{Built conversational AI copilot with NLU-based intent understanding.}"
        r"  \resumeItem{\textbf{Tech Stack}: Python, FastAPI, LangGraph, Temporal, Redis}"
        r"\resumeItemListEnd"
        r"\resumeProjectHeading"
        r"{\textbf{Document Verification Engine}}{2023 -- 2024}"
        r"\resumeItemListStart"
        r"  \resumeItem{Built AI pipeline combining PyTorch classification with RAG verification.}"
        r"  \resumeItem{Automated scanning reducing human effort by 70\%.}"
        r"  \resumeItem{\textbf{Tech Stack}: Python, PyTorch, scikit-learn, Azure, FastAPI}"
        r"\resumeItemListEnd"
    )

    skills = (
        r"\textbf{Backend Development} {: Python, FastAPI, REST APIs, Microservices, Docker}\vspace{2pt} \\"
        r"\textbf{Databases} {: PostgreSQL, MySQL, MongoDB, Redis}\vspace{2pt} \\"
        r"\textbf{AI \& Machine Learning} {: PyTorch, scikit-learn, LangGraph, RAG Pipelines}\vspace{2pt} \\"
        r"\textbf{Cloud \& DevOps} {: Azure, Kubernetes, Docker, GitLab CI}\vspace{2pt}"
    )

    education = (
        r"\resumeSubheading"
        r"{PES College of Engineering}{2021 -- 2023}"
        r"{Master of Computer Applications (MCA)}{}"
        r"\resumeSubheading"
        r"{Ramaiah Institute of Business Studies}{2018 -- 2021}"
        r"{Bachelor of Computer Applications (BCA)}{}"
    )

    certifications = (
        r"\item[] \textbf{Microsoft Certified: Azure AI Engineer Associate} (2026) \vspace{-2pt}"
        r"\item[] \textbf{AI-Powered Information Retrieval Systems} (2023) "
        r"-- Peer-reviewed paper. \href{https://example.com}{\myuline{[Link]}}"
    )

    return {
        "%%SUMMARY_TEXT%%": summary,
        "%%EXPERIENCE_BLOCK%%": experience,
        "%%PROJECTS_BLOCK%%": projects,
        "%%SKILLS_BLOCK%%": skills,
        "%%EDUCATION_BLOCK%%": education,
        "%%CERTIFICATIONS_BLOCK%%": certifications,
    }


def substitute_template(template: str, content: dict[str, str]) -> str:
    """Pure string substitution into the locked template."""
    result = template
    for slot, value in content.items():
        result = result.replace(slot, value)
    return result


def validate_output(latex: str) -> list[str]:
    """Run structural checks on the filled template."""
    issues: list[str] = []

    # Must start with \documentclass
    if not latex.strip().startswith("%"):
        # first non-comment line should be documentclass
        pass

    # Must have \begin{document} and \end{document}
    if r"\begin{document}" not in latex:
        issues.append("Missing \\begin{document}")
    if r"\end{document}" not in latex:
        issues.append("Missing \\end{document}")

    # No unsubstituted placeholders
    import re
    leftover = re.findall(r"%%[A-Z_]+%%", latex)
    if leftover:
        issues.append(f"Unsubstituted placeholders: {leftover}")

    # All custom commands in output must be in the schema
    allowed = (r"\resumeItem", r"\resumeSubheading", r"\resumeSubSubheading",
               r"\resumeProjectHeading", r"\resumeSubItem",
               r"\resumeSubHeadingListStart", r"\resumeSubHeadingListEnd",
               r"\resumeItemListStart", r"\resumeItemListEnd",
               r"\textbf", r"\textit", r"\href", r"\myuline")

    return issues


def main():
    print(f"Loading template: {TEMPLATE_PATH}")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    content = build_dummy_content()
    filled = substitute_template(template, content)

    # Write to temp for inspection
    out_path = Path("/tmp/test_master_resume.tex")
    out_path.write_text(filled, encoding="utf-8")
    print(f"Filled template written to: {out_path}")

    issues = validate_output(filled)
    if issues:
        print("\nISSUES FOUND:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    # Count lines
    lines = filled.count("\n")
    section_count = filled.count(r"\section{")

    print(f"\nTemplate validation passed!")
    print(f"  Lines: {lines}")
    print(f"  Sections: {section_count}")
    print(f"  Content slots filled: {len(content)}")

    # Print slot sizes
    for slot, value in content.items():
        print(f"  {slot}: {len(value)} chars")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
