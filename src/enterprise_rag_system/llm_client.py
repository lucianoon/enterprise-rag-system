"""Single port to the LLM — any model, one contract.

Both LLM-backed components in this package (the answer generator and the
faithfulness judge) go through :func:`complete`. Two backends sit behind it:

- ``anthropic`` — the native Anthropic SDK.
- ``openai`` — any endpoint speaking the OpenAI chat-completions API, which
  covers OpenAI, OpenRouter, Groq, Together, DeepInfra, Fireworks, vLLM,
  Ollama and LM Studio with no per-provider code.

Selection is entirely environment-driven, so swapping models never requires a
code change:

===========================  ==============================================
``RAG_LLM_BACKEND``          ``auto`` (default), ``anthropic`` or ``openai``
``RAG_LLM_BASE_URL``         OpenAI-compatible endpoint; selects the
                             ``openai`` backend in ``auto`` mode
``RAG_LLM_API_KEY``          credential; falls back to ``OPENAI_API_KEY`` or
                             ``ANTHROPIC_API_KEY`` per backend
===========================  ==============================================

In ``auto`` mode: an Anthropic key wins; otherwise a base URL or an OpenAI key
selects ``openai``; with neither, nothing is available and callers fall back to
their deterministic path.

Local servers (Ollama, LM Studio, vLLM) usually need no credential. When a base
URL is set and no key is, a placeholder is sent — the OpenAI client requires a
non-empty string and the local server ignores the value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"

#: Sent when a base URL is set but no credential is (local servers).
LOCAL_PLACEHOLDER_KEY = "not-needed"


@dataclass(frozen=True)
class LLMConfig:
    """Backend, model and credentials resolved from the environment."""

    backend: str
    model: str
    api_key: str | None = None
    base_url: str | None = None


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _base_url() -> str | None:
    return _env("RAG_LLM_BASE_URL", "OPENAI_BASE_URL")


def resolve_backend() -> str | None:
    """Effective backend, or ``None`` when nothing is configured."""
    requested = (os.environ.get("RAG_LLM_BACKEND") or "auto").strip().lower()
    if requested in {"anthropic", "openai"}:
        return requested
    if requested not in {"auto", ""}:
        raise ValueError(
            f"Invalid RAG_LLM_BACKEND: {requested!r}. Use 'auto', 'anthropic' or 'openai'."
        )
    if _env("RAG_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        return "anthropic"
    if _base_url() or _env("OPENAI_API_KEY"):
        return "openai"
    return None


def resolve(model: str | None = None) -> LLMConfig:
    """Build the client configuration. ``model`` overrides the environment."""
    backend = resolve_backend()
    if backend is None:
        raise RuntimeError(
            "No model configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY or "
            "RAG_LLM_BASE_URL (for a local server such as Ollama)."
        )
    chosen = model or os.environ.get("RAG_LLM_MODEL") or None
    if backend == "anthropic":
        return LLMConfig(
            backend="anthropic",
            model=chosen or DEFAULT_ANTHROPIC_MODEL,
            api_key=_env("RAG_LLM_API_KEY", "ANTHROPIC_API_KEY"),
        )
    base_url = _base_url()
    return LLMConfig(
        backend="openai",
        model=chosen or DEFAULT_OPENAI_MODEL,
        api_key=_env("RAG_LLM_API_KEY", "OPENAI_API_KEY")
        or (LOCAL_PLACEHOLDER_KEY if base_url else None),
        base_url=base_url,
    )


def is_available() -> bool:
    """True when a backend resolves and its SDK is importable."""
    try:
        backend = resolve_backend()
    except ValueError:
        return False
    if backend is None:
        return False
    module = "anthropic" if backend == "anthropic" else "openai"
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def describe(model: str | None = None) -> str:
    """Short label for the active backend, for logs and response metadata."""
    try:
        config = resolve(model)
    except RuntimeError:
        return "unconfigured"
    return f"{config.model} @ {config.base_url}" if config.base_url else config.model


def complete(system: str, prompt: str, *, model: str | None = None, max_tokens: int = 1024) -> str:
    """Run one completion against the configured backend and return its text."""
    config = resolve(model)
    if config.backend == "anthropic":
        import anthropic

        client = (
            anthropic.Anthropic(api_key=config.api_key)
            if config.api_key
            else anthropic.Anthropic()
        )
        message = client.messages.create(
            model=config.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        # Safety classifiers can decline the request: HTTP 200 with empty or
        # partial content. Without this check the caller would treat a refusal
        # as a valid (empty) answer instead of falling back.
        if message.stop_reason == "refusal":
            raise RuntimeError("The model refused the request on content policy grounds.")
        return "".join(b.text for b in message.content if b.type == "text").strip()

    import openai

    client_oa = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
    completion = client_oa.chat.completions.create(
        model=config.model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()
