<!-- research-kit-kind thesis: 2026-11-13a -->
# Kind: thesis

A thesis is the paper kind plus assembly from earlier projects. Read
`pm/kinds/paper.md` too (add the paper kind if it is not active): its literature
pipeline (P5), writing stages (P6), citation and reference-manager rules apply
unchanged and are not repeated here. The manuscript lives in
`paper/manuscript/`; the thesis uses the same folders. Stage folders are
`pm/stages/NN-thesis-<topic>/`; in light mode the table is a checklist only.
Evidence tags are CONFIRMED / LIKELY / GUESS.

## Stage table

At most one open thesis stage at a time. Stages 3-4 repeat per chapter.
Writing and literature stages from the paper kind slot in between as needed.

| # | Stage | Driver | Deliverable | Done when |
|---|-------|--------|-------------|-----------|
| 1 | scope and chapter map | lead + user | `thesis-map.md`: question, chapters, source project per chapter, rules the institution sets | user approves the map; every chapter names its source or "new" |
| 2 | source inventory | analyst | one row per source project: stage notes, "Load-bearing numbers", "Do not quote", open handoffs, evidence status | every chapter's sources are listed with their pinned commit or hash |
| 3 | import a chapter | writer | chapter draft whose claims each cite a source stage note, tags carried over | no claim is untagged; no quoted item sits on a source "Do not quote" list |
| 4 | reconcile | analyst + critic | list of conflicts (units, conventions, notation, library versions, numbers) and one decision per conflict | each conflict has a decision entry (`rk add decision ...`) and every chapter follows it |
| 5 | connect (introduction, discussion, conclusion) | writer | framing chapters tied to the chapter map | each thesis claim in the conclusion points to a chapter claim with the same tag |
| 6 | review | critics | review files under the stage `notes/` | every finding is fixed, parked as a deferred entry (`rk add deferred ...`), or rejected with a reason |
| 7 | close | lead | stage README, frozen manuscript copy with sha256 | user says "close stage"; the core close checklist is done |

## Rules

### Assembling from earlier projects

1. Cite the source project's stage note (project, stage, file) for every imported claim, not only the paper. Why: the note holds the evidence and the caveats.
2. Carry evidence tags across unchanged; a claim never gets stronger by moving into a thesis. Why: the thesis chapter has not seen the data again.
3. Never quote an item on a source project's "Do not quote" list; copy those entries into this repo's `pm/README.md` "Do not quote" instead. Why: a refutation must travel with the claim it refutes.
4. Re-derive a load-bearing number from its source run, or tag it LIKELY with the source cited. Why: a copied number has lost its provenance.
5. Pin each source by commit or sha256 in the inventory, and read it from a frozen copy. Why: source repos keep changing and the thesis must stay reproducible.
6. Treat published papers by the same author as sources, not as truth: reuse text only with the cite and the publisher's reuse terms checked. Why: self-plagiarism and copyright rules still apply.
7. When two sources disagree, record both values and the decision as a decision entry (`rk add decision ...`); never average silently. Why: the committee will ask which one is right.
8. Decide units, conventions and notation once for the whole thesis, label every chapter with them, never convert quietly. Why: chapters from different projects used different ones.
9. Rebuild every figure from its source data and script, and name script and commit in the caption note. Why: pasted figures cannot be checked.

### Working discipline

10. Do not edit a source repo from the thesis repo; copy what you need into a frozen import folder and cite it. Why: sources stay as published.
11. Mark text not yet checked against its source as GUESS until a critic confirms it. Why: assembled prose reads fluent and confirmed whether or not it is.
12. Keep the institution's formatting, length and ethics rules in the appendix of `AGENTS.md`, not here. Why: they differ per institution.
13. Every chapter is reviewed by a critic who has the source stage note open. Why: only a reader with the source can spot drift.
14. Anything the thesis promises but no source supports becomes a deferred entry (`rk add deferred ... --note "<missing evidence>"`). Why: a gap must stay visible until it is filled or cut.
15. Agents never touch hardware unless the user explicitly tells them to; a new measurement is an experiment-kind stage, not a thesis stage. Why: new data needs its own provenance chain.
