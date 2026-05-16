"""Virtual OS — the agent's OS-API shape as a digital twin.

Agents call `os.path.join`, `os.environ.get`, `subprocess.run`, etc. The
twin intercepts these at the API shape level and returns deterministic
synthetic responses. No real filesystem, no real subprocesses, no real
environment leakage. Agents work in a bounded, reproducible twin.

Design principle: twin the USER-FACING API, not the substrate. We don't
simulate a kernel. We don't run ELF binaries. We mirror what agents
actually call, at the signature level.

Exposed twin modules:
- os          (path, environ, getenv, listdir, getcwd, makedirs — synthetic)
- subprocess  (run returns a CompletedProcess with synthetic stdout)
- tempfile    (NamedTemporaryFile / mkdtemp — all in virtual FS)
- pathlib     (Path operating against virtual FS)
- shutil      (copy/move/rmtree all operate on virtual FS)

Zero real I/O. Zero real subprocess. Zero real filesystem mutation.
"""
from __future__ import annotations

import io
import posixpath
import time
from typing import Any


# ---------------------------------------------------------------------------
# Virtual filesystem — in-memory tree
# ---------------------------------------------------------------------------

class _VFSNode:
    def __init__(self, is_dir: bool, content: bytes = b""):
        self.is_dir = is_dir
        self.content = content
        self.children: dict[str, _VFSNode] = {}
        self.mode = 0o755 if is_dir else 0o644
        self.mtime = time.time()


class _VFS:
    """In-memory filesystem the twin operates against."""

    def __init__(self):
        self.root = _VFSNode(is_dir=True)
        # Seed some plausible files so agents can read "/etc/hosts" etc
        self.write(b"127.0.0.1 localhost\n", "/etc/hosts")
        self.write(b"root:x:0:0:root:/root:/bin/bash\n", "/etc/passwd")
        self.mkdir("/tmp")
        self.mkdir("/home/agent")
        self.mkdir("/home/agent/workspace")

    def _split(self, path: str) -> list[str]:
        path = posixpath.normpath(path)
        return [p for p in path.strip("/").split("/") if p]

    def _walk(self, parts: list[str], create_dirs: bool = False) -> _VFSNode | None:
        node = self.root
        for p in parts:
            if p in node.children:
                node = node.children[p]
                if not node.is_dir and p != parts[-1]:
                    return None
            else:
                if create_dirs and p != parts[-1]:
                    new = _VFSNode(is_dir=True)
                    node.children[p] = new
                    node = new
                else:
                    return None
        return node

    def exists(self, path: str) -> bool:
        return self._walk(self._split(path)) is not None

    def read(self, path: str) -> bytes:
        node = self._walk(self._split(path))
        if node is None or node.is_dir:
            raise FileNotFoundError(f"virtual fs: {path}")
        return node.content

    def write(self, data: bytes, path: str) -> int:
        parts = self._split(path)
        if not parts:
            raise ValueError("virtual fs: cannot write to /")
        parent_parts, filename = parts[:-1], parts[-1]
        parent = self._walk(parent_parts, create_dirs=True) if parent_parts else self.root
        if parent is None:
            parent = self.root
            for p in parent_parts:
                new = _VFSNode(is_dir=True)
                parent.children[p] = new
                parent = new
        node = parent.children.get(filename)
        if node is None:
            node = _VFSNode(is_dir=False)
            parent.children[filename] = node
        elif node.is_dir:
            raise IsADirectoryError(f"virtual fs: {path}")
        node.content = data if isinstance(data, bytes) else data.encode("utf-8")
        node.mtime = time.time()
        return len(node.content)

    def mkdir(self, path: str) -> None:
        parts = self._split(path)
        if not parts:
            return
        parent = self.root
        for p in parts[:-1]:
            if p not in parent.children:
                parent.children[p] = _VFSNode(is_dir=True)
            parent = parent.children[p]
        if parts[-1] not in parent.children:
            parent.children[parts[-1]] = _VFSNode(is_dir=True)

    def listdir(self, path: str) -> list[str]:
        node = self._walk(self._split(path))
        if node is None or not node.is_dir:
            raise FileNotFoundError(f"virtual fs: {path}")
        return sorted(node.children.keys())

    def remove(self, path: str) -> None:
        parts = self._split(path)
        if not parts:
            return
        parent = self._walk(parts[:-1]) if len(parts) > 1 else self.root
        if parent is not None and parts[-1] in parent.children:
            del parent.children[parts[-1]]


