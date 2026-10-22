"""Propose–Probe–Compose (harness2 task-level recursion) for one role instruction on one host.

Sessions (model calls) and rollouts (fixture runs) are injected, so the budget identity, the
omitted-is-inherited edit contract and the evidence boundary are testable without a model.
evals/ppc.py supplies the real ones.
"""
import json
import random
import re

from agent_platform_mcp.tools.stdout_artifacts import _mask

MAX_TEXT = 64 * 1024
FENCE = "`" * 3
_HEADING = re.compile(r"^# .+$", re.M)
_EDIT = re.compile(r'<section heading="(# [^"\n]+)">\n(.*?)\n</section>', re.S)
_CHOICE = re.compile(FENCE + r"choice\s*\n\s*([A-Z])\s*\n\s*" + FENCE)
_WHY = re.compile(r"<why>(.*?)</why>", re.S)
# Sections whose existing lines must survive every edit (append-only); spec §5.3 "never weaken policy".
_PROTECTED = re.compile(r"rule|polic|security|safety|constraint|approval|permission|gate|boundar|observation|completion|done", re.I)
_OVERRIDE = re.compile(r"\b(ignore|disregard|override|bypass|skip)\b[^\n]{0,60}\b(rules?|polic\w*|instructions?|approvals?|"
                       r"safety|security|verification|constraints?)\b", re.I)


class BudgetError(AssertionError):
    """The run did not land on R = 4k rollouts and P = 3k sessions, or ran out of time."""


def sections(text):
    starts = [match.start() for match in _HEADING.finditer(text)]
    if not starts:
        raise ValueError('instruction has no "# " sections')
    found = {}
    for index, start in enumerate(starts):
        chunk = text[start:starts[index + 1] if index + 1 < len(starts) else len(text)]
        heading, _, body = chunk.partition("\n")
        if heading.strip() in found:
            raise ValueError(f"duplicate section: {heading.strip()}")
        found[heading.strip()] = body.strip("\n")
    return text[:starts[0]], found


def _render(preamble, found):
    return preamble + "\n\n".join(f"{heading}\n\n{body}" for heading, body in found.items()).rstrip() + "\n"


def parse_edits(output):
    edits = {}
    for heading, body in _EDIT.findall(output):
        heading = heading.strip()
        if heading in edits or not body.strip():
            raise ValueError("duplicate or empty section edit")
        if _HEADING.search(body):
            raise ValueError("section body cannot contain '# ' headings")
        edits[heading] = body.strip("\n")
    if not edits:
        raise ValueError('no <section heading="# ..."> edits found')
    return edits


def _guard(current, edits):
    for heading, body in edits.items():
        old = current.get(heading)
        added = body if old is None else "\n".join(line for line in body.split("\n") if line not in old.split("\n"))
        if _OVERRIDE.search(added):
            raise ValueError(f"{heading}: edits may not tell the role to ignore or bypass rules")
        if old is not None and _PROTECTED.search(heading):
            kept = set(body.split("\n"))
            if any(line.strip() and line not in kept for line in old.split("\n")):
                raise ValueError(f"{heading} is a policy section; existing lines can only be extended")


def apply_edits(base, edits):
    preamble, current = sections(base)
    _guard(current, edits)
    text = _render(preamble, {**current, **edits})
    if text == _render(preamble, current):
        raise ValueError("edits change nothing")
    if len(text.encode("utf-8")) > MAX_TEXT or _mask(text) != text:
        raise ValueError("candidate is oversized or contains suspected secrets")
    return text


class Ledger:
    """R = 4k rollouts (k base + 2k candidates + k finals), P = 3k sessions (k INV + k DOM + k compose)."""

    def __init__(self, k):
        self.k = k
        self.entries = []

    def rollout(self, label):
        self.entries.append({"kind": "rollout", "label": label})

    def session(self, label, attempts):
        self.entries.append({"kind": "session", "label": label, "attempts": attempts})

    def counts(self):
        return (sum(e["kind"] == "rollout" for e in self.entries), sum(e["kind"] == "session" for e in self.entries))

    def check(self):
        if self.counts() != (4 * self.k, 3 * self.k):
            raise BudgetError(f"ledger {self.counts()} != (4k, 3k) for k={self.k}")

    def to_dict(self):
        rollouts, sessions = self.counts()
        return {"k": self.k, "rollouts": rollouts, "sessions": sessions,
                "expected": {"rollouts": 4 * self.k, "sessions": 3 * self.k}, "entries": self.entries}


BOUNDARY = ("Use only the instruction text, lessons and execution records below. Do not claim behavior the records "
            "do not show. Evaluation criteria and expected answers are intentionally withheld.")
EDIT_FORMAT = ('Return only changed sections, each as <section heading="# Heading">\nnew body\n</section>. '
               "Omitted sections are inherited unchanged; sections cannot be deleted. Never weaken platform policy, "
               'approval, verification or safety rules. Do not put "# " headings inside a body.')
LENS = {"INV": "general, task-invariant improvements to how this role plans, verifies and reports",
        "DOM": "improvements specific to this role's domain, grounded in the approved lessons"}


def _records(rows):
    return json.dumps(rows, ensure_ascii=False, indent=1)


def _options(options):
    return "\n\n".join(f"### Option {o['id']}\n{o['instruction']}\n#### Records\n{_records(o['records'])}"
                       for o in options)


