# Hermes transport

Use the lead's `delegate_task(goal=..., context=...)`; for an independent
wave, use `tasks` with one `{goal, context}` per child. Use role names in the
goals and pass the full saved brief in `context`. Top-level interactive
calls notify on completion; a batch normally notifies after all its children.
In finite chat runs consume synchronous results instead. Keep the returned
child and delegation IDs with the role and expected report path in the
handoff when waiting.

With default delegation all children share the configured `delegation.model`
or inherit the lead's model. Do not send imaginary per-task `model` values.
If the operator configured role routes via advanced delegation, follow
the exposed tool schema and confirm the route mapping. If the user required
model separation and routes aren't configured, ask before proceeding.

For an idle worker or loop critic use `action: continue` with its
`subagent_id` and the new gated brief when the tool allows it. Otherwise
start a fresh child with the saved context only after confirming the earlier
child is no longer writing. Never continue a blind critic. Use `clarify`
for lead decisions or ask in chat. This adapter assumes the local terminal
backend and that children can access the same project and report files.
