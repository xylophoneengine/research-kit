# OpenCode V2 transport

Use `subagent` from the lead session. Resolve each role to its native
OpenCode subagent profile: `rk-junior`, `rk-senior`, `rk-expert`,
`rk-architect`, or `rk-critic` (both critic lenses). Check which are
available in the active session. For an unconfigured role use `general`
unless the user or project requires a particular model. If no role
profiles are configured, all roles use the same `general` profile.
A profile without a model pin inherits the lead's model. Never infer a
model from the profile's name or invent a profile to match a requested model.

Pass the complete brief as the prompt. Save the returned `sessionID`
alongside the role and report path in the lead's handoff when waiting.
The `<subagent>` completion yields control back to the lead. Continue an
idle worker or loop critic by `sessionID` only after a new gated brief;
never continue a blind critic. Use a fresh child and the saved context if
the old session cannot resume and is confirmed no longer writing.
Use `question` for lead decisions, or ask in chat if unavailable.
