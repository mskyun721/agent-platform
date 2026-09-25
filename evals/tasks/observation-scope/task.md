# Observation scope report

Read observations.py as input data. Write health.json containing an array of objects,
one per case: {"id":case id,"active_session":session id,"status":status,"latest_turn_at":timestamp or null}.
Do not change existing input or source/test files.

Use status captured when the current session has a stored /platform turn and the poll is
no older than 30 seconds; unavailable when no stored current-session turn exists; excluded
when all current-session turns belong to another project; stale when poll is older than
30 seconds (takes precedence). latest_turn_at is the newest stored /platform timestamp
for the active session, or null. An old session's count is not current capture evidence.
An unchanged log is not missing evidence. For mixed cwd logs, consider each turn's scope.
