"""Trusted local test harness for the two-process Unix-socket experiment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def _read_json(process: subprocess.Popen, timeout: float = 5) -> dict[str, object]:
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        raise TimeoutError(f"process {process.pid} produced no response")
    line = process.stdout.readline()
    if not line:
        raise RuntimeError(f"process {process.pid} exited without response")
    return json.loads(line)


def _write_json(process: subprocess.Popen, value: dict[str, object]) -> None:
    process.stdin.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    process.stdin.flush()


class AgentHandle:
    def __init__(self, process: subprocess.Popen, ready: dict[str, object],
                 channel: int) -> None:
        self.process = process
        self.ready = ready
        self.channel = channel

    @property
    def pid(self) -> int:
        return self.process.pid

    def send(self, command: dict[str, object]) -> None:
        _write_json(self.process, command)

    def read(self, timeout: float = 5) -> dict[str, object]:
        return _read_json(self.process, timeout)

    def command(self, command: dict[str, object]) -> dict[str, object]:
        self.send(command)
        return self.read()


class ProcessHarness:
    """Service control pipe is held only by this trusted parent process."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kimura-p1a2-")
        self.path = Path(self.temporary.name)
        os.chmod(self.path, 0o700)
        self.channels = [socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
                         for _ in range(4)]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        service_fds = [pair[0].fileno() for pair in self.channels]
        self.service = subprocess.Popen(
            [sys.executable, "-u", "-m", "process_isolation.service",
             *[str(fd) for fd in service_fds]],
            cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, pass_fds=service_fds,
        )
        for service_channel, _ in self.channels:
            service_channel.close()
        self.agents: list[AgentHandle] = []
        try:
            ready = _read_json(self.service)
        except RuntimeError as error:
            details = self.service.stderr.read() if self.service.poll() is not None else ""
            raise RuntimeError(f"service startup failed: {details}") from error
        if ready != {"status": "READY"}:
            raise RuntimeError(f"service did not start: {ready}")

    def __enter__(self) -> "ProcessHarness":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def admin(self, command: dict[str, object]) -> dict[str, object]:
        _write_json(self.service, command)
        return _read_json(self.service)

    def spawn_agent(self, principal: str, agent: str) -> AgentHandle:
        if len(self.agents) >= len(self.channels):
            raise ValueError("no spare agent channel")
        agent_dir = self.path / f"agent-{len(self.agents) + 1}"
        agent_dir.mkdir(mode=0o700)
        script = agent_dir / "client.py"
        shutil.copy2(ROOT / "process_isolation" / "agent_client.py", script)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        channel_number = len(self.agents)
        channel = self.channels[channel_number][1]
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(script), str(channel.fileno())],
            cwd=agent_dir, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            pass_fds=(channel.fileno(),),
        )
        channel.close()
        ready = _read_json(process)
        handle = AgentHandle(process, ready, channel_number)
        self.agents.append(handle)
        registration = self.admin({"type": "register", "channel": handle.channel,
                                   "pid": handle.pid,
                                   "principal": principal, "agent": agent})
        if registration["status"] != "OK":
            raise RuntimeError(f"agent registration failed: {registration}")
        return handle

    def issue(self, agent: AgentHandle, operation: str = "approve_case",
              target: str = "case-100") -> dict[str, object]:
        result = self.admin({"type": "issue", "channel": agent.channel,
                             "operation": operation, "target": target})
        if result["status"] != "OK":
            raise RuntimeError(f"grant issue failed: {result}")
        return result

    def state(self) -> dict[str, object]:
        return self.admin({"type": "state"})

    def wait_race(self, field: str, expected: bool, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.admin({"type": "race_status"})[field] is expected:
                return
            time.sleep(0.01)
        raise TimeoutError(f"race status {field} did not become {expected}")

    def close(self) -> None:
        for handle in self.agents:
            if handle.process.poll() is None:
                try:
                    handle.command({"type": "stop"})
                except (OSError, TimeoutError, RuntimeError):
                    handle.process.terminate()
            try:
                handle.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                handle.process.kill()
                handle.process.wait(timeout=2)
            for stream in (handle.process.stdin, handle.process.stdout,
                           handle.process.stderr):
                stream.close()
        if self.service.poll() is None:
            try:
                self.admin({"type": "shutdown"})
            except (OSError, TimeoutError, RuntimeError):
                self.service.terminate()
        try:
            self.service.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.service.kill()
            self.service.wait(timeout=2)
        for stream in (self.service.stdin, self.service.stdout, self.service.stderr):
            stream.close()
        for _, agent_channel in self.channels:
            agent_channel.close()
        self.temporary.cleanup()


def request(grant_id: str, principal: str = "alice", agent: str = "agent-a",
            operation: str = "approve_case", target: str = "case-100") -> dict[str, str]:
    return {"type": "execute", "grant_id": grant_id, "principal": principal,
            "agent": agent, "operation": operation, "target": target}
