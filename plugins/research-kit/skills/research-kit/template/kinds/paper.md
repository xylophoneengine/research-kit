<!-- research-kit-kind paper: 2026-11-13a -->
# Kind: paper

Rules for writing a research paper: literature, writing stages, citations. They add to the core `AGENTS.md`; they never relax it. Stage folders are `pm/stages/NN-paper-<topic>/` (full mode); in light mode the stage table is a checklist only. Evidence tags (CONFIRMED / LIKELY / GUESS), Done when, the ledger (core 4.2) works as in core. Placeholder `<ID>` = paper id from the appendix.

## P0. Prerequisite: ARS skills (academic-research-skills plugin)

Paper pipeline runs on the ARS plugin. First session in a paper repo: lead checks it is present (skills named `academic-research-skills:*` in skill list, or `/plugin` shows it installed). Absent: ask user to install (recommended) or proceed without ARS. Plugin and slash commands are user-run (`/plugin` -> Marketplaces -> add/install `academic-research-skills`; give the command in its own message). Never improvise the pipeline silently. Update announced: tell user (`/plugin update academic-research-skills`); never update silently mid-stage. Why: a plugin change mid-stage changes what produced the deliverable.

ARS = default tool for every literature and writing stage. Use it, don't reinvent. Which step in which stage: table in P2 (only stage -> mode map). Mode names: plugin `MODE_REGISTRY.md` (single source of truth); check names there when opening a stage.

- Invoke PARENT skill with mode arg on session model. Most light `/ars-*` slash commands pin a small model (frontmatter `model: sonnet`), so can't run on session model; check the command file before relying on it. Use pinned ones only for jobs fine on Sonnet (abstract, format convert).
- ARS runs inside team model, not beside it. Interactive modes (plan, Socratic dialogue) = user dialogue, run in lead session. Every mode writing a deliverable file (scan, outline, full, revision) is driven by a named teammate. Output still goes through critic loop (core 2.2) and, for literature, cross-audit (P5.6). ARS plugin agents (`synthesis_agent`, `research_architect_agent`, `report_compiler_agent`) are dispatched by the skill itself; they don't replace the roster and aren't addressed via `SendMessage`.
- ARS outputs land in the stage folder named in `BRIEF.md`, never in `paper/` or `pm/` root.
- Record in stage README which ARS skill + mode + version produced each deliverable. Why: reruns must be reproducible.

## P1. First session (after core 0.2 steps 1-4)

1. ARS check (P0).
2. Create `paper/library/pdfs/` and `paper/archive/`. `paper/manuscript/` waits until the draft stage.
3. Skeleton files, headings only (jr): `pm/living/paper_ledger.md` (first line `Repo tag: <tag>`, then header row from P5.1).
4. ASK user which reference-manager tag marks this repo's library entries (Zotero tag, e.g. `mypaper`). Short, lowercase, unique per paper repo, so every library entry traces to its repo. Propose one derived from `<ID>` as recommended option; user may type own. Never start any import or fetch before the tag is fixed. Record in appendix + first line of `pm/living/paper_ledger.md`.
5. Appendix lines for this kind: working title + venue + length; authors (first/main, co-authors, supervisor); reference manager + repo tag; paper topic (3 lines, for scoping literature work).
6. Existing material (thesis, draft, reference list)? -> open a seed stage (row 1, P3). Else -> open the goal + lit-scan stage (row 2). First ARS deliverable either way = `pm/living/GOALS.md`, agreed with user before any scan starts.

Roles for this kind: user = first/main author; co-authors and supervisors get neutral wording in text. `pm/living/paper_ledger.md` is a teammate file: the lead never edits it. Why: one writer per ledger keeps it in sync with the library.

## P2. Stage table

Column `#` = order, not stage number (NN is the next free number, core 3.1). Adapt the stage set per paper; ARS skill + mode per stage kind stays. Lead names skill + mode in `BRIEF.md` when opening the stage. Stage with no ARS entry = no ARS, never invent one.

