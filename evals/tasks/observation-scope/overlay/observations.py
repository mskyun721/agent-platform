# Immutable evaluator input. Times are UTC; now is 2026-09-25T12:00:00Z.
# Capture scope is exactly /platform; another cwd inside one transcript must not
# discard matching /platform turns. Cached/unchanged logs still count as stored evidence.
CASES = [
 {'id':'current','active_session':'s1','poll':'2026-09-25T11:59:58Z','turns':[{'session':'s1','cwd':'/platform','ts':'2026-09-25T11:59:50Z','stored':True}]},
 {'id':'historical-only','active_session':'s2','poll':'2026-09-25T11:59:58Z','turns':[{'session':'s0','cwd':'/platform','ts':'2026-09-20T00:00:00Z','stored':True}]},
 {'id':'mixed-path','active_session':'s3','poll':'2026-09-25T11:59:58Z','turns':[{'session':'s3','cwd':'/other','ts':'2026-09-25T11:50:00Z','stored':False},{'session':'s3','cwd':'/platform','ts':'2026-09-25T11:59:51Z','stored':True}]},
 {'id':'other-project','active_session':'s4','poll':'2026-09-25T11:59:58Z','turns':[{'session':'s4','cwd':'/other','ts':'2026-09-25T11:59:52Z','stored':False}]},
 {'id':'unchanged-log','active_session':'s5','poll':'2026-09-25T11:59:58Z','unchanged':True,'turns':[{'session':'s5','cwd':'/platform','ts':'2026-09-25T11:59:53Z','stored':True}]},
 {'id':'stale-worker','active_session':'s6','poll':'2026-09-25T11:50:00Z','turns':[{'session':'s6','cwd':'/platform','ts':'2026-09-25T11:49:00Z','stored':True}]},
]
