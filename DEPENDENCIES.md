# Dependency and license manifest

Phase 0 requires Python 3.12 or later. The recorded verification environment used CPython 3.12.3. A fresh virtual environment is optional; the project runs with Python's standard library and needs no installed Python package, runtime or development.

| Direct dependency | Purpose | License |
|---|---|---|
| Python 3.12+ standard library | Runtime (`argparse`, `dataclasses`, `hashlib`, `json`, `os`, `pathlib`, `threading`, `typing`), tests (`copy`, `threading`, `unittest`), and mutation runner (`ast`, `json`, `os`, `pathlib`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`) | Python Software Foundation License, with component notices in the Python distribution |

Development dependencies: none. `unittest` and `venv` are part of Python's standard library. The verification environment's virtual environment contains `pip 24.0`, supplied by `venv`; the project neither imports nor invokes it. Git 2.43.0 was used for local version control only and is not a code dependency.

The Phase 0 manifest above is based on a review of its Python imports and the documented run commands. In those reference modules, no third-party Python package, ArduPilot/MAVLink component, model SDK, network service, or physical-device library is imported. The repository's original code is licensed under Apache-2.0; see `LICENSE` and `NOTICE`.

Phase 1A adds only `dataclasses`, `argparse`, `json`, `pathlib`, `copy`, `unittest`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, and `os` from the same Python standard library. It has no new runtime or development package dependency.

Phase 1A.1 adds no external dependency. Its simulated session registry, binding service, evidence generator, tests, and mutation runner use the Python standard library and existing Phase 0 code only.

Phase 1A.2 adds no external package dependency. It uses standard-library `os`, `socket`, `subprocess`, `select`, `threading`, `tempfile`, and JSON support for local process and IPC checks. The inherited `AF_UNIX` datagram socketpair and file-descriptor passing require a Unix-like OS; this run used Linux. The experiment does not call an external network service.

The full evaluation also needs permission to create local socketpairs, pass file descriptors to child processes, spawn subprocesses, and write to the system temporary directory. The observed environment was Linux with CPython 3.12.3. Git is needed to make a local clone or build the archive from an index; `evaluate.py` itself does not require Git.

## Optional external-target experiments

The reference suite and offline external evidence verification remain
standard-library-only. The HTTP and live SITL adapters require the pinned
DroneServer checkout and its locked dependencies; these are not core dependencies.
The SITL collector imports upstream MCP integration helpers, pymavlink and pytest
through that environment and launches the official ArduCopter 4.5.7 simulator.
See SITL_ASSESSMENT.md for versions, hashes and preparation. Dependency licenses
remain with their upstream distributions. No simulator binary is included here.
The DroneServer mutation fixture's upstream context is covered by the MIT notice
in external_assessment/fixtures/DRONESERVER_LICENSE.txt.