| # | stage | ARS skill (mode) | consumes | driver | deliverable | Done when |
|---|-------|------------------|----------|--------|-------------|-----------|
| 1 | seed existing material (optional, P3) | none (import teammates, P5.1-P5.3, P5.8) | existing refs, PDFs, bib | jr/sr | ledger, PDFs, tagged library entries, corpus passport | sync check passes (P5.1); passport validator exits 0; both critics YES |
| 2 | goal + lit-scan | `deep-research` (`three-way-scan` / `lit-review` for scan; `socratic` optional for GOALS dialogue, skip if user has concrete goals) | passport if seeded | lead: GOALS dialogue, writes `pm/living/GOALS.md`, user confirms. exp/sr: scan | `pm/living/GOALS.md`, scan files ending in `## Candidates for paper_ledger.md` | user's GOALS sign-off logged as a user decision (`rk add decision ... --owner user`) before the scan starts; cross-audit file (P5.6) exists with every conflict resolved |
| 3 | source sync | none (import teammates, P5.1-P5.3) | candidates | jr/sr | ledger = PDFs = tagged library entries, passport rebuilt | sync check passes; passport fresh (P5.8) |
| 4 | scan update | `deep-research` (`three-way-scan` / `lit-review` / `fact-check`, full-text re-read) | ledger, passport | exp read, sr audit | updated scans | cross-audit file exists, every conflict resolved |
| 5 | experiments / benchmarks (only if new runs needed) | none (core 6 + software kind "Benchmarks"; add that kind first). `deep-research` `fact-check` only for literature claims | GOALS | sr/exp | `deliverables/bench/` | run sheet commands reproduce the outputs; both critics YES |
| 6 | code / prep, reruns `NNb` (only if experiments need a rerun) | none (core 6 + software kind "Benchmarks") | experiments | sr/exp | code, run sheet, numbers | quality gate exits 0; numbers stamped at a clean commit; both critics YES |
| 7 | plan | `academic-paper` (`plan`), session model | GOALS, scans, numbers | lead session (Socratic user dialogue) | `chapter_plan.md`, `insight_collection.md` | both files exist; both critics YES; user decisions logged verbatim |
| 8 | outline | `academic-paper` (`outline-only`) | chapter_plan, insight_collection, passport | exp writer teammate | `outline.md`, `claims_register.md` | every claim in `claims_register.md` has an owner file; both critics YES |
| 9 | full draft | `academic-paper` (`full`). `academic-pipeline` only phase-by-phase (Mode B: `ARS_PASSPORT_RESET=1` + `resume_from_passport`, one pipeline stage per paper stage), else it swallows rows 10-12 | outline, claims_register, passport | exp writer, sr support | `paper/manuscript/current/` | both critics YES; `citation-check` run with no open error; README records which integrity gate ran (`academic-pipeline` mid-entry at Stage 2.5, stopped at its checkpoint), or none |
| 10 | review | `academic-paper-reviewer` (`full`; `methodology-focus` for method-heavy paper) | draft | exp | `paper/manuscript/reviews/`; keep Revision Roadmap + Round-1 reviewer config cards (needed by `re-review`) | panel report and Roadmap files exist; user has read the panel report (logged as a user decision, `rk add decision ... --owner user`) |
| 11 | revision | `academic-paper` (`revision`; `revision-coach` on real reviewer comments; `rebuttal-audit` on response letter), then `academic-paper-reviewer` (`re-review`) | Roadmap, pre-revision draft, response letter, Round-1 cards, author sidecar (else `re-review` returns `manifest_incomplete`) | exp | new `paper/manuscript/versions/vNN_*`, response letter | `re-review` marks every Roadmap item resolved or rebutted; both critics YES |
| 12 | finalize | `academic-paper` (`abstract-only` with language pair from outline Phase 0; `citation-check`, `disclosure`, `format-convert`) | final draft | sr | final manuscript, disclosure | final `citation-check` with no open error; README records which gate ran (Stage 4.5 exists only inside `academic-pipeline`), or none; user sign-off logged |

`sr-screener` (ARS >= 3.23.0): only for systematic / scoping / rapid reviews, only on user request, as own stage `NNb` after a `deep-research` `systematic-review` (or `sr-screener` `protocol`) stage. Input = database exports (RIS / nbib / WoS / CSV) + protocol. Modes protocol -> pilot -> ta-screen -> ft-screen -> report. Its `literature_corpus` output becomes the passport (P5.8). `systematic-review` never hands over to it automatically.

Freeze step at close (core 3.4 step 7): from the draft stage on, freeze `paper/manuscript/versions/vNN_<label>/` (sr). Why: reviews and response letters cite a fixed text.

## P3. Existing material to adopt

Thesis, draft or reference list: row 1, no ARS. Ledger metadata comes from retrieved records (Crossref/DataCite), never copied from the adopted bib (it may carry errors). Each adopted PDF gets an identity check (title + first author + year) and a provenance note. An existing draft goes to `paper/archive/` as input for GOALS dialogue and outline, never into ARS mid-entry. Ledger -> ARS corpus passport (P5.8), otherwise ARS ignores the seed. First ARS stage = row 2, after the passport exists.

