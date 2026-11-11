# Problem and goals

## Problem

- Frequent focus changes and context switching carry a high cognitive cost.
- Work resumed after weeks or months starts from zero: the state it was left in is not remembered.
- Ideas stall halfway: enthusiasm fades, priorities change, or they are simply forgotten.
- Claude Code sessions accumulate with forks, open, without a clear conclusion. It is unclear whether their work was committed, pushed, or merged.
- With N sessions on the same project or idea, it is unclear which one is the most advanced.
- There is no clear, compact view of any of this.

## Desired capabilities

1. **Compact overview**: what I have been working on and whether it is finished or pending, without taking the whole screen.
2. **Resume support**: when I do not remember what I was doing, get a brief of where the work stands and the next step.
3. **Periodic reminder**: every 15 days, a notification listing work that has been left pending.
4. **Communication drafts**: in the background, generate drafts of articles or communication pieces describing the work, for:
   - an internal personal portfolio shared with management and other team leads;
   - cumulative progress updates of what the team has built;
   - a personal blog or LinkedIn.
   Drafts are curated by relevance per audience and presented on a fixed weekday for approval. Approved pieces are first "published" to a wiki or a local directory, never directly to an external platform.
5. **Prioritization**: help reduce dispersion and prioritize activities.

## Non-goals (for now)

- Reading ChatGPT web, Codex web, or Claude web/desktop chat history (cloud-only; may enter later through manual export).
- Supporting the personal machine (rarely used; may enter later through export).
- Automatic publication to external platforms.

## Constraints

- **Two domains that must not mix**: work (the employer) and personal/academic. Every thread is tagged with its domain at ingestion; curators only read their own domain.
- **Data governance**: transcripts contain internal data (clients, work items, code). External publication requires an explicit sanitization step and human approval.
- **Zero maintenance burden**: a tool against dispersion that needs manual feeding becomes another source of dispersion. The MVP must work without manual input; manual marks are optional refinements.
