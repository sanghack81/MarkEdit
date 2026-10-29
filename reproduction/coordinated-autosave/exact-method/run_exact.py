"""Extract MarkEdit's unchanged autosave method and test only synchronized content.

Each executable owns temporary files. No installed application is controlled.
"""
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ORIGINAL = HERE / "upstream-EditorDocument.swift"


def digest(data):
    return hashlib.sha256(data).hexdigest()


original_bytes = ORIGINAL.read_bytes()
assert digest(original_bytes) == "624cf9ab46e238b1c89512e0bdcd64a7ce256fed66ae147adf566d511092cea5", "Unexpected upstream source snapshot"
(HERE / "upstream-EditorDocument.swift").write_bytes(original_bytes)
start_token = b"  override func autosave(withImplicitCancellability implicitlyCancellable: Bool) async throws {\n"
assert original_bytes.count(start_token) == 1
start = original_bytes.index(start_token)
end = original_bytes.index(b"\n  }\n", start) + len(b"\n  }\n")
method = original_bytes[start:end]
(HERE / "original_autosave.swift").write_bytes(method)
assert method == b"".join(original_bytes.splitlines(keepends=True)[379:396])

prefix = r'''import AppKit
setbuf(stdout, nil)
let operation = CommandLine.arguments[1]
let modified = CommandLine.arguments[2] == "modified"
let lookup = CommandLine.arguments[3] == "lookup"
let root = URL(fileURLWithPath: CommandLine.arguments[4], isDirectory: true)
let first = root.appendingPathComponent("owned.md")
let second = root.appendingPathComponent("different.md")
let initial = "on-disk-initial\n"
let latest = "cached-latest\n"
try Data(initial.utf8).write(to: first)
let controller = NSDocumentController.shared
var updateContentCalls = 0
var writeSafelyCalls = 0
var dataCalls = 0

final class Probe: NSDocument {
  var stringValue = ""
  var isOutdated = false // The content is outdated, needs an update
  var isTerminating = false
  private var revertedDate: Date = .distantPast

  var hasBeenReverted: Bool {
    Date.now.timeIntervalSince(revertedDate) < 1
  }

  override class var autosavesInPlace: Bool { true }
  override func read(from data: Data, ofType typeName: String) throws {
    stringValue = String(decoding: data, as: UTF8.self)
  }
  override func data(ofType typeName: String) throws -> Data {
    dataCalls += 1
    Swift.print("DATA_REQUESTED", dataCalls, stringValue.data(using: .utf8)!.base64EncodedString())
    return Data(stringValue.utf8)
  }
  override func canAsynchronouslyWrite(to url: URL, ofType typeName: String, for saveOperation: NSDocument.SaveOperationType) -> Bool {
    true
  }
  override func writeSafely(to url: URL, ofType typeName: String, for saveOperation: NSDocument.SaveOperationType) throws {
    writeSafelyCalls += 1
    Swift.print("WRITE_SAFELY", writeSafelyCalls)
    try super.writeSafely(to: url, ofType: typeName, for: saveOperation)
  }

  // shortcut: only isOutdated=false is tested; use real editor dependencies before testing that branch.
  private func updateContent(userInitiated: Bool = false) async {
    updateContentCalls += 1
    fatalError("UNTESTED_UPDATE_CONTENT_CALLED")
  }

  func updateContent(userInitiated: Bool = false, saveAction: @escaping (() -> Void) = {}) {
    Task { @MainActor in
      await updateContent(userInitiated: userInitiated)
      saveAction()
    }
  }

'''

callback = r'''  override func autosave(
    withImplicitCancellability implicitlyCancellable: Bool,
    completionHandler: @escaping (Error?) -> Void
  ) {
    Swift.print("CALLBACK_ENTER")
    let saveAction = {
      do {
        if !self.hasBeenReverted && self.isTerminating && self.hasUnautosavedChanges, let fileURL = self.fileURL, let fileType = self.fileType {
          try self.writeSafely(to: fileURL, ofType: fileType, for: .autosaveAsOperation)
          self.fileModificationDate = .now
          completionHandler(nil)
          return
        }

        super.autosave(withImplicitCancellability: implicitlyCancellable, completionHandler: completionHandler)
      } catch {
        completionHandler(error)
      }
    }

    if isOutdated {
      updateContent(saveAction: saveAction)
    } else {
      saveAction()
    }
  }
'''

