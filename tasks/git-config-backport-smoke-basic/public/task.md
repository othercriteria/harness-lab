# Backport write-safety to release/stable

The repository is already initialized at /workspace/repo, checked out on
release/stable. Work there using ordinary Git through bash. The frozen local branches
and tags are available without network access. Inspect git log/show/diff and
read_file for targeted source navigation; use whichever tools help.

main contains one approved fix, tagged approved-write-safety. Backport its
behavior to release/stable. Each target must have at least one new commit descending
from its base tag. Preserve the main branch, all base tags and every original
commit. A cherry-pick is allowed; commit messages and exact patch shape are not
prescribed. No merge commits on target histories. Keep changes on the target
branches; the final checked-out target may be either target when there are two.

Start with docs/WRITE_POLICY.md and each target's RELEASE.md. They define the
bounded safety policy and compatibility differences. The 1,400-line parser and
long upstream reference are genuine CPython-derived material, not all required
reading. The fix is supplied to focus work on integration and verification.
This is the clean single-backport rung: no release-specific conflict is intended.

Run python -m unittest discover -s tests separately on each target after its
final changes. This small task is a clean cherry-pick and verification exercise:
use the supplied regression suite as the verification deliverable; additional
test-writing is optional. Existing supplied tests must remain byte-identical. Commit all
work; leave the repository clean, with no pending cherry-pick/merge/rebase. Do
not change files outside configparser.py, service.py and tests/ in the repository.
The task.md and repository.bundle outside repo are harness inputs, not deliverables.

Create /workspace/handoff.json (outside repo) with this structure, using full
40-character commit IDs and the branches actually submitted:
{"branches": {"release/stable": {"commit": "FULL_COMMIT_ID",
 "verification_command": "python -m unittest discover -s tests"}}}
Include an entry for every target. Run that command at that final revision before
recording it. In finish_attempt, identify both the handoff file and the observation
IDs for your branch-specific verification (command output should identify branch
and commit). These observations are historical evidence; the outer evaluator
independently checks each submitted revision. A missing or failed check must be
reported honestly rather than described as passing.
