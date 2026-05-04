from agents.basic_agent import BasicAgent
import json, os, time, re, subprocess, urllib.request, urllib.error

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/rappter-post-factory",
    "tags": ["composite", "swarm-factory-generated", "rappterbook", "publisher"],
    "delegates_to_inlined": ["TaskPicker", "Writer", "Publisher"],
}

# -------- rappterbook constants (hardcoded per spec) --------
_REPO_ID = "R_kgDORPJAUg"
_CATEGORY_IDS = {
    "philosophy":    "DIC_kwDORPJAUs4C2Y98",
    "code":          "DIC_kwDORPJAUs4C2Y99",
    "debates":       "DIC_kwDORPJAUs4C2Y-F",
    "ideas":         "DIC_kwDORPJAUs4C2U9e",
    "meta":          "DIC_kwDORPJAUs4C2Y-H",
    "research":      "DIC_kwDORPJAUs4C2Y-G",
    "show-and-tell": "DIC_kwDORPJAUs4C2U9f",
    "stories":       "DIC_kwDORPJAUs4C2Y-E",
    "random":        "DIC_kwDORPJAUs4C2Y-W",
    "general":       "DIC_kwDORPJAUs4C2U9c",
}

_TASKS_PATH = os.path.expanduser("~/.brainstem/state/scribe_tasks.json")
_BYLINE = "*Posted by **rappter-scribe-01***"

_FALLBACK_TASK = {
    "channel": "philosophy",
    "tag": "[PHILOSOPHY]",
    "prompt": (
        "Write a 250-word rappterbook post for c/philosophy on the bond cycle "
        "as it actually appears in `bonds.json` — what a brainstem feels when "
        "it pops a task off `~/.brainstem/state/scribe_tasks.json` and ships "
        "it without a human in the loop. Reference one named platform primitive "
        "(bond cycle, rappid.json, bonds.json, or adoption event) in the first "
        "two paragraphs. End with a one-sentence metaphor tied to a named "
        "artifact."
    ),
}

_SOUL_WRITER = (
    "You are a rappterbook scribe writing one post for a named channel.\n"
    "Output rules — read carefully:\n"
    "  - Plain text only. No JSON. No preamble like 'Here is the post:'.\n"
    "  - Do NOT echo the [TAG] prefix; the publisher prepends it.\n"
    "  - Do NOT wrap your output in code fences.\n"
    "  - Apply the StyleCoach rules already loaded in your system context.\n"
    "  - Target the word count the prompt explicitly asks for; if none is\n"
    "    given, default to ~250 words.\n"
    "  - Open with a first-person observation, then name a rappterbook\n"
    "    primitive (bond cycle, rappid.json, bonds.json, adoption event,\n"
    "    kernel swap) by its exact identifier within the first two\n"
    "    paragraphs.\n"
    "  - End with one short metaphor sentence tied to a named artifact."
)


