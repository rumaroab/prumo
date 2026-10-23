from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class RunnerResult:
    command: list[str]
    returncode: int
    runner: str
    external_job_id: str | None = None
    runtime_identity: str | None = None


class LocalContainerRunner:
    name = "local-docker"

    def available(self) -> tuple[bool, str]:
        if not shutil.which("docker"):
            return False, "Docker is not installed"
        try:
            checked = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                     capture_output=True, text=True, timeout=3)
        except subprocess.TimeoutExpired:
            return False, "Docker service did not respond"
        if checked.returncode:
            return False, "Docker service is not running"
        return True, f"Docker {checked.stdout.strip()} is available"

    def image_available(self, image: str) -> bool:
        try:
            return subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=3).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def run(self, image: str, workdir: Path, command: list[str], *, platform: str = "linux/amd64",
            timeout: int = 1800, cpus: int = 2, memory: str = "4g", mounts: list[tuple[Path, str]] | None = None) -> RunnerResult:
        container_name = f"forest-fire-{workdir.name}".replace("_", "-")
        invocation = ["docker", "run", "--rm", "--name", container_name, "--network", "none", "--cpus", str(cpus),
                      "--memory", memory, "--platform", platform, "-v", f"{workdir.resolve()}:/work",
                      "-w", "/work"]
        for source, target in mounts or []:
            invocation += ["-v", f"{source.resolve()}:{target}:ro"]
        invocation += [image, *command]
        identity = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                                  capture_output=True, text=True).stdout.strip() or None
        process = subprocess.Popen(invocation, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + timeout
        cancelled = False
        timed_out = False
        while process.poll() is None:
            if (workdir / "cancel.requested").exists():
                cancelled = True
                subprocess.run(["docker", "stop", "--time", "10", container_name], capture_output=True)
                break
            if time.monotonic() >= deadline:
                subprocess.run(["docker", "stop", "--time", "10", container_name], capture_output=True)
                timed_out = True
                break
            time.sleep(.5)
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", container_name], capture_output=True)
            stdout, stderr = process.communicate(timeout=5)
        (workdir / "runner.log").write_text(stdout + "\n" + stderr)
        if timed_out:
            raise TimeoutError(f"Container {container_name} exceeded {timeout} seconds; see runner.log")
        return RunnerResult(invocation, 130 if cancelled else process.returncode, self.name,
                            runtime_identity=identity)


class SshSlurmRunner:
    name = "ssh-slurm"

    def __init__(self) -> None:
        self.host = os.getenv("SLURM_HOST")
        self.base = os.getenv("SLURM_BASE_DIR")
        self.partition = os.getenv("SLURM_PARTITION", "")

    def available(self) -> tuple[bool, str]:
        if not self.host or not self.base:
            return False, "Set SLURM_HOST and SLURM_BASE_DIR"
        if not shutil.which("ssh") or not shutil.which("rsync"):
            return False, "ssh and rsync are required"
        return True, f"Configured for {self.host}"

    def run(self, workdir: Path, command: list[str], *, timeout: int = 21600,
            on_submit: Callable[[str], None] | None = None,
            on_state: Callable[[str], None] | None = None,
            existing_job_id: str | None = None) -> RunnerResult:
        available, reason = self.available()
        if not available:
            raise RuntimeError(reason)
        remote = f"{self.base.rstrip('/')}/{workdir.name}"
        checksum = subprocess.run(["ssh", self.host, "sha256sum", command[0]], capture_output=True,
                                  text=True).stdout.strip().split()
        runtime_identity = f"sha256:{checksum[0]}" if checksum else None
        job_id = existing_job_id
        if job_id is None:
            subprocess.run(["ssh", self.host, "mkdir", "-p", remote], check=True)
            subprocess.run(["rsync", "-a", f"{workdir.resolve()}/", f"{self.host}:{remote}/"], check=True)
            script = ("#!/bin/sh\n#SBATCH --output=runner.log\n#SBATCH --error=runner-error.log\n"
                      "set -eu\ncd " + _quote(remote) + "\n" +
                      " ".join(_quote(item) for item in command) + "\n")
            (workdir / "job.sh").write_text(script)
            subprocess.run(["rsync", "-a", str(workdir / "job.sh"), f"{self.host}:{remote}/job.sh"], check=True)
            submit = ["ssh", self.host, "sbatch", "--parsable"]
            if self.partition:
                submit += ["--partition", self.partition]
            submit += [f"{remote}/job.sh"]
            job_id = subprocess.run(submit, capture_output=True, text=True, check=True).stdout.strip().split(";")[0]
            if on_submit:
                on_submit(job_id)
        deadline = time.monotonic() + timeout
        last_state = None
        while time.monotonic() < deadline:
            status = subprocess.run(["ssh", self.host, "squeue", "-h", "-j", job_id, "-o", "%T"],
                                    capture_output=True, text=True)
            state = status.stdout.strip().splitlines()[0] if status.stdout.strip() else ""
            if not state:
                break
            if state != last_state and on_state:
                on_state(state)
            last_state = state
            time.sleep(5)
        else:
            subprocess.run(["ssh", self.host, "scancel", job_id], check=False)
            raise TimeoutError(f"Slurm job {job_id} exceeded {timeout} seconds")
        subprocess.run(["rsync", "-a", f"{self.host}:{remote}/", f"{workdir.resolve()}/"], check=True)
        state = subprocess.run(["ssh", self.host, "sacct", "-n", "-j", job_id, "-o", "State"],
                               capture_output=True, text=True).stdout
        return RunnerResult(command, 0 if "COMPLETED" in state else 1, self.name, job_id, runtime_identity)

    def cancel(self, job_id: str) -> None:
        if self.host:
            subprocess.run(["ssh", self.host, "scancel", job_id], check=False)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
