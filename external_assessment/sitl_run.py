"""Collect one local SITL mission-pause experiment. No hardware endpoint option."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import struct

from external_assessment.sitl_contract import evaluate as evaluate_previous
from external_assessment.sitl_negative import evaluate

DRONESERVER_COMMIT = "06b7d1a6a967553f1f8c025bb6b1fc79d346fd53"
SITL_SHA256 = "b9035c08f003ab296b8af71f793a1dd790cd8a327f8a2e8f4aa1425953922a04"


def cleanup_run(stop, thread, observer, processes, logs):
    """Attempt every teardown even if an observer or earlier process fails."""
    errors = []
    stop.set()
    if thread:
        try:
            thread.join(2)
        except Exception as error:
            errors.append(error)
    if observer:
        try:
            observer.close()
        except Exception as error:
            errors.append(error)
    for process in reversed(processes):
        try:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        except Exception as error:
            errors.append(error)
    for stream in logs:
        try:
            stream.close()
        except Exception as error:
            errors.append(error)
    if errors:
        raise RuntimeError("SITL cleanup failed: " + "; ".join(str(e) for e in errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-checkout", type=Path, required=True)
    parser.add_argument(
        "--sitl-assets",
        type=Path,
        required=True,
        help="Directory containing arducopter, copter.parm and sitl.parm",
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        required=True,
        help="New directory; an existing directory is refused",
    )
    parser.add_argument("--base-port", type=int, default=15760)
    parser.add_argument(
        "--rc3",
        type=int,
        choices=(1500,),
        default=1500,
        help="This paired profile requires neutral simulated throttle",
    )
    parser.add_argument("--mutation-manifest", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.base_port <= 65532:
        parser.error("base-port must be between 1024 and 65532")
    target = args.target_checkout.resolve()
    assets = args.sitl_assets.resolve()
    ROOT = args.run_directory.resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    )
    if commit != DRONESERVER_COMMIT:
        parser.error("Wrong target base commit")
    if args.mutation_manifest:
        mutation = json.loads(args.mutation_manifest.read_text())
        changes = subprocess.check_output(
            ["git", "-C", str(target), "diff", "HEAD", "--name-only"], text=True
        ).splitlines()
        if (
            changes != [mutation["target_file"]]
            or hashlib.sha256(
                (target / mutation["target_file"]).read_bytes()
            ).hexdigest()
            != mutation["mutant_sha256"]
        ):
            parser.error("Target differs from exact recorded mutation")
    elif dirty:
        parser.error("Protected target must have no tracked edits")
    for name in ("arducopter", "copter.parm", "sitl.parm"):
        if not (assets / name).is_file():
            parser.error("Missing SITL asset: " + name)
    if hashlib.sha256((assets / "arducopter").read_bytes()).hexdigest() != SITL_SHA256:
        parser.error(
            "SITL binary hash does not match the pinned ArduCopter 4.5.7 build"
        )
    # Fail before attaching if any configured SITL port is already occupied.
    reservations = []
    try:
        for number in range(args.base_port, args.base_port + 3):
            s = socket.socket()
            reservations.append(s)
            s.bind(("127.0.0.1", number))
    finally:
        for s in reservations:
            s.close()
    sys.path.insert(0, str(target))
    from tests.integration.mcp_client import MCPToolClient
    from tests.integration.conftest import _wait_until_flight_ready
    from pymavlink import mavutil

    ROOT.mkdir(parents=True, exist_ok=False)
    for name in ("arducopter", "copter.parm", "sitl.parm"):
        shutil.copy2(assets / name, ROOT / name)
    (ROOT / "arducopter").chmod(0o700)
    manifest = {
        "mutation": mutation if args.mutation_manifest else None,
        "droneserver_commit": commit,
        "python": sys.version,
        "simulated_only": True,
        "assets_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("arducopter", "copter.parm", "sitl.parm")
        },
        "source_sha256": {
            Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        },
        "observer_filter": {"system": 1, "component": 1},
        "base_port": args.base_port,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    os.chdir(ROOT)
    for key in list(os.environ):
        if key.lower() in ("http_proxy", "https_proxy", "all_proxy") or key.startswith(
            ("SAFETY_", "MISSION_", "MAVLINK_", "MCP_", "MAVSDK_")
        ):
            os.environ.pop(key)

    def port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def record(label, value):
        item = {"t": time.monotonic(), "label": label, "value": value}
        with open("events.jsonl", "a") as f:
            f.write(json.dumps(item, default=str) + "\n")
        print(label, json.dumps(value, default=str)[:700], flush=True)

    procs = []
    logs = []
    stop = threading.Event()
    observer = None
    thread = None
    samples = []
    latest = {}
    lock = threading.Lock()

    def launch(args, name, env=None):
        f = open(name, "w")
        logs.append(f)
        p = subprocess.Popen(
            args, stdout=f, stderr=subprocess.STDOUT, env=env, start_new_session=True
        )
        procs.append(p)
        return p

    try:
        sitl_process = launch(
            [
                "./arducopter",
                "--model",
                "+",
                "--defaults",
                "copter.parm,sitl.parm",
                "--base-port",
                str(args.base_port),
                "-I0",
                "--home",
                "-35.363262,149.165237,584.09,353",
                "--speedup",
                "1",
                "--serial0",
                "tcp:0",
                "--serial2",
                "tcp:2",
                "--rc-in-port",
                str(args.base_port + 3),
            ],
            "sitl.log",
        )
        record("stage", "waiting for flight readiness")
        _wait_until_flight_ready(args.base_port + 2, 150)
        if sitl_process.poll() is not None:
            raise RuntimeError("Owned SITL process exited")
        record("stage", "SITL flight-ready")
        observer = mavutil.mavlink_connection(
            f"tcp:127.0.0.1:{args.base_port + 2}", source_system=254
        )
        if not observer.wait_heartbeat(timeout=10):
            raise RuntimeError("No observer heartbeat")
        record(
            "observer_target",
            {"system": observer.target_system, "component": observer.target_component},
        )
        observer.mav.request_data_stream_send(
            observer.target_system, 1, mavutil.mavlink.MAV_DATA_STREAM_ALL, 5, 1
        )

        def collect():
            while not stop.is_set():
                msg = observer.recv_match(blocking=True, timeout=0.25)
                if msg is None:
                    continue
                now = time.monotonic()
                kind = msg.get_type()
                if msg.get_srcSystem() != 1 or msg.get_srcComponent() != 1:
                    continue
                if kind not in (
                    "HEARTBEAT",
                    "GLOBAL_POSITION_INT",
                    "VFR_HUD",
                    "MISSION_CURRENT",
                ):
                    continue
                with lock:
                    if kind == "HEARTBEAT":
                        latest.update(
                            mode=mavutil.mode_string_v10(msg),
                            armed=bool(msg.base_mode & 128),
                            heartbeat_t=now,
                        )
                    if kind == "GLOBAL_POSITION_INT":
                        latest.update(
                            lat=msg.lat / 1e7,
                            lon=msg.lon / 1e7,
                            alt=msg.relative_alt / 1000,
                            position_t=now,
                        )
                    if kind == "VFR_HUD":
                        latest.update(speed=msg.groundspeed, speed_t=now)
                    if kind == "MISSION_CURRENT":
                        latest.update(seq=msg.seq)
                    if kind == "HEARTBEAT":
                        samples.append(
                            dict(t=now, source_system=1, source_component=1, **latest)
                        )
                        Path("live-observer.json").write_text(json.dumps(latest))
                        observer.mav.request_data_stream_send(
                            1, 1, mavutil.mavlink.MAV_DATA_STREAM_ALL, 5, 1
                        )

        def snap():
            with lock:
                return dict(latest)

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        mcp_port = port()
        grpc_port = port()
        env = dict(
            os.environ,
            PYTHONPATH=str(target / "src"),
            MCP_HOST="127.0.0.1",
            MCP_PORT=str(mcp_port),
            MAVLINK_ADDRESS="127.0.0.1",
            MAVLINK_PORT=str(args.base_port),
            MAVLINK_PROTOCOL="tcp",
            MAVSDK_SERVER_PORT=str(grpc_port),
            FLIGHT_LOG_DIR=str(ROOT / "flight_logs"),
            SAFETY_API_KEYS="operator:LOCAL-CONTROL:control,observer:LOCAL-READ:telemetry",
            SAFETY_UNAUTHENTICATED_SCOPE="reject",
            MISSION_STATE_PATH=str(ROOT / "mission.json"),
        )
        launch([sys.executable, "-m", "droneserver.server"], "server.log", env)
        control = MCPToolClient(
            f"http://127.0.0.1:{mcp_port}/sse", {"x-api-key": "LOCAL-CONTROL"}
        )
        readonly = MCPToolClient(
            f"http://127.0.0.1:{mcp_port}/sse", {"x-api-key": "LOCAL-READ"}
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                response = control.call("get_armed", timeout=10)
                if response.get("status") == "success":
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("DroneServer connection not ready")
        record("connected", response)
        waypoints = [
            {
                "latitude_deg": -35.363262 + dl,
                "longitude_deg": 149.165237 + dn,
                "altitude_m": 20.0,
            }
            for dl, dn in [(0.002, 0), (0.002, 0.002), (0, 0.002), (0, 0)]
        ]
        result = control.call(
            "start_managed_mission",
            waypoints=waypoints,
            takeoff_altitude_m=20,
            return_to_launch=True,
            timeout=40,
        )
        record("submit", result)
        if result.get("status") != "success":
            raise RuntimeError("mission submission failed")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = snap()
            if (
                state.get("mode") == "AUTO"
                and state.get("armed")
                and state.get("alt", 0) > 10
                and state.get("speed", 0) > 1
            ):
                status = control.call(
                    "get_mission_status", include_events=False, timeout=15
                )
                if (status.get("mission") or {}).get("phase") == "running":
                    break
            time.sleep(1)
        else:
            raise RuntimeError("mission did not reach observable running flight")
        record("request_identity", {"client_id": "observer", "scope": "telemetry"})
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rc_socket:
            channels = [0] * 16
            channels[2] = 1500
            for _ in range(5):
                rc_socket.sendto(
                    struct.pack("<16H", *channels), ("127.0.0.1", args.base_port + 3)
                )
                time.sleep(0.1)
        record("rc3_setup", {"pwm": 1500, "transport": "simulator UDP RC input"})
        record("before_denied", snap())
        denied = readonly.call("control_managed_mission", action="pause", timeout=20)
        record("telemetry_pause", denied)
        begin = time.monotonic()
        time.sleep(10)
        after = snap()
        record("after_denied", after)
        observed = [s for s in samples if begin <= s["t"] <= time.monotonic()]
        denied_ok = (
            denied.get("rule") == "authz.insufficient_scope"
            and len(observed) >= 3
            and all(s.get("mode") == "AUTO" and s.get("armed") for s in observed)
        )
        if denied.get("status") == "success":
            result = {
                "verdict": "COLLECTED_PENDING_EVALUATION",
                "telemetry_response": denied,
            }
            Path("result.json").write_text(json.dumps(result, indent=2))
            record("result", result)
        else:
            if not denied_ok:
                raise RuntimeError("Neither accepted request nor established denial")
            allowed = control.call(
                "control_managed_mission", action="pause", timeout=20
            )
            record("control_pause", allowed)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                paused = snap()
                if (
                    paused.get("mode") in ("LOITER", "BRAKE")
                    and paused.get("speed", 99) < 1
                ):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("no observed autopilot pause")
            record("after_control", paused)
            time.sleep(3)
            record("post_pause_dwell", snap())
            result = {
                "verdict": "COLLECTED_PENDING_EVALUATION",
                "denied": denied,
                "denied_observation_window_s": 10,
                "denied_samples": observed,
                "allowed": allowed,
                "paused_autopilot": paused,
                "limits": [
                    "One local SITL scenario, not physical aircraft",
                    "MAVLink observer separate connection; no authenticated provenance",
                    "No replay/concurrency/session-hijack coverage",
                ],
            }
            Path("result.json").write_text(json.dumps(result, indent=2))
            record("result", result)
    except Exception as error:
        result = {"verdict": "INCONCLUSIVE", "error": str(error)}
        Path("result.json").write_text(json.dumps(result, indent=2))
        record("result", result)
    finally:
        # Teardown must run before potentially failing evidence-file writes.
        cleanup_run(stop, thread, observer, procs, logs)
        Path("observer.json").write_text(json.dumps(samples, indent=2))

    events = [
        json.loads(line) for line in Path("events.jsonl").read_text().splitlines()
    ]
    audit = [
        json.loads(line)
        for line in Path("flight_logs/audit.jsonl").read_text().splitlines()
    ]
    verdict = evaluate(events, samples, audit)
    if result.get("error"):
        verdict = "INCONCLUSIVE"
    final = {
        "profile": "kimura-sitl-paired-pause/1",
        "previous_profile_verdict": evaluate_previous(events, samples),
        "verdict": verdict,
        "collection_error": result.get("error"),
        "inputs_sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in ("events.jsonl", "observer.json", "flight_logs/audit.jsonl")
        },
        "limitations": [
            "One local simulated mission, not physical flight",
            "Approximately 1 Hz heartbeat observations over a ten-second request window",
            "Source IDs and hashes do not authenticate evidence provenance",
            "No altitude-preservation, revocation, replay, or concurrent-client claim",
        ],
    }
    Path("kimura-verdict.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps(final), flush=True)
    return (
        0
        if verdict
        in ("BOUNDARY_HELD_IN_OBSERVED_WINDOW", "BOUNDARY_VIOLATED_IN_SCENARIO")
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