suffix = r'''}

let doc = try Probe(contentsOf: first, ofType: "public.plain-text")
controller.addDocument(doc)
if !NSFileCoordinator.filePresenters.contains(where: { ($0 as AnyObject) === doc }) {
  NSFileCoordinator.addFilePresenter(doc)
}
if modified {
  doc.stringValue = latest
  doc.updateChangeCount(.changeDone)
}
precondition(!doc.isOutdated && !doc.isTerminating && !doc.hasBeenReverted)
precondition(doc.isDocumentEdited == modified && doc.hasUnautosavedChanges == modified)
Swift.print("SETUP", "isOutdated=\(doc.isOutdated)", "isTerminating=\(doc.isTerminating)", "hasBeenReverted=\(doc.hasBeenReverted)", "isDocumentEdited=\(doc.isDocumentEdited)", "hasUnautosavedChanges=\(doc.hasUnautosavedChanges)")

if operation == "direct" {
  Task { @MainActor in
    do {
      try await doc.autosave(withImplicitCancellability: false)
      let stored = try String(contentsOf: first, encoding: .utf8)
      precondition(stored == (modified ? latest : initial))
      precondition(updateContentCalls == 0)
      Swift.print("DIRECT_FINISHED", "updateContentCalls=\(updateContentCalls)", "dataCalls=\(dataCalls)", "writeSafelyCalls=\(writeSafelyCalls)")
      exit(0)
    } catch {
      Swift.print("DIRECT_ERROR", error)
      exit(3)
    }
  }
} else {
  DispatchQueue.global().async {
    let coordinator = NSFileCoordinator(filePresenter: nil)
    var error: NSError?
    Swift.print("COORDINATOR_START")
    coordinator.coordinate(writingItemAt: first, options: .forMerging, error: &error) { url in
      do {
        let before = try Data(contentsOf: url)
        Swift.print("COORDINATED_PREWRITE_BASE64", before.base64EncodedString())
        precondition(before == Data((modified ? latest : initial).utf8))
        try Data("external\n".utf8).write(to: url)
        Swift.print("COORDINATED_WRITE")
      } catch {
        Swift.print("WRITE_ERROR", error)
        exit(4)
      }
    }
    Swift.print("COORDINATOR_FINISHED", String(describing: error))
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
      precondition(updateContentCalls == 0)
      Swift.print("FINAL", "updateContentCalls=\(updateContentCalls)", "dataCalls=\(dataCalls)", "writeSafelyCalls=\(writeSafelyCalls)")
      exit(error == nil ? 0 : 2)
    }
  }
  if lookup {
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
      Swift.print("LOOKUP_START")
      precondition(controller.document(for: second) == nil)
      Swift.print("LOOKUP_RETURNED")
    }
  }
}
RunLoop.main.run()
'''

sources = {
    "inherited": prefix.encode() + suffix.encode(),
    "exact-original": prefix.encode() + method + suffix.encode(),
    "callback-candidate": prefix.encode() + callback.encode() + suffix.encode(),
}
for variant, source in sources.items():
    (HERE / f"{variant}.swift").write_bytes(source)
assert sources["exact-original"].count(method) == 1
inserted_start = sources["exact-original"].index(start_token)
inserted_method = sources["exact-original"][inserted_start:inserted_start + len(method)]
assert inserted_method == method

