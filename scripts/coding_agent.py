"""mini-SWE-agent adapters: local HTTP model and isolated execution only."""

import copy
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace

from control import DeadlineExceeded
from mini_bootstrap import (
    BASH_TOOL,
    FormatError,
    Submitted,
    format_toolcall_observation_messages,
    parse_toolcall_actions,
)
from sandbox import ScratchState, perform_tool, write_json

TOOL_OUTPUT_CHARS = 12000


def bash_tool(limits):
    """Describe this runtime without mutating the upstream tool schema."""
    tool = copy.deepcopy(BASH_TOOL)
    tool["function"]["description"] = (
        "Run bash in a fresh shell in /workspace. "
        f"At most {limits.get('tool_timeout_seconds', 10)} seconds per call, "
        "within remaining agent time. "
        f"Output is stdout then stderr, limited to {TOOL_OUTPUT_CHARS} characters "
        "(truncated=true omits the tail). Save long output under /workspace and read "
        "selected lines. Check output as well as returncode; pipelines can hide failures."
        " The command time limit reports exception_info=tool_wall_limit and stops the command and"
        " descendants; it cannot continue in a later call."
    )
    tool["function"]["parameters"]["properties"]["command"]["description"] = (
        "Bash source, including any quoting needed by the shell; at most "
        f"{limits.get('max_command_bytes', 8192)} UTF-8 bytes."
    )
    if limits.get("persistent_scratch", False):
        tool["function"]["description"] += (
            " Files in /tmp persist between calls within this attempt;"
            " scratch files are not part of the submitted workspace."
        )
    if limits.get("run_checks", False):
        tool["function"]["description"] += (
            " Use run_checks for verification commands; it displays bounded beginning/end"
            " output and records command/file evidence."
        )
    return tool


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects disabled for local model requests")


