import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_the_demo_records_every_answer_it_plays_back(tmp_path):
    out = tmp_path / "data.json"
    subprocess.run([sys.executable, str(ROOT / "demo" / "record.py"), str(out)], check=True, capture_output=True, cwd=ROOT)
    data = json.loads(out.read_text())
    for route in ("/api/state", "/api/schedule", "/api/calendar", "/api/runs", "/api/cdm", "/api/cookies", "/api/inbox", "/api/status?full=1"):
        assert route in data["routes"], route
    assert data["live"] and data["logs"]
    # every sign-in shown is on a service the demo has, so no row is invented and Retry is offered
    state = data["routes"]["/api/state"]
    assert state["authentication_setups"]
    assert all(setup["service"] in state["authentication_methods"] and not setup["backend"]
               for setup in state["authentication_setups"])
    assert "/var/" not in out.read_text() and "/tmp/" not in out.read_text()  # no path of the machine it was recorded on
    subprocess.run(["node", "--check", str(ROOT / "demo" / "demo.js")], check=True)
