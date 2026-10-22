"""Central configuration: model per node, limits and the priority scale.
All values are generic (independent of any particular corpus)."""

# --- Model per node (swap here without touching node code) ---
MODELS: dict[str, str] = {
    "extractor": "gpt-5-mini",       # one call per chunk (high volume) -> cheap
    "consolidator": "gpt-5.6-luna",  # one call over all candidates -> mid-tier, large context
    "writer": "gpt-5-mini",          # batches of plain writing -> cheap
    "critic": "gpt-6-luna",          # one review per round, different model than writer
}
# Extra constructor kwargs per node.
MODEL_PARAMS: dict[str, dict] = {
    "writer": {"reasoning_effort": "low"},  # rewording needs little reasoning
}

# --- Loading ---
SUPPORTED_EXTENSIONS = (".txt", ".md", ".eml", ".pdf", ".docx", ".html", ".htm")
CHUNK_CHARS = 12_000   # ~3k tokens: whole sections of context, small enough for a cheap model
CHUNK_OVERLAP = 800    # a requirement split by a chunk boundary is seen whole once

# --- Grounding: share of a quote's characters found (in order) in its source chunk ---
GROUNDING_THRESHOLD = 0.8

# --- Consolidator: candidates per call; keeps each call's output small and complete ---
CONSOLIDATION_BATCH = 80

# --- Writer ---
WRITER_BATCH_SIZE = 20

# --- Feedback loop ---
MAX_ITERATIONS = 2                 # hard cap on rework loops
CRITIC_ACTIONABLE = ("high", "medium")
DESCRIPTION_MIN_WORDS = 20         # shorter is not a "paragraph-long" explanation

# --- LLM robustness ---
LLM_MAX_RETRIES = 5     # transport retries with backoff (429/5xx), done by the client
LLM_PARSE_RETRIES = 2   # extra attempts when structured output fails
LLM_TIMEOUT_S = 600
MAX_CONCURRENCY = 10

# --- Priority scale (MoSCoW), rendered into the document ---
PRIORITY_SCALE: dict[str, str] = {
    "Must": "Essential; mandated by stakeholders, law or the core purpose. Without it the "
            "release fails.",
    "Should": "Important and expected, but a workaround exists or it can follow shortly.",
    "Could": "Desirable improvement (nice to have); included if time and budget allow.",
    "Won't": "Explicitly agreed to be left out of the current release (deferred).",
}