class LocalModel:
    """No retries, remote providers, credentials, or implicit external lookups."""

    def __init__(self, origin, model, sampling, limits, output):
        parsed = urllib.parse.urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not parsed.port
        ):
            raise ValueError("Expected an explicit http://127.0.0.1:PORT endpoint")
        self.origin = origin.rstrip("/")
        self.model = model
        self.sampling = sampling
        from protocol import reject_retired_options

        reject_retired_options(limits)
        self.limits = limits
        if "review_reasoning_only" in limits:
            from inference_phase import validate

            validate(limits)
        self.output = output
        self.calls = 0
        self.completion_tokens = 0
        self.prompt_tokens = 0
        self.history = None
        self.tool_environment = None
        self.fresh_context = None
        self.progress_reminder = None
        self.agent_deadline = None
        self.budget_feedback_sent = False
        self.prefix_warmup = None
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def record_http_error(self, error, prefix):
        """Keep bounded backend diagnostics without retrying or inventing usage."""
        cap = 65536
        record = {"status": error.code, "reason": str(error.reason), "body_cap": cap}
        body_path = prefix.parent / (prefix.name + ".http-error.body.bin")
        try:
            raw = error.read(cap + 1)
            body_path.write_bytes(raw[:cap])
            record.update(
                body_file=body_path.name,
                body_bytes=min(len(raw), cap),
                truncated=len(raw) > cap,
            )
        except OSError as capture_error:
            record["capture_error"] = {
                "type": type(capture_error).__name__,
                "message": str(capture_error),
            }
        finally:
            error.close()
        write_json(prefix.parent / (prefix.name + ".http-error.json"), record)

    def context_post(self, endpoint, data, prefix):
        name = f"{prefix}.{endpoint}"
        write_json(self.output / (name + ".request.json"), data)
        body = json.dumps(data).encode()
        if len(body) > self.limits.get("max_request_bytes", 131072):
            raise DeadlineExceeded("Context measurement request byte cap exceeded")
        request = urllib.request.Request(
            self.origin + "/" + endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with self.opener.open(
                request, timeout=min(10, self.limits["request_timeout_seconds"])
            ) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("Context measurement response byte cap exceeded")
            decoded = json.loads(raw)
            write_json(self.output / (name + ".response.json"), decoded)
            return decoded
        except urllib.error.HTTPError as error:
            self.record_http_error(error, self.output / name)
            raise
        finally:
            write_json(
                self.output / (name + ".timing.json"),
                {"wall_seconds": time.monotonic() - started},
            )

    def count_tokens(self, payload, phase):
        def post(endpoint, data):
            return self.context_post(
                endpoint, data, f"context-{self.calls + 1:03d}.{phase}"
            )

        rendered = post("apply-template", payload)
        if not isinstance(rendered.get("prompt"), str):
            raise ValueError("Backend did not provide a rendered prompt")
        tokens = post(
            "tokenize",
            {"content": rendered["prompt"], "add_special": True, "parse_special": True},
        ).get("tokens")
        if not isinstance(tokens, list) or any(type(t) is not int for t in tokens):
            raise ValueError("Backend did not provide integer prompt tokens")
        return len(tokens)

    def request_messages(self, messages):
        """One projection for every initial preparation and notice recount."""
        return self.fresh_context.project(messages) if self.fresh_context else messages

    def query(self, messages):
        remaining = self.limits["total_completion_token_limit"] - self.completion_tokens
        if remaining <= 0:
            raise DeadlineExceeded("Completion-token budget exhausted")
        if self.fresh_context is not None and self.history is None:
            raise ValueError("Fresh context requires measured observation history")
        reset_applied = (
            self.fresh_context.before_query(messages, self)
            if self.fresh_context is not None
            else False
        )
        reset_applied = reset_applied or bool(
            self.fresh_context and self.fresh_context.measurement_pending
        )
        checkpoint_request = bool(
            self.fresh_context and self.fresh_context.checkpoint_pending
        )
        if self.progress_reminder is not None:
            self.progress_reminder.before_query(
                messages,
                self,
                reset_applied=reset_applied,
                checkpoint_pending=checkpoint_request,
            )
        wire_messages = [
            {k: v for k, v in message.items() if k != "extra"}
            for message in self.request_messages(messages)
        ]
        payload = {
            "model": self.model,
            "messages": wire_messages,
            "tools": [bash_tool(self.limits)],
            "stream": False,
            "cache_prompt": True,
            "seed": self.limits.get("seed", 42),
            "max_tokens": min(
                remaining, self.limits["max_completion_tokens_per_request"]
            ),
            **self.sampling,
        }
        if self.limits.get("require_tool_call", False):
            # Native decoding constraint; all ordinary responses already require
            # tool use. Preserve the same setting during context measurement.
            payload["tool_choice"] = "required"
        inference_phase = None
        thinking_enabled = True
        if self.limits.get("review_reasoning_only", False):
            from inference_phase import select

            inference_phase = select(self.fresh_context)
            thinking_enabled = inference_phase["enable_thinking"]
            payload["chat_template_kwargs"] = {"enable_thinking": thinking_enabled}
        if thinking_enabled and "reasoning_budget_tokens" in self.limits:
            # Native per-thinking-block closure; reply, total, context and wall
            # caps remain independent. Admit model/template support separately.
            payload["reasoning_budget_tokens"] = self.limits["reasoning_budget_tokens"]
            payload["reasoning_budget_message"] = ""
        if self.limits.get("structured_finalization", False):
            from finish_attempt import TOOL as FINISH_TOOL

            payload["tools"].append(FINISH_TOOL)
            if self.limits.get("read_file", False):
                from read_file import TOOL as READ_TOOL

                payload["tools"].append(READ_TOOL)
            if self.limits.get("exact_text_edit", False):
                from edit_file import TOOL as EDIT_TOOL

                payload["tools"].append(EDIT_TOOL)
            if self.limits.get("whole_file_write", False):
                from write_file import TOOL as WRITE_TOOL

                payload["tools"].append(WRITE_TOOL)
            if self.limits.get("run_checks", False):
                from run_checks import TOOL as CHECK_TOOL

                payload["tools"].append(CHECK_TOOL)
        if self.fresh_context and self.fresh_context.summary_enabled:
            from context_checkpoint import REPLY_TOKENS, THINK_TOKENS
            from context_checkpoint import tool as checkpoint_tool

            # Keep the tool prefix stable on every request in this treatment.
            payload["tools"].append(
                checkpoint_tool(
                    self.limits.get("shared_evidence", False),
                    progress=self.limits.get("checkpoint_progress", False),
                )
            )
            if checkpoint_request:
                payload["max_tokens"] = min(payload["max_tokens"], REPLY_TOKENS)
                if "reasoning_budget_tokens" in payload:
                    payload["reasoning_budget_tokens"] = min(
                        payload["reasoning_budget_tokens"], THINK_TOKENS
                    )
        if thinking_enabled and "reasoning_deadline" in self.limits:
            from reasoning_deadline import allocate

            allocation = allocate(
                self.limits["reasoning_deadline"],
                payload["reasoning_budget_tokens"],
                self.agent_deadline,
                time.monotonic(),
            )
            payload["reasoning_budget_tokens"] = allocation["effective_reasoning_cap"]
            write_json(
                self.output / f"request-{self.calls + 1:03d}.reasoning-budget.json",
                allocation,
            )
        context_report = None
        context_path = self.output / f"context-{self.calls + 1:03d}.json"
        if self.history is not None:
            started = time.monotonic()
            before_reset = None
            if reset_applied:
                before_reset = self.count_tokens(
                    {
                        **payload,
                        "messages": self.history.wire(
                            self.fresh_context.pre_reset_messages
                        ),
                    },
                    "reset-before",
                )
            payload, context_report = self.history.prepare(
                self.request_messages(messages),
                payload,
                self.count_tokens,
                self.limits["context_capacity_tokens"],
            )
            if (
                self.fresh_context is not None
                and not checkpoint_request
                and not reset_applied
            ):
                recovered = self.fresh_context.consider_pressure(
                    messages, self, context_report
                )
                if recovered or self.fresh_context.checkpoint_pending:
                    # No inference was sent and no allowances were charged. Rebuild
                    # the payload after the new checkpoint notice or archive reset.
                    pressure_prefix = f"context-{self.calls + 1:03d}.pressure"
                    write_json(
                        self.output / (pressure_prefix + ".json"), context_report
                    )
                    write_json(
                        self.output / (pressure_prefix + ".request.json"), payload
                    )
                    for evidence in self.output.glob(
                        f"context-{self.calls + 1:03d}.before.*"
                    ):
                        evidence.rename(
                            evidence.with_name(
                                evidence.name.replace(
                                    ".before.", ".pressure.before.", 1
                                )
                            )
                        )
                    allocation = (
                        self.output
                        / f"request-{self.calls + 1:03d}.reasoning-budget.json"
                    )
                    if allocation.exists():
                        allocation.rename(
                            self.output / (pressure_prefix + ".reasoning-budget.json")
                        )
                    return self.query(messages)
            available = context_report["available_completion_tokens"]
            if (
                self.limits.get("context_budget_feedback", False)
                and not self.budget_feedback_sent
                and available > 0
                and min(available, remaining) <= 8192
            ):
                measured = context_report["input_tokens_after"]
                notice = {
                    "role": "user",
                    "content": (
                        "Harness budget notice (one-time): before this notice, the"
                        f" rendered prompt used {measured} tokens, leaving {available}"
                        " tokens of context after the safety reserve. The remaining"
                        f" total completion allowance was {remaining} tokens. This"
                        " notice and subsequent messages consume additional context."
                        " Resolve known discrepancies, perform proportionate final checks,"
                        " and explicitly submit when finished. Avoid speculative rewrites"
                        " or repeating checks without a concrete reason. This notice"
                        " does not certify correctness or extend any budget."
                    ),
                    "extra": {
                        "budget_notice": {
                            "input_tokens_before_notice": measured,
                            "context_headroom_before_notice": available,
                            "completion_tokens_remaining": remaining,
                        },
                        "timestamp": time.time(),
                    },
                }
                # Persist the notice in the outer history. Old messages, observations,
                # and their archives remain unchanged; recount the actual rendered view.
                messages.append(notice)
                self.budget_feedback_sent = True
                payload["messages"] = self.history.wire(self.request_messages(messages))
                after_notice = self.count_tokens(payload, "budget-feedback")
                available = (
                    self.limits["context_capacity_tokens"]
                    - after_notice
                    - self.history.policy["safety_tokens"]
                )
                payload["max_tokens"] = max(
                    0, min(context_report["requested_completion_tokens"], available)
                )
                context_report.update(
                    budget_notice=notice["extra"]["budget_notice"],
                    feedback_render_token_delta=after_notice - measured,
                    input_tokens_after=after_notice,
                    available_completion_tokens=available,
                    effective_completion_tokens=payload["max_tokens"],
                )
            context_report["preparation_seconds"] = time.monotonic() - started
            context_report["wire_sha256"] = hashlib.sha256(
                json.dumps(payload).encode()
            ).hexdigest()
            write_json(context_path, context_report)
            if reset_applied:
                self.fresh_context.measured(before_reset, context_report)
            if payload["max_tokens"] <= 0:
                raise DeadlineExceeded("No context headroom after observation policy")
        body = json.dumps(payload).encode()
        if len(body) > self.limits.get("max_request_bytes", 131072):
            raise DeadlineExceeded("Serialized request byte cap exceeded")
        if self.history is not None and self.limits.get(
            "deduplicate_file_reads", False
        ):
            self.history.note_current_context(payload["messages"])
        if self.calls == 0 and self.prefix_warmup is not None:
            from prefix_warmup import verify_scored_prefix

            rendered = self.context_post("apply-template", payload, "prefix-match")
            match = verify_scored_prefix(
                payload, self.prefix_warmup, rendered["prompt"]
            )
            write_json(self.output / "prefix-warmup-match.json", match)
        self.calls += 1
        prefix = self.output / f"request-{self.calls:03d}"
        write_json(prefix.with_suffix(".request.json"), payload)
        if inference_phase is not None:
            write_json(
                prefix.with_suffix(".inference-phase.json"),
                {
                    **inference_phase,
                    "original_agent_deadline_monotonic": self.agent_deadline,
                    "completion_tokens_before_request": self.completion_tokens,
                    "chat_template_kwargs": payload["chat_template_kwargs"],
                    "effective_reasoning_cap": payload.get("reasoning_budget_tokens"),
                },
            )
        request = urllib.request.Request(
            self.origin + "/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with self.opener.open(
                request, timeout=self.limits["request_timeout_seconds"]
            ) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            self.record_http_error(error, prefix)
            raise
        finally:
            write_json(
                prefix.with_suffix(".timing.json"),
                {"wall_seconds": time.monotonic() - started},
            )
        prefix.with_suffix(".response.bin").write_bytes(raw)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Response byte cap exceeded")
        response = json.loads(raw)
        if self.calls == 1 and self.prefix_warmup is not None:
            from prefix_warmup import scored_cache_usage

            write_json(
                self.output / "prefix-warmup-usage.json", scored_cache_usage(response)
            )
        usage = response.get("usage", {})
        for name in ("completion_tokens", "prompt_tokens"):
            if not isinstance(usage.get(name), int) or usage[name] < 0:
                raise ValueError(f"Missing/invalid token usage: {name}")
        self.completion_tokens += usage["completion_tokens"]
        self.prompt_tokens += usage["prompt_tokens"]
        if context_report is not None:
            context_report["observed_prompt_tokens"] = usage["prompt_tokens"]
            context_report["token_count_delta"] = (
                usage["prompt_tokens"] - context_report["input_tokens_after"]
            )
            write_json(context_path.with_suffix(".usage.json"), context_report)
            if context_report["token_count_delta"] != 0:
                raise ValueError("Rendered token count disagrees with backend usage")
        choice = response["choices"][0]
        message = dict(choice["message"])
        max_calls = self.limits.get("max_tool_calls_per_response", 4)
        response_calls = message.get("tool_calls")
        checkpoint_call = (
            isinstance(response_calls, list)
            and bool(self.fresh_context and self.fresh_context.summary_enabled)
            and any(
                isinstance(call, dict)
                and isinstance(call.get("function"), dict)
                and call["function"].get("name") == "checkpoint_context"
                for call in response_calls
            )
        )
        if checkpoint_request or checkpoint_call:
            from context_checkpoint import action as checkpoint_action

            try:
                actions = checkpoint_action(
                    message,
                    response,
                    choice.get("finish_reason"),
                    requested=checkpoint_request,
                    shared=self.limits.get("shared_evidence", False),
                    progress=self.limits.get("checkpoint_progress", False),
                    history=self.history,
                )
            except FormatError as error:
                if checkpoint_request:
                    self.fresh_context.checkpoint_response(
                        accepted=False, error=error.messages[0]["content"]
                    )
                raise
            self.fresh_context.checkpoint_response(accepted=True)
        elif self.limits.get("structured_finalization", False):
            from finish_attempt import actions as parse_finish_actions

            try:
                actions = parse_finish_actions(
                    message,
                    response,
                    self.history,
                    finish_reason=choice.get("finish_reason"),
                    edit_file_enabled=self.limits.get("exact_text_edit", False),
                    write_file_enabled=self.limits.get("whole_file_write", False),
                    read_file_enabled=self.limits.get("read_file", False),
                    run_checks_enabled=self.limits.get("run_checks", False),
                    max_calls=max_calls,
                )
            except FormatError as error:
                # The delegated bash parser may reject truncated JSON before
                # finish_attempt can attach the raw response to its diagnostic.
                error.messages[0].setdefault("extra", {})["response"] = response
                raise
        else:
            tool_calls = [
                SimpleNamespace(
                    id=call["id"], function=SimpleNamespace(**call["function"])
                )
                for call in message.get("tool_calls", [])
            ]
            try:
                actions = parse_toolcall_actions(
                    tool_calls,
                    format_error_template="{{ error }} Use the bash tool with a string command. To finish: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                    template_kwargs={"finish_reason": choice.get("finish_reason")},
                )
            except FormatError as error:
                error.messages[0]["extra"]["response"] = response
                raise
        if len(actions) > max_calls or any(
            action.get("tool") not in ("finish_attempt", "checkpoint_context")
            and not isinstance(action.get("command"), str)
            for action in actions
        ):
            if self.limits.get("recover_tool_limit_errors", False):
                raise FormatError(
                    {
                        "role": "user",
                        "content": (
                            "No calls from that response were executed. "
                            f"Received {len(actions)} calls; use at most {max_calls}"
                            " tool calls per response, each bash call with a string command."
                            " Split additional calls across responses. Retry within these limits."
                        ),
                        "extra": {
                            "interrupt_type": "FormatError",
                            "response": response,
                        },
                    }
                )
            raise ValueError(
                f"Expected at most {max_calls} string commands per response"
            )
        if self.limits.get("spec_blocker_exit", False) and not self.limits.get(
            "structured_finalization", False
        ):
            from spec_blocker import validate_actions

            validate_actions(actions, response)
        message["extra"] = {
            "actions": actions,
            "response": response,
            "cost": 0.0,
            "timestamp": time.time(),
        }
        for action in actions:
            if action.get("tool") == "read_file":
                action["model_request"] = self.calls
        return message

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, message, outputs, template_vars=None):
        if (
            self.limits.get("time_budget_feedback")
            and self.tool_environment is not None
        ):
            outputs = [
                {
                    **output,
                    "remaining_model_calls": max(
                        0, self.limits["step_limit"] - self.calls
                    ),
                    "remaining_tool_calls": max(
                        0,
                        self.tool_environment.tool_call_limit
                        - self.tool_environment.calls,
                    ),
                }
                for output in outputs
            ]
        observations = format_toolcall_observation_messages(
            actions=message.get("extra", {}).get("actions", []),
            outputs=outputs,
            observation_template="{{ output | tojson }}",
            template_vars=template_vars,
        )
        plain_text = self.limits.get("plain_tool_observations", False)
        if self.history is not None:
            actions = message.get("extra", {}).get("actions", [])
            if len(actions) != len(observations):
                raise ValueError("Cannot associate tool observations with actions")
            for observation, action in zip(observations, actions, strict=True):
                self.history.record(
                    observation,
                    "finish_attempt (provisional review; no command execution)"
                    if action.get("tool") == "finish_attempt"
                    else "checkpoint_context (unverified memory; no command execution)"
                    if action.get("tool") == "checkpoint_context"
                    else action["command"],
                    plain_text=plain_text,
                )
        elif plain_text:
            from observations import literal_observation

            for observation in observations:
                observation["content"] = literal_observation(
                    json.loads(observation["content"])
                )
        if self.fresh_context is not None:
            self.fresh_context.completed_cycle(message, observations)
        if self.progress_reminder is not None:
            self.progress_reminder.completed_cycle(message, observations)
        return observations

    def get_template_vars(self):
        return {}

    def serialize(self):
        return {
            "info": {
                "local_model": {
                    "origin": self.origin,
                    "model": self.model,
                    "sampling": self.sampling,
                    "calls": self.calls,
                    "completion_tokens": self.completion_tokens,
                    "prompt_tokens": self.prompt_tokens,
                    **(
                        {
                            "fresh_context": {
                                "reset_applied": self.fresh_context.boundary
                                is not None,
                                "completed_tool_cycles": self.fresh_context.cycles,
                                "after_elapsed_agent_fraction": self.fresh_context.fraction,
                                "min_remaining_agent_seconds": self.fresh_context.minimum_remaining,
                                "decision": self.fresh_context.decision,
                                **(
                                    {
                                        "trigger": self.fresh_context.trigger,
                                        "reset_count": self.fresh_context.reset_count,
                                        "max_resets": self.fresh_context.max_resets,
                                    }
                                    if self.fresh_context.trigger != "elapsed"
                                    else {}
                                ),
                            }
                        }
                        if self.fresh_context is not None
                        else {}
                    ),
                }
            }
        }