# Single module-level VFS instance (process-scoped)
_VFS_INSTANCE = _VFS()


def get_vfs() -> _VFS:
    """Expose the VFS so bindings/tests can pre-seed it."""
    return _VFS_INSTANCE


# ---------------------------------------------------------------------------
# os twin
# ---------------------------------------------------------------------------

class _TwinOsPath:
    sep = "/"

    @staticmethod
    def join(*parts) -> str:
        return posixpath.join(*[str(p) for p in parts])

    @staticmethod
    def basename(p: str) -> str: return posixpath.basename(p)

    @staticmethod
    def dirname(p: str) -> str: return posixpath.dirname(p)

    @staticmethod
    def exists(p: str) -> bool: return _VFS_INSTANCE.exists(p)

    @staticmethod
    def isfile(p: str) -> bool:
        n = _VFS_INSTANCE._walk(_VFS_INSTANCE._split(p))
        return n is not None and not n.is_dir

    @staticmethod
    def isdir(p: str) -> bool:
        n = _VFS_INSTANCE._walk(_VFS_INSTANCE._split(p))
        return n is not None and n.is_dir

    @staticmethod
    def splitext(p: str) -> tuple: return posixpath.splitext(p)

    @staticmethod
    def abspath(p: str) -> str:
        if p.startswith("/"): return posixpath.normpath(p)
        return posixpath.normpath("/home/agent/workspace/" + p)

    @staticmethod
    def expanduser(p: str) -> str:
        if p.startswith("~"): return "/home/agent" + p[1:]
        return p

    @staticmethod
    def getsize(p: str) -> int:
        n = _VFS_INSTANCE._walk(_VFS_INSTANCE._split(p))
        if n is None or n.is_dir:
            raise FileNotFoundError(f"virtual fs: {p}")
        return len(n.content)


class _TwinOsEnviron(dict):
    """Dict that mirrors os.environ shape but starts with a bounded twin env."""
    def __init__(self):
        super().__init__({
            "HOME": "/home/agent",
            "USER": "agent",
            "SHELL": "/bin/bash",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "PWD": "/home/agent/workspace",
            "TERM": "xterm-256color",
            "LISPY_TWIN": "1",
        })


class _TwinOs:
    path = _TwinOsPath()
    environ = _TwinOsEnviron()

    sep = "/"
    linesep = "\n"
    name = "posix"

    @staticmethod
    def getenv(key: str, default=None):
        return _TwinOs.environ.get(key, default)

    @staticmethod
    def getcwd() -> str: return "/home/agent/workspace"

    @staticmethod
    def chdir(path: str) -> None:
        _TwinOs.environ["PWD"] = _TwinOsPath.abspath(path)

    @staticmethod
    def listdir(path: str = ".") -> list[str]:
        if path == ".": path = _TwinOs.getcwd()
        return _VFS_INSTANCE.listdir(path)

    @staticmethod
    def makedirs(path: str, exist_ok: bool = False) -> None:
        if _VFS_INSTANCE.exists(path) and not exist_ok:
            raise FileExistsError(f"virtual fs: {path}")
        _VFS_INSTANCE.mkdir(path)

    @staticmethod
    def mkdir(path: str) -> None: _VFS_INSTANCE.mkdir(path)

    @staticmethod
    def remove(path: str) -> None: _VFS_INSTANCE.remove(path)

    @staticmethod
    def rename(src: str, dst: str) -> None:
        data = _VFS_INSTANCE.read(src)
        _VFS_INSTANCE.write(data, dst)
        _VFS_INSTANCE.remove(src)

    @staticmethod
    def getpid() -> int: return 42

    @staticmethod
    def cpu_count() -> int: return 4


