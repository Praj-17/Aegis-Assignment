"""Per-framework baseline tool sets used to detect drift / unexpected tool use.

In production, baselines would come from a learned profile of each agent over
a quiet window of observation. For the MVP we ship a small, explicit table.
"""

from __future__ import annotations

# Tools that are *normal* for a given framework. Anything outside this set
# (and outside the agent's own declared tools) is flagged as drift.
FRAMEWORK_BASELINE_TOOLS: dict[str, set[str]] = {
    "langchain": {
        "external_llm_call",
        "search",
        "wikipedia",
        "calculator",
        "python_repl",
    },
    "crewai": {
        "external_llm_call",
        "search",
        "task_delegate",
        "summarize",
    },
    "llama_index": {
        "external_llm_call",
        "vector_search",
        "summarize",
    },
    "direct_sdk_or_agentic_llm": {
        "external_llm_call",
    },
    "mcp": {
        "external_llm_call",
        "filesystem",
        "git",
    },
}


def baseline_for(framework: str | None) -> set[str]:
    if not framework:
        return set()
    return FRAMEWORK_BASELINE_TOOLS.get(framework, set())
