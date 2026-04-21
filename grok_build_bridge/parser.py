"""YAML parser and schema validator for bridge configuration files.

Loads a ``bridge.yaml`` file, validates it against
``grok_build_bridge/schema/bridge.schema.json``, applies defaults, and
returns an immutable mapping ready for downstream consumers.

Why immutable? Once a bridge run has started, mutating the config from a
downstream module is a silent-bug vector (who changed ``deploy.target``?).
Freezing with :class:`types.MappingProxyType` turns such mistakes into a
loud ``TypeError`` at the exact callsite.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

_SCHEMA_PATH: Final[Path] = Path(__file__).parent / "schema" / "bridge.schema.json"

# Entry-point defaults can't live in JSON Schema because the default depends
# on a sibling field (`build.language`). We resolve it in a post-validation
# pass so the schema stays declarative and the cross-field rule stays in code.
_ENTRYPOINT_BY_LANGUAGE: Final[dict[str, str]] = {
    "python": "main.py",
    "typescript": "index.ts",
    "go": "main.go",
}


class BridgeConfigError(ValueError):
    """Raised when a bridge YAML document fails to parse or validate.

    Carries enough structured context (``key_path``, ``expected``, ``line``,
    ``column``) for both machine consumers and the Rich panel renderer to
    pinpoint the problem without re-parsing the file.
    """

    def __init__(
        self,
        message: str,
        *,
        key_path: Iterable[str | int] | None = None,
        expected: str | None = None,
        line: int | None = None,
        column: int | None = None,
        source_path: str | Path | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.key_path: tuple[str | int, ...] = tuple(key_path or ())
        self.expected: str | None = expected
        self.line: int | None = line
        self.column: int | None = column
        self.source_path: str | None = str(source_path) if source_path else None

    def render(self, console: Console | None = None) -> None:
        """Print a colored Rich panel highlighting the offending key path."""
        console = console or Console(stderr=True)
        body = Text()

        body.append("key: ", style="bold")
        pretty_path = ".".join(str(p) for p in self.key_path) if self.key_path else "<root>"
        body.append(pretty_path, style="bold red")
        body.append("\n")

        if self.expected is not None:
            body.append("expected: ", style="bold")
            body.append(self.expected, style="green")
            body.append("\n")

        body.append("reason: ", style="bold")
        body.append(self.message, style="yellow")

        if self.line is not None:
            body.append("\nlocation: ", style="bold")
            loc = f"line {self.line}"
            if self.column is not None:
                loc += f", column {self.column}"
            if self.source_path:
                loc = f"{self.source_path}:{loc}"
            body.append(loc, style="cyan")

        console.print(Panel(body, title="🚫 Invalid bridge.yaml", border_style="red"))


def _load_schema() -> dict[str, Any]:
    """Read and cache the JSON schema bundled with the package."""
    # Not using functools.lru_cache because we want fresh reads in tests that
    # patch the schema path; this is cheap (tens of KB) so re-reading is fine.
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _build_default_filling_validator() -> type[Draft202012Validator]:
    """Return a Draft 2020-12 validator subclass that populates defaults.

    The jsonschema library deliberately does NOT fill defaults — doing so
    would mutate user data during what looks like a pure check. We only want
    that mutation inside :func:`load_yaml`, which explicitly copies the
    document first, so we build a dedicated validator here rather than
    monkey-patching the shared one.
    """
    base_properties = Draft202012Validator.VALIDATORS["properties"]

    def _set_defaults(
        validator: Draft202012Validator,
        properties: dict[str, Any],
        instance: Any,
        schema: dict[str, Any],
    ) -> Any:
        if isinstance(instance, dict):
            for prop, subschema in properties.items():
                if isinstance(subschema, dict) and "default" in subschema:
                    instance.setdefault(prop, copy.deepcopy(subschema["default"]))
        yield from base_properties(validator, properties, instance, schema)

    return validators.extend(
        Draft202012Validator, {"properties": _set_defaults}
    )


_DefaultFillingValidator: Final[type[Draft202012Validator]] = (
    _build_default_filling_validator()
)


def _raise_from_validation_error(
    exc: ValidationError,
    *,
    source_path: str | Path | None = None,
) -> None:
    """Translate a :class:`ValidationError` into a :class:`BridgeConfigError`.

    We surface:
      * ``key_path`` — dotted path to the offending field
      * ``expected`` — a short, human description derived from the subschema
      * ``message`` — jsonschema's own message, which already reads well
    """
    key_path: list[str | int] = list(exc.absolute_path)

    # ``required`` failures fire at the parent level, so ``absolute_path``
    # points at the container rather than the missing field. Lift the first
    # missing key into the path so users see ``build.grok_prompt`` instead of
    # an unhelpful ``build``.
    if exc.validator == "required" and isinstance(exc.instance, dict):
        required_keys = exc.validator_value or []
        missing = [k for k in required_keys if k not in exc.instance]
        if missing:
            key_path.append(missing[0])

    # ``additionalProperties`` also fires at the parent level. Surface the
    # offending extra key so the panel reads like the rest of the errors.
    if exc.validator == "additionalProperties" and isinstance(exc.instance, dict):
        allowed = set()
        sub = exc.schema if isinstance(exc.schema, dict) else {}
        allowed.update(sub.get("properties", {}).keys())
        extras = [k for k in exc.instance if k not in allowed]
        if extras:
            key_path.append(extras[0])

    # ``exc.schema`` points at the subschema that failed; pulling the most
    # useful hint out of it (enum / type / pattern / required) keeps the
    # error message actionable instead of a wall of JSON.
    expected: str | None = None
    sub = exc.schema if isinstance(exc.schema, dict) else {}
    if "enum" in sub:
        expected = f"one of {sub['enum']}"
    elif "type" in sub:
        expected = str(sub["type"])
    elif "pattern" in sub:
        expected = f"string matching /{sub['pattern']}/"
    elif "required" in sub:
        expected = f"required keys: {sub['required']}"

    raise BridgeConfigError(
        exc.message,
        key_path=key_path,
        expected=expected,
        source_path=source_path,
    )


def validate(config: dict[str, Any]) -> None:
    """Validate ``config`` against the bundled JSON schema.

    Standalone — does **not** mutate, does **not** apply defaults. Use this
    when you already have a parsed mapping (e.g. from a test fixture or an
    API body) and just want a yes/no answer plus a structured error.
    """
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.absolute_path))
    if errors:
        _raise_from_validation_error(errors[0])


def _freeze(obj: Any) -> Any:
    """Recursively wrap ``dict``/``list`` structures in immutable views.

    The top-level comes back as a :class:`types.MappingProxyType`; nested
    mappings are wrapped likewise and lists become tuples. The result still
    quacks like a dict for reads but any attempted mutation raises
    :class:`TypeError`.
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


