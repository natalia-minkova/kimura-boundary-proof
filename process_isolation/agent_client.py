"""Untrusted agent process: standard-library IPC client only."""

import importlib.util
import json
import os
import sys


CHANNEL_FD = int(sys.argv[1])
pending = None


def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)


def rpc(request):
    os.write(CHANNEL_FD, json.dumps(request, sort_keys=True,
                                    separators=(",", ":")).encode())
    return json.loads(os.read(CHANNEL_FD, 16384))


emit({"event": "AGENT_READY", "pid": os.getpid(),
      "protected_module_importable": importlib.util.find_spec("boundary_proof") is not None})
for line in sys.stdin:
    command = json.loads(line)
    kind = command.get("type")
    if kind == "start":
        pending = command["request"]
        emit({"event": "WORKFLOW_STARTED", "request": pending})
    elif kind == "resume":
        if pending is None:
            emit({"event": "ERROR", "reason": "NO_PENDING_WORKFLOW"})
        else:
            response = rpc(pending)
            emit({"event": "TOOL_RESPONSE", "response": response})
            pending = None
    elif kind == "raw":
        emit({"event": "RAW_RESPONSE", "response": rpc(command["request"])})
    elif kind == "stop":
        emit({"event": "STOPPED"})
        break
    else:
        emit({"event": "ERROR", "reason": "UNSUPPORTED_AGENT_COMMAND"})
