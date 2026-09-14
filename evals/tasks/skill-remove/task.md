# Managed Skill Removal

Implement exercise(enable, disable, remove) in exercise_skill.py. The evaluator
starts with a real managed skill already enabled in a temporary project. Each
callback takes no arguments and invokes the platform's real skill manager.

First attempt remove and verify it raises RuntimeError while enabled. Then call
disable, then remove successfully. Return a dict with blocked_while_enabled=True
and removed=True only after those outcomes occur. Do not call enable again. Keep
the existing calc implementation and tests unchanged. No global/project settings,
real service files, or external commands need changing. Run pytest for the existing
arithmetic tests; the external evaluator checks the skill lifecycle separately.
