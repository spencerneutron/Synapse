#!/usr/bin/env python3
"""
scrub.py — the deterministic scrub gate: what must not leave a personal store.

  synapse share scrub <note> [--json] [--out FILE]
  synapse share lint <path>... [--json]       # files, or folders (*.md, recursive)

Every match has one outcome. FIXED: rewritten automatically (home paths become
~/, temp paths <tmp>/, session wikilinks "an earlier session"). BLOCKED:
sharing stops until the text is removed (secrets, emails, private IPs, host
names, device ids). REWRITE: a person or agent must reword it (session-local
references, the user's own name, text aimed at an agent). A line that ends with
<!-- synapse:allow --> exempts REWRITE findings on that line, never the others.
The whole text is scanned, front matter and code fences included: a secret in
code is still a secret. Pure text work: no DB, no network.
"""

import argparse
import getpass
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

FIXED, BLOCKED, REWRITE = "fixed", "blocked", "rewrite"
ALLOW = "<!-- synapse:allow -->"
SKIP_USERS = {"root", "admin", "user", "dev", "test", "runner", "ubuntu", "ec2-user"}


@dataclass
class Finding:
    kind: str        # e.g. "home-path", "github-token", "session-ref"
    outcome: str     # FIXED, BLOCKED, or REWRITE
    line: int        # 1-based line in the input text
    excerpt: str     # the matched text; secrets redacted to first 4 chars + "…"
    message: str     # one short sentence: what to do


