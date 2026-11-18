# Hermes transport

Use the lead's `delegate_task(goal=..., context=...)`; for an independent
wave, use `tasks` with one `{goal, context}` per child. Use role names in the
goals and pass the full saved brief in `context`. Top-level interactive
calls notify on completion; a batch normally notifies after all its children.
In finite chat runs consume synchronous results instead. Keep the returned
child and delegation IDs with the role and expected report path in the
handoff when waiting.

With default delegation all children share the configured `delegation.model`
or inherit the lead's model. No per-task `model` argument is supported.
With advanced delegation, use the exposed `option` (`model_map`) or
`profile` (`profile_routes`) field. Resolve the roles against the route
names advertised by the active tool: `rk-junior`, `rk-senior`, `rk-expert`,
`rk-architect` and `rk-critic` (both critic lenses). Pass the selected
route for each child, including in a batch. If a staffed role has no matching
route under the advanced backend, ask which advertised route to use unless
the user already supplied one. Don't silently rely on the backend default.
Check the returned route metadata and report any fallback instead of
claiming the requested model ran.

For an idle worker or loop critic use `action: continue` with its
`subagent_id` and the new gated brief when the tool allows it. Otherwise
start a fresh child with the saved context only after confirming the earlier
child is no longer writing. Never continue a blind critic. Use `clarify`
for lead decisions or ask in chat. This adapter assumes the local terminal
backend and that children can access the same project and report files.
