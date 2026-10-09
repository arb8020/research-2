# Background jobs on the Connect kernel (kernel.ts runJob installs this once per kernel, then calls start/kill).
# A job is a subprocess whose output streams to the page while the kernel stays free for other cells:
#   - it runs in its own session (process group), so interrupting a scratch cell (SIGINT to the kernel's group)
#     never reaches it, and kill() can end it with every child it started;
#   - its output goes out as iopub `stream` messages parented to the execute_request that started it (captured at
#     start), so the page routes it to the cell that pressed Run however many other cells run meanwhile;
#   - its end is one display_data with MIME application/vnd.blogs.job+json {job, exit}.
from __future__ import annotations

import codecs as _codecs
import contextlib as _contextlib
import os as _os
import signal as _signal
import subprocess as _subprocess
import sys as _sys
import threading as _threading


class _BlogsJobs:
    CHUNK = 65536
    MAX_OUTPUT_BYTES = 4 << 20  # per job; past this the rest is dropped (a runaway print loop), the job still runs

    def __init__(self) -> None:
        self.procs: dict[str, _subprocess.Popen[bytes]] = {}  # job id -> its process, while it runs

    def start(self, job_id: str, argv: list[str], cwd: str) -> None:
        assert job_id not in self.procs, f"job {job_id} is already running"
        kernel = get_ipython().kernel  # noqa: F821 (IPython global)
        parent = kernel.get_parent()  # the launching execute_request's header (ipykernel 7)
        argv = [_sys.executable if a == "@python" else a for a in argv]
        proc = _subprocess.Popen(argv, cwd=cwd, stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT, bufsize=0, start_new_session=True)

        def send(msg_type: str, content: dict[str, object]) -> None:
            kernel.session.send(kernel.iopub_socket, msg_type, content, parent=parent, ident=kernel._topic(msg_type))

        def pump() -> None:
            decoder = _codecs.getincrementaldecoder("utf-8")("replace")
            sent = 0
            while chunk := _os.read(proc.stdout.fileno(), self.CHUNK):
                if sent < self.MAX_OUTPUT_BYTES:
                    send("stream", {"name": "stdout", "text": decoder.decode(chunk)})
                    sent += len(chunk)
                    if sent >= self.MAX_OUTPUT_BYTES:
                        send("stream", {"name": "stdout", "text": f"\n[output past {self.MAX_OUTPUT_BYTES >> 20} MB dropped]\n"})
            rc = proc.wait()
            self.procs.pop(job_id, None)
            send("display_data", {"data": {"application/vnd.blogs.job+json": {"job": job_id, "exit": rc}, "text/plain": f"job {job_id} exited {rc}"},
                                  "metadata": {}, "transient": {}})

        self.procs[job_id] = proc
        _threading.Thread(target=pump, daemon=True, name=f"blogs-job-{job_id}").start()

    def kill(self, job_id: str) -> None:
        """SIGTERM to the job's whole process group. A job that already ended is not an error (it raced the click)."""
        proc = self.procs.get(job_id)
        if proc is not None:
            with _contextlib.suppress(ProcessLookupError):
                _os.killpg(proc.pid, _signal.SIGTERM)


_blogs_jobs = _BlogsJobs()