class IsolatedEnvironment:
    def __init__(
        self,
        runtime,
        workspace,
        output,
        timeout,
        tool_call_limit=24,
        *,
        max_command_bytes=8192,
        spec_blocker_exit=False,
        structured_finalization=False,
        exact_text_edit=False,
        whole_file_write=False,
        persistent_scratch=False,
        read_file=False,
        deduplicate_file_reads=False,
        run_checks=False,
    ):
        self.runtime = runtime
        self.workspace = workspace
        # Tool calls publish new immutable workspace generations. Keep only this
        # public starting-generation path, never a task/evaluator root.
        self.initial_workspace = workspace
        self.output = output
        if type(persistent_scratch) is not bool:
            raise ValueError("Invalid persistent_scratch")
        self.scratch = ScratchState(output / "scratch") if persistent_scratch else None
        if (
            type(read_file) is not bool
            or type(deduplicate_file_reads) is not bool
            or (deduplicate_file_reads and not read_file)
        ):
            raise ValueError("Invalid read_file policy")
        self.read_file = read_file
        if type(run_checks) is not bool or (run_checks and not structured_finalization):
            raise ValueError("run_checks requires structured finalization")
        self.checks = output / "checks" if run_checks else None
        if self.checks is not None:
            self.checks.mkdir()
        self.deduplicate_file_reads = deduplicate_file_reads
        self.read_tools = set()
        self.timeout = timeout
        self.tool_call_limit = tool_call_limit
        self.max_command_bytes = max_command_bytes
        self.spec_blocker_exit = spec_blocker_exit
        self.spec_blocker_claim = None
        self.structured_finalization = structured_finalization
        if exact_text_edit and not structured_finalization:
            raise ValueError("Exact edit requires structured finalization")
        self.exact_text_edit = exact_text_edit
        if whole_file_write and not structured_finalization:
            raise ValueError("Whole-file write requires structured finalization")
        self.whole_file_write = whole_file_write
        self.final_handoff = None
        self.history = None
        self.calls = 0
        self.agent_deadline = None
        self.observations = None
        self.history_archive = None
        self.fresh_context = None

    def execute(self, action):
        self.calls += 1
        if self.calls > self.tool_call_limit:
            raise DeadlineExceeded("Tool-call budget exhausted")
        if self.structured_finalization:
            from finish_attempt import (
                ECHO,
                NAME,
                compact_handoff,
                envelope,
                failure,
                validate,
            )
            from spec_blocker import Blocked, reserved

            if (
                self.agent_deadline is not None
                and time.monotonic() >= self.agent_deadline
            ):
                raise DeadlineExceeded("Agent wall budget exhausted")
            if action.get("tool") == "checkpoint_context":
                if self.fresh_context is None:
                    raise ValueError("Checkpoint requires an owning reset controller")
                self.fresh_context.accept_checkpoint(action["payload"])
                prefix = self.output / f"tool-{self.calls:03d}"
                write_json(
                    prefix.with_suffix(".request.json"),
                    {
                        "mode": "adapter-control",
                        "executed": False,
                        "name": "checkpoint_context",
                        "arguments": action["payload"],
                        "raw_arguments": action.get("raw_arguments"),
                    },
                )
                notice = (
                    "Unverified checkpoint saved. No commands executed or work submitted."
                    " The next request may reset context if the original remaining-time"
                    " floor still permits it; all budgets continue unchanged."
                )
                write_json(
                    prefix.with_suffix(".result.json"),
                    {
                        "ok": True,
                        "executed": False,
                        "checkpoint_control": "summary_saved",
                        "cleanup_required": False,
                        "stdout": notice,
                        "stderr": "",
                    },
                )
                return {
                    "returncode": 0,
                    "output": notice,
                    "truncated": False,
                    "remaining_agent_seconds": max(
                        0.0, round(self.agent_deadline - time.monotonic(), 1)
                    ),
                }
            if action.get("tool") == "read_file" and self.read_file:
                from read_file import read
                from read_file import validate as validate_read

                arguments = validate_read(action["arguments"])
                prefix = self.output / f"tool-{self.calls:03d}"
                started = time.monotonic()
                output = read(self.workspace, arguments)
                metadata = output.get("file_read")
                if (
                    self.deduplicate_file_reads
                    and not arguments["reread"]
                    and metadata
                    and self.history
                ):
                    identifier = self.history.prior_file_read(metadata)
                    notice = (
                        f"Unchanged requested range is already in your current context at {identifier}."
                        " Use reread=true to receive the text again."
                    )
                    if identifier is not None and len(output["output"]) > len(notice):
                        output["output"] = notice
                        output["file_read"] = {
                            **metadata,
                            "contents_returned": False,
                            "context_observation_id": identifier,
                        }
                if self.agent_deadline is not None:
                    output["remaining_agent_seconds"] = max(
                        0.0, round(self.agent_deadline - time.monotonic(), 1)
                    )
                write_json(
                    prefix.with_suffix(".request.json"),
                    {
                        "mode": "adapter-read",
                        "name": "read_file",
                        "executed": False,
                        "arguments": arguments,
                        "workspace_generation": self.workspace.name,
                        "model_request": action.get("model_request"),
                        "tool_call_id": action.get("tool_call_id"),
                    },
                )
                write_json(
                    prefix.with_suffix(".result.json"),
                    {
                        "ok": output["returncode"] == 0,
                        "executed": False,
                        "read_only": True,
                        "cleanup_required": False,
                        "wall_seconds": time.monotonic() - started,
                        "visible": output,
                    },
                )
                self.read_tools.add(self.calls)
                return output
            if action.get("tool") == NAME:
                try:
                    value = validate(action["payload"], self.history)
                    handoff = envelope(value, self.history)
                    projection = compact_handoff(handoff)
                except (
                    ValueError,
                    UnicodeError,
                    RecursionError,
                    TypeError,
                    KeyError,
                ) as error:
                    raise failure(error) from error
                prefix = self.output / f"tool-{self.calls:03d}"
                disposition = value["disposition"]
                terminal = "Submitted" if disposition == "submitted" else "Blocked"
                write_json(
                    prefix.with_suffix(".request.json"),
                    {
                        "mode": "adapter-control",
                        "executed": False,
                        "name": NAME,
                        "arguments": value,
                        "raw_arguments": action.get("raw_arguments"),
                    },
                )
                if (
                    disposition == "submitted"
                    and self.fresh_context is not None
                    and self.fresh_context.offer_submission()
                ):
                    notice = (
                        "Handoff recorded for review; final submission is not yet accepted."
                        " One fresh-context review is requested using the existing remaining"
                        " budgets. Inspect current files against the public contract, repair"
                        " concrete gaps and run focused checks, then call finish_attempt again."
                        " If reset is unavailable, continue review in the current context."
                    )
                    write_json(self.output / "review-handoff.json", handoff)
                    write_json(
                        prefix.with_suffix(".result.json"),
                        {
                            "ok": True,
                            "executed": False,
                            "review_control": "fresh_context_requested",
                            "handoff_status": "provisional_unverified_model_handoff",
                            "cleanup_required": False,
                            "stdout": notice,
                            "stderr": "",
                        },
                    )
                    return {
                        "returncode": 0,
                        "output": notice,
                        "truncated": False,
                        "remaining_agent_seconds": max(
                            0.0, round(self.agent_deadline - time.monotonic(), 1)
                        ),
                    }
                write_json(self.output / "final-handoff.json", handoff)
                write_json(
                    prefix.with_suffix(".result.json"),
                    {
                        "ok": True,
                        "executed": False,
                        "terminal_control": terminal,
                        "handoff_status": "unverified_model_handoff",
                        "cleanup_required": False,
                        "stdout": "",
                        "stderr": "",
                    },
                )
                self.final_handoff = handoff
                exception = Submitted if disposition == "submitted" else Blocked
                raise exception(
                    {
                        "role": "exit",
                        "content": terminal,
                        "extra": {
                            "exit_status": terminal,
                            "submission": "See final workspace"
                            if disposition == "submitted"
                            else "",
                            "final_handoff": projection,
                        },
                    }
                )
            if action.get("tool") is not None and not (
                (self.exact_text_edit and action["tool"] == "edit_file")
                or (self.whole_file_write and action["tool"] == "write_file")
                or (self.checks is not None and action["tool"] == "run_checks")
            ):
                raise failure("Unknown action")
            if action["command"].strip() == ECHO or reserved(action["command"]):
                raise failure(
                    "This bash command cannot finish the attempt. Call finish_attempt alone"
                )
        elif action.get("tool") is not None:
            raise ValueError("Typed terminal tool is not enabled")
        if self.spec_blocker_exit:
            from spec_blocker import Blocked, format_error, parse

            try:
                claim = parse(action["command"])
            except (ValueError, UnicodeError, RecursionError) as error:
                raise format_error(error) from error
            if claim is not None:
                # A serial, quiescent adapter control; never shell output or a model path.
                prefix = self.output / f"tool-{self.calls:03d}"
                write_json(
                    prefix.with_suffix(".request.json"),
                    {
                        "mode": "adapter-control",
                        "executed": False,
                        "arguments": {"command": action["command"]},
                    },
                )
                envelope = {
                    "status": "unadjudicated",
                    "claim": claim,
                    "source": "model",
                    "coding_submission": False,
                }
                write_json(self.output / "spec-blocker-claim.json", envelope)
                write_json(
                    prefix.with_suffix(".result.json"),
                    {
                        "ok": True,
                        "executed": False,
                        "terminal_control": "Blocked",
                        "claim_status": "unadjudicated",
                        "cleanup_required": False,
                        "stdout": "",
                        "stderr": "",
                    },
                )
                self.spec_blocker_claim = envelope
                raise Blocked(
                    {
                        "role": "exit",
                        "content": "Blocked: unadjudicated model claim",
                        "extra": {
                            "exit_status": "Blocked",
                            "submission": "",
                            "blocker_claim": envelope,
                        },
                    }
                )
        options = {"observations": self.observations} if self.observations else {}
        if self.history_archive is not None:
            options["history_archive"] = self.history_archive
        if self.scratch is not None:
            options["scratch"] = self.scratch
        if self.checks is not None:
            options["checks"] = self.checks
        editing = self.exact_text_edit and action.get("tool") == "edit_file"
        writing = self.whole_file_write and action.get("tool") == "write_file"
        checking = self.checks is not None and action.get("tool") == "run_checks"
        if checking:
            from run_checks import bounded_output, identity, save, shell_command
            from run_checks import validate as validate_check

            check_arguments = validate_check(action["arguments"])
            before_check = identity(self.workspace, check_arguments["cwd"])
            options["public_interface"] = {
                "tool": "run_checks",
                "arguments": check_arguments,
            }
        if editing:
            from sandbox_worker import validate_edit_arguments

            validate_edit_arguments(action["arguments"])
        if writing:
            from sandbox_worker import validate_write_arguments

            validate_write_arguments(action["arguments"])
        result, updated = perform_tool(
            self.runtime,
            self.workspace,
            "edit_file" if editing else "write_file" if writing else "execute",
            action["arguments"]
            if editing or writing
            else {
                "command": shell_command(check_arguments)
                if checking
                else action["command"]
            },
            self.timeout,
            self.output / f"tool-{self.calls:03d}",
            max_command_bytes=self.max_command_bytes,
            **options,
        )
        self.workspace = updated
        (self.output / "latest-workspace.txt").write_text(str(updated) + "\n")
        text = result.get("stdout", "") + result.get("stderr", "")
        output = {
            "returncode": result.get("returncode", -1),
            "output": text[:TOOL_OUTPUT_CHARS],
            "truncated": len(text) > TOOL_OUTPUT_CHARS,
            "exception_info": result.get("stopped_by") or result.get("error") or "",
        }
        if self.agent_deadline is not None:
            output["remaining_agent_seconds"] = max(
                0.0, round(self.agent_deadline - time.monotonic(), 1)
            )
        if checking:
            output["output"], output["output_window"] = bounded_output(
                text, TOOL_OUTPUT_CHARS
            )
            after_check = identity(updated, check_arguments["cwd"])
            output["check_record"] = save(
                self.checks,
                self.calls,
                check_arguments,
                before_check,
                after_check,
                output,
            )
            write_json(
                self.output / f"tool-{self.calls:03d}.check.json",
                output["check_record"],
            )
        if (
            not self.structured_finalization
            and action["command"].strip()
            == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
            and result.get("ok")
            and text.strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        ):
            raise Submitted(
                {
                    "role": "exit",
                    "content": "Submitted",
                    "extra": {
                        "exit_status": "Submitted",
                        "submission": "See final workspace",
                    },
                }
            )
        return output

    def get_template_vars(self):
        return {"cwd": "/workspace"}

    def serialize(self):
        return {
            "info": {
                "environment": {
                    "kind": "isolated-snapshot",
                    "calls": self.calls,
                    "workspace": str(self.workspace),
                    "runtime": self.runtime.manifest,
                }
            }
        }