def propose_prompt(dim, role, base, lessons, base_records, index, k):
    return (f"[propose {dim} {index}/{k}] Improve the `{role}` role instruction: {LENS[dim]}.\n{BOUNDARY}\n{EDIT_FORMAT}\n\n"
            f"## Current instruction\n{base}\n\n## Approved lessons\n{lessons or '(none)'}\n\n"
            f"## Execution records with the current instruction\n{_records(base_records)}")


def compose_prompt(role, base, options, index, k):
    return (f"[compose {index}/{k}] Compose one refined `{role}` instruction from the behavioral contrasts between the "
            f"options' execution records. Edit the current instruction.\n{BOUNDARY}\n{EDIT_FORMAT}\n\n"
            f"## Current instruction\n{base}\n\n## Options\n{_options(options)}")


def select_prompt(role, options):
    return (f"[select] Choose the `{role}` instruction whose execution records are best. Keeping the current behavior "
            f"is a valid choice when no option is clearly better.\n{BOUNDARY}\n"
            f"Answer with {FENCE}choice\\n<letter>\\n{FENCE} and <why>one or two sentences citing the records</why>.\n\n"
            + _options(options))


def _anonymize(names, rng):
    shuffled = list(names)
    rng.shuffle(shuffled)
    return {chr(ord("A") + index): name for index, name in enumerate(shuffled)}


def parse_choice(output, id_map):
    choices = _CHOICE.findall(output)
    if len(choices) != 1 or choices[0] not in id_map:
        raise ValueError("selection must contain exactly one valid choice")
    why = _WHY.search(output)
    return choices[0], (why.group(1).strip() if why else "")


def _attempt(make_prompt, base, session):
    note, error = "", ""
    for attempt in (1, 2):
        try:
            return apply_edits(base, parse_edits(session(make_prompt(note)))), {
                "attempts": attempt, "kept_base": False, "fell_back": False, "error": ""}
        except (ValueError, RuntimeError) as exc:
            error = str(exc)[:400]
            note = f"\n\nYour previous answer was invalid ({error}). Follow the edit format exactly."
    return base, {"attempts": 2, "kept_base": True, "fell_back": True, "error": error}


def run(*, role, k, base, lessons, session, rollout, seed=0):
    if type(k) is not int or not 1 <= k <= 4:
        raise ValueError("k must be an integer 1..4")
    sections(base)
    ledger, rng = Ledger(k), random.Random(seed)
    stages, rollouts, candidates, finals = [], {}, {}, {}
    try:
        for index in range(1, k + 1):
            rollouts[f"base{index}"] = rollout(base, f"base{index}")
            ledger.rollout(f"base{index}")
        base_records = [rollouts[f"base{index}"] for index in range(1, k + 1)]
        for dim in ("INV", "DOM"):
            for index in range(1, k + 1):
                label = f"{dim.lower()}{index}"
                text, stage = _attempt(lambda note, d=dim, i=index: propose_prompt(d, role, base, lessons, base_records, i, k)
                                       + note, base, session)
                ledger.session(label, stage["attempts"])
                stages.append({"label": label, **stage})
                candidates[label] = text
        for label, text in candidates.items():
            rollouts[label] = rollout(text, label)
            ledger.rollout(label)
        pool = {"base": base, **candidates}
        evidence = {"base": base_records, **{label: [rollouts[label]] for label in candidates}}
        for index in range(1, k + 1):
            label = f"agg{index}"
            id_map = _anonymize(pool, rng)
            options = [{"id": letter, "instruction": pool[name], "records": evidence[name]} for letter, name in id_map.items()]
            text, stage = _attempt(lambda note, o=options, i=index: compose_prompt(role, base, o, i, k) + note, base, session)
            ledger.session(label, stage["attempts"])
            stages.append({"label": label, **stage})
            finals[label] = text
        for label, text in finals.items():
            rollouts[f"final-{label}"] = rollout(text, f"final-{label}")
            ledger.rollout(f"final-{label}")
        ledger.check()
    except (BudgetError, RuntimeError, ValueError) as exc:
        exc.ledger, exc.partial = ledger.to_dict(), {"candidates": candidates, "finals": finals, "rollouts": rollouts}
        raise
    choices = {"base": base, **finals}
    records = {"base": base_records, **{label: [rollouts[f"final-{label}"]] for label in finals}}
    id_map = _anonymize(choices, rng)
    options = [{"id": letter, "instruction": choices[name], "records": records[name]} for letter, name in id_map.items()]
    try:
        letter, why = parse_choice(session(select_prompt(role, options)), id_map)
        chosen, fallback = id_map[letter], False
    except BudgetError as exc:
        exc.ledger, exc.partial = ledger.to_dict(), {"candidates": candidates, "finals": finals, "rollouts": rollouts}
        raise
    except (ValueError, RuntimeError) as exc:
        chosen, why, fallback = "base", f"selection fell back to base: {str(exc)[:200]}", True
    return {"k": k, "ledger": ledger.to_dict(), "stages": stages, "candidates": candidates, "finals": finals,
            "rollouts": rollouts, "selection": {"chosen": chosen, "why": why, "id_map": id_map, "fallback": fallback},
            "text": choices[chosen], "changed": choices[chosen] != base}
