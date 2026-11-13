"""Read-only loopback observatory for outer-harness evidence. No execution APIs."""

import argparse
import hashlib
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path("/bulk/dlk/local-harness/runs")
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,180}\Z")
# Parser-control inference calls use case names, not the coding harness sequence.
# Keep case-name families explicit: template/tokenizer files are not model calls.
CONTROL_PREFIX = r"(?:unrestricted|bounded\d+|insufficient|long_prefix_bounded\d+)"
REQUEST = re.compile(
    rf"(?P<prefix>request-\d+|tool-\d+|{CONTROL_PREFIX})\.request\.json\Z"
)
CONTROL_ARTIFACT = re.compile(
    rf"{CONTROL_PREFIX}\.(?:request\.json|response\.bin|timing\.json)\Z"
)
NATIVE_CASES = (
    "observation_submitted",
    "contract_blocked",
    "honest_unverified",
    "representative_fields",
)
RECOVERY_CASES = ("case-a", "case-b")
NATIVE_ARTIFACT = re.compile(
    r"(?:" + "|".join(NATIVE_CASES) + r")/"
    r"(?:request-\d+\.(?:request\.json|response\.bin|timing\.json)"
    r"|context-\d+(?:\.usage)?\.json|control-result\.json|supplied-history\.json)\Z"
)
ARTIFACT = re.compile(
    r"(?:context-\d+(?:\.usage)?\.json|behavioral-verification\.json|spec-blocker-claim\.json|final-handoff\.json|review-handoff\.json|finalization-review\.json|outer-adjudication\.json|summary\.json|trajectory\.json|changes\.diff|agent-config\.json|sampling\.json|inputs\.json|request-\d+\.(?:request\.json|response\.bin|timing\.json)|tool-\d+\.(?:request\.json|result\.json|cleanup\.json|stdout\.bin|stderr\.bin)|verification\.(?:result\.json|cleanup\.json))\Z"
)
RECOVERY_ARTIFACT = re.compile(
    r"(?:case-a|case-b)/(?:"
    + ARTIFACT.pattern.removesuffix(r"\Z")
    + r"|parsed-handoff\.json)\Z"
)


