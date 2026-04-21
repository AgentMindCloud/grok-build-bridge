"""Compiled regex library for the static half of the safety scan.

Every entry is a pair of ``(compiled_regex, issue_message)``. Messages are
short, human-readable strings that :func:`grok_build_bridge.safety.scan_generated_code`
copies verbatim into the :class:`SafetyReport`.

Design principles — each pattern has to survive two tests:

1. **Signal over noise**: the pattern should flag a real foot-gun, not a
   vaguely risky substring. A flag that fires on harmless code trains
   users to ignore the whole report.
2. **Language-agnostic where cheap**: patterns that work for Python-ish,
   JS-ish, and Go-ish syntax at once live in :data:`STATIC_CHECKS`;
   language-specific rules are gated inside
   :func:`grok_build_bridge.safety._run_static_scans`.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Secret-shaped strings
# ---------------------------------------------------------------------------

# AWS access key id: always AKIA/ASIA/etc. + 16 uppercase/digits.
# Anchored on the AKIA prefix so generic 20-char uppercase hex does not match.
_AWS_ACCESS_KEY: Final[re.Pattern[str]] = re.compile(
    r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)[A-Z0-9]{16}\b"
)

# xAI key format as documented on console.x.ai: "xai-" followed by 80+
# url-safe characters. We require length ≥ 32 after the prefix to avoid
# matching "xai-foo" in comments or test fixtures. This still catches the
# real keys, which are much longer.
_XAI_KEY: Final[re.Pattern[str]] = re.compile(r"\bxai-[A-Za-z0-9_-]{32,}\b")

# OpenAI keys: legacy "sk-<48 chars>" or "sk-proj-<...>" project keys.
# We require the 'sk-' prefix plus at least 20 trailing chars.
_OPENAI_KEY: Final[re.Pattern[str]] = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")

# GitHub personal / fine-grained tokens ("ghp_" / "github_pat_") — included
# because generated code sometimes leaks deploy tokens committed for CI.
_GITHUB_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,})\b"
)

# ---------------------------------------------------------------------------
# Dangerous runtime constructs
# ---------------------------------------------------------------------------

# eval(...) / exec(...) — both Python and JS idioms. We require the ``(``
# immediately after the identifier and a word boundary before it to avoid
# matching ``method.exec(`` on e.g. SQL query builders.
_EVAL_CALL: Final[re.Pattern[str]] = re.compile(r"\b(?:eval|exec)\s*\(")

# Unbounded ``while True:`` / ``while (true)`` with no visible ``break`` in
# the surrounding block (we scan the next ~40 lines). Handled by the safety
# module rather than a bare regex because a pure regex can't prove the
# ``break`` is in the *same* loop body; but for the ``matched?`` signal a
# bare substring catch is good enough — the LLM double-checks.
_WHILE_TRUE: Final[re.Pattern[str]] = re.compile(r"\bwhile\s*\(?\s*(?:True|true|1)\s*\)?\s*:")

# subprocess.*(..., shell=True, ...). Matches both keyword and positional
# usage that explicitly opts into a shell. We don't flag ``shell=False``.
_SHELL_TRUE: Final[re.Pattern[str]] = re.compile(
    r"\bsubprocess\.[A-Za-z_]+\s*\([^)]*shell\s*=\s*True", re.DOTALL
)

# Bare os.system() / os.popen() / commands.getoutput() — all route through
# ``/bin/sh -c`` and are the classic command-injection vector.
_OS_SYSTEM: Final[re.Pattern[str]] = re.compile(
    r"\bos\.(?:system|popen)\s*\(|\bcommands\.getoutput\s*\("
)

# requests.get/post/put/delete/patch(...) that does NOT include a
# ``timeout=`` kwarg anywhere in the call. The negative look-ahead scopes
# to a single balanced paren depth — good enough for linear code, and the
# LLM pass catches the exotic cases.
_REQUESTS_NO_TIMEOUT: Final[re.Pattern[str]] = re.compile(
    r"\brequests\.(?:get|post|put|delete|patch|head|request)\s*\((?![^)]*\btimeout\s*=)[^)]*\)"
)

# pickle.load(s) / yaml.load without ``Loader=SafeLoader``. Both are classic
# arbitrary-code-execution sinks when fed untrusted input.
_UNSAFE_DESERIALIZATION: Final[re.Pattern[str]] = re.compile(
    r"\bpickle\.loads?\s*\(|\byaml\.load\s*\((?![^)]*SafeLoader)"
)

# ---------------------------------------------------------------------------
# The public catalog
# ---------------------------------------------------------------------------

# Ordered so that the most damning findings (leaked secrets) appear first
# in the generated report. Each message starts with a short slug that
# downstream code can key on (e.g. ``"shell-call"`` in tests).
STATIC_CHECKS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        _AWS_ACCESS_KEY,
        "hardcoded-secret: AWS access key id appears in source — move it to an env var",
    ),
    (
        _XAI_KEY,
        "hardcoded-secret: xAI API key appears in source — load from XAI_API_KEY env var",
    ),
    (
        _OPENAI_KEY,
        "hardcoded-secret: OpenAI key appears in source — move it to an env var",
    ),
    (
        _GITHUB_TOKEN,
        "hardcoded-secret: GitHub token appears in source — use a secrets manager",
    ),
    (
        _EVAL_CALL,
        "unsafe-eval: eval()/exec() call detected — reject arbitrary-code execution",
    ),
    (
        _WHILE_TRUE,
        "infinite-loop: unbounded while-True loop — add a break condition or max iterations",
    ),
    (
        _SHELL_TRUE,
        "shell-call: subprocess with shell=True is command-injection prone — use shell=False with a list of args",
    ),
    (
        _OS_SYSTEM,
        "shell-call: os.system/os.popen is command-injection prone — prefer subprocess.run with shell=False",
    ),
    (
        _REQUESTS_NO_TIMEOUT,
        "no-timeout: requests call without timeout= — add an explicit timeout to avoid hangs",
    ),
    (
        _UNSAFE_DESERIALIZATION,
        "unsafe-deserialization: pickle.load / yaml.load without SafeLoader — use safe alternatives",
    ),
)
