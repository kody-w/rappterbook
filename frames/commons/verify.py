#!/usr/bin/env python3
"""verify.py — walk the commons chain and prove it, stdlib only.

    python3 frames/commons/verify.py            # verifies frames/commons/chain.jsonl
    python3 frames/commons/verify.py path.jsonl # any chain in this format

Rules (as minted by scripts/commons_frame.py): payload_hash = sha256("rapp/1:particle" + 0x1f + JCS(payload));
frame_hash = sha256("rapp/1:wave" + 0x1f + JCS(frame minus frame_hash/sig)); seq strictly +1;
prev == predecessor's payload_hash (genesis prev is null). Exit 0 only when every frame holds.
"""
import hashlib, json, sys, os

def jcs(v): return json.dumps(v, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
def h(space, v): return hashlib.sha256((space + "\x1f" + jcs(v)).encode()).hexdigest()

def main(path):
    frames = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    prev, problems = None, []
    for f in frames:
        seq = f.get("seq")
        if h("rapp/1:particle", f["payload"]) != f["payload_hash"]:
            problems.append(f"seq {seq}: payload_hash mismatch")
        pre = {k: f[k] for k in f if k not in ("frame_hash", "sig")}
        if h("rapp/1:wave", pre) != f["frame_hash"]:
            problems.append(f"seq {seq}: frame_hash mismatch")
        if prev is None:
            if f.get("prev") is not None: problems.append(f"seq {seq}: genesis prev must be null")
        else:
            if f.get("prev") != prev["payload_hash"]: problems.append(f"seq {seq}: prev != predecessor payload_hash")
            if seq != prev["seq"] + 1: problems.append(f"seq {seq}: seq not +1")
            if f["utc"] < prev["utc"]: problems.append(f"seq {seq}: utc went backwards")
        prev = f
    if problems:
        print("FAIL:", *problems, sep="\n  "); return 1
    print(f"OK: {len(frames)} frames, chain verified, head {prev['frame_hash'][:16]}…" if prev else "OK: empty chain")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "chain.jsonl")))