output = Path(tempfile.mkdtemp(prefix="markedit-exact-method-"))
preserved = HERE / "runs" / output.name
print(f"RESULTS={output}", flush=True)
manifest = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "original_path": str(ORIGINAL),
    "original_source_sha256": digest(original_bytes),
    "original_method_lines": [380, 396],
    "extracted_method_sha256": digest(method),
    "inserted_method_sha256": digest(inserted_method),
    "byte_for_byte_equal": inserted_method == method,
    "generated_sources_sha256": {variant: digest(source) for variant, source in sources.items()},
    "compiler": subprocess.check_output(["/usr/bin/swiftc", "--version"], text=True),
    "platform": platform.platform(),
    "os_version": subprocess.check_output(["/usr/bin/sw_vers"], text=True),
    "result_path": str(output),
    "preserved_result_path": str(preserved),
    "runner_sha256": digest(Path(__file__).read_bytes()),
    "tested_branches": ["isOutdated=false", "hasBeenReverted=false", "isTerminating=false", "super.autosave", "clean and cached-modified NSDocument"],
    "untested_branches": ["isOutdated=true and actual updateContent/WebKit", "termination writeSafely branch", "recent revert", "formatting", "untitled document heading", "full MarkEdit app"],
    "adapted_dependencies": ["synchronous UTF-8 read", "UTF-8 data serialization", "isOutdated=true updateContent stub that traps if called"],
}
(HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
report = {"manifest": manifest, "cases": []}

for variant in sources:
    build = subprocess.run(["/usr/bin/swiftc", "-swift-version", "5", str(HERE / f"{variant}.swift"), "-o", str(output / variant)], capture_output=True, text=True, timeout=60)
    (output / f"{variant}.build.log").write_text(build.stdout + build.stderr)
    build.check_returncode()

cases = [(variant, state, "write", False) for variant in sources for state in ["clean", "modified"]]
cases += [(variant, "modified", "direct", False) for variant in ["exact-original", "callback-candidate"]]
cases += [(variant, "clean", "write", True) for variant in ["exact-original", "callback-candidate"]]
for variant, state, operation, lookup in cases:
    name = f"{variant}-{state}-{operation}" + ("-lookup" if lookup else "")
    case = output / name
    case.mkdir()
    command = [str(output / variant), operation, state, "lookup" if lookup else "no-lookup", str(case)]
    with (case / "stdout.log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        timed_out = False
        exit_code = None
        try:
            try:
                exit_code = child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                timed_out = True
                with (case / "sample-command.log").open("w") as sample_log:
                    sample = subprocess.run(["/usr/bin/sample", str(child.pid), "1", "-file", str(case / "process.sample.txt")], stdout=sample_log, stderr=subprocess.STDOUT, timeout=10)
                if sample.returncode:
                    raise RuntimeError(f"sample failed for {name}: {sample.returncode}")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    stdout = (case / "stdout.log").read_text()
    completed = exit_code == 0 and ("DIRECT_FINISHED" if operation == "direct" else "COORDINATOR_FINISHED nil") in stdout
    if completed:
        expected_file = (b"cached-latest\n" if state == "modified" else b"on-disk-initial\n") if operation == "direct" else b"external\n"
        assert (case / "owned.md").read_bytes() == expected_file, name
        assert "updateContentCalls=0" in stdout, name
        if lookup:
            assert "LOOKUP_RETURNED" in stdout, name
    assert "UNTESTED_UPDATE_CONTENT_CALLED" not in stdout, name
    assert "WRITE_ERROR" not in stdout and "DIRECT_ERROR" not in stdout, name
    row = {"name": name, "variant": variant, "state": state, "operation": operation, "lookup": lookup, "child_pid": child.pid, "timed_out": timed_out, "exit_code": exit_code, "completed": completed, "stdout": stdout}
    report["cases"].append(row)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(row), flush=True)

controls = [row for row in report["cases"] if row["variant"] != "exact-original" or row["operation"] == "direct"]
assert all(row["completed"] for row in controls), "Passing controls failed; inspect report."
preserved.parent.mkdir(exist_ok=True)
shutil.copytree(output, preserved)
(HERE / "latest-results.txt").write_text(str(preserved) + "\n")
print(f"PRESERVED_RESULTS={preserved}", flush=True)
print("CONTROLS_VALID; exact-method results are observations, not assumed cross-OS outcomes.", flush=True)
