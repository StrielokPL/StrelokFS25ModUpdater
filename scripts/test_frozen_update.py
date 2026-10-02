"""Exercise the packaged Windows helper with an actual frozen parent and restart."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

with tempfile.TemporaryDirectory(prefix="updater test ") as directory:
    root = Path(directory)
    dist = Path("packaging/dist")
    for name in ("UpdateProbe.exe", "StrelokFS25ModUpdaterHelper.exe"):
        shutil.copy2(dist / name, root / name)
    env = {**os.environ, "LOCALAPPDATA": str(root), "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    subprocess.run([str(root / "UpdateProbe.exe")], env=env, check=True, timeout=90)
    deadline = time.monotonic() + 90
    result = root / "restarted.json"
    while not result.exists() and time.monotonic() < deadline:
        time.sleep(0.25)
    if not result.exists():
        for log in root.rglob("*.log"):
            print(log.read_text(encoding="utf-8"))
        raise RuntimeError("Updated frozen application did not start")
    old = json.loads((root / "original.json").read_text())
    new = json.loads(result.read_text())
    assert old["extraction"] != new["extraction"], (old, new)
    assert (root / ".UpdateProbe.exe.previous").is_file()
    assert not (root / "staged update.exe").exists()
    # Allow onefile bootloaders to release executables before deleting the test directory.
    time.sleep(3)
    print("Frozen Windows update completed with an independent Python runtime")