class Evidence:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = root.resolve()

    def child(self, parent, name):
        if not NAME.fullmatch(name) or name in (".", ".."):
            raise ValueError("Invalid identifier")
        path = parent / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Path outside evidence root")
        return path

    def text(self, path, limit=262144):
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Path outside evidence root")
        try:
            with path.open("rb") as stream:
                raw = stream.read(limit + 1)
            return raw[:limit].decode("utf-8", errors="replace"), len(raw) > limit
        except FileNotFoundError:
            return "", False

    def tail(self, path, limit=12000):
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Path outside evidence root")
        try:
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - limit))
                return stream.read(limit).decode("utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def read(self, path):
        raw, truncated = self.text(path)
        if not raw or truncated:
            return None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            return None  # Writer may still be publishing this artifact.

    def live_owner(self, root):
        child = self.read(root / "background/child.json") or {}
        pid = child.get("pid")
        if type(pid) is not int or pid <= 0:
            return False
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            return str(root / "voice").encode() in argv and any(
                b"with_speech_released.py" in a for a in argv
            )
        except (FileNotFoundError, PermissionError):
            return False

    def outer_adjudication(self, trial, summary):
        """Read an outer-owned verdict bound to the exact immutable raw summary."""
        if "unsafe_cleanup" in summary or "cancelled" in summary:
            return None
        verdict = self.read(trial / "outer-adjudication.json")
        raw, truncated = self.text(trial / "summary.json")
        if not isinstance(verdict, dict) or truncated:
            return None
        posthoc_failure = False
        if summary.get("task_adjudication", {}).get("status") != "pending_outer_rubric":
            # Later contract or runtime findings may reject a frozen raw result.
            # This path cannot promote a failed result.
            if (
                (verdict.get("review_kind"), verdict.get("disposition"))
                not in {
                    ("posthoc_contract", "failed_coding"),
                    ("posthoc_protocol", "nonconforming_run"),
                }
                or not isinstance(verdict.get("rationale"), str)
                or not verdict["rationale"].strip()
                or not isinstance(verdict.get("evidence"), list)
                or not verdict["evidence"]
            ):
                return None
            posthoc_failure = True
        disposition = verdict.get("disposition")
        expected = {
            "verified_coding": (True, True, "Submitted"),
            "verified_coding_bad_handoff": (True, False, "Submitted"),
            "supported_blocker": (None, True, "Blocked"),
            "supported_blocker_bad_handoff": (None, False, "Blocked"),
            "unsupported_blocker": (False, False, "Blocked"),
            "failed_coding": (False, False, "Submitted"),
            "nonconforming_run": (None, False, "Submitted"),
        }
        if disposition == "nonconforming_run" and (
            verdict.get("review_kind") != "posthoc_protocol"
            or verdict.get("protocol_conforming") is not False
            or not posthoc_failure
        ):
            return None
        diagnostic = self.is_diagnostic(summary)
        if diagnostic:
            expected = {"reviewed_diagnostic": (None, None, "Submitted")}
            results = verdict.get("diagnostic_results")
            if summary.get("diagnostic_kind") == "input-probe":
                if not isinstance(results, dict) or any(
                    type(results.get(key)) is not bool
                    for key in (
                        "format_valid",
                        "inputs_valid",
                        "deterministic",
                        "difference_found",
                    )
                ):
                    return None
            elif (
                not isinstance(results, dict)
                or type(results.get("sound_on_controls")) is not bool
                or type(results.get("incorrect_controls_detected")) is not int
                or type(results.get("incorrect_controls_total")) is not int
                or not 0
                <= results["incorrect_controls_detected"]
                <= results["incorrect_controls_total"]
                or results["incorrect_controls_total"] <= 0
            ):
                return None
        if (
            type(verdict.get("version")) is not int
            or verdict["version"] != 1
            or verdict.get("status") != "adjudicated"
            or verdict.get("task") != summary.get("task")
            or verdict.get("raw_summary_sha256")
            != hashlib.sha256(raw.encode()).hexdigest()
            or not isinstance(disposition, str)
            or disposition not in expected
            or verdict.get("coding_correctness") is not expected[disposition][0]
            or verdict.get("task_handling_correctness") is not expected[disposition][1]
            or (
                not posthoc_failure
                and not diagnostic
                and (
                    not summary.get("clean_agent_halt")
                    or not summary.get("within_budget")
                    or (summary.get("agent_outcome") or {}).get("exit_status")
                    != expected[disposition][2]
                )
            )
        ):
            return None
        return verdict

    @staticmethod
    def is_diagnostic(summary):
        return (
            summary.get("diagnostic_kind") in ("independent-test-author", "input-probe")
            and summary.get("coding_goal_credit") == 0
        )

    @staticmethod
    def allowed_artifact(name):
        return bool(
            ARTIFACT.fullmatch(name)
            or CONTROL_ARTIFACT.fullmatch(name)
            or NATIVE_ARTIFACT.fullmatch(name)
            or RECOVERY_ARTIFACT.fullmatch(name)
        )

    @staticmethod
    def request_files(root):
        files = []
        for directory in [
            root,
            *(root / name for name in (*NATIVE_CASES, *RECOVERY_CASES)),
        ]:
            if directory.is_symlink() or not directory.is_dir():
                continue
            files.extend(
                path
                for path in directory.glob("*.request.json")
                if REQUEST.fullmatch(path.name)
                and (
                    directory == root
                    or NATIVE_ARTIFACT.fullmatch(f"{directory.name}/{path.name}")
                    or RECOVERY_ARTIFACT.fullmatch(f"{directory.name}/{path.name}")
                )
                and path.is_file()
                and not path.is_symlink()
            )
        return files

    @staticmethod
    def is_control(summary, files):
        return (
            isinstance(summary.get("kind"), str)
            and "control" in summary["kind"].lower()
            and isinstance(summary.get("cases"), list)
        ) or any(
            CONTROL_ARTIFACT.fullmatch(path.name)
            or NATIVE_ARTIFACT.fullmatch(f"{path.parent.name}/{path.name}")
            or RECOVERY_ARTIFACT.fullmatch(f"{path.parent.name}/{path.name}")
            for path in files
        )

    def run(self, name, details=True):
        root = self.child(self.root, name)
        if not (root / "command.json").is_file():
            raise ValueError("Not a campaign directory")
        bg = self.read(root / "background/summary.json") or {}
        exp = self.read(root / "experiment/summary.json") or {}
        if bg:
            state = "complete" if bg.get("ok") else "stopped with error"
        elif self.live_owner(root):
            state = "live"
        else:
            state = "unfinished / owner not observed"
        trials = []
        experiment = self.child(root, "experiment")
        for trial in sorted(experiment.glob("trial-*")):
            if trial.is_symlink() or not trial.is_dir():
                continue
            summary = self.read(trial / "summary.json") or {}
            adjudication = self.outer_adjudication(trial, summary)
            pending = (
                summary.get("task_adjudication", {}).get("status")
                == "pending_outer_rubric"
            )
            events = self.request_files(trial)
            control = self.is_control(summary, events)
            diagnostic = self.is_diagnostic(summary)
            passed = summary.get("passed" if control else "success")
            if control and (
                summary.get("completed") is False
                or summary.get("error")
                or "unsafe_cleanup" in summary
                or "cancelled" in summary
            ):
                # A successful sub-step is not a completed control. Preserve
                # the raw summary, but do not promote a stale success flag.
                passed = False
            trial_name = trial.name
            trial_state = (
                ("passed" if passed else "failed")
                if type(passed) is bool
                else ("in progress" if state == "live" else "unfinished")
            )
            if (
                summary.get("task_adjudication", {}).get("status")
                == "pending_outer_rubric"
            ):
                terminal = summary.get("agent_outcome", {}).get("exit_status")
                if "unsafe_cleanup" in summary:
                    trial_state = "unsafe cleanup / stopped"
                elif "cancelled" in summary:
                    trial_state = "cancelled / unadjudicated"
                elif not summary.get("clean_agent_halt", False):
                    trial_state = "stopped / unadjudicated"
                else:
                    trial_state = (
                        "blocked claim / unadjudicated"
                        if terminal == "Blocked"
                        else "awaiting outer adjudication"
                    )
            if adjudication:
                trial_state = {
                    "verified_coding": "passed",
                    "verified_coding_bad_handoff": "correct code / handoff failed",
                    "supported_blocker": "supported blocker",
                    "supported_blocker_bad_handoff": "supported blocker / handoff failed",
                    "unsupported_blocker": "unsupported blocker",
                    "failed_coding": "failed",
                    "reviewed_diagnostic": "diagnostic reviewed",
                    "nonconforming_run": "runtime nonconformance",
                }[adjudication["disposition"]]
                passed = (
                    False
                    if adjudication["disposition"]
                    in {
                        "nonconforming_run",
                        "verified_coding_bad_handoff",
                        "supported_blocker_bad_handoff",
                    }
                    else adjudication["coding_correctness"]
                )
            trials.append(
                {
                    "name": trial_name,
                    "state": trial_state,
                    "kind": "diagnostic"
                    if diagnostic
                    else "control"
                    if control
                    else "coding",
                    "diagnostic_kind": summary.get("diagnostic_kind")
                    if diagnostic
                    else None,
                    "passed": passed,
                    "control_kind": summary.get("kind") if control else None,
                    "commands_executed": summary.get("commands_executed")
                    if control
                    else None,
                    "task": summary.get("task", trial_name[9:]),
                    "seed": summary.get("seed"),
                    "correct": adjudication["coding_correctness"]
                    if adjudication
                    else None
                    if pending
                    else summary.get(
                        "verified_correctness", summary.get("canonical_correctness")
                    ),
                    "clean": summary.get("clean_agent_completion"),
                    **(
                        {
                            "clean_halt": summary.get("clean_agent_halt"),
                            "blocker_claim": summary.get("spec_blocker_claim"),
                            "adjudication": adjudication
                            or summary["task_adjudication"],
                        }
                        if "task_adjudication" in summary or adjudication
                        else {}
                    ),
                    "seconds": summary.get(
                        "elapsed_seconds" if control else "task_wall_seconds"
                    ),
                    "events": len(events),
                    "outcome": (summary.get("interpretation") or summary.get("error"))
                    if control
                    else (summary.get("agent_outcome") or summary.get("agent_error")),
                }
            )
        profile = self.read(root / "experiment/profile.json") or {}
        protocol = self.read(root / "experiment/protocol.json") or {}
        result = {
            "name": name,
            "state": state,
            "modified": (root / "command.json").stat().st_mtime,
            "trials": trials,
            "kind": "control"
            if trials and all(t["kind"] == "control" for t in trials)
            else "diagnostic"
            if trials and all(t["kind"] == "diagnostic" for t in trials)
            else "coding",
            "model": profile.get("artifact", {}).get("name"),
            "protocol": protocol.get("protocol"),
            "budget": protocol.get("task_wall_seconds"),
            "restored": bg.get("restored"),
        }
        if details:
            result["lifecycle"] = {
                "background": bg,
                "voice": self.read(root / "voice/result.json"),
                "ollama": self.read(root / "ollama/result.json"),
                "experiment": exp,
            }
            result["server_tail"] = self.tail(root / "experiment/server.log")
            result["config"] = {
                "protocol": protocol,
                "sampling": profile.get("sampling"),
                "server_args": profile.get("server_args"),
                "artifact": {
                    k: profile.get("artifact", {}).get(k)
                    for k in ("id", "revision", "quantization")
                },
            }
        return result

    def runs(self, page=1, page_size=20, query=""):
        """Index names/mtimes globally, then read evidence only for the visible page.

        No persistent cache: new campaigns, terminal receipts and outer verdicts
        remain visible on the next refresh. Search covers all campaign names.
        """
        if type(page) is not int or page < 1:
            raise ValueError("page must be a positive integer")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise ValueError("page_size must be between 1 and 50")
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("query must be at most 200 characters")
        index = []
        for path in self.root.iterdir():
            try:
                if (
                    not NAME.fullmatch(path.name)
                    or path.is_symlink()
                    or not path.is_dir()
                    or (path / "command.json").is_symlink()
                    or not (path / "command.json").is_file()
                ):
                    continue
                index.append((path.name, (path / "command.json").stat().st_mtime))
            except (OSError, ValueError):
                continue
        index.sort(key=lambda item: (-item[1], item[0]))
        matching = [item for item in index if query.casefold() in item[0].casefold()]
        pages = max(1, (len(matching) + page_size - 1) // page_size)
        page = min(page, pages)
        start = (page - 1) * page_size
        output = []
        unavailable = []
        for name, _ in matching[start : start + page_size]:
            try:
                output.append(self.run(name, False))
            except (OSError, ValueError):
                # Preserve index totals during concurrent publication/removal,
                # and explicitly distinguish an unreadable row from no match.
                unavailable.append(name)
        return {
            "runs": output,
            "total": len(index),
            "matching": len(matching),
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "query": query,
            "newest": index[0][0] if index else None,
            "unavailable": unavailable,
        }

    def trial(self, run, trial):
        return self.child(self.child(self.child(self.root, run), "experiment"), trial)

    def artifact(self, run, trial, name):
        if not self.allowed_artifact(name):
            raise ValueError("Artifact is not in the read-only allowlist")
        path = self.trial(run, trial)
        for component in name.split("/"):
            path = self.child(path, component)
        if not path.is_file():
            raise ValueError("Artifact not available")
        content, truncated = self.text(path, 131072)
        return {"name": name, "text": content, "truncated": truncated}

    def trace(self, run, trial):
        root = self.trial(run, trial)
        if not root.is_dir():
            raise ValueError("Trial unavailable")
        records = []
        files = self.request_files(root)
        summary = self.read(root / "summary.json") or {}
        cases = {
            case["name"]: case
            for case in summary.get("cases", [])
            if isinstance(case, dict) and isinstance(case.get("name"), str)
        }
        files = sorted(files, key=lambda p: (p.stat().st_mtime, p.name))[-80:]
        last_model_request = {}
        for path in files:
            if not path.name.startswith("tool-"):
                last_model_request[path.parent] = path
        for path in files:
            req = self.read(path)
            if not isinstance(req, dict):
                continue
            prefix = path.name.removesuffix(".request.json")
            directory = path.parent
            nested = directory != root
            record = {
                "id": f"{directory.name}/{prefix}" if nested else prefix,
                "at": path.stat().st_mtime,
                "kind": "tool" if prefix.startswith("tool-") else "model",
            }
            if record["kind"] == "model":
                response = self.read(directory / (prefix + ".response.bin")) or {}
                choice = (response.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                timing = self.read(directory / (prefix + ".timing.json")) or {}
                case = cases.get(directory.name if nested else prefix, {})
                if nested and not case:
                    case = self.read(directory / "control-result.json") or {}
                    if directory.name in RECOVERY_CASES and not case:
                        case = self.read(directory / "summary.json") or {}
                state = "returned" if response else "awaiting response"
                request_end = None
                end_evidence = case or summary
                if not response and end_evidence:
                    state = "attempt ended / response unavailable"
                    error = end_evidence.get("agent_error") or end_evidence.get("error")
                    error = error if isinstance(error, dict) else {"message": error}
                    reason = error.get("message") or end_evidence.get("cancelled")
                    # DeadlineExceeded also denotes exhausted context/token budgets.
                    # Attribute timeout only to the final model request in this scope.
                    if path == last_model_request.get(directory):
                        if (
                            error.get("type") == "TimeoutError"
                            or "timed out" in str(reason).lower()
                        ):
                            state = "request timed out"
                        elif "wall deadline expired" in str(reason).lower():
                            state = "attempt deadline reached"
                    request_end = {
                        "state": state,
                        "reason": reason,
                        "error_type": error.get("type"),
                        "response": "No readable response payload was recorded.",
                        "accounting": "No client-reported token usage is available for this request; completed-response totals omit it.",
                        "note": "This describes the outer attempt's recorded end, not a backend completion acknowledgement.",
                    }
                record.update(
                    state=state,
                    request_end=request_end,
                    finish=choice.get("finish_reason"),
                    usage=response.get("usage"),
                    context=self.read(
                        directory / (prefix.replace("request-", "context-") + ".json")
                    ),
                    context_usage=self.read(
                        directory
                        / (prefix.replace("request-", "context-") + ".usage.json")
                    ),
                    seconds=timing.get("wall_seconds", case.get("elapsed_seconds")),
                    control_case=case or None,
                    seed=req.get("seed"),
                    limit=req.get("max_tokens"),
                    messages=len(req.get("messages", [])),
                    content=(msg.get("content") or "")[:24000],
                    reasoning=(msg.get("reasoning_content") or "")[:24000],
                    tool_calls=msg.get("tool_calls") or [],
                )
                if prefix == "request-001" or CONTROL_ARTIFACT.fullmatch(path.name):
                    record["initial_prompt"] = req.get("messages", [])[:2]
            else:
                result = self.read(directory / (prefix + ".result.json"))
                cleanup = self.read(directory / (prefix + ".cleanup.json"))
                if result:
                    result = dict(result)
                    for key in ("stdout", "stderr"):
                        value = result.get(key, "")
                        if len(value) > 24000:
                            result[key] = (
                                value[:24000]
                                + "\n[Display truncated; see raw artifact.]"
                            )
                typed = req.get("mode") == "adapter-control" and req.get("name") in (
                    "finish_attempt",
                    "checkpoint_context",
                )
                record.update(
                    tool_name=req.get("name", "bash"),
                    arguments=req.get("arguments")
                    if typed or req.get("name") in ("edit_file", "write_file")
                    else None,
                    adapter_control=typed,
                    executed=req.get("executed") if typed else None,
                    terminal_control=result.get("terminal_control") if result else None,
                    review_control=result.get("review_control") if result else None,
                    checkpoint_control=result.get("checkpoint_control")
                    if result
                    else None,
                    cleanup_required=result.get("cleanup_required") if result else None,
                    state="checkpoint saved / unverified memory"
                    if typed and result and result.get("checkpoint_control")
                    else "review requested / not submitted"
                    if typed and result and result.get("review_control")
                    else (
                        "adapter terminal / "
                        + str(result.get("terminal_control", "unknown"))
                    )
                    if typed and result
                    else "adapter pending"
                    if typed
                    else "adapter terminal / unadjudicated"
                    if result and result.get("terminal_control") == "Blocked"
                    else "returned"
                    if result
                    else ("transport stopped" if cleanup else "executing"),
                    command=req.get("arguments", {}).get("command"),
                    timeout=req.get("timeout"),
                    result=result,
                    cleanup=cleanup,
                )
                if not result:
                    record["transport_stdout"] = self.text(
                        directory / (prefix + ".stdout.bin"), 16000
                    )[0]
                    record["transport_stderr"] = self.text(
                        directory / (prefix + ".stderr.bin"), 16000
                    )[0]
            records.append(record)
        return {
            "events": records,
            "summary": summary or None,
            "outer_adjudication": self.outer_adjudication(root, summary),
            "kind": "diagnostic"
            if self.is_diagnostic(summary)
            else "control"
            if self.is_control(summary, files)
            else "coding",
            "diff": self.text(root / "changes.diff", 65536)[0],
            "artifacts": sorted(
                p.relative_to(root).as_posix()
                for directory in [
                    root,
                    *(root / name for name in (*NATIVE_CASES, *RECOVERY_CASES)),
                ]
                if directory.is_dir() and not directory.is_symlink()
                for p in directory.iterdir()
                if p.is_file()
                and not p.is_symlink()
                and self.allowed_artifact(p.relative_to(root).as_posix())
            ),
        }


class Handler(BaseHTTPRequestHandler):
    evidence = None

    def do_GET(self):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if (
            self.headers.get("Host") not in allowed
            or self.headers.get("Origin")
            not in (None, *("http://" + h for h in allowed))
            or self.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            self.send_error(403)
            return
        route = urlsplit(self.path)
        params = parse_qs(route.query)

        def arg(key):
            return params.get(key, [""])[0]

        try:
            if route.path == "/api/runs":
                data = self.evidence.runs(
                    page=int(arg("page") or "1"),
                    page_size=int(arg("page_size") or "20"),
                    query=arg("q"),
                )
            elif route.path == "/api/run":
                data = self.evidence.run(arg("run"))
            elif route.path == "/api/trace":
                data = self.evidence.trace(arg("run"), arg("trial"))
            elif route.path == "/api/artifact":
                data = self.evidence.artifact(arg("run"), arg("trial"), arg("name"))
            elif route.path in ("/", "/app.js", "/style.css"):
                filename = {
                    "/": "index.html",
                    "/app.js": "app.js",
                    "/style.css": "style.css",
                }[route.path]
                mime = {
                    "/": "text/html",
                    "/app.js": "text/javascript",
                    "/style.css": "text/css",
                }[route.path]
                self.respond((PROJECT / "observatory" / filename).read_bytes(), mime)
                return
            else:
                self.send_error(404)
                return
            self.respond(
                json.dumps(data, ensure_ascii=True).encode(), "application/json"
            )
        except (ValueError, OSError, KeyError) as error:
            self.respond(
                json.dumps({"error": str(error)}).encode(), "application/json", 400
            )

    def respond(self, body, mime, status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args) > 1 else "") not in ("200",):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.evidence = Evidence()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(
        f"Local harness observatory: http://127.0.0.1:{server.server_port}", flush=True
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
