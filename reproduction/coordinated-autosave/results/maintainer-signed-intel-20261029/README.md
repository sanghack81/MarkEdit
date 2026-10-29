# Maintainer-supplied signed build, Intel verification

On October 29, 2026, the unmodified signed build from [the maintainer’s attachment](https://github.com/MarkEdit-app/MarkEdit/issues/1833#issuecomment-6487766486) was tested on the original Intel iMac19,1, macOS 15.8.1 (24H32).

The ZIP SHA-256 is `ac00139201396742d29a1e3f0a94697eb810104ef9a2ca8740d53737f394483d`. The executable SHA-256 is `e628eb9832fde880b1747d28b26db76158e435ba51d57cba1ed5aa1a81759e0d`. The build reports 1.36.0 (96), the same displayed version as the installed original; its hash differs. `codesign --verify --deep --strict` passed, with YING ZHONG (TCKG8FBVG6) as signer. Gatekeeper accepted it as Notarized Developer ID. Its signature was verified again after the test.

The user saved and closed the installed app first. The author’s app was copied unchanged to a temporary location and run with its normal bundle identifier, app group, sandbox and existing user settings. No plist edits, source edits, re-signing, preference reset or app-group isolation overlay was applied. The installed `/Applications/MarkEdit.app` executable hash remained unchanged. Normal app startup can write shared application state; this is not a claim that every preference/cache byte stayed unchanged.

The test opened a tiny local `existing.md`, observed its window, took a one-second baseline sample, then started the existing standalone `.forMerging` writer. The driver waited **up to two seconds** for writer exit; it returned sooner when the writer completed. It then requested opening `next.md` and collected a five-second sample and window list.

Results:

- Writer access was granted 9.083 ms after `WRITE_REQUEST`; it logged `WRITE_DONE` and `COORDINATOR_RETURNED nil`, and exited 0 before the next-open request.
- `next.md` appeared onscreen under the same tested PID 3952.
- `existing.md` contained the exact expected external fixture bytes, preserved as `existing-after.md`.
- The after-sample contains 4,235 main-thread samples, with zero in `_NSDocumentSerializationSemaphore.wait`.
- These observations preceded cleanup. The driver then stopped its test app; it did not replace or reopen the installed original app.

This is one bounded successful check of the supplied binary against the earlier controlled sequence, not long-term ordinary-use validation. Internal editor readiness/`isOutdated` were not instrumented in this signed release binary. The exact external writer in the natural incident and the coordinated `isOutdated == true` path remain unverified.

The reports, writer log, complete process samples, window observations and fixture bytes are adjacent. `archived-driver.py` records the guarded invocation; its original absolute paths are redacted, so it is an audit artifact rather than a directly portable runner. For repeatable commands use the parent [reproduction instructions](../../README.md#1-full-application-reproduction). Path redaction and hashes are recorded in `artifact-provenance.json`.
