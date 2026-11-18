"""Load the pinned harness without reading the user's global dotenv settings."""

import importlib
import os
import tempfile

_empty_config = tempfile.TemporaryDirectory(prefix="local-harness-mini-config-")
os.environ["MSWEA_GLOBAL_CONFIG_DIR"] = _empty_config.name
os.environ["MSWEA_SILENT_STARTUP"] = "1"

DefaultAgent = importlib.import_module("minisweagent.agents.default").DefaultAgent
exceptions = importlib.import_module("minisweagent.exceptions")
FormatError = exceptions.FormatError
Submitted = exceptions.Submitted
actions = importlib.import_module("minisweagent.models.utils.actions_toolcall")
BASH_TOOL = actions.BASH_TOOL
format_toolcall_observation_messages = actions.format_toolcall_observation_messages
parse_toolcall_actions = actions.parse_toolcall_actions
