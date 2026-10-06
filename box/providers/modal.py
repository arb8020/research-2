"""Modal Sandbox provider — exec via SDK, not SSH.

Every sandbox's entrypoint waits on a fifo for its job (JOB_ENTRYPOINT). Exec-driven use never
spawns one, and the sandbox idles to its timeout as a default sandbox would. `spawn` writes the
job script and opens the fifo; the job then IS the sandbox's main process. Its stdout and stderr
are the sandbox's (`Sandbox.from_id(id).stdout` replays them to any process, `.logs` keeps them
after exit), its status is the sandbox's, and the sandbox ends with it.
"""

from __future__ import annotations

import queue
import shlex
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import modal

from box import gpus
from box.provider import Box, ExecResult, LogLine, Mount, Offering, Status, VolumeEntry
from observe import span

JOB_DIR = "/box"
JOB_ENTRYPOINT = ("bash", "-c", f"mkdir -p {JOB_DIR} && mkfifo {JOB_DIR}/go && read -r _ < {JOB_DIR}/go && exec bash {JOB_DIR}/job.sh")
TIMEOUT_EXIT = 124  # coreutils `timeout`
KILL_AFTER_S = 30
FIFO_WAIT_S = 60  # for the entrypoint to start and open its fifo (image pull is before create returns)
OFFERING_TAG = "box.offering"  # <gpu id>:<count>, so get() can rebuild the Offering
TAIL_LIMIT = 10_000  # lines Job.logs(follow=False) returns for a running job
LIST_LIMIT = 500  # sandboxes list() reads; far above any real number of concurrent boxes

def _resolve_image(image: str | None) -> modal.Image:
    """Resolve an image string to a modal.Image.

    - None                         → default debian_slim + torch/numpy
    - ends with 'Dockerfile'       → Image.from_dockerfile(path)
    - contains '/' or ':'          → Image.from_registry(ref)
    - otherwise                    → Image.from_name(name)  (pre-built Modal image)
    """
    if image is None:
        return modal.Image.debian_slim(python_version="3.11")
    if image.lower().endswith("dockerfile"):
        return modal.Image.from_dockerfile(image, context_dir=Path(image).parent)
    if "/" in image or ":" in image:
        return modal.Image.from_registry(image)
    return modal.Image.from_name(image)


