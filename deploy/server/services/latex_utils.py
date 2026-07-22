r"""LaTeX utility functions — escaping, parsing, command validation.

These are pure functions with no side effects or external dependencies.
Used by N8 (assembler) and N9 (validator).
"""

import re

# LaTeX special characters that must be escaped in text content
_LATEX_SPECIAL_CHARS: dict[str, str] = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# Reverse map for unescaping
_LATEX_UNESCAPE_CHARS: dict[str, str] = {
    r"\&": "&",
    r"\%": "%",
    r"\$": "$",
    r"\#": "#",
    r"\_": "_",
    r"\{": "{",
    r"\}": "}",
    r"\textasciitilde{}": "~",
    r"\textasciicircum{}": "^",
}

# Regex: matches a LaTeX command followed by its brace-delimited argument groups
_COMMAND_WITH_ARGS = re.compile(
    r"\\([a-zA-Z@]+)"           # command name
    r"((?:\{[^}]*\})*)"         # zero or more {arg} groups
)

# Regex: matches a single brace group (handles nested braces)
_BRACE_GROUP = re.compile(r"\{((?:[^{}]|\{[^{}]*\})*)\}")


def escape_special_chars(text: str) -> str:
    """Escape LaTeX special characters in plain text content.

    Only call this on raw text (summary paragraph, user-provided strings).
    Do NOT call on already-LaTeX-formatted content from Gemini.
    """
    result = text
    for char, escaped in _LATEX_SPECIAL_CHARS.items():
        result = result.replace(char, escaped)
    return result


def unescape_special_chars(text: str) -> str:
    """Reverse escape_special_chars. Used when extracting raw text from LaTeX."""
    result = text
    for escaped, char in _LATEX_UNESCAPE_CHARS.items():
        result = result.replace(escaped, char)
    return result


def count_braces(latex: str) -> tuple[int, int, int, int]:
    """Count opening/closing braces, distinguishing structural from escaped.

    Returns: (open_count, close_count, escaped_open_count, escaped_close_count)
    """
    # Remove comments
    clean = re.sub(r"(?<!\\)%.*$", "", latex, flags=re.MULTILINE)

    escaped_open = len(re.findall(r"\\\{", clean))
    escaped_close = len(re.findall(r"\\\}", clean))

    all_open = clean.count("{")
    all_close = clean.count("}")

    structural_open = all_open - escaped_open
    structural_close = all_close - escaped_close

    return structural_open, structural_close, escaped_open, escaped_close


def check_brace_balance(latex: str) -> tuple[bool, str | None]:
    """Verify structural braces are balanced.

    Returns: (True, None) if balanced, (False, error_message) if not.
    """
    structural_open, structural_close, _, _ = count_braces(latex)
    if structural_open != structural_close:
        return False, (
            f"Unbalanced braces: {structural_open} open, {structural_close} close"
        )
    return True, None


def check_environment_matching(latex: str) -> tuple[bool, str | None]:
    """Verify every \\begin{X} has a matching \\end{X}.

    Uses a stack-based approach. Handles nested environments.
    """
    begins = re.finditer(r"\\begin\{([^}]+)\}", latex)
    ends = re.finditer(r"\\end\{([^}]+)\}", latex)

    # Build ordered list of (position, type, env_name)
    events: list[tuple[int, str, str]] = []
    for m in begins:
        events.append((m.start(), "begin", m.group(1)))
    for m in ends:
        events.append((m.start(), "end", m.group(1)))

    events.sort(key=lambda e: e[0])

    stack: list[str] = []
    for pos, kind, env_name in events:
        if kind == "begin":
            stack.append(env_name)
        elif kind == "end":
            if not stack:
                return False, f"Unexpected \\end{{{env_name}}} at position {pos}"
            expected = stack.pop()
            if expected != env_name:
                return False, (
                    f"Mismatched environment at position {pos}: "
                    f"expected \\end{{{expected}}}, found \\end{{{env_name}}}"
                )

    if stack:
        return False, f"Unclosed environments: {', '.join(stack)}"
    return True, None


def check_placeholders(latex: str) -> tuple[bool, str | None]:
    """Verify no unsubstituted template placeholders remain."""
    placeholders = re.findall(r"%%[A-Z_]+%%", latex)
    if placeholders:
        return False, f"Unsubstituted placeholders: {', '.join(placeholders)}"
    return True, None


def parse_custom_command_args(
    latex: str, command_names: tuple[str, ...]
) -> list[dict]:
    """Extract all calls to given custom commands with their argument counts.

    Returns list of dicts: {line, command, arg_count, args: [...]}

    Uses a stack-based brace parser that handles arbitrary nesting
    (e.g., \resumeProjectHeading{{\\textbf{X} $|$ \\emph{Y}}}{Date}).

    Used by N9 to validate argument counts against CUSTOM_COMMAND_SCHEMA.
    """
    results: list[dict] = []
    lines = latex.split("\n")

    for cmd in command_names:
        escaped = re.escape(cmd)
        for line_idx, line in enumerate(lines, start=1):
            pos = 0
            while True:
                # Find next occurrence of this command
                m = re.search(escaped, line[pos:])
                if not m:
                    break
                start = pos + m.end()
                # Parse argument groups from this position
                args = _extract_brace_groups(line, start)
                if args is not None:
                    results.append({
                        "line": line_idx,
                        "command": cmd,
                        "arg_count": len(args),
                        "args": args,
                    })
                pos = start + 1  # advance past command
                if args is not None:
                    # Skip past the parsed arguments
                    args_len = sum(len(a) + 2 for a in args)  # +2 for {}
                    pos = start + args_len

    return results


def _extract_brace_groups(text: str, start: int) -> list[str] | None:
    """Extract top-level brace-delimited argument groups starting at position.

    Returns list of raw argument strings (without outer braces), or None
    if no brace groups found.

    Handles nested braces correctly using a depth counter.
    """
    if start >= len(text) or text[start] != "{":
        return None

    groups: list[str] = []
    i = start

    while i < len(text) and text[i] == "{":
        depth = 0
        buf: list[str] = []
        i += 1  # skip opening {
        depth = 1
        group_start = i

        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    groups.append(text[group_start:i])
                    i += 1  # skip closing }
                    break
            i += 1

        if depth != 0:
            # Unclosed group — stop parsing
            break

    return groups if groups else None


def strip_latex_commands(text: str) -> str:
    """Remove LaTeX commands, keeping only text content.

    Used by N10f fallback to extract raw text from broken LaTeX.

    Strategy: iteratively peel off outer commands by repeatedly
    consuming \\command{{...}} groups from left to right, then
    remove residual braces and control sequences.
    """
    import re

    result = text
    changed = True
    while changed:
        prev = result
        # Remove \command{arg1}{arg2}... — extract inner content
        result = re.sub(
            r"\\[a-zA-Z@]+\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
            r"\1",
            result,
        )
        changed = (result != prev)

    # Remove remaining \command without args
    result = re.sub(r"\\[a-zA-Z@]+", "", result)
    # Remove residual braces that were inner content boundaries
    result = result.replace("{", "").replace("}", "")

    return result.strip()