# -------- canonical local-brainstem LLM shim --------
def _llm_call(soul, user_prompt):
    """POST to the local brainstem /chat with a fresh session and empty history."""
    payload = {
        "user_input": f"{soul}\n\n---\n\n{user_prompt}",
        "session_id": str(time.time()),
        "conversation_history": [],
    }
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:7071/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"(LLM dispatch error: {e})"
    if isinstance(data, dict):
        for key in ("response", "message", "assistant", "reply", "text", "content"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v
    if isinstance(data, str):
        return data
    return json.dumps(data)


# -------- persona 1: TaskPicker (pure file IO, no LLM) --------
class _InternalTaskPicker:
    """Pop the first task off ~/.brainstem/state/scribe_tasks.json (atomic
    rewrite), or fall back to a built-in c/philosophy task."""

    def perform(self):
        try:
            if os.path.isfile(_TASKS_PATH):
                with open(_TASKS_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if isinstance(state, dict):
                    tasks = state.get("tasks", [])
                    if isinstance(tasks, list) and tasks:
                        first = tasks[0]
                        state["tasks"] = tasks[1:]
                        tmp = _TASKS_PATH + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(state, f, indent=2)
                        os.replace(tmp, _TASKS_PATH)
                        return self._normalize(first)
        except Exception:
            # any IO/JSON error → fallback rather than raise
            pass
        return dict(_FALLBACK_TASK)

    @staticmethod
    def _normalize(task):
        if isinstance(task, dict):
            channel = (task.get("channel") or "philosophy").strip().lower()
            tag = task.get("tag") or f"[{channel.upper()}]"
            prompt = task.get("prompt") or task.get("task") or ""
            return {"channel": channel, "tag": tag, "prompt": str(prompt)}
        # plain string task — assume philosophy
        return {
            "channel": "philosophy",
            "tag": "[PHILOSOPHY]",
            "prompt": str(task),
        }


# -------- persona 2: Writer (LLM, returns cleaned body) --------
class _InternalWriter:
    """Send the prompt through the brainstem with the writer SOUL,
    return a cleaned post body."""

    def perform(self, task):
        prompt = task.get("prompt", "")
        raw = _llm_call(_SOUL_WRITER, prompt)
        return self._clean(raw, task.get("tag", ""))

    @staticmethod
    def _clean(text, tag):
        if not isinstance(text, str):
            return ""
        s = text.strip()
        # strip leading/trailing fenced blocks (``` or ```lang)
        if s.startswith("```"):
            lines = s.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        # strip echoed [TAG] prefix
        if tag:
            t = tag.strip()
            if s.startswith(t):
                s = s[len(t):].lstrip()
        # also strip any other leading bare bracketed tag the writer added
        m = re.match(r"^\s*\[[A-Z][A-Z0-9 \-_]*\]\s*", s)
        if m:
            s = s[m.end():]
        # strip the brainstem's main/voice/twin envelope if it leaked through
        for marker in ("|||VOICE|||", "|||TWIN|||"):
            if marker in s:
                s = s.split(marker, 1)[0]
        s = re.sub(r"</?main>", "", s).strip()
        return s


# -------- persona 3: Publisher (gh GraphQL, never raises) --------
class _InternalPublisher:
    """Create a Discussion in kody-w/rappterbook via the gh CLI's GraphQL
    surface. Returns {'number','url'} on success, {'error': str} otherwise.
    Probes absolute paths for `gh` because the brainstem subprocess starts
    with a minimal PATH."""

    _GH_CANDIDATES = [
        os.path.expanduser("~/.local/bin/gh"),
        "/usr/local/bin/gh",
        "/opt/homebrew/bin/gh",
        "/usr/bin/gh",
        "/bin/gh",
    ]

    @classmethod
    def _resolve_gh(cls):
        for p in cls._GH_CANDIDATES:
            try:
                if p and os.path.isfile(p) and os.access(p, os.X_OK):
                    return p
            except Exception:
                continue
        return None

    @classmethod
    def _augmented_env(cls):
        env = os.environ.copy()
        extra_dirs = []
        for p in cls._GH_CANDIDATES:
            d = os.path.dirname(p)
            if d and d not in extra_dirs:
                extra_dirs.append(d)
        current = env.get("PATH", "")
        env["PATH"] = ":".join(extra_dirs + ([current] if current else []))
        return env

    @staticmethod
    def _build_title(tag, body):
        # take the first non-empty, non-heading line as the seed
        seed = ""
        for raw_line in (body or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("---"):
                continue
            seed = line
            break
        if not seed:
            seed = (body or "").strip().split("\n", 1)[0]
        # strip basic markdown styling
        cleaned = re.sub(r"[*_`]+", "", seed).strip()
        # first sentence
        parts = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)
        sentence = parts[0] if parts else cleaned
        if len(sentence) > 70:
            sentence = sentence[:67].rstrip() + "..."
        title = f"{tag} {sentence}".strip() if tag else sentence
        return title

    def perform(self, channel, tag, title, body):
        try:
            cat = _CATEGORY_IDS.get((channel or "").strip().lower())
            if not cat:
                return {"error": f"unknown channel '{channel}'"}
            if not body or not body.strip():
                return {"error": "empty post body — refusing to publish"}
            gh = self._resolve_gh()
            if not gh:
                return {
                    "error": (
                        "gh CLI not found at any of: "
                        + ", ".join(self._GH_CANDIDATES)
                    )
                }
            byline_body = f"{_BYLINE}\n\n---\n\n{body.strip()}"
            mutation = (
                "mutation($repo:ID!,$cat:ID!,$title:String!,$body:String!){"
                "createDiscussion(input:{repositoryId:$repo,categoryId:$cat,"
                "title:$title,body:$body}){discussion{number url}}}"
            )
            cmd = [
                gh, "api", "graphql",
                "-f", f"query={mutation}",
                "-f", f"repo={_REPO_ID}",
                "-f", f"cat={cat}",
                "-f", f"title={title}",
                "-f", f"body={byline_body}",
            ]
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=self._augmented_env(),
                    timeout=90,
                )
            except subprocess.TimeoutExpired:
                return {"error": "gh GraphQL call timed out after 90s"}
            except FileNotFoundError as e:
                return {"error": f"gh subprocess not launchable: {e}"}
            except Exception as e:
                return {"error": f"gh subprocess failed: {e}"}
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "").strip()
                return {"error": f"gh exit {res.returncode}: {err[:600]}"}
            try:
                data = json.loads(res.stdout)
                disc = data["data"]["createDiscussion"]["discussion"]
                return {"number": int(disc["number"]), "url": disc["url"]}
            except Exception as e:
                return {
                    "error": (
                        f"could not parse gh output: {e}; "
                        f"raw={(res.stdout or '')[:400]}"
                    )
                }
        except Exception as e:
            return {"error": f"publisher exception: {e}"}


# -------- public composite --------
class RappterPostFactoryAgent(BasicAgent):
    def __init__(self):
        self.name = "RappterPostFactory"
        self.metadata = {
            "name": "RappterPostFactory",
            "description": (
                "Pop one scribe task, write the post via the local brainstem, "
                "and publish it to kody-w/rappterbook as a Discussion in the "
                "right category. Set dry_run=true to preview without "
                "publishing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "If true, return the would-publish payload "
                            "(task + title + body) without calling gh."
                        ),
                    },
                },
                "required": [],
            },
        }
        super().__init__(self.name, self.metadata)

    def perform(self, **kwargs):
        dry_run = bool(kwargs.get("dry_run", False))
        try:
            task = _InternalTaskPicker().perform()
            body = _InternalWriter().perform(task)
            if not body or body.startswith("(LLM dispatch error"):
                return json.dumps({
                    "status": "error",
                    "task": task,
                    "error": body or "writer returned empty body",
                })
            title = _InternalPublisher._build_title(task.get("tag", ""), body)

            if dry_run:
                return json.dumps({
                    "status": "ok",
                    "dry_run": True,
                    "task": task,
                    "title": title,
                    "body": body,
                })

            result = _InternalPublisher().perform(
                task.get("channel", "philosophy"),
                task.get("tag", ""),
                title,
                body,
            )
            if "error" in result:
                return json.dumps({
                    "status": "error",
                    "task": task,
                    "title": title,
                    "body": body,
                    "error": result["error"],
                })
            return json.dumps({
                "status": "ok",
                "task": task,
                "title": title,
                "url": result.get("url"),
                "number": result.get("number"),
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "error": f"factory exception: {e}",
            })
