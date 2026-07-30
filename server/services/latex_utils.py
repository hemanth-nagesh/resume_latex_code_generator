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


# ---------------------------------------------------------------------------
# Deterministic LaTeX Sanitizer — fixes common Gemini output issues
# programmatically without requiring an LLM call. Applied BEFORE N9
# validation and as part of N8 assembly.
# ---------------------------------------------------------------------------

# Lines containing these patterns are "safe" contexts where raw & is valid
_TABULAR_ENV_RE = re.compile(r"\\begin\{(tabular\*?|tabularx|longtable)\}")
_NEWCOMMAND_RE = re.compile(r"\\(new|renew)command")

# Match raw & not preceded by backslash
_RAW_AMP_RE = re.compile(r"(?<!\\)&")

# Match raw % not preceded by backslash (but not at end-of-line comments)
_RAW_PERCENT_RE = re.compile(r"(?<!\\)%")

# Match raw $ not preceded by backslash and not part of $|$ separator
_RAW_DOLLAR_RE = re.compile(r"(?<!\\)\$(?!\|?\$)")

# Match raw # not preceded by backslash
_RAW_HASH_RE = re.compile(r"(?<!\\)#")

# Common patterns Gemini produces that contain raw & in text
# e.g., "ML & AI", "Frameworks & Libraries", "R&D"
_TEXT_AMP_PATTERNS = re.compile(
    r"(?<!\\)&"  # any raw & that isn't already escaped
)


def sanitize_latex_source(latex: str) -> str:
    """Deterministic sanitizer for assembled LaTeX source.

    Fixes common issues WITHOUT requiring an LLM call:
    1. Raw '&' outside tabular environments → \\&
    2. Raw '%' that isn't a LaTeX comment → \\%
    3. Double-escaped characters (\\\\&) → \\&
    4. Mismatched braces in simple cases

    This is safe to call on fully-assembled LaTeX because it respects
    LaTeX command structure and only modifies characters in text positions.

    Returns: sanitized LaTeX source string.
    """
    lines = latex.split("\n")
    result_lines = []
    in_tabular = False
    tabular_depth = 0

    for line in lines:
        # Track tabular environment state
        for m in re.finditer(r"\\begin\{(tabular\*?|tabularx|longtable)\}", line):
            in_tabular = True
            tabular_depth += 1
        for m in re.finditer(r"\\end\{(tabular\*?|tabularx|longtable)\}", line):
            tabular_depth -= 1
            if tabular_depth <= 0:
                in_tabular = False
                tabular_depth = 0

        # Skip lines that are in safe contexts
        if in_tabular:
            result_lines.append(line)
            continue
        if _NEWCOMMAND_RE.search(line):
            result_lines.append(line)
            continue

        # Process this line for forbidden characters
        fixed_line = _fix_line_chars(line)
        result_lines.append(fixed_line)

    result = "\n".join(result_lines)

    # Fix double-escaping issues (e.g., \\& → \&)
    result = _fix_double_escapes(result)

    return result


def _fix_line_chars(line: str) -> str:
    """Fix forbidden characters on a single line.

    Strategy: split the line into "LaTeX command" segments and "text" segments.
    Only escape special chars in text segments.
    """
    # Strip LaTeX comment portion (keep it separate)
    comment = ""
    comment_match = re.search(r"(?<!\\)%", line)
    if comment_match:
        # Check if this % is actually inside a command argument
        # by counting brace depth at this position
        pos = comment_match.start()
        depth = 0
        for i in range(pos):
            if line[i] == "{" and (i == 0 or line[i-1] != "\\"):
                depth += 1
            elif line[i] == "}" and (i == 0 or line[i-1] != "\\"):
                depth -= 1
        if depth == 0:
            # It's a genuine comment
            comment = line[pos:]
            line = line[:pos]

    # Fix raw & characters
    # We need to be careful: & is valid inside $|$ math separators,
    # but NOT valid as raw text outside tabular
    fixed = _escape_raw_ampersands(line)

    return fixed + comment


def _escape_raw_ampersands(line: str) -> str:
    """Escape raw & characters that appear in text content.

    Preserves:
    - Already escaped \\& 
    - & inside \\begin{tabular} (handled by caller)
    - & in \\newcommand definitions (handled by caller)

    Escapes:
    - Raw & in \\textbf{Frameworks & Libraries}
    - Raw & in \\resumeItem{...R&D...}
    - Raw & in any other text position
    """
    result = []
    i = 0
    while i < len(line):
        if line[i] == "&":
            # Check if preceded by backslash (already escaped)
            if i > 0 and line[i-1] == "\\":
                result.append("&")  # already escaped, keep as-is
            else:
                # Check if this is part of $|$ math separator (unlikely with &)
                # In resume context, raw & is almost never intentional
                result.append("\\&")
        else:
            result.append(line[i])
        i += 1
    return "".join(result)


def _fix_double_escapes(text: str) -> str:
    """Fix common double-escape issues.

    When both Gemini AND our sanitizer escape the same char, we get \\\\&
    instead of \\&. Fix these.
    """
    # \\& → \& (but NOT \\\\& which is a literal backslash + escaped &)
    text = re.sub(r"(?<!\\)\\\\&", r"\\&", text)
    text = re.sub(r"(?<!\\)\\\\%", r"\\%", text)
    text = re.sub(r"(?<!\\)\\\\\$", r"\\$", text)
    text = re.sub(r"(?<!\\)\\\\#", r"\\#", text)
    return text


def sanitize_gemini_section_output(text: str) -> str:
    """Sanitize a single section's Gemini-generated LaTeX output.

    Called by N8 assembler on each section before substitution into template.
    Lighter-weight than sanitize_latex_source — focuses on the most common
    Gemini output issues:
    1. Raw & in text content (e.g., "ML & AI")
    2. Raw % that breaks compilation
    3. Unicode characters that LaTeX can't handle

    Does NOT modify:
    - LaTeX commands (\\textbf, \\resumeItem, etc.)
    - Already-escaped characters (\\&, \\%, etc.)
    - Math mode content ($...$)
    """
    if not text:
        return ""

    lines = text.split("\n")
    result = []

    for line in lines:
        # Skip empty lines
        if not line.strip():
            result.append(line)
            continue

        # Fix raw & outside of already-escaped contexts
        fixed = _escape_raw_ampersands(line)

        # Fix common unicode characters that break pdflatex
        fixed = _fix_unicode_chars(fixed)

        result.append(fixed)

    return "\n".join(result)


def _fix_unicode_chars(line: str) -> str:
    """Replace common Unicode characters with LaTeX equivalents."""
    replacements = {
        "\u2013": "--",      # en-dash
        "\u2014": "---",     # em-dash
        "\u2018": "`",       # left single quote
        "\u2019": "'",       # right single quote
        "\u201c": "``",      # left double quote
        "\u201d": "''",      # right double quote
        "\u2026": "...",     # ellipsis
        "\u00a0": "~",       # non-breaking space
        "\u2022": r"\textbullet{}",  # bullet
        "\u2192": r"$\rightarrow$",  # right arrow
        "\u2190": r"$\leftarrow$",   # left arrow
        "\u00b1": r"$\pm$",  # plus-minus
        "\u2265": r"$\geq$", # >=
        "\u2264": r"$\leq$", # <=
        "\u2260": r"$\neq$", # !=
    }
    for char, replacement in replacements.items():
        line = line.replace(char, replacement)
    return line


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
