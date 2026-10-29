# MarkEdit coordinated-autosave hang: reproduction and recorded evidence

Evidence for [issue #1833](https://github.com/MarkEdit-app/MarkEdit/issues/1833) and [PR #1840](https://github.com/MarkEdit-app/MarkEdit/pull/1840).

On October 28, 2026, the installed MarkEdit 1.36.0 hung again on the Intel iMac while opening a 7,848-byte Markdown file in Google Drive. A 30-second full-process sample shows the main thread blocked in `documentForURL:` → `_isLocatedByURL:` → `_NSDocumentSerializationSemaphore.wait` throughout all 24,599 main-thread samples. A background `willSaveCallback` thread waits in `NSUIActivityManager userActivityWillSave:`. [Full-process sample](results/natural-20261028-full-process.sample.txt) · [selected threads](results/natural-20261028-selected-threads.sample.txt).

We then induced a file-coordination hang with ordinary local temporary files in the full source-built application on both Intel and M4 Pro. The callback-autosave comparison completed the external write and opened the next document under the same sequence.

**Limit:** the exact external writer in the natural incident remains unknown. The patched app was not installed for everyday use. These results establish a reproducible mechanism and a working fix for that mechanism; they do not establish that every intermittent hang has the same cause. All timeout observations are bounded, not proof of an eternal deadlock.

## 1. Full-application reproduction

Source: MarkEdit 1.36.0, commit [`d0b6ab653f1daf412a0816ff050f457d4c323c3c`](https://github.com/MarkEdit-app/MarkEdit/tree/d0b6ab653f1daf412a0816ff050f457d4c323c3c). Build using the project's [development guide](https://github.com/MarkEdit-app/MarkEdit/wiki/Development). The comparison keeps this version's application/document code and applies [the callback-autosave hunk](provenance/v1.36-callback-autosave.patch). PR #1840 applies that change and a regression test to upstream main `19baac886f7304cbc4bab9d0245bab548bb5c473`.

Use a separate source-built app with its own identifier/settings so the experiment cannot reuse an installed app process or document restoration state. In a logged-in desktop session:

1. Compile the standalone writer and create two tiny local files:

   ```sh
   # Start in this reproduction directory.
   FIXTURE_DIR=$(mktemp -d /tmp/markedit-coordinate.XXXXXX)
   swiftc gui/coordinate.swift -o "$FIXTURE_DIR/coordinate"
   printf '# Existing fixture\n\nOpened before coordinated writing.\n' > "$FIXTURE_DIR/existing.md"
   printf '# Next fixture\n\nOpened during coordination.\n' > "$FIXTURE_DIR/next.md"
   REPRO_APP='/absolute/path/to/isolated-source-built/MarkEdit.app'
   open -n -a "$REPRO_APP" "$FIXTURE_DIR/existing.md"
   ```

2. Wait until `existing.md` is fully loaded. Leave its editor unchanged. In the recorded M4 run, `isContentReady == true`, `isOutdated == false`, `isDocumentEdited == false`, and `hasUnautosavedChanges == false` were verified before starting the writer.
3. Request an external `.forMerging` write to the **already-open** file, then open a **different** file:

   ```sh
   "$FIXTURE_DIR/coordinate" "$FIXTURE_DIR/existing.md" > "$FIXTURE_DIR/coordinator.log" 2>&1 &
   # Wait two seconds, then issue the next request.
   sleep 2
   open -a "$REPRO_APP" "$FIXTURE_DIR/next.md"
   cat "$FIXTURE_DIR/coordinator.log"
   ```

   `coordinate.swift` uses a separate process and the real `NSFileCoordinator`. It prints `WRITE_REQUEST` before coordination, `WRITE_GRANTED` only inside the accessor, then writes fixture bytes and prints `WRITE_DONE` and `COORDINATOR_RETURNED nil` on success. Only the temporary fixture is overwritten.
4. On the original build, the writer remained at `WRITE_REQUEST`; `next.md` did not get a window. Sample that app's PID with `sample PID 10 -file original.sample.txt`. On the callback build, the writer completed, the fixture bytes changed, and `next.md` got a window. Use a new fixture directory and app process for each variant. End only the isolated probe/writer processes after collecting evidence.

Recorded comparison (one paired final run per architecture):

| Machine | Original app | Callback app |
| --- | --- | --- |
| iMac19,1, Intel x86_64, macOS 15.8.1 (24H32), 5-second sample | 4,166/4,166 main-thread samples in document serialization wait; writer pending; no next window; no disk update | 0/4,100 in that wait; writer exit 0; next window present; expected disk bytes |
| M4 Pro Mac mini, native arm64, macOS 27.0 (26A428), 10-second sample | 8,548/8,548 in that wait; writer pending; no next window; no disk update | 0/6,732 in that wait; writer exit 0 before the two-second next-open request; next window present; expected disk bytes and advancing UI heartbeat |

The final Intel original run entered the wait via `_checkAutosavingThenContinue:`. An [earlier original Intel run](results/gui/intel-earlier-lookup-main-thread.sample.txt) and the M4 original run entered it via `documentForURL:`, matching the natural incident's lookup path. Do not read every wait sample as an identical full stack.

[Intel results](results/gui/intel-comparison.json) · [M4 results](results/gui/arm-comparison.json). The adjacent files contain individual reports, writer logs, full-process samples and complete main-thread excerpts. The drivers checked window presence and actual bytes on disk; they stopped their own pending children only after sampling. Cleanup was not used to make the callback case pass.

### Probe differences

These were isolated debug builds, not pristine release binaries. Bundle/app-group identities and settings were separate; Quick Look plugins and URL-scheme/default-handler registrations were removed. On macOS 27 the sandbox denied the probe's shared-container startup copy, so that unrelated Quick Look initialization was explicitly skipped and the unused app-group entitlement omitted. The normal app sandbox remained enabled. Native window-title/heartbeat tracing was added on M4 because window titles were unavailable to the SSH process. Document getters ran once before coordination, not during the wait. Updates were disabled in each probe's settings. Both original and callback variants used equivalent isolation measures, with per-variant bundle/group IDs; their open/autosave behavior differed by the linked callback hunk.

The archived [source overlays](provenance/) and [Intel](gui/intel-driver.py)/[M4](gui/arm-driver.py) observation drivers show the experiment's changes. The drivers expect already-built isolated bundles; the M4 driver also expects the matching tracing overlay. This folder does not automate app signing/packaging or claim a pristine-release binary A/B.

## 2. Standalone exact-method reproduction (no app build needed)

Requirements: macOS with AppKit, `swiftc`, and Python 3. From this directory:

```sh
python3 exact-method/run_exact.py
```

The runner uses the bundled `upstream-EditorDocument.swift` from the exact 1.36.0 commit, verifies its SHA-256, extracts lines 380–396, and verifies that the original autosave method is inserted byte-for-byte into a minimal `NSDocument` subclass. It compiles inherited/original/callback variants and creates only new temporary fixture files. Each child has a five-second observation period; on timeout its sample is captured and that child is stopped. Outputs are preserved under `exact-method/runs/`.

This is an extracted-method experiment, separate from the full-app comparison above. `isOutdated`, `isTerminating`, and `hasBeenReverted` are false. An unchanged document and an edited document whose current text is already cached are tested. Reading/serialization use UTF-8; a fail-if-called stub makes any accidental use of the untested editor-refresh path visible.

The **10 distinct cases**, not 10 repetitions, gave this same pattern on Intel/macOS 15.8.1/Swift 6.2.4 and M4/macOS 27.0/Swift 6.4:

| Operation | Inherited AppKit | Exact original method | Callback candidate |
| --- | --- | --- | --- |
| Coordinated write, unchanged document | Completed | Five-second timeout | Completed |
| Coordinated write, edited text already cached | Completed | Five-second timeout | Completed |
| Direct autosave, edited text already cached | Not run | Completed | Completed |
| Coordinated write plus lookup of another URL | Not run | Five-second timeout | Completed |

Passing write cases verify that the external accessor sees the current document bytes **before** overwriting and that the final disk bytes are correct. Passing lookup cases require `LOOKUP_RETURNED`. Original-method timeouts are recorded, not assumed by an assertion: the runner can report a different outcome on another OS. [Intel report](results/exact-method/intel-report.json) · [M4 report](results/exact-method/arm-report.json).

The upstream source SHA-256 is `624cf9ab46e238b1c89512e0bdcd64a7ce256fed66ae147adf566d511092cea5`; the extracted/inserted original method SHA-256 is `12f83fecd821dcbad0d6a4f5372df8e98d8ee5f7a37eab27893f7e43e721ad95`. The published runner differs from the recorded runner only by using this bundled source path and asserting the pinned source hash. Its own newly generated manifest records its current hash. The public runner was rerun on the Mac mini on October 29: the [new report](results/exact-method/published-runner-m4-20261029-report.json) again records seven completions and three original-method timeouts.

## 3. Regression in the real MarkEdit test target

At PR commit `77cc8767adb4c8b1e3e29ca587b2a9ae65d6a4cb`, build CoreEditor as described in the development guide, then run:

```sh
xcodebuild test -project MarkEdit.xcodeproj -scheme MarkEditMac \
  -only-testing:MarkEditMacTests/EditorDocumentTests/testAutosaveCompletesDuringCoordinatedFileAccess \
  -destination 'platform=macOS' CODE_SIGN_IDENTITY="" CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO
```

For the original-method control, retain the added test but restore only `MarkEditMac/Sources/Editor/Models/EditorDocument.swift` from base commit `19baac886f7304cbc4bab9d0245bab548bb5c473` in a disposable worktree. Run the same command.

The test uses the actual `EditorDocument`, its presenter queue, `relinquishPresentedItem(toWriter:)`, and `savePresentedItemChanges`. On a three-second timeout it records `XCTFail` **before** reacquiring access to let the test clean up. The original method failed in 3.130 seconds; the callback method passed in 0.018 seconds. The final full hosted target executed 39 tests, one expected System Keychain entitlement skip, zero failures. [Recorded log excerpts and full-log hashes](results/hosted-tests.txt).

Those tests ran on the Mac mini. A subsequent amendment changed one termination comment only; executable code and tests match the final PR. This is local validation, not a claim that GitHub CI passed.

## Scope and provenance

The proposed fix covers `isOutdated == false`, meaning the editor's current text is already synchronized with the document model; that can still include unsaved document changes. Coordinated saving while `isOutdated == true` is outside the demonstrated fix. The existing asynchronous refresh and termination/error paths remain in the patch, but full application termination was not tested here.

[artifact-provenance.json](artifact-provenance.json) records source artifact names and SHA-256 values. Published reports redact home-directory identities and per-user temporary directory prefixes; full-process samples and explicitly labeled thread excerpts are both included. No actual user document content is included. The MarkEdit source snapshot retains its upstream copyright and is covered by the repository's MIT license.
