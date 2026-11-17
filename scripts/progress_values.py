"""Shared progress vocabulary for model-authored progress reports.

Single authoritative source for the change and check-result value
tuples, shared by progress_report and progress_summary. Dependency-free
and standard-library-only: plain tuple constants with no import-time
work, no I/O, and no evidence or framework imports.
"""

CHANGE_VALUES = ("advanced", "unchanged", "regressed", "uncertain")
CHECK_RESULT_VALUES = ("passing", "failing", "stale", "unknown")
