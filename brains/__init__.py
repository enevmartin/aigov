"""Brain adapters — the ONLY code that knows which LLM runtime is in use.

Each subpackage implements :class:`brains.base.BrainAdapter` for one runtime
(``claude_code``, ``openclaw``, ``api``). The core selects an adapter by the
``brain`` key in ``config.yaml`` and interacts with it purely through the
file-based task contract.
"""
