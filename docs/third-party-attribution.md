# Third-party attribution

## CPython in the Git backport tasks

Four task bundles include the configuration parser, its documentation and the license file from CPython v3.13.0. All four share the import commit `77b1c16e80e437c062561b7a4a8a44fa559d30fd` inside the bundle. Its tree contains these upstream files byte for byte. [CPython v3.13.0](https://github.com/python/cpython/tree/v3.13.0)

| File in CPython | Path inside the bundle |
| --- | --- |
| `Lib/configparser.py` | `configparser.py` |
| `Doc/library/configparser.rst` | `docs/upstream-configparser.rst` |
| `LICENSE` | `LICENSE` |

Each task directory below contains the bundle at `public/repository.bundle` and the full upstream SHA-256 digests in the `provenance` section of `task.json`. The Lab authored the branch histories, write policy, service and tests. The bundled `PROVENANCE.md` records that distinction.

| Task manifests | Where to find the upstream parser |
| --- | --- |
| [Smoke](../tasks/git-config-backport-smoke/task.json) and [Smoke Basic](../tasks/git-config-backport-smoke-basic/task.json) | The import commit, the `release/stable` branch and the `base-stable` tag. The parser on `main` includes downstream changes. |
| [Dual](../tasks/git-config-backport-dual/task.json) and [Dual Public Tests](../tasks/git-config-backport-dual-public-tests/task.json) | The import commit. The parser on `main`, `release/stable` and `release/legacy` includes downstream changes. |

The CPython license file and documentation retain their upstream bytes throughout all four bundle histories. To read the bundled provenance and full license from the Lab repository root, use Git to inspect the objects directly. The example needs no network access or checkout.

```sh
bundle=tasks/git-config-backport-smoke/public/repository.bundle
reader=$(mktemp -d)
git clone --quiet --bare "$bundle" "$reader/smoke.git"
git -C "$reader/smoke.git" show refs/tags/base-stable:PROVENANCE.md
git -C "$reader/smoke.git" show refs/tags/base-stable:LICENSE
```

## mini-SWE-agent and the Worker loop

The Worker uses mini-SWE-agent 2.4.6, copyright © 2025 Kilian A. Lieret and Carlos E. Jimenez, under the MIT License. The Lab imports its agent loop, exceptions and tool-call helpers through `scripts/mini_bootstrap.py`. The local model client, isolated tool adapter and independent verifier are Lab components. The dependency is pinned in `pyproject.toml` and `uv.lock`. [Upstream release](https://github.com/SWE-agent/mini-swe-agent/tree/v2.4.6) · [Upstream license text](licenses/mini-swe-agent.txt)

## Historical HCAST measurements

The comparison report includes aggregate outcomes on a task adapted from METR HCAST. The public ladder uses the Lab’s authored JavaScript release-channel task at the short ceiling. The HCAST fixtures, their graders and the local reference implementations are held in the private archive. METR’s upstream notice requests that solutions remain protected. [Upstream notice](https://github.com/METR/hcast-public/blob/03438239d200fb3e89a5ddfc62ab4d23cc1866fb/LICENSE)
