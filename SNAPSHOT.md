# Snapshot provenance

The [first public snapshot](https://github.com/othercriteria/harness-lab/commit/c7b7b842d9cf7f32b4ca0b89aba04de5ee5e6421) came from development revision `057c88d638773dade1a05710193fe309db896e10`. The merge that follows it has two parents. Its first parent is that exact published snapshot. Its second parent carries the filtered history of the files selected for release. The merge kept the snapshot tree byte for byte.

The second parent preserves all 455 development commits in order, with their authors, dates and messages. Of those, 179 change the published files and 276 have the same tree as their first parent. Many of the latter recorded workstation experiments whose evidence remains in the private archive. The [commit map](docs/development-commits.tsv) translates the original IDs in receipts into public Git IDs. Use `git log --first-parent main` for the release sequence and `git log --all -- path/to/file` for an individual file. Historical checkouts contain only the selected files. The release snapshot is the starting point for running the examples.

The [public issue tracker](https://github.com/othercriteria/harness-lab/issues) carries the original issue numbers. Each migrated issue and comment records its original date. Links to evidence retained only in the private archive are identified in the migration notes. New work belongs in the public tracker.

The snapshot includes the Worker runtime, Delegate, Verifier, Observatory, authored tasks, example workstation profiles and protocols, selected evidence, and the portable CI suite. The operator must supply hardware-specific assets for live inference. The root license covers the Lab’s original code and documentation. [Attribution](docs/third-party-attribution.md)

## Historical examples

| Material included here | Source in the development archive | Independent check |
| --- | --- | --- |
| [Checkpoint policy and its tests](examples/reviewing-worker-output/historical) | The files at [development `8f98938c`](https://github.com/othercriteria/harness-lab/commit/af8a47a87b0d122066bde0e3bc73a57c089f008b). The [Worker patch](examples/reviewing-worker-output/accepted/worker.patch) covers the two files from landing [development `3aaf108`](https://github.com/othercriteria/harness-lab/commit/1410543b7ca025d219d6d9400272a64d9ca01d0f). | Run all 14 original policy tests and inspect the three inventory-bound evidence files. |
| [Observatory starter files](examples/preparing-worker-package/starter) | The two files selected from [development `0deaaef5`](https://github.com/othercriteria/harness-lab/commit/6a18691d6be8e5a35219e4ea1d0b94782b2f7c3d). The [landing diff](examples/preparing-worker-package/landed.patch) comes from [development `4a99ddb`](https://github.com/othercriteria/harness-lab/commit/1aeaefed8ec5364b71bf276a8f74071ae355d41e). | Rebuild the package and compare its snapshot, contract, portable spec and request with the recorded identities. |
| [Selected Worker trace](examples/replaying-worker-trace/packet) | Original portable evidence packet from the private development tree. | Replay the recorded actions, patch digest, check outcomes and review binding on CPU. |

The reader guides and package preparer use the in-tree files. The two recipe registries resolve the measured server catalogs and protocols under `configs/recipe-inputs/`. Those inputs retain their recorded SHA-256 digests. The launch catalog also includes the measured profiles absent from the development checkout. Machine-specific paths inside profiles identify the original setup. The historical evidence retains its original hashes and timing. Preparing a new live job with this source tree produces a new runtime identity.

From a full clone, run `python3 -B -S -m unittest -v tests.test_public_pins` to check the historical files against public Git objects, replay both patches, run the 14 original checkpoint tests, and verify the published recipe bindings. CI runs the same command. The digest checks cover the bundled freeze records. Starting inference also requires the external weights and installed runtime described in those records.

## Task coverage

The public ladder spans 60–720 seconds of model time on the measured workstation. The release-channel rung supplies a short authored repair. Historical HCAST measurements remain attributed to the private task; the public ladder omits the HCAST source, reference solutions and task-specific graders. The JavaScript rung has separate timing and review evidence and no measured human baseline. Other archived campaigns, diagnostic-only cases and the original raw traces live outside this release. [Task ladder](docs/ladder.md)
