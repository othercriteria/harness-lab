"""Shared progress vocabulary for model-authored progress reports.

Single authoritative source for the change and check-result value
tuples and the text/payload size bounds, shared by progress_report,
progress_summary, and progress_inspect. Dependency-free and
standard-library-only: plain constants with no import-time work, no
I/O, and no evidence or framework imports.
"""

CHANGE_VALUES = ("advanced", "unchanged", "regressed", "uncertain")
CHECK_RESULT_VALUES = ("passing", "failing", "stale", "unknown")

# Per-field text bound: at most TEXT_BOUND characters AND TEXT_BOUND
# UTF-8 bytes. Every UTF-8 character encodes to at least one byte, so
# the byte bound is the stricter one; consumers enforce it plus
# nonempty and control-character rules.
TEXT_BOUND = 300
# Whole-report bound: UTF-8 bytes of the serialized report payload
# (json.dumps with ensure_ascii=False and default separators). Exactly
# PAYLOAD_UTF8_BYTES is allowed; the aggregate cap applies even when every individual field
# is within its own cap.
PAYLOAD_UTF8_BYTES = 4096