def rx(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


# --- FIXED: (kind, pattern, replacement function, message) -------------------
def _unix_home(m): return "~"
def _win_home(m): return "~"
def _tmp(m): return "<tmp>"
def _session(m): return "an earlier session"


# A home folder, with the prefixes it hides behind: file://, WSL (/mnt/c,
# //wsl.localhost/<distro>, \\wsl$\<distro>), macOS volumes, /export/home.
UNIX_HOME_PREFIX = (r"(?:file://)?(?://wsl(?:\.localhost|\$)/[^/\s]+|/mnt/[A-Za-z]|/Volumes/[^/\n]+?|"
                    r"/System/Volumes/Data|/private|/export)?")
FIXED_RULES = [
    ("home-path", rx(r"(?<![\w])(?:file:///)?[A-Za-z]:[\\/]Users[\\/][^\\/\s'\"`:)\]]+", re.I), _win_home,
     "Home path replaced with ~/."),
    ("home-path", rx(r"\\\\wsl(?:\.localhost|\$)\\[^\\\s]+\\home\\[^\\\s'\"`:)\]]+", re.I), _win_home,
     "Home path replaced with ~/."),
    ("home-path", rx(r"(?<![\w.~-])" + UNIX_HOME_PREFIX + r"/(?:Users|home)/[^/\s'\"`:)\]]+(?=/|\b)"),
     _unix_home, "Home path replaced with ~/."),
    ("tmp-path", rx(r"(?<![\w.~-])(?:/private)?/var/folders/[^/\s]+/[^/\s]+/[A-Za-z0-9](?=/|\b)"), _tmp,
     "Temp path replaced with <tmp>/."),
    ("session-link", rx(r"\[\[(?:Sessions/)?Session\b[^\]]*\]\]|\[\[Sessions/[^\]]*\]\]"), _session,
     "Link to a session note replaced with plain words."),
    ("session-link", rx(r"\[[^\]\n]*\]\((?:[^)\s]*/)?Sessions/[^)\n]*\)"), _session,
     "Link to a session note replaced with plain words."),
]

# --- BLOCKED secrets: (kind, pattern); excerpts are redacted -----------------
NA = r"(?<![A-Za-z0-9])"            # token must not continue an identifier
SECRETS = [
    ("aws-key", rx(NA + r"(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])")),
    ("github-token", rx(NA + r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("api-key", rx(NA + r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("slack-token", rx(NA + r"xox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google-key", rx(NA + r"AIza[0-9A-Za-z_-]{35}")),
    ("stripe-key", rx(NA + r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("private-key", rx(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", rx(NA + r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("bearer-token", rx(r"\bBearer\s+(?![<${])[A-Za-z0-9._~+/-]{16,}=*")),
    ("webhook-url", rx(r"https://(?:hooks\.slack\.com/services|(?:discord|discordapp)\.com/api/webhooks|"
                       r"[\w.-]+\.webhook\.office\.com)/[^\s)\]>\"']+", re.I)),
]
URL_CRED = rx(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]+)@[^\s/]+", re.I)
ASSIGN = rx(r"(?<![A-Za-z0-9])(?:api[_-]?key|secret|token|password|passwd|client[_-]?secret|"
            r"access[_-]?key|auth)(?:[_-][A-Za-z]+)?[\"']?\s*[:=]\s*[\"']?([^\s\"',;]+)", re.I)
PLACEHOLDER = rx(r"^(?:<|\$|\{\{|x{3}|\*{3}|…|\.{3}|your[-_ ]|changeme)|example", re.I)

# --- BLOCKED identity and network --------------------------------------------
EMAIL = rx(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w-])")
EMAIL_OK_DOMAIN = rx(r"(?:^|\.)(?:example\.(?:com|org|net)|example|test|invalid|localhost)$|"
                     r"^users\.noreply\.github\.com$|^noreply\.", re.I)
EMAIL_FILE_EXT = {"png", "jpg", "jpeg", "gif", "svg", "webp", "md", "py", "js", "ts", "json", "txt"}
OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
PRIVATE_IP = rx(rf"(?<![\d.])(?:10\.{OCTET}\.{OCTET}\.{OCTET}|172\.(?:1[6-9]|2\d|3[01])\.{OCTET}\.{OCTET}|"
                rf"192\.168\.{OCTET}\.{OCTET})(?![\d]|\.\d)|"
                r"(?<![\w:])(?:fe80|f[cd][0-9a-f]{2}):(?::?[0-9a-f]{1,4}){1,7}(?:%\w+)?(?![\w:])", re.I)
HOSTNAME = [
    rx(r"(?<![\w.-])[\w-]+(?:\.[\w-]+)*\.(?:local|lan|internal|corp)(?![\w-]|\.\w)", re.I),
    rx(r"\b[A-Z][a-z]+s?-(?:MacBook(?:-(?:Pro|Air))?|iMac|Mac-(?:mini|Pro|Studio)|Mac)\b"),
    rx(r"\b(?:DESKTOP|LAPTOP)-[A-Z0-9]{6,}\b"),
    rx(r"\b[A-Za-z]+s-(?:mbp|mba|macbook\w*|imac|mac-?mini|mac-?studio|laptop|desktop|pc)\b", re.I),
]
HEX = r"[0-9a-fA-F]"
DEVICE_ID = [
    rx(rf"\b{HEX}{{8}}-{HEX}{{4}}-{HEX}{{4}}-{HEX}{{4}}-{HEX}{{12}}\b"),
    rx(rf"\b0000{HEX}{{4}}-{HEX}{{16}}\b"),
    rx(rf"(?<![\w:-])(?:{HEX}{{2}}[:-]){{5}}{HEX}{{2}}(?![\w:-])"),
]

# --- REWRITE -----------------------------------------------------------------
ISSUE_REF = rx(r"(?<![\w/&#\[\]-])#(\d+)\b")
COLOR_CTX = rx(r"(?:color|background|border|fill|stroke|shadow|gradient|bg|rgb|hsl)[^#]*$", re.I)
# "Phase 1:" defines a step (a pattern's own vocabulary); "Phase 3 shipped" points
# at one session's plan.
PHASE = rx(r"\b(?:Wave|Phase|Sprint|Milestone|Slice) [A-Z0-9]{1,3}\b(?!:)")
# Bare day words are often product vocabulary ("today's chores", "the Today
# widget"), so they count only next to a session word or a first person.
DAY = r"(?:yesterday|today|tomorrow|tonight)"
TIME_WORDS = rx(rf"\b(?:this morning|last night|earlier today|last session|this session|previous session|"
                rf"next session|last week|this week|{DAY}(?:'s)? (?:session|meeting|call|standup|sync|run)|"
                rf"{DAY},? (?:we|I)(?= ))\b", re.I)
AGENT = [
    rx(r"\bignore (?:(?:all|any) )?(?:previous|prior|above) instructions", re.I),
    rx(r"\bdisregard (?:(?:the|all) )?(?:previous|prior|above)", re.I),
    rx(r"\byou are now\b", re.I),
    rx(r"\bsystem prompt\b", re.I),
    rx(r"<system-reminder>", re.I),
    rx(r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+(?:-\w+\s+)*)?(?:ba|z|da)?sh\b"),
    rx(r"\|\s*sudo\s+(?:-\w+\s+)*(?:ba|z|da)?sh\b"),
    rx(r"\biex\s*\(.*\birm\b|\birm\b[^\n]*\|\s*iex\b", re.I),
]


def redact(s: str) -> str:
    return s[:4] + "…"


PASSWORD_KEY = rx(r"pass(?:wd|word)?\b|pwd\b", re.I)


def real_secret(value: str, key: str = "") -> bool:
    v = value.rstrip(".)]")
    if PLACEHOLDER.search(v):
        return False
    if PASSWORD_KEY.match(key):   # passwords are short: 6+ chars with a digit or symbol
        return len(v) >= 6 and any(not c.isalpha() for c in v)
    return len(v) >= 12 and any(c.isalpha() for c in v) and any(c.isdigit() for c in v)


def line_matches(line: str, user: str | None) -> list[tuple[int, int, str, str, str, str]]:
    """Non-FIXED candidates as (start, end, kind, outcome, excerpt, message), best first."""
    out = []

    def add(m, kind, outcome, message, secret=False, span=None):
        s, e = span or m.span()
        out.append((s, e, kind, outcome, redact(m.group(0)) if secret else m.group(0), message))

    for kind, pat in SECRETS:
        for m in pat.finditer(line):
            add(m, kind, BLOCKED, "Remove this secret; never share credentials.", True)
    for m in URL_CRED.finditer(line):
        if not re.match(r"[<$]|\{\{", m.group(1)):
            add(m, "url-credentials", BLOCKED, "Remove the credentials from this URL.", True)
    for m in ASSIGN.finditer(line):
        if real_secret(m.group(1), m.group(0).lstrip("\"'")):
            add(m, "secret", BLOCKED, "Remove this credential value; name the variable instead.", True)
    for m in EMAIL.finditer(line):
        dom = m.group(1)
        if (EMAIL_OK_DOMAIN.search(dom) or dom.rsplit(".", 1)[1].lower() in EMAIL_FILE_EXT
                or m.group(0).lower().startswith(("noreply@", "git@"))):
            continue
        add(m, "email", BLOCKED, "Remove this email address.")
    for m in PRIVATE_IP.finditer(line):
        add(m, "private-ip", BLOCKED, "Remove this private network address.")
    for pat in HOSTNAME:
        for m in pat.finditer(line):
            add(m, "hostname", BLOCKED, "Remove this machine or internal host name.")
    for pat in DEVICE_ID:
        for m in pat.finditer(line):
            add(m, "device-id", BLOCKED, "Remove this device identifier.")
    if not line.rstrip().endswith(ALLOW):
        for m in ISSUE_REF.finditer(line):
            if COLOR_CTX.search(line[:m.start()]):   # a CSS colour such as #333
                continue
            add(m, "session-ref", REWRITE, "Name the issue or topic in words; a bare number means nothing here.")
        for m in PHASE.finditer(line):
            add(m, "session-ref", REWRITE, "Say what this phase was instead of its label.")
        for m in TIME_WORDS.finditer(line):
            add(m, "session-ref", REWRITE, "Use an absolute date or drop the time reference.")
        if user and len(user) >= 3 and user.lower() not in SKIP_USERS:
            for m in re.finditer(rf"(?<![\w-]){re.escape(user)}(?![\w-])", line, re.I):
                add(m, "username", REWRITE, "Replace the user's name with a role or 'the user'.")
        for pat in AGENT:
            for m in pat.finditer(line):
                add(m, "agent-directed", REWRITE, "Remove text that gives instructions to an agent.")
    return out


def _scan(text: str, user: str | None) -> tuple[str, list[Finding]]:
    """One pass over the lines: apply FIXED rules, then check what remains."""
    new_lines, findings = [], []
    for n, line in enumerate(text.split("\n"), 1):
        for kind, pat, repl, message in FIXED_RULES:
            def sub(m, kind=kind, repl=repl, message=message):
                findings.append(Finding(kind, FIXED, n, m.group(0), message))
                return repl(m)
            line = pat.sub(sub, line)
        new_lines.append(line)
        taken = []                       # spans already reported on this line
        for s, e, kind, outcome, excerpt, message in line_matches(line, user):
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            findings.append(Finding(kind, outcome, n, excerpt, message))
    findings.sort(key=lambda f: f.line)
    return "\n".join(new_lines), findings


def default_user() -> str | None:
    try:
        return getpass.getuser()
    except Exception:
        return None


def scrub(text: str, user: str | None = None) -> tuple[str, list[Finding]]:
    """Apply every FIXED rule; return the new text and all findings (fixed ones included)."""
    return _scan(text, user or default_user())


def lint(text: str, user: str | None = None) -> list[Finding]:
    """Change nothing; return every finding. A FIXED-kind match still present is a failure."""
    return _scan(text, user or default_user())[1]


def blocking(findings: list[Finding]) -> list[Finding]:
    """Findings that stop sharing: outcome BLOCKED or REWRITE."""
    return [f for f in findings if f.outcome in (BLOCKED, REWRITE)]


def notes_in(paths_: list[str]) -> list[Path]:
    out = []
    for p in map(Path, paths_):
        if p.is_dir():
            out += sorted(f for f in p.rglob("*.md") if f.is_file() and not any(
                part.startswith(".") or part == "Retracted" for part in f.relative_to(p).parts[:-1]))
        else:
            out.append(p)
    return out


def cmd_scrub(args) -> int:
    try:
        text = Path(args.path).read_text(encoding="utf-8")
    except OSError as e:
        print(f"synapse: cannot read {args.path}: {e}", file=sys.stderr)
        return 2
    new, findings = scrub(text)
    ok = not blocking(findings)
    if args.out:
        Path(args.out).write_text(new, encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": ok, "text": new, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        if not args.out:
            sys.stdout.write(new)
        for f in findings:
            print(f"line {f.line}: {f.outcome} {f.kind}: {f.message} ({f.excerpt})", file=sys.stderr)
    return 0 if ok else 1


def cmd_lint(args) -> int:
    notes = notes_in(args.paths)
    rows = []
    for p in notes:
        try:
            found = lint(p.read_text(encoding="utf-8"))
        except OSError as e:
            print(f"synapse: cannot read {p}: {e}", file=sys.stderr)
            return 2
        rows += [(p, f) for f in found]
    if args.json:
        print(json.dumps({"ok": not rows, "notes": len(notes),
                          "findings": [{"path": str(p), **asdict(f)} for p, f in rows]}, indent=2))
    elif rows:
        for p, f in rows:
            print(f"{p}:{f.line} {f.outcome} {f.kind}: {f.message} ({f.excerpt})")
    else:
        print(f"ok: {len(notes)} notes clean")
    return 1 if rows else 0


def add_parsers(sub) -> None:
    p = sub.add_parser("scrub", help="fix and flag what must not leave a personal note")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", help="write the scrubbed note here instead of stdout")
    p.set_defaults(func=cmd_scrub)
    p = sub.add_parser("lint", help="fail if a note is not safe to share as it is")
    p.add_argument("paths", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lint)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_parsers(parser.add_subparsers(dest="cmd", required=True))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
