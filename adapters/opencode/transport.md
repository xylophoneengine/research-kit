# OpenCode V2 transport

Use `subagent` from the lead session. `general` is the fallback agent for
all roles and inherits the parent model unless configured otherwise.
For role-specific models use available subagent profiles `rk-junior`,
`rk-senior`, `rk-expert`, `rk-architect` and `rk-critic` (both critic lenses).
Show the effective mapping at roster confirmation. If a requested profile
or model is unavailable, ask before substituting; role names alone do not
select a model.

Pass the complete brief as the prompt. Save the returned `sessionID`
alongside the role and report path in the lead's handoff when waiting.
The `<subagent>` completion yields control back to the lead. Continue an
idle worker or loop critic by `sessionID` only after a new gated brief;
never continue a blind critic. Use a fresh child and the saved context if
the old session cannot resume and is confirmed no longer writing.
Use `question` for lead decisions, or ask in chat if unavailable.