class ModalBox:
    """A running Modal Sandbox. Exec via SDK, not SSH."""

    def __init__(
        self,
        sandbox: modal.Sandbox,
        offering: Offering,
        *,
        labels: dict[str, str] | None = None,
        resume: str | None = None,
    ):
        self._sandbox = sandbox
        self.provider_id = sandbox.object_id
        self.offering = offering
        self.labels = dict(labels or {})
        self.status = Status.RUNNING
        self.resume_script = resume

    def spawn(self, cmd: str, *, env: dict[str, str] | None = None, timeout: int | None = None) -> ModalJob:
        exports = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in (env or {}).items())
        limit = f"timeout --kill-after={KILL_AFTER_S} {timeout} " if timeout else ""
        script = f"{exports}exec {limit}bash -c {shlex.quote(cmd)}\n"
        with span("box.spawn", attributes={"provider": "modal", "sandbox_id": self.provider_id, "cmd": cmd[:200]}):
            self._sandbox.filesystem.write_text(script, f"{JOB_DIR}/job.sh")
            self._open_fifo()
        return ModalJob(self._sandbox)

    def _open_fifo(self) -> None:
        """Sandbox.create returns before the entrypoint has made the fifo, so wait for it (a plain
        write would create a regular file and the entrypoint's mkfifo would then fail). The
        entrypoint is the only reader; a second spawn finds none and the write would block, so
        the whole trigger is bounded and fails instead. A job that finishes before this exec
        returns shuts the sandbox down under it: that is a started job, not an error."""
        fifo = f"{JOB_DIR}/go"
        trigger = self._sandbox.exec(
            "timeout", str(FIFO_WAIT_S), "bash", "-c", f"until [ -p {fifo} ]; do sleep 0.1; done; echo go > {fifo}"
        )
        try:
            trigger.wait()
        except modal.exception.ConflictError:
            if self._sandbox.poll() is None:
                raise
            return
        if trigger.returncode != 0:
            raise RuntimeError(f"{self.provider_id}: no job entrypoint waiting (already spawned?)")

    def job(self) -> ModalJob:
        return ModalJob(self._sandbox)

    def wait(self, timeout: float = 900.0) -> None:
        # Modal sandboxes are ready immediately after create.
        with span("box.wait", attributes={"provider": "modal", "sandbox_id": self.provider_id}) as s:
            s.set_attr("n_polls", 0)
            if self._sandbox.poll() is not None:
                self.status = Status.TERMINATED
                raise RuntimeError(f"Sandbox {self.provider_id} already terminated")

    def exec(
        self,
        cmd: str,
        *,
        env: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run cmd under bash. stream=True tees stdout/stderr to the local terminal line by line as
        they arrive (a hang shows as silence after the last line, not silence from the start).
        timeout (seconds) kills the command; the result then has returncode != 0."""
        import sys
        import threading

        with span("box.exec", attributes={"provider": "modal", "sandbox_id": self.provider_id, "cmd": cmd[:200]}) as s:
            kwargs = {}
            if env:
                kwargs["env"] = env
            if timeout:
                kwargs["timeout"] = timeout
            p = self._sandbox.exec("bash", "-c", cmd, **kwargs)
            if stream:
                chunks: dict[str, list[str]] = {"out": [], "err": []}

                def pump(src, key, sink):
                    for line in src:
                        chunks[key].append(line)
                        sink.write(line)
                        sink.flush()

                t_err = threading.Thread(target=pump, args=(p.stderr, "err", sys.stderr), daemon=True)
                t_err.start()
                pump(p.stdout, "out", sys.stdout)
                t_err.join()
                stdout, stderr = "".join(chunks["out"]), "".join(chunks["err"])
            else:
                stdout = p.stdout.read()
                stderr = p.stderr.read()
            p.wait()
            # Modal reports -1 (or None) for a command it killed on timeout. Normalise to 124,
            # coreutils `timeout`'s convention, so a timeout is always a nonzero failure.
            timed_out = p.returncode is None or p.returncode == -1
            rc = 124 if timed_out else p.returncode
            s.set_attrs(
                returncode=rc,
                timed_out=timed_out,
                stdout_bytes=len(stdout),
                stderr_bytes=len(stderr),
            )
            return ExecResult(stdout=stdout, stderr=stderr, returncode=rc)

    def upload(self, local: str, remote: str) -> None:
        """Upload a local file via the sandbox filesystem API (no size limit from argv)."""
        from pathlib import Path

        r = self.exec(f"mkdir -p \"$(dirname '{remote}')\"")
        if r.returncode != 0:
            raise RuntimeError(f"upload: mkdir for {remote} failed: {r.stderr}")
        self._sandbox.filesystem.write_bytes(Path(local).read_bytes(), remote)

    def download(self, remote: str, local: str) -> None:
        from pathlib import Path

        data = self._sandbox.filesystem.read_bytes(remote)
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(data)

    def terminate(self) -> None:
        with span("box.terminate", attributes={"provider": "modal", "sandbox_id": self.provider_id}):
            self._sandbox.terminate()
            self.status = Status.TERMINATED


class ModalJob:
    """The sandbox's main process (see the module docstring)."""

    def __init__(self, sandbox: modal.Sandbox) -> None:
        self._sandbox = sandbox

    def logs(self, *, follow: bool) -> Iterator[LogLine]:
        if follow or self._sandbox.poll() is not None:
            return _replay(self._sandbox)
        return (
            LogLine("stderr" if e.source == "stderr" else "stdout", e.message)
            for e in self._sandbox.logs.tail(TAIL_LIMIT)
            if e.source != "system"
        )

    def poll(self) -> int | None:
        return self._sandbox.poll()

    def wait(self) -> int:
        self._sandbox.wait(raise_on_termination=False)
        rc = self._sandbox.returncode
        assert rc is not None, f"{self._sandbox.object_id}: waited, but no exit status"
        return rc

    def kill(self) -> None:
        self._sandbox.terminate(wait=True)


def _replay(sandbox: modal.Sandbox) -> Iterator[LogLine]:
    """Both streams from their first line to EOF, interleaved as they arrive. The queue is
    bounded: a slow reader backpressures the pumps instead of buffering without limit."""
    lines: queue.Queue[LogLine | None] = queue.Queue(maxsize=1000)

    def pump(src: IO[str], stream: str) -> None:
        for text in src:
            lines.put(LogLine(stream, text))  # type: ignore[arg-type]
        lines.put(None)

    for src, name in ((sandbox.stdout, "stdout"), (sandbox.stderr, "stderr")):
        threading.Thread(target=pump, args=(src, name), daemon=True).start()
    open_streams = 2
    while open_streams:
        line = lines.get()
        if line is None:
            open_streams -= 1
        else:
            yield line


class ModalVolume:
    def __init__(self, name: str) -> None:
        self.name = name
        self._vol = modal.Volume.from_name(name)

    def ls(self, path: str, *, recursive: bool = False) -> list[VolumeEntry]:
        return [
            VolumeEntry(e.path, float(e.mtime), e.type == modal.volume.FileEntryType.DIRECTORY)
            for e in self._vol.listdir(path, recursive=recursive)
        ]

    def read(self, path: str) -> bytes:
        try:
            return b"".join(self._vol.read_file(path))
        except modal.exception.NotFoundError as exc:
            raise FileNotFoundError(f"{self.name}:{path}") from exc

    def rm(self, path: str) -> None:
        self._vol.remove_file(path, recursive=True)


class Modal:
    """Modal provider. launch() returns a ModalBox."""

    name = "modal"

    def __init__(self, *, profile: str = "default"):
        self._app = modal.App.lookup("box", create_if_missing=True)

    @property
    def app_id(self) -> str:
        return self._app.app_id

    def search(
        self,
        *,
        gpu_model: str | None = None,
        gpu_count: int = 1,
    ) -> list[Offering]:
        """GPU types box knows Modal rents (box/gpus.py), priced from gpus.json. gpu_model is a
        canonical name or a Modal id, any case; unknown gives []. Modal has no availability API:
        you request and it either works or errors."""
        with span("box.search", attributes={"provider": "modal", "gpu_model": gpu_model, "gpu_count": gpu_count}) as s:
            prices = gpus.prices()["modal"]
            offerings = [
                Offering(
                    provider=self.name,
                    id=g.modal,
                    gpu_model=g.name,
                    gpu_count=gpu_count,
                    gpu_memory_gb=g.vram_gb,
                    price_hr=prices[g.name] * gpu_count if g.name in prices else None,
                )
                for g in gpus.GPUS
                if g.modal and (gpu_model is None or gpu_model.lower() in (g.name.lower(), g.modal.lower()))
            ]
            s.set_attr("n_results", len(offerings))
            return offerings

    def build_image(
        self,
        image: str | modal.Image | None = None,
        *,
        add_python: str | None = None,
        mounts: dict[str, str | Mount] | None = None,
        pip: list[str] | None = None,
        pyproject: str | None = None,
        apt: list[str] | None = None,
    ) -> modal.Image:
        """Build an image from a spec. Each layer is optional; all are cached by content.

        Level 1 primitive — call this directly when you need to debug image builds
        or compose layers manually. launch() calls it internally.

        Args:
            image:      base — Dockerfile path, OCI ref, Modal name, modal.Image, or None.
            add_python: inject a managed Python into the base (e.g. "3.11").
                        Use with from_registry CUDA images that lack Python.
            mounts:     {remote_path: local_dir | Mount} — code, added at sandbox start.
            pip:        Python packages to install (e.g. ["torch>=2.4", "numpy"]).
            pyproject:  path to a pyproject.toml — deps read from it (single source of truth).
            apt:        System packages to install (e.g. ["git", "curl"]).
        """
        with span("box.build_image", attributes={"provider": "modal"}) as s:
            if isinstance(image, modal.Image):
                img = image
            elif image and ("/" in image or ":" in image) and not image.lower().endswith("dockerfile"):
                # OCI registry ref with optional add_python
                kwargs = {}
                if add_python:
                    kwargs["add_python"] = add_python
                img = modal.Image.from_registry(image, **kwargs)
            else:
                img = _resolve_image(image)

            if apt:
                img = img.apt_install(*apt)

            if pyproject:
                img = img.pip_install_from_pyproject(pyproject)
            if pip:
                img = img.pip_install(*pip)

            for remote_path, source in (mounts or {}).items():
                mount = source if isinstance(source, Mount) else Mount(source)
                img = img.add_local_dir(mount.local, remote_path=remote_path, ignore=list(mount.ignore))

            s.set_attr("layers", f"apt={bool(apt)} pip={bool(pip)} pyproject={bool(pyproject)} mounts={bool(mounts)}")
            return img

    def create(
        self,
        offering: Offering,
        image: modal.Image,
        *,
        volumes: dict[str, str] | None = None,
        timeout: int = 3600,
        labels: dict[str, str] | None = None,
    ) -> ModalBox:
        """Create a sandbox from a built image. No setup script — just the sandbox, its
        entrypoint waiting for a job (module docstring). labels become Modal sandbox tags.

        Level 1 primitive — call this directly when you need control over the
        create step, or to separate image build from sandbox creation.
        """
        with span("box.create", attributes={
            "provider": "modal",
            "gpu_model": offering.gpu_model,
            "gpu_count": offering.gpu_count,
        }) as s:
            gpu_spec = offering.id
            if offering.gpu_count > 1:
                gpu_spec = f"{offering.id}:{offering.gpu_count}"

            modal_volumes = {}
            if volumes:
                for vol_name, mount_path in volumes.items():
                    modal_volumes[mount_path] = modal.Volume.from_name(
                        vol_name, create_if_missing=True
                    )

            try:
                tags = {**(labels or {}), OFFERING_TAG: f"{offering.id}:{offering.gpu_count}"}
                sandbox = modal.Sandbox.create(
                    *JOB_ENTRYPOINT,
                    app=self._app,
                    image=image,
                    gpu=gpu_spec,
                    timeout=timeout,
                    tags=tags,
                    **({"volumes": modal_volumes} if modal_volumes else {}),
                )
            except modal.exception.RemoteError as e:
                msg = str(e)
                if "Image build" in msg and "failed" in msg:
                    # Modal doesn't surface Dockerfile build logs through the SDK.
                    # Escalate with actionable guidance.
                    raise RuntimeError(
                        f"Image build failed (Modal does not expose build logs via SDK).\n"
                        f"  Original: {msg}\n"
                        f"  To debug: use build_image() to build a base, then run the "
                        f"failing step inside a sandbox via box.exec() to see the error.\n"
                        f"  Example:\n"
                        f"    img = provider.build_image('Dockerfile-base-only')\n"
                        f"    box = provider.create(offering, img)\n"
                        f"    box.exec('the-command-that-fails')"
                    ) from e
                raise
            s.set_attr("sandbox_id", sandbox.object_id)
            return ModalBox(sandbox=sandbox, offering=offering, labels=labels)

    def launch(
        self,
        offering: Offering,
        *,
        image: str | modal.Image | None = None,
        add_python: str | None = None,
        mounts: dict[str, str | Mount] | None = None,
        volumes: dict[str, str] | None = None,
        pip: list[str] | None = None,
        pyproject: str | None = None,
        apt: list[str] | None = None,
        setup: str | None = None,
        resume: str | None = None,
        timeout: int = 3600,
        labels: dict[str, str] | None = None,
        **kwargs,
    ) -> ModalBox:
        """Launch a Modal sandbox. Convenience over build_image() + create().

        Three layers, plus optional lifecycle scripts:

        1. image  — the environment (Dockerfile, OCI ref, modal.Image, or None).
                     Cached by content. Changes rarely.
        2. mounts — code. {remote_path: local_dir}. Baked into the image.
        3. volumes — data. {volume_name: mount_path}. Persistent across launches.
        4. pip    — Python packages to install in the image.
        5. apt    — System packages to install in the image.

        6. setup  — shell script path (inside the sandbox). Runs once after 1-5
                     are assembled, before returning the box.
        7. resume — shell script path. Stored on the box for the caller to exec on
                     subsequent wakes.
        """
        with span("box.launch", attributes={
            "provider": "modal",
            "gpu_model": offering.gpu_model,
            "gpu_count": offering.gpu_count,
        }):
            img = self.build_image(image, add_python=add_python, mounts=mounts, pip=pip, pyproject=pyproject, apt=apt)
            box = self.create(offering, img, volumes=volumes, timeout=timeout, labels=labels)
            box.resume_script = resume

            if setup:
                result = box.exec(f"bash {setup}")
                if result.returncode != 0:
                    box.terminate()
                    raise RuntimeError(
                        f"Setup script failed (exit {result.returncode}):\n"
                        f"{result.stderr}\n{result.stdout}"
                    )

            return box

    def list(self) -> list[Box]:
        boxes = []
        for n, sandbox in enumerate(modal.Sandbox.list(app_id=self.app_id)):
            assert n < LIST_LIMIT, f"more than {LIST_LIMIT} running sandboxes under app box"
            tags = sandbox.get_tags()
            if OFFERING_TAG in tags:
                boxes.append(self._reattach(sandbox, tags))
        return boxes

    def get(self, box_id: str) -> ModalBox:
        try:
            sandbox = modal.Sandbox.from_id(box_id)
        except (modal.exception.NotFoundError, modal.exception.InvalidError) as exc:
            raise LookupError(f"no Modal sandbox {box_id}: {exc}") from exc
        tags = sandbox.get_tags()
        if OFFERING_TAG not in tags:
            raise LookupError(f"{box_id} was not launched by box (no {OFFERING_TAG} tag)")
        return self._reattach(sandbox, tags)

    def _reattach(self, sandbox: modal.Sandbox, tags: dict[str, str]) -> ModalBox:
        gpu, _, count = tags[OFFERING_TAG].rpartition(":")
        (offering,) = [o for o in self.search(gpu_count=int(count)) if o.id == gpu]
        labels = {k: v for k, v in tags.items() if k != OFFERING_TAG}
        box = ModalBox(sandbox, offering, labels=labels)
        box.status = Status.RUNNING if sandbox.poll() is None else Status.TERMINATED
        return box

    def volumes(self) -> list[tuple[str, float]]:
        found = []
        for vol in modal.Volume.objects.list():
            info = vol.info()
            assert info.name is not None, f"listed volume {vol.object_id} has no name"
            found.append((info.name, info.created_at.timestamp()))
        return found

    def volume(self, name: str) -> ModalVolume:
        return ModalVolume(name)

    def delete_volume(self, name: str) -> None:
        modal.Volume.objects.delete(name)