## P4. Paper folders, brief appends, claims

```
paper/
  library/pdfs/     all PDFs, never sorted by stage
  archive/          pre-project / superseded material, historical only
  manuscript/       created at the first full-draft stage
    current/        main text + refs file - always the latest
    figures/        final figures; each lists the module that produced it
    versions/       frozen vNN_<label>/ at every stage close from the draft stage on
    reviews/        simulated + real reviews, response letters
```

Brief appends (core 2.3) for this kind:
- Research briefs state PDF reading mode (P5.4) and page-cite rule (P5.5).
- Touching the reference manager: paste its rules (P5.2) into the brief.
- Fetcher brief: step 1 = reference-manager check (P5.3).

Claims (in addition to core 5.1-5.2):
- Claims affirmative: say what we do. No "nobody / first / unlike X", no attack on a named group. Method contrasts at the level of method families. Why: such claims rarely survive review.
- Prior art: credit lineage explicitly (who computed it first, even if only for a different device). Contribution = scale + uses unless a read proves otherwise. Every novelty sentence survives the claim-survival table (claim -> closest prior art -> "survives as ...").
- Co-author works cited neutrally.
- `claims_register.md` (outline deliverable): one row per claim with owner file + wording guardrails. Critics check every draft against it.

## P5. Literature and sources

### P5.1 Ledger

