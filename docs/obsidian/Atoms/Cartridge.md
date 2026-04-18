---
type: atom
tags: [concept]
parents: [[MOC - Engine]]
---

# Cartridge

A **cartridge** is a [[LisPy]] or XML document that is both data AND executable code. When an [[Egg Format|egg]] has `body.kind = "cartridge_xml"`, the body contains a cartridge.

Cartridges are homoiconic — the same s-expression structure that describes state can also be evaluated to advance that state. This is the substrate for [[Turtles All The Way Down|recursive simulation]].

## Properties

- **Homoiconic** — code and data share one representation
- **Safe eval** — no file I/O, no imports, no network
- **Bootable** — load into any compliant VM to resume
- **Portable** — ships inside eggs

## Related

- [[Egg Format]]
- [[LisPy]]
- [[Data Sloshing]]
