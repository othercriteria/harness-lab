"""Compare the two unsigned receipt formats using inert packet bytes only."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://github.com/othercriteria/harness-lab/blob/main/examples/binding-probe-results/README.md#browser-observation-v1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_binding(candidate, style):
    if style == "Lab":
        receipt = json.loads((candidate / "receipt.json").read_bytes())
        return receipt["artifact_sha256"], receipt["probe"]
    statement = json.loads((candidate / "statement.json").read_bytes())
    if (
        statement["_type"] != STATEMENT_TYPE
        or statement["predicateType"] != PREDICATE_TYPE
    ):
        raise ValueError("Unsupported statement or predicate type")
    (subject,) = statement["subject"]
    return subject["digest"]["sha256"], statement["predicate"]


def mismatch(binding, manifest, patch, verifier, driver, stdout):
    subject, probe = binding
    if sha256(manifest) != subject:
        return "subject"
    if sha256(patch) != json.loads(manifest)["diff_sha256"]:
        return "patch"
    if sha256(verifier) != probe["verifier_sha256"]:
        return "verifier"
    if sha256(driver) != json.loads(verifier)["browser_driver_sha256"]:
        return "driver"
    if sha256(stdout) != probe["stdout_sha256"]:
        return "stdout"
    return None


def replay(packet, history):
    case = history["cases"][0]
    driver = (packet / "browser.cjs").read_bytes()
    verifier = (packet / "verifier.json").read_bytes()
    if sha256(driver) != case["replay_driver_sha256"]:
        raise ValueError("Driver differs from the previously published digest")
    worker = packet / "worker"
    integrated = packet / "integrated"
    if sha256((worker / "artifact.json").read_bytes()) != case["artifact_sha256"]:
        raise ValueError("Worker manifest differs from the previously published digest")
    if sha256((integrated / "artifact.json").read_bytes()) == case["artifact_sha256"]:
        raise ValueError("Integrated manifest unexpectedly matches the reviewed Worker")
    print("Historical review: its artifact digest selects only the Worker manifest.")
    for label, folder, other, historical_name in [
        ("Worker", worker, integrated, "worker"),
        ("Integrated", integrated, worker, "pr"),
    ]:
        manifest = (folder / "artifact.json").read_bytes()
        patch = (folder / "changes.patch").read_bytes()
        stdout = (folder / "stdout.txt").read_bytes()
        other_manifest = (other / "artifact.json").read_bytes()
        other_patch = (other / "changes.patch").read_bytes()
        observed = json.loads(stdout.splitlines()[-1])
        for name, fields in case["observed_replays"][historical_name].items():
            if any(observed[name][key] != value for key, value in fields.items()):
                raise ValueError(
                    f"{label}: disagrees with historical {name} observation"
                )
        results = []
        for style in ["Lab", "Statement v1"]:
            binding = read_binding(folder, style)
            results.append(binding)
            for expected, artifact, display, definition, code, output in [
                (None, manifest, patch, verifier, driver, stdout),
                ("subject", other_manifest, other_patch, verifier, driver, stdout),
                ("patch", manifest, other_patch, verifier, driver, stdout),
                ("stdout", manifest, patch, verifier, driver, stdout.rstrip(b"\n")),
                ("verifier", manifest, patch, verifier + b" ", driver, stdout),
                ("driver", manifest, patch, verifier, driver + b" ", stdout),
            ]:
                actual = mismatch(binding, artifact, display, definition, code, output)
                if actual != expected:
                    raise ValueError(f"{style}: expected {expected}, observed {actual}")
            print(
                f"{label}, {style}: matched. Rejected substitutions of subject, patch, stdout, verifier and driver."
            )
        if results[0] != results[1] or results[0][1]["exit_code"] != 0:
            raise ValueError(f"{label}: inconsistent capture facts or failed execution")
        facts = results[0][1]
        if (
            facts["launcher_arguments"] != ["17", historical_name]
            or not facts["producer"]
            or datetime.fromisoformat(facts["finished_at"]).utcoffset() is None
        ):
            raise ValueError(f"{label}: missing or inconsistent invocation details")
    if (worker / "stdout.txt").read_bytes() != (integrated / "stdout.txt").read_bytes():
        raise ValueError("The two outputs in this example should be byte-identical")
    print(
        "Both candidates produced the same stdout bytes. Swapping only those outputs is undetectable."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, nargs="?", default=HERE / "packet")
    replay(
        parser.parse_args().packet,
        json.loads((ROOT / "results/footsteps-transfer-001.json").read_bytes()),
    )