def _apply_cross_field_defaults(doc: dict[str, Any]) -> None:
    """Fill defaults that depend on sibling fields (e.g. entrypoint ↔ language)."""
    build = doc.get("build")
    if not isinstance(build, dict):
        return
    language = build.get("language", "python")
    if "entrypoint" not in build:
        build["entrypoint"] = _ENTRYPOINT_BY_LANGUAGE[language]


def load_yaml(path: str | Path) -> MappingProxyType[str, Any]:
    """Read ``path``, validate it, apply defaults, and return a frozen mapping.

    Errors are always raised as :class:`BridgeConfigError`. The helper also
    pretty-prints a Rich panel to stderr on failure so a user running the
    CLI sees the problem immediately rather than hunting through a stack
    trace.
    """
    p = Path(path)
    try:
        raw_text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        err = BridgeConfigError(
            f"bridge YAML not found: {p}",
            key_path=(),
            expected="readable file path",
            source_path=p,
        )
        err.render()
        raise err from exc
    except OSError as exc:
        err = BridgeConfigError(
            f"could not read bridge YAML ({exc.strerror or exc}): {p}",
            source_path=p,
        )
        err.render()
        raise err from exc

    try:
        loaded = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        # ``problem_mark`` is set for nearly every PyYAML parse error; when it
        # is, we forward line/column so the Rich panel can point the user at
        # the exact byte that tripped the parser.
        mark = getattr(exc, "problem_mark", None)
        err = BridgeConfigError(
            f"YAML syntax error: {exc}",
            line=(mark.line + 1) if mark else None,
            column=(mark.column + 1) if mark else None,
            source_path=p,
        )
        err.render()
        raise err from exc

    if not isinstance(loaded, dict):
        err = BridgeConfigError(
            "bridge YAML must be a mapping at the top level",
            expected="object (mapping)",
            source_path=p,
        )
        err.render()
        raise err

    # Deep-copy so the caller's raw YAML parse tree is never mutated by the
    # default-filling validator. Matters if a caller passes a pre-loaded dict
    # into a future ``load_dict`` helper — we keep the same invariant here.
    document: dict[str, Any] = copy.deepcopy(loaded)

    schema = _load_schema()
    validator = _DefaultFillingValidator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        try:
            _raise_from_validation_error(first, source_path=p)
        except BridgeConfigError as err:
            err.render()
            raise

    _apply_cross_field_defaults(document)

    return _freeze(document)
