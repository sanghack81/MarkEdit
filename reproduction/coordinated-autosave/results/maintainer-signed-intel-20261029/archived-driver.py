"""Test the exact signed maintainer binary after the user saved and closed MarkEdit."""
import datetime
import hashlib
import json
import os
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


PREPARED_APP = '/tmp/REDACTED/markedit-maintainer-test.9g_2enyf/MarkEdit.app'
EXPECTED_BINARY_SHA256 = 'e628eb9832fde880b1747d28b26db76158e435ba51d57cba1ed5aa1a81759e0d'
ORIGINAL_BINARY_SHA256 = '801a3633ee63b0df13b243f9c717844b3a29b372f25f301a862dcbe0aa505438'
EVIDENCE_DIR = Path('/Users/REDACTED/Library/CloudStorage/Dropbox/Downloads/family_chores/markedit_hang_check/results/20261029-212600-intel-maintainer-build-6222d1')

app = Path(sys.argv[1]).resolve()
with (app / "Contents/Info.plist").open("rb") as f:
    info = plistlib.load(f)
assert info["CFBundleIdentifier"] == "app.cyan.markedit"
assert app == Path(PREPARED_APP).resolve(), "Only the prepared author build may be launched"
binary = app / "Contents/MacOS" / info["CFBundleExecutable"]
assert hashlib.sha256(binary.read_bytes()).hexdigest() == EXPECTED_BINARY_SHA256
production_binary = Path("/Applications/MarkEdit.app/Contents/MacOS/MarkEdit")
assert hashlib.sha256(production_binary.read_bytes()).hexdigest() == ORIGINAL_BINARY_SHA256
processes = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
assert not any(len(parts := line.strip().split(None, 1)) == 2 and parts[1].endswith("/Contents/MacOS/MarkEdit") for line in processes.splitlines()), "Close the existing MarkEdit before this test"
root = Path(tempfile.mkdtemp(prefix="markedit-maintainer-run-"))
print(f"RESULTS={root}", flush=True)
assets = Path('/tmp/REDACTED/markedit-maintainer-test.9g_2enyf')
for name in ["coordinate", "windows"]:
    (root / name).symlink_to(assets / name)
first = root / "existing.md"
second = root / "next.md"
first.write_text("# Existing fixture\n\nOpened before coordinated writing.\n")
second.write_text("# Next fixture\n\nOpened during coordination.\n")


def matching_pids():
    output = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
    return [int(parts[0]) for line in output.splitlines()
            if len(parts := line.strip().split(None, 1)) == 2
            and parts[1].startswith("/") and Path(parts[1]).resolve() == binary]


assert not matching_pids(), "Close the existing probe instance before starting this test."
report = {"binary_sha256": EXPECTED_BINARY_SHA256, "binary_unmodified": True, "shared_production_settings": True, "app": str(app), "bundle_id": info["CFBundleIdentifier"],
          "started_at": datetime.datetime.now().astimezone().isoformat()}
pid = None
writer = None
try:
    command = ["/usr/bin/open", "-n", "-a", str(app), str(first), "--args",
               "-ApplePersistenceIgnoreState", "YES"]
    subprocess.run(command, check=True, capture_output=True, timeout=15)
    report["launch_command"] = command
    for _ in range(24):
        pids = matching_pids()
        if pids:
            assert len(pids) == 1
            pid = pids[0]
            windows = subprocess.check_output([str(root / "windows"), str(pid)], text=True, timeout=5)
            (root / "windows-before.json").write_text(windows)
            if any(w.get("kCGWindowName") == first.name for w in json.loads(windows)):
                break
        time.sleep(0.5)
    else:
        raise RuntimeError("Probe did not show the first fixture window")
    report["pid"] = pid
    with (root / "sample-command.log").open("w") as log:
        subprocess.run(["/usr/bin/sample", str(pid), "1", "-file", str(root / "before.sample.txt")],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=10)
    with (root / "coordinator.log").open("w") as log:
        writer = subprocess.Popen([str(root / "coordinate"), str(first)], stdout=log, stderr=subprocess.STDOUT)
        report["coordinator_pid"] = writer.pid
        try:
            report["coordinator_exit_before_next_open"] = writer.wait(timeout=2)
        except subprocess.TimeoutExpired:
            report["coordinator_exit_before_next_open"] = None
        subprocess.run(["/usr/bin/open", "-a", str(app), str(second)], check=True, capture_output=True, timeout=10)
        time.sleep(1)
        with (root / "sample-command.log").open("a") as sample_log:
            subprocess.run(["/usr/bin/sample", str(pid), "5", "-file", str(root / "after.sample.txt")],
                           stdout=sample_log, stderr=subprocess.STDOUT, check=True, timeout=15)
        windows = subprocess.check_output([str(root / "windows"), str(pid)], text=True, timeout=5)
        (root / "windows-after.json").write_text(windows)
        report["next_window_present"] = any(w.get("kCGWindowName") == second.name for w in json.loads(windows))
        report["coordinator_still_pending"] = writer.poll() is None
        report["coordinator_exit"] = writer.poll()
    report["external_write_reached_disk"] = first.read_bytes() == b"# External fixture update\n\nWritten by the isolated coordinator.\n"
    report["serialization_wait_in_sample"] = "_NSDocumentSerializationSemaphore wait" in (root / "after.sample.txt").read_text()
    if report["coordinator_exit"] == 0:
        assert report["external_write_reached_disk"] and report["next_window_present"]
finally:
    if writer is not None and writer.poll() is None:
        writer.kill()
        writer.wait(timeout=5)
    if pid is not None and pid in matching_pids():
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if pid not in matching_pids():
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
    report["finished_at"] = datetime.datetime.now().astimezone().isoformat()
    report["probe_stopped"] = not matching_pids()
    report["installed_binary_unchanged"] = hashlib.sha256(production_binary.read_bytes()).hexdigest() == ORIGINAL_BINARY_SHA256
    report["runtime_signature_exit"] = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True).returncode
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    import shutil
    shutil.copytree(root, EVIDENCE_DIR / "run", symlinks=True)
    (EVIDENCE_DIR / "test-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report), flush=True)
assert report["coordinator_exit"] == 0 and report["external_write_reached_disk"] and report["next_window_present"], "The maintainer-build reproduction did not complete"
assert report["probe_stopped"] and report["installed_binary_unchanged"] and report["runtime_signature_exit"] == 0