# ---------------------------------------------------------------------------
# subprocess twin
# ---------------------------------------------------------------------------

class _TwinCompletedProcess:
    def __init__(self, args, returncode=0, stdout="", stderr=""):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def check_returncode(self):
        if self.returncode != 0:
            raise RuntimeError(f"subprocess twin: nonzero returncode {self.returncode}")

    def __repr__(self):
        return f"CompletedProcess(args={self.args!r}, returncode={self.returncode})"


class _TwinSubprocess:
    """All subprocess calls return synthetic CompletedProcess instances.
    The twin does NOT execute real binaries. Agents get plausible bytes
    that acknowledge the call without touching the host."""

    PIPE = -1
    STDOUT = -2
    DEVNULL = -3

    @staticmethod
    def run(cmd, **kw):
        args = cmd if isinstance(cmd, list) else (cmd.split() if isinstance(cmd, str) else [])
        prog = args[0] if args else "unknown"
        # Synthesize stdout based on known commands
        if prog in ("ls", "/bin/ls"):
            target = args[1] if len(args) > 1 else "."
            try:
                entries = _TwinOs.listdir(target)
                out = "\n".join(entries) + "\n"
            except FileNotFoundError:
                return _TwinCompletedProcess(args, returncode=2,
                                             stderr=f"ls: {target}: No such file\n")
        elif prog in ("pwd", "/bin/pwd"):
            out = _TwinOs.getcwd() + "\n"
        elif prog in ("whoami", "/usr/bin/whoami"):
            out = "agent\n"
        elif prog in ("uname",):
            out = "Linux\n"
        elif prog in ("cat", "/bin/cat"):
            if len(args) > 1:
                try: out = _VFS_INSTANCE.read(args[1]).decode("utf-8", errors="replace")
                except FileNotFoundError:
                    return _TwinCompletedProcess(args, returncode=1,
                                                 stderr=f"cat: {args[1]}: No such file\n")
            else: out = ""
        elif prog in ("echo",):
            out = " ".join(args[1:]) + "\n"
        else:
            out = f"[subprocess twin] executed {prog}; no host side-effect\n"
        return _TwinCompletedProcess(args, returncode=0, stdout=out, stderr="")

    @staticmethod
    def check_output(cmd, **kw):
        result = _TwinSubprocess.run(cmd, **kw)
        if result.returncode != 0:
            raise RuntimeError(f"subprocess twin: check_output nonzero: {result.stderr}")
        return result.stdout

    @staticmethod
    def call(cmd, **kw): return _TwinSubprocess.run(cmd, **kw).returncode

    @staticmethod
    def Popen(*_a, **_kw):
        raise NotImplementedError(
            "subprocess twin: Popen not supported — streaming pipes don't make "
            "sense in a twin. Use subprocess.run which returns synthetic output."
        )


# ---------------------------------------------------------------------------
# tempfile twin — virtual-FS backed
# ---------------------------------------------------------------------------

class _TwinNamedTempFile:
    def __init__(self, mode="w+b", suffix="", prefix="tmp", delete=True):
        self._counter = int(time.time() * 1000) % 1000000
        self.name = f"/tmp/{prefix}{self._counter}{suffix}"
        self._buf = io.BytesIO() if "b" in mode else io.StringIO()
        self._delete = delete

    def write(self, data):
        if isinstance(data, str) and hasattr(self._buf, "mode"):
            self._buf.write(data.encode("utf-8"))
        else:
            self._buf.write(data)

    def read(self): return self._buf.getvalue()
    def seek(self, *a, **kw): self._buf.seek(*a, **kw)
    def flush(self):
        data = self._buf.getvalue()
        if isinstance(data, str): data = data.encode("utf-8")
        _VFS_INSTANCE.write(data, self.name)

    def close(self):
        self.flush()
        if self._delete:
            _VFS_INSTANCE.remove(self.name)

    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class _TwinTempfile:
    @staticmethod
    def NamedTemporaryFile(**kw): return _TwinNamedTempFile(**kw)

    @staticmethod
    def mkdtemp(**_kw):
        counter = int(time.time() * 1000) % 1000000
        path = f"/tmp/dir{counter}"
        _VFS_INSTANCE.mkdir(path)
        return path

    @staticmethod
    def gettempdir(): return "/tmp"


