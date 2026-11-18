# Snapshot provenance

This repository begins with a public source snapshot selected from Local Harness Lab development revision `057c88d638773dade1a05710193fe309db896e10`. The private archive retains the original commits, issue discussions, experiment store and full campaign ledger. Original commit, job and package identifiers in the evidence describe that archive. This repository has its own Git history.

The snapshot includes the Worker runtime, Delegate, Verifier, Observatory, authored tasks, example workstation profiles and protocols, selected evidence, and the portable CI suite. The operator must supply hardware-specific assets for live inference. The root license covers the Lab’s original code and documentation. [Attribution](docs/third-party-attribution.md)

## Historical examples

| Material included here | Source in the development archive | Independent check |
| --- | --- | --- |
| [Checkpoint policy and its tests](examples/reviewing-worker-output/historical) | The files at `8f98938c546be353de613bebd042445a71ca3180`. The [Worker patch](examples/reviewing-worker-output/accepted/worker.patch) covers the two files from landing `3aaf108`. | Run all 14 original policy tests and inspect the three inventory-bound evidence files. |
| [Observatory starter files](examples/preparing-worker-package/starter) | The two files selected from `0deaaef59c1a76bb4da9fe7b9cb16d418940a7de`. The [landing diff](examples/preparing-worker-package/landed.patch) comes from `4a99ddb`. | Rebuild the package and compare its snapshot, contract, portable spec and request with the recorded identities. |
| [Selected Worker trace](examples/replaying-worker-trace/packet) | Original portable evidence packet from the private development tree. | Replay the recorded actions, patch digest, check outcomes and review binding on CPU. |

The reader guides and package preparer use the in-tree files. The two recipe registries resolve the measured server catalogs and protocols under `configs/recipe-inputs/`. Those inputs retain their recorded SHA-256 digests. The launch catalog also includes the measured profiles absent from the development checkout. Machine-specific paths inside profiles identify the original setup. The historical evidence retains its original hashes and timing. Preparing a new live job with this source tree produces a new runtime identity.

## Task coverage

The public ladder spans 60–720 seconds of model time on the measured workstation. The release-channel rung supplies a short authored repair. Historical HCAST measurements remain attributed to the private task; the public ladder omits the HCAST source, reference solutions and task-specific graders. The JavaScript rung has separate timing and review evidence and no measured human baseline. Other archived campaigns, diagnostic-only cases and the original raw traces live outside this release. [Task ladder](docs/ladder.md)