`pm/living/paper_ledger.md` = single list of every source. One row per source:
`| key | authors (year) | title | venue | DOI | role | pdf | reference-manager key/tag | status |`
- role in `core | method | standard | software | related-work | optional`.
- status in `ok` (row + PDF + manager) / `no-pdf` / `manager-only-metadata` / `failed:<reason>`.
- DOIs verified via Crossref (DataCite for theses/datasets) before entering ledger. Else `DOI unverified`.
- PDF naming: `Author et al. - YEAR - Title.pdf`, in `paper/library/pdfs/`.
- First line of ledger = `Repo tag: <tag>` (P1 step 4). Every source filed in the reference manager and tagged with it. Tag = only link library entry <-> repo. Teammate adding an item sets the tag in the same call; item without tag = sync-check failure. Item already in library (other repo's tag): ADD this repo's tag (items carry several repo tags). Never remove or rename another repo's tag, never create a duplicate item.
- Ledger row, PDF, reference-manager entry stay in sync. Each import pass appends `## Sync check (<date>)` (PDFs <-> `ok` rows 1:1; manager tag set = ledger set; counts asserted by per-key checks, never from a capped search result). The checker is a script frozen in the stage's `code/`; it checks per key via the manager's local API across all libraries, accepts a PDF or EPUB child, and exempts group items from the file-child test.
- Single writer on ledger at any time (import teammate). Scans end with `## Candidates for paper_ledger.md` in row format. Import teammate merges them.
- Open-access substitutes: separate ledger row + separate manager item, cross-referenced. Cite original, read and quote substitute.

### P5.2 Reference manager (Zotero)

Zotero writes follow the `research-kit-lit:zotero` skill: load it before any write; teammates that touch Zotero spawn as `research-kit-lit:zotero-worker`. Skill absent: ask the user to install the `research-kit-lit` plugin; until then, no attachments. Why: the skill carries the preflight and stop conditions.
Rules to paste into every brief that touches the manager (the skill has the procedure):
- Attach files only through the desktop client's own storage sync (WebDAV), never vendor cloud (quota). Write mode hybrid/web: do NOT attach; the tool may silently upload to cloud while its reply claims WebDAV.
- New batch: attach ONE file first, verify it is not on the cloud (skill's `/file` check). Any error mentioning quota or cloud storage: stop, report exact text.
- Group libraries: no attachments on group items (their files always sync through the vendor cloud). Tag only, file stays in `paper/library/pdfs/`, ledger manager cell `KEY (group <id>) / <tag>`.
- Writes (add, update, attach, collection edit) allow-listed in settings; anything else needs a user ask.
- Tag search caps at 100 results: verify sync by per-key metadata or the local HTTP API.
- Titles go in as plain text (strip `<i>`, `<scp>`, `&amp;`). Soft file-size limit ~28 MB: shrink with ghostscript, attach the small copy, keep the original.
- Other reference manager: record it in the appendix and adapt these rules there.

### P5.3 Retrieval ladder (every fetch brief)

1. Reference manager first (children check on ledger key; if a PDF child exists, copy it from manager storage, never fetch). Reads never gated, writes are.
2. Unpaywall / publisher OA link via curl.
3. Browser automation (downloads land in `~/Downloads`; move into `paper/library/pdfs/`).
4. On failure: `rk add fetch "<key>: <title>" --note "DOI ...; URL ...; file <target filename>; manager <key>" --link <task id> --who <name>`. Open fetch entries are what the user still fetches by hand (STATUS.md "Open fetches"). When the PDF arrives, the import teammate attaches it, flips the ledger status, and runs `rk close F-<n> --note "attached"`. No pointer row anywhere else.
Never use paywall-circumvention sites. Fetcher reporting `FAILED` for a PDF already in the manager = brief error.

### P5.4 PDF reading mode (every read / audit / scan brief states it)

Extract text first (manager full text or `pdftotext -layout`). Read and quote from text. Open page images only for passages text cannot carry (equations, tables, figures, scans, non-Latin script) or to confirm a printed page, limited to pages in question. Never read a whole PDF as images (one stage produced 519 MB of transcripts with no gain in precision).

### P5.5 Page citations and re-reads

Give BOTH PDF page index and printed page (`PDF p. 7 / printed p. 569`). State cover sheet / online-first pagination. Quote <= 3 lines per claim. Read the passage yourself, never inherit a prior agent's page cite. Rows a prior pass marked "verified unchanged" get the same full re-read as changed rows. Why: inherited cites were wrong often enough to matter.

### P5.6 Literature scan pipeline

Scan -> cross-audit by a teammate on a DIFFERENT model (expert read -> senior audit; senior scan -> full expert sweep, then senior audit). Audit written to a side file. Audit wins on conflict -> user check -> import teammate (ledger + manager) -> sync check. No expert edits a deliverable without that cross-audit. Why: one model's blind spots repeat across its own passes.

### P5.7 Corpus saturation

Declare literature saturated explicitly (user decision entry, dated by the ledger: `rk add decision ... --owner user`) after the last scan stops producing narrowing prior art. Log follow-up refs as "not fetched". Saturated corpus = skip outline Phase 1.

### P5.8 ARS corpus passport

ARS reads our sources only as `literature_corpus[]` in a Material Passport (`passport.yaml`); no adapter reads `paper_ledger.md`. Without a passport ARS searches external databases only and ignores the ledger. Needed in EVERY ARS literature / writing run after a source sync, not only adopted repos: `deep-research` (`lit-review`, `three-way-scan`, `full`, `systematic-review`), `academic-paper` (`outline-only`, `full`). `socratic` and `plan` never read it.
- Build with a converter script in the stage's `code/`: ledger -> passport, `obtained_via: other`, one entry per ledger row, unfillable rows to `rejection_log.yaml`. Write `HANDOFF_ars_corpus.md` for it (goal, inputs, converter, validator, how the run locates the passport).
- Validate with the plugin's `scripts/check_literature_corpus_schema.py --passport <file>`.
- Adapter dependencies (`requirements-dev.txt`): user installs, agents never do.
- Rebuild after every ledger change (any edit, not only a source sync); fresh iff passport `obtained_at` == ledger mtime. The converter asserts the expected row count (bump it with each ledger change) and has a selfcheck; full author lists live in a side file the converter reads (the ledger row keeps "X et al."). First ARS run on a new passport: check the "PRE-SCREENED FROM USER CORPUS:" block sums to the entry count (a wrong path fails silently).
- GOALS / research question first: corpus entries are screened against it like any search hit.
- How a skill invocation locates `passport.yaml` is not documented: record the answer in the `BRIEF.md` of the first stage that uses it.

## P6. Writing stages (plan -> outline -> draft -> review -> revise)

- Plan stage: Socratic chapter-by-chapter (lead session, user dialogue), argument stress test on goals + numbers. Output `chapter_plan.md`, `insight_collection.md`. Each user decision is a decision entry (`rk add decision ... --owner user`, the user's words in `--note`).
- Outline stage: structure, word budget per section, figure/table plan, evidence map (every claim -> source key), transitions, open items carried to draft; `claims_register.md`. Phase 0 confirms genre, venue, citation style, abstract language, length.
- Every written deliverable runs the critic loop (core 2.2) before the user sees it: writer teammate (expert) -> `crit1` + `crit2` -> fix -> v2 -> v3 at most (two fix rounds), then escalate. Keep every version. Why: the user's reading time is the scarcest review.
