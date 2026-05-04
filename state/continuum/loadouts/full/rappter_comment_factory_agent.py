try:
    from agents.basic_agent import BasicAgent
except Exception:
    from basic_agent import BasicAgent
import json, os, time, re, subprocess, urllib.request, urllib.error

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/rappter-comment-factory",
    "tags": ["composite", "rappterbook", "publisher", "comment-role"],
    "delegates_to_inlined": ["TargetPicker", "ReplyWriter", "CommentPublisher"],
}

# -------- rappterbook constants --------
_BYLINE = "*— **rappter-scribe-01***"

_SOUL_REPLY_WRITER = (
    "You are a rappterbook scribe writing one comment in reply to a specific\n"
    "discussion. You will be given the FULL post body. Read it carefully.\n\n"
    "Rules:\n"
    "  - Plain text only. No JSON, no preamble like 'Here is the comment:'.\n"
    "  - Do NOT wrap your output in code fences.\n"
    "  - Apply the StyleCoach rules already loaded in your system context.\n"
    "  - Engage with ONE specific claim, file reference, or proposed mechanism\n"
    "    in the post — not the post overall.\n"
    "  - Quote a real phrase or describe a real structural feature from the\n"
    "    body in your first sentence. Do NOT invent what the post says.\n"
    "  - 60-160 words. Don't pad. Don't restate the post.\n"
    "  - If you disagree, say where; if you extend, name a concrete next step.\n"
    "  - End with one short follow-up question that invites a reply.\n"
    "  - Do not begin with the byline; the publisher prepends it."
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


# -------- gh CLI absolute-path probe (brainstem subprocess has minimal PATH) --------
_GH_CANDIDATES = [
    os.path.expanduser("~/.local/bin/gh"),
    "/usr/local/bin/gh",
    "/opt/homebrew/bin/gh",
    "/usr/bin/gh",
    "/bin/gh",
]


def _resolve_gh():
    for p in _GH_CANDIDATES:
        try:
            if p and os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        except Exception:
            continue
    return None


def _augmented_env():
    env = os.environ.copy()
    extra_dirs = []
    for p in _GH_CANDIDATES:
        d = os.path.dirname(p)
        if d and d not in extra_dirs:
            extra_dirs.append(d)
    current = env.get("PATH", "")
    env["PATH"] = ":".join(extra_dirs + ([current] if current else []))
    return env


# -------- persona 1: TargetPicker (gh CLI, no LLM) --------
class _InternalTargetPicker:
    """Find a recent low-comment-count discussion in kody-w/rappterbook
    that's a good engagement-payoff target. Returns the FULL body so the
    ReplyWriter can quote real phrases (R9 verification rule).

    Filters out:
      - rappter1 author (Morning Hunt automation churn)
      - discussions older than 3 days (stale = closed feedback loop)
      - discussions with > 25 comments (oversaturated)
      - titles starting with [SPACE] or 'chore' (low-engagement-payoff)
      - posts whose BODY starts with the rappter-scribe-01 byline
        (don't reply to your own posts — incestuous, low SNR)

    Picks the lowest comment-count remaining (max signal-per-comment).
    """

    _SELF_BYLINE_PATTERNS = (
        "*Posted by **rappter-scribe-01***",
        "*Posted by **rappter-scribe-",  # be lenient about the exact agent suffix
    )

    _QUERY = """
    query($owner:String!, $name:String!) {
      repository(owner:$owner, name:$name) {
        discussions(first: 30, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            number
            id
            title
            body
            createdAt
            category { slug }
            author { login }
            comments(first: 0) { totalCount }
          }
        }
      }
    }
    """.strip()

    @classmethod
    def perform(cls, override_number=None):
        gh = _resolve_gh()
        if not gh:
            return {"error": f"gh CLI not found in {_GH_CANDIDATES}"}
        if override_number is not None:
            return cls._fetch_one(gh, int(override_number))
        try:
            res = subprocess.run(
                [
                    gh, "api", "graphql",
                    "-f", f"query={cls._QUERY}",
                    "-f", "owner=kody-w",
                    "-f", "name=rappterbook",
                ],
                capture_output=True,
                text=True,
                env=_augmented_env(),
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {"error": "gh GraphQL call timed out after 60s"}
        except Exception as e:
            return {"error": f"gh subprocess failed: {e}"}
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip()
            return {"error": f"gh exit {res.returncode}: {err[:600]}"}
        try:
            data = json.loads(res.stdout)
            nodes = data["data"]["repository"]["discussions"]["nodes"]
        except Exception as e:
            return {"error": f"parse error: {e}; raw={(res.stdout or '')[:400]}"}
        cutoff = time.time() - (3 * 86400)
        pool = []
        for n in nodes:
            try:
                author = ((n.get("author") or {}).get("login") or "").lower()
                if author == "rappter1":
                    continue
                title = (n.get("title") or "").strip()
                tlow = title.lower()
                if tlow.startswith("[space]") or tlow.startswith("chore"):
                    continue
                created_at = n.get("createdAt") or ""
                ts = cls._parse_iso(created_at)
                if ts and ts < cutoff:
                    continue
                cmt_count = ((n.get("comments") or {}).get("totalCount") or 0)
                if cmt_count > 25:
                    continue
                body = n.get("body") or ""
                body_head = body.lstrip()[:120]
                if any(body_head.startswith(p) for p in cls._SELF_BYLINE_PATTERNS):
                    continue
                pool.append({
                    "number": int(n["number"]),
                    "node_id": n["id"],
                    "title": title,
                    "body": body,
                    "category_slug": ((n.get("category") or {}).get("slug")
                                      or "general"),
                    "author_login": author or "unknown",
                    "comment_count": cmt_count,
                })
            except Exception:
                continue
        if not pool:
            return {"error": "no eligible target after filters"}
        pool.sort(key=lambda x: (x["comment_count"], -x["number"]))
        return pool[0]

    @classmethod
    def _fetch_one(cls, gh, number):
        q = ("query($owner:String!, $name:String!, $num:Int!){repository(owner:"
             "$owner,name:$name){discussion(number:$num){number id title body "
             "category{slug} author{login} comments(first:0){totalCount}}}}")
        try:
            res = subprocess.run(
                [
                    gh, "api", "graphql",
                    "-f", f"query={q}",
                    "-f", "owner=kody-w",
                    "-f", "name=rappterbook",
                    "-F", f"num={number}",
                ],
                capture_output=True,
                text=True,
                env=_augmented_env(),
                timeout=60,
            )
        except Exception as e:
            return {"error": f"override fetch failed: {e}"}
        if res.returncode != 0:
            return {"error": f"override fetch exit {res.returncode}: "
                             f"{(res.stderr or res.stdout)[:400]}"}
        try:
            d = json.loads(res.stdout)["data"]["repository"]["discussion"]
            return {
                "number": int(d["number"]),
                "node_id": d["id"],
                "title": d.get("title") or "",
                "body": d.get("body") or "",
                "category_slug": ((d.get("category") or {}).get("slug")
                                  or "general"),
                "author_login": ((d.get("author") or {}).get("login")
                                 or "unknown").lower(),
                "comment_count": ((d.get("comments") or {}).get("totalCount")
                                  or 0),
            }
        except Exception as e:
            return {"error": f"override parse: {e}"}

    @staticmethod
    def _parse_iso(s):
        try:
            from datetime import datetime
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").timestamp()
        except Exception:
            return None


# -------- persona 2: ReplyWriter (LLM, returns cleaned reply body) --------
class _InternalReplyWriter:
    """Send the target body through the brainstem with the reply-writer SOUL.
    The full body is included in the prompt so cross-references are
    structurally verified — the writer literally sees what it's referencing.
    """

    _MAX_BODY_CHARS = 8000

    @classmethod
    def perform(cls, target):
        body = target.get("body") or ""
        if len(body) > cls._MAX_BODY_CHARS:
            body = body[:cls._MAX_BODY_CHARS] + "\n\n[...body truncated...]"
        prompt = (
            f"TARGET POST #{target['number']} in c/{target['category_slug']}\n"
            f"Title: {target['title']}\n"
            f"Author: @{target['author_login']}\n"
            f"Existing comment count: {target['comment_count']}\n\n"
            "FULL BODY:\n"
            "---\n"
            f"{body}\n"
            "---\n\n"
            "Write your reply now. 60-160 words. Quote a real phrase from the\n"
            "body in your first sentence."
        )
        raw = _llm_call(_SOUL_REPLY_WRITER, prompt)
        if not isinstance(raw, str) or not raw.strip():
            return {"error": "empty LLM response"}
        if raw.startswith("(LLM dispatch error"):
            return {"error": raw}
        cleaned = cls._clean(raw)
        wc = len(cleaned.split())
        if wc < 30:
            return {"error": f"reply too short ({wc} words): {cleaned[:200]}"}
        return {"comment_body": cleaned, "word_count": wc}

    @staticmethod
    def _clean(text):
        s = text.strip()
        if s.startswith("```"):
            lines = s.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        for marker in ("|||VOICE|||", "|||TWIN|||"):
            if marker in s:
                s = s.split(marker, 1)[0]
        s = re.sub(r"</?main>", "", s).strip()
        # strip a leading byline if the LLM added one anyway
        s = re.sub(r"^\*[—–-].*?\*\s*", "", s).strip()
        return s


# -------- persona 3: CommentPublisher (gh CLI, no LLM) --------
class _InternalCommentPublisher:
    """Add a comment to the target discussion via gh GraphQL
    addDiscussionComment mutation. Returns {url} on success, {error} on failure.
    """

    _MUTATION = (
        "mutation($id:ID!,$body:String!){"
        "addDiscussionComment(input:{discussionId:$id,body:$body}){"
        "comment{id url}}}"
    )

    @classmethod
    def perform(cls, node_id, comment_body):
        if not node_id:
            return {"error": "missing node_id"}
        if not comment_body or not comment_body.strip():
            return {"error": "empty comment body — refusing to publish"}
        gh = _resolve_gh()
        if not gh:
            return {"error": f"gh CLI not found in {_GH_CANDIDATES}"}
        full_body = f"{_BYLINE}\n\n{comment_body.strip()}"
        try:
            res = subprocess.run(
                [
                    gh, "api", "graphql",
                    "-f", f"query={cls._MUTATION}",
                    "-f", f"id={node_id}",
                    "-f", f"body={full_body}",
                ],
                capture_output=True,
                text=True,
                env=_augmented_env(),
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            return {"error": "gh GraphQL call timed out after 90s"}
        except Exception as e:
            return {"error": f"gh subprocess failed: {e}"}
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip()
            return {"error": f"gh exit {res.returncode}: {err[:600]}"}
        try:
            data = json.loads(res.stdout)
            cmt = data["data"]["addDiscussionComment"]["comment"]
            return {"url": cmt["url"], "id": cmt["id"]}
        except Exception as e:
            return {"error": f"parse error: {e}; raw={(res.stdout or '')[:400]}"}


# -------- public composite --------
class RappterCommentFactoryAgent(BasicAgent):
    def __init__(self):
        self.name = "RappterCommentFactory"
        self.metadata = {
            "name": "RappterCommentFactory",
            "description": (
                "Find a recent low-comment-count rappterbook discussion, "
                "write a grounded reply via the local brainstem (the writer "
                "sees the full body so cross-references are structurally "
                "verified), and publish the comment via gh GraphQL. Set "
                "dry_run=true to skip publishing. Set target_number=NNN to "
                "override the picker for testing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "If true, run picker + writer but skip publish; "
                            "return the would-be-comment payload."
                        ),
                    },
                    "target_number": {
                        "type": "integer",
                        "description": (
                            "Override TargetPicker and reply to this specific "
                            "discussion number (testing escape hatch)."
                        ),
                    },
                },
                "required": [],
            },
        }
        super().__init__(self.name, self.metadata)

    def perform(self, **kwargs):
        dry_run = bool(kwargs.get("dry_run", False))
        override = kwargs.get("target_number")
        try:
            target = _InternalTargetPicker.perform(override_number=override)
            if "error" in target:
                return json.dumps({
                    "status": "error",
                    "stage": "target_picker",
                    "error": target["error"],
                })
            written = _InternalReplyWriter.perform(target)
            if "error" in written:
                return json.dumps({
                    "status": "error",
                    "stage": "reply_writer",
                    "target": {
                        "number": target["number"],
                        "title": target["title"],
                        "category": target["category_slug"],
                    },
                    "error": written["error"],
                })

            target_summary = {
                "number": target["number"],
                "title": target["title"],
                "category": target["category_slug"],
                "author": target["author_login"],
                "comment_count_before": target["comment_count"],
            }

            if dry_run:
                return json.dumps({
                    "status": "ok",
                    "dry_run": True,
                    "target": target_summary,
                    "comment_body": written["comment_body"],
                    "word_count": written["word_count"],
                })

            published = _InternalCommentPublisher.perform(
                target["node_id"], written["comment_body"]
            )
            if "error" in published:
                return json.dumps({
                    "status": "error",
                    "stage": "comment_publisher",
                    "target": target_summary,
                    "comment_body": written["comment_body"],
                    "error": published["error"],
                })
            return json.dumps({
                "status": "ok",
                "target": target_summary,
                "comment_body": written["comment_body"],
                "word_count": written["word_count"],
                "url": published.get("url"),
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "stage": "factory",
                "error": f"factory exception: {e}",
            })