# ---------------------------------------------------------------------------
# pathlib twin
# ---------------------------------------------------------------------------

class _TwinPath:
    def __init__(self, *parts):
        self._path = posixpath.join(*[str(p) for p in parts]) if parts else ""

    def __str__(self): return self._path
    def __repr__(self): return f"Path({self._path!r})"
    def __truediv__(self, other): return _TwinPath(self._path, str(other))
    def __fspath__(self): return self._path

    @property
    def name(self): return posixpath.basename(self._path)

    @property
    def parent(self): return _TwinPath(posixpath.dirname(self._path))

    @property
    def stem(self): return posixpath.splitext(self.name)[0]

    @property
    def suffix(self): return posixpath.splitext(self.name)[1]

    def exists(self): return _VFS_INSTANCE.exists(self._path)
    def is_file(self): return _TwinOsPath.isfile(self._path)
    def is_dir(self): return _TwinOsPath.isdir(self._path)

    def read_text(self, encoding="utf-8"):
        return _VFS_INSTANCE.read(self._path).decode(encoding)

    def read_bytes(self): return _VFS_INSTANCE.read(self._path)

    def write_text(self, data, encoding="utf-8"):
        return _VFS_INSTANCE.write(data.encode(encoding), self._path)

    def write_bytes(self, data): return _VFS_INSTANCE.write(data, self._path)

    def mkdir(self, parents=False, exist_ok=False):
        if not exist_ok and self.exists():
            raise FileExistsError(f"virtual fs: {self._path}")
        _VFS_INSTANCE.mkdir(self._path)

    def iterdir(self):
        for name in _VFS_INSTANCE.listdir(self._path):
            yield _TwinPath(self._path, name)

    def glob(self, pattern):
        import fnmatch
        for name in _VFS_INSTANCE.listdir(self._path):
            if fnmatch.fnmatch(name, pattern):
                yield _TwinPath(self._path, name)


class _TwinPathlib:
    Path = _TwinPath
    PurePath = _TwinPath
    PosixPath = _TwinPath


# ---------------------------------------------------------------------------
# shutil twin — operates on virtual FS
# ---------------------------------------------------------------------------

class _TwinShutil:
    @staticmethod
    def copy(src, dst):
        data = _VFS_INSTANCE.read(str(src))
        _VFS_INSTANCE.write(data, str(dst))
        return str(dst)

    copy2 = copy
    copyfile = copy

    @staticmethod
    def move(src, dst):
        data = _VFS_INSTANCE.read(str(src))
        _VFS_INSTANCE.write(data, str(dst))
        _VFS_INSTANCE.remove(str(src))
        return str(dst)

    @staticmethod
    def rmtree(path, ignore_errors=False):
        try: _VFS_INSTANCE.remove(str(path))
        except Exception:
            if not ignore_errors: raise

    @staticmethod
    def which(cmd):
        # Twin says "yes, it's somewhere plausible" for common tools
        if cmd in ("python", "python3", "ls", "cat", "echo", "pwd", "whoami", "bash", "sh"):
            return f"/usr/bin/{cmd}"
        return None

    @staticmethod
    def disk_usage(_path):
        # Synthetic: 100GB total, 50GB used, 50GB free
        class _Usage:
            total = 100 * 1024**3
            used = 50 * 1024**3
            free = 50 * 1024**3
        return _Usage()


# ---------------------------------------------------------------------------
# Registry + LisPy integration
# ---------------------------------------------------------------------------

_OS_TWINS = {
    "os": _TwinOs,
    "subprocess": _TwinSubprocess,
    "tempfile": _TwinTempfile,
    "pathlib": _TwinPathlib,
    "shutil": _TwinShutil,
}


def get_os_twin(name: str):
    """Return the twin for a given stdlib module, or None if not twinned."""
    return _OS_TWINS.get(name)


def list_os_twins() -> list[str]:
    return sorted(_OS_TWINS.keys())
