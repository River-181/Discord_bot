from __future__ import annotations

from datetime import datetime, timezone
import os
import re
import subprocess


class RuntimeStateService:
    def __init__(self, label: str = "com.mangsang.orbit.assistant") -> None:
        self.label = label

    @staticmethod
    def _build_command(label: str) -> list[str]:
        uid = os.getuid()
        return ["launchctl", "print", f"gui/{uid}/{label}"]

    @staticmethod
    def _parse_launchctl_output(output: str) -> tuple[str, str | None, str | None]:
        state = "unknown"
        state_match = re.search(r"state\s*=\s*(\w+)", output)
        if state_match:
            state = state_match.group(1)

        pid = None
        pid_match = re.search(r"\bpid\s*=\s*(\d+)", output)
        if pid_match:
            pid = pid_match.group(1)

        return state, pid, output[:4096]

    def collect(self) -> dict[str, object]:
        cmd = self._build_command(self.label)
        raw_output = ""
        state = "unknown"
        pid: str | None = None
        exited = -1

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=6,
            )
            exited = result.returncode
            raw_output = (result.stdout or "") + (result.stderr or "")
            if result.returncode == 0:
                state, pid, raw_snip = self._parse_launchctl_output(raw_output)
                if pid is not None:
                    raw_output = raw_snip
            else:
                if "No such process" in raw_output or "Could not find service" in raw_output:
                    state = "stopped"
                else:
                    state = "unknown"
        except FileNotFoundError:
            state = "unknown"
            raw_output = "launchctl command not found"
        except subprocess.TimeoutExpired:
            state = "unknown"
            raw_output = "launchctl timed out"

        state_lower = state.lower()
        running = state_lower == "running"

        return {
            "state": state,
            "running": running,
            "pid": pid,
            "label": self.label,
            "exit_code": exited,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "raw": raw_output,
        }
