"""
Model layer for local agent loop.

Provider-neutral. The loop doesn't care which model backs it.

Configuration via environment:
  MODEL_PROVIDER  — "mock", "anthropic", or omit for auto-detect
  MODEL_API_KEY   — API key for the chosen provider
  MODEL_NAME      — model name override (optional)
  MODEL_BASE_URL  — base URL override (optional)

Legacy: ANTHROPIC_API_KEY still works as fallback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol, Optional


@dataclass
class ModelOutput:
    """What the model proposes."""
    transformed_text: str
    proposed_action: str
    proposed_path: str


class ModelClient(Protocol):
    """Any model that can produce a proposal from input."""
    def run(self, input_text: str, output_path: str) -> ModelOutput: ...


class MockModel:
    """Deterministic mock: uppercase input, propose file.write."""

    # deterministic by design · #24 ⟪·⟫
    #
    #           |\    _,,,---,,_
    #     ZZZzz /,`.-'`'    -.  ;-;;,_
    #          |,4-  ) )-,_. ,\ (  `'-'
    #         '---''(_/--'  `-'\_)
    #
    # some things compile once and stay linked forever.

    def run(self, input_text: str, output_path: str) -> ModelOutput:
        return ModelOutput(
            transformed_text=input_text.upper(),
            proposed_action="file.write",
            proposed_path=output_path,
        )


class AnthropicModel:
    """Calls Claude via the anthropic SDK. Parses a structured proposal."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514",
                 base_url: Optional[str] = None):
        import anthropic
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._model = model

    def run(self, input_text: str, output_path: str) -> ModelOutput:
        prompt = (
            "You are a local file-processing agent. "
            "Given the input text below, produce a transformed version and propose writing it to the given path.\n\n"
            f"Input text:\n{input_text}\n\n"
            f"Output path: {output_path}\n\n"
            "Respond with ONLY a JSON object with these exact keys:\n"
            '{"transformed_text": "...", "proposed_action": "file.write", "proposed_path": "..."}\n'
            "No markdown, no explanation."
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        data = _parse_model_response(text)
        return ModelOutput(
            transformed_text=data["transformed_text"],
            proposed_action=data["proposed_action"],
            proposed_path=data["proposed_path"],
        )


def _parse_model_response(text: str) -> dict:
    """Accept raw JSON or a fenced JSON block."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            cleaned = "\n".join(lines[1:-1]).strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
    return json.loads(cleaned)


PROVIDERS = {
    "mock": lambda **_: MockModel(),
    "anthropic": lambda api_key, model=None, base_url=None, **_: AnthropicModel(
        api_key=api_key,
        model=model or "claude-sonnet-4-20250514",
        base_url=base_url,
    ),
}


def get_model(provider: Optional[str] = None) -> ModelClient:
    """
    Return a model client based on configuration.

    Resolution order:
    1. Explicit provider argument
    2. MODEL_PROVIDER env var
    3. Auto-detect from MODEL_API_KEY or ANTHROPIC_API_KEY
    4. Fall back to mock
    """
    provider = provider or os.environ.get("MODEL_PROVIDER", "").lower()
    api_key = os.environ.get("MODEL_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    model_name = os.environ.get("MODEL_NAME")
    base_url = os.environ.get("MODEL_BASE_URL")

    if provider == "mock" or (not provider and not api_key):
        return MockModel()

    if not provider:
        provider = "anthropic"

    factory = PROVIDERS.get(provider)
    if factory is None:
        raise ValueError(f"Unknown model provider: {provider}")
    if provider != "mock" and not api_key:
        raise ValueError(f"MODEL_API_KEY required for provider: {provider}")

    return factory(api_key=api_key, model=model_name, base_url=base_url)
