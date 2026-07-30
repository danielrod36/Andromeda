"""LLM adapter, tools, and curated state view (U5).

This package implements the LLM integration layer:

- :mod:`src.llm.state_view` — curated state view (R2): the LLM never sees
  the full state, only a safe subset.
- :mod:`src.llm.prompts` — system prompt and prompt templates.
- :mod:`src.llm.tools` — tool definitions for state mutation; every tool
  routes through the command funnel (:meth:`Engine.apply`).
- :mod:`src.llm.adapter` — thin adapter wrapping a Pydantic AI ``Agent``
  with structured output, retry, and usage limits (R3, R18, R19).
"""
