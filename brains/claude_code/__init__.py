"""The ``claude_code`` brain — drives the local ``claude`` CLI.

The only implemented adapter for now. One "cabinet session" processes all
pending tasks in a single batch run (conserves the Claude Pro limit); it is
normally invoked by ``deploy/aigov-session.timer`` via ``aigov session``.
"""

from brains.claude_code.runner import ClaudeCodeBrain, get_brain, run_cabinet_session

__all__ = ["ClaudeCodeBrain", "get_brain", "run_cabinet_session"]
