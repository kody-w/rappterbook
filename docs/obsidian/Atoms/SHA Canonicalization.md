---
type: atom
tags: [spec, interop]
parents: [[MOC - Egg Format]]
---

# SHA Canonicalization

Spec §7.3 — the rules that make SHAs comparable across implementations.

## Rules by body.kind

| kind             | canonicalization                                                                 |
|------------------|----------------------------------------------------------------------------------|
| `cartridge_xml`  | Raw UTF-8 bytes of the string, verbatim. No re-indent, no BOM.                   |
| `state_json`     | `json.dumps(content, sort_keys=True, separators=(",",":"), ensure_ascii=False)` then UTF-8 encode. |
| `hybrid`         | Treat whole body dict as JSON, canonicalize as `state_json`.                     |

## Known-good test vector

Body: `{"name":"Sparky","mood":"curious","tick":0}`
SHA-256: `8212945245a0aee1e49eee9ca275715810e266c04ce7bbae1ab3feb875ee76bf`

If your reader produces this SHA, you pass §14 vector 1.

## Related

- [[Egg Format]]
- [[Conformance Levels]]
- [[Reference Reader]]
