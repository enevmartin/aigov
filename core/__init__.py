"""aigov core — brain-agnostic engine: ingest, queue, contracts, publish.

The core NEVER imports from ``brains/`` and contains no LLM-provider code.
It communicates with brains exclusively through the file-based task contract
(see ``core.contracts``).
"""
