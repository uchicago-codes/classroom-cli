#!/usr/bin/env python3
"""
Per-student assignment repositories, replacing GitHub Classroom.

GitHub Classroom was decommissioned on 2026-08-28. This reproduces the part
of it most courses used: one private repo per student per assignment, created
from a template or empty, with staff access through a GitHub team.

Typical sequence
----------------

  Once a quarter, and whenever a TA joins or leaves:

    1.  classroom.py --team
        Creates the staff team named in the roster if it does not exist, and
        makes its membership match the staff list. This is what gives you and
        your TAs access to every student repo.

    2.  classroom.py --roster
        Checks every GitHub username is real, nobody is listed twice, and the
        team matches the roster. Changes nothing. --create runs this itself,
        so this step is for looking before you leap.

  Per assignment:

    3.  classroom.py --create --name assignment-3
        One empty private repo per student, with a README.

    3b. classroom.py --create --name assignment-3 --template <template-repo>
        The same, but populated from a template repo. Use this when students
        need starter code.

    4.  classroom.py --status --name assignment-3
        Who accepted the invitation, who has pushed, and when. Run it the
        morning after the deadline.

  Before doing any of that for real:

    classroom.py --create --name apitest --only yourhandle
        One throwaway repo for yourself, to confirm the whole path works.
        Delete it in the GitHub UI afterwards; this script cannot.

  Add --dry-run to --team or --create to see the plan and send nothing.

Other useful forms
------------------

    classroom.py --create --name final-project        # any name, not just assignments
    classroom.py --create --name assignment-3 --only jdoe   # a student who enrolled late
    classroom.py --status --name assignment-3 --only jdoe   # one student

Repo names are <course>-<year>-<term>-<name>-<github username>, with the first
three read from the roster: --name assignment-3 gives
cs101-2026-autumn-assignment-3-octocat.

Commands act for real. Nothing here can delete or overwrite a student repo.

Authentication comes from the gh CLI, so there is no second token to manage.
Run `gh auth status` if calls start failing.
"""

import argparse, json, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

class C:
    """
    ANSI codes, blank when output is not a terminal.

    Colour is decoration, so it has to disappear cleanly when piped to a file
    or a pager, and when NO_COLOR is set.
    """
    _on = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    BOLD  = "\033[1m"  if _on else ""
    DIM   = "\033[2m"  if _on else ""
    RED   = "\033[31m" if _on else ""
    GREEN = "\033[32m" if _on else ""
    AMBER = "\033[33m" if _on else ""
    BLUE  = "\033[34m" if _on else ""
    CYAN  = "\033[36m" if _on else ""
    OFF   = "\033[0m"  if _on else ""


def colour_help(text: str) -> str:
    """
    Highlight the commands and section headings in the help text.

    The help lives in the module docstring so it stays readable in the source
    and in `pydoc`. Colour is applied on the way out, and only to a terminal.
    """
    if not C._on:
        return text

    # Section headings, marked by a rule of dashes underneath.
    text = re.sub(r"^(\S[^\n]*)\n(-{3,})$",
                  lambda m: f"{C.BOLD}{m.group(1)}{C.OFF}\n{C.DIM}{m.group(2)}{C.OFF}",
                  text, flags=re.M)

    # Command lines, with any trailing comment dimmed rather than coloured.
    def cmd(m):
        body, comment = m.group(1).rstrip(), m.group(2) or ""
        out = f"{C.CYAN}{body}{C.OFF}"
        return out + (f"  {C.DIM}{comment.strip()}{C.OFF}" if comment else "")

    text = re.sub(r"(classroom\.py[^\n#]*)(#[^\n]*)?", cmd, text)

    # The naming rule, in the prose under the examples. <placeholders> in
    # amber so the shape is readable at a glance, and the literal example in
    # cyan to match the command lines above it.
    text = re.sub(r"(<[a-z][a-z ]*>)", f"{C.AMBER}\\1{C.OFF}", text)
    # Only the prose occurrence. A general rule would match inside the command
    # lines already wrapped above, nesting codes and cutting their colour short.
    text = text.replace(
        "roster: --name assignment-3 gives",
        f"roster: {C.CYAN}--name assignment-3{C.OFF} gives")
    text = text.replace(
        "cs101-2026-autumn-assignment-3-octocat",
        f"{C.CYAN}cs101-2026-autumn-assignment-3-octocat{C.OFF}")
    return text


def head(text: str) -> None:
    print(f"\n{C.BOLD}{C.BLUE}{text}{C.OFF}")


def ok(text: str) -> None:
    print(f"  {C.GREEN}\u2713{C.OFF}  {text}")


def warn_(text: str) -> None:
    print(f"  {C.AMBER}\u26a0{C.OFF}  {C.AMBER}{text}{C.OFF}")


def bad(text: str) -> None:
    print(f"  {C.RED}\u2717{C.OFF}  {C.RED}{text}{C.OFF}")


def note(text: str) -> None:
    print(f"  {C.DIM}{text}{C.OFF}")


# Everything course-specific lives in the roster file, so this script is
# portable between courses and institutions without editing the source.
# There are deliberately no fallbacks for the organisation or the course:
# guessing either would create repos in the wrong place.
STAFF_TEAM = "instructors"
REQUIRED = ("org", "course", "year", "term")
# Beside the script by default. --roster-file points somewhere else, so the
# roster can live in a course repo while the script lives in its own.
ROSTER = Path(__file__).resolve().parent / "roster.yml"


def shown(p: Path) -> str:
    """A path as the user would type it: relative to here if it can be."""
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------- gh

def gh(*args: str, check: bool = True) -> tuple[int, str]:
    """Run a gh command. Returns (returncode, stdout)."""
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"gh {' '.join(args[:3])} failed:\n  {r.stderr.strip()[:400]}")
    return r.returncode, r.stdout


def api(path: str, method: str = "GET", check: bool = True, **fields) -> dict | list | None:
    args = ["api", path, "-X", method]
    for k, v in fields.items():
        args += ["-f", f"{k}={v}"] if isinstance(v, str) else ["-F", f"{k}={json.dumps(v)}"]
    code, out = gh(*args, check=check)
    if code:
        return None
    try:
        return json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- roster

SAMPLE = """org: your-github-org
course: cs101
year: 2026
term: autumn

# Instructors and TAs. Everyone here gets push on every student repo, via
# the GitHub team named below.
team: instructors
staff:
  - github: yourhandle
    name: Your Name
    role: instructor
  - github: someta
    name: A Teaching Assistant
    role: ta

students:
  - cnetid: cat
    name: Octo Cat
    github: octocat
"""


def org() -> str:
    """The GitHub organisation, from the roster."""
    return load_roster()["org"]


def load_roster() -> dict:
    if not ROSTER.exists():
        sys.exit(
            f"No roster at {shown(ROSTER)}\n\n"
            f"{SAMPLE}\n"
            "  It is gitignored: student names paired with identifiers are\n"
            "  educational records. Remove the line from .gitignore if you\n"
            "  want it versioned."
        )
    import yaml
    try:
        data = yaml.safe_load(ROSTER.read_text()) or {}
    except yaml.YAMLError as e:
        sys.exit(f"{shown(ROSTER)} is not valid YAML\n  {e}")

    if not isinstance(data, dict):
        sys.exit(f"{shown(ROSTER)} should be a mapping with "
                 f"'staff' and 'students' keys.")
    data.setdefault("staff", [])
    data.setdefault("students", [])
    data.setdefault("team", STAFF_TEAM)
    missing = [k for k in REQUIRED if not str(data.get(k) or "").strip()]
    if missing:
        sys.exit(f"{shown(ROSTER)} is missing: {', '.join(missing)}\n"
                 f"  Every roster needs org, course, year and term. See "
                 f"roster.example.yml.")
    return data


def course_prefix(data: dict) -> str:
    """cs101-2026-autumn, matching the repos the old Classroom made."""
    return f"{data['course']}-{data['year']}-{data['term']}"


def students(only: str | None = None) -> list[dict]:
    """
    The students to act on.

    --only narrows to one person and will match staff as well, so the
    instructor can create a throwaway repo for themselves to check the
    whole path works before running it for a class.
    """
    data = load_roster()
    rows = data["students"]

    if only:
        pool = rows + data["staff"]
        match = [r for r in pool
                 if str(r.get("github", "")).lower() == only.lower()]
        if not match:
            names = ", ".join(sorted(str(r.get("github")) for r in pool
                                     if r.get("github")))
            sys.exit(f"'{only}' is not in the roster.\n  Roster has: {names}")
        return match

    if not rows:
        sys.exit(f"{shown(ROSTER)} lists no students.")
    return rows


def check_one(person: dict, need: tuple[str, ...], seen: dict, kind: str,
              quiet: bool = False) -> int:
    """Validate one roster entry. Returns the number of problems found."""
    user = str(person.get("github") or "").strip()
    name = str(person.get("name") or "").strip()

    blank = [f for f in need if not str(person.get(f) or "").strip()]
    if blank:
        bad(f"{name or '(no name)'}: missing {', '.join(blank)}")
        return 1
    if user.lower() in seen:
        bad(f"{user}: listed twice, already a {seen[user.lower()]}")
        return 1
    seen[user.lower()] = kind

    # A typo here silently creates a repo nobody can reach.
    if api(f"users/{user}", check=False) is None:
        bad(f"{user} is not a GitHub account  ({name})")
        return 1

    if not quiet:
        extra = person.get("role") or person.get("cnetid") or ""
        ok(f"{C.DIM}{kind:<8}{C.OFF} {user:<20} {C.DIM}{extra}{C.OFF}")
    return 0


def check_roster(quiet: bool = False) -> tuple[int, int]:
    data = load_roster()
    staff, studs = data["staff"], data["students"]
    if not quiet:
        head(f"\U0001F4CB  {shown(ROSTER)}")
        note(f"{course_prefix(data)}   team {data['team']}   "
             f"{len(staff)} staff, {len(studs)} students")
        print()

    # Bad rows are fatal: a typo creates a repo nobody can reach, and this
    # script cannot delete one.
    seen: dict[str, str] = {}
    fatal = sum(check_one(p, ("github", "name"), seen, "staff", quiet)
                for p in staff)
    fatal += sum(check_one(p, ("github", "name", "cnetid"), seen, "student", quiet)
                 for p in studs)
    warn = 0

    print()
    # The team is what actually grants staff access, so a mismatch between the
    # file and GitHub means someone has access they should not, or lacks it.
    if not team_exists(data["team"]):
        # Listing every member as "not in team" would be true but useless.
        bad(f"team '{data['team']}' does not exist in {org()}")
        note(f"   run:  python3 {Path(__file__).name} --team")
        fatal += 1
    else:
        actual = {m["login"].lower() for m in
                  (api(f"orgs/{org()}/teams/{data['team']}/members?per_page=100",
                       check=False) or [])}
        listed = {str(p.get("github", "")).lower() for p in staff if p.get("github")}
        # Drift is worth knowing but does not corrupt anything, so it warns
        # rather than blocking a create.
        for extra in sorted(actual - listed):
            warn_(f"in team, not in roster:  {extra}")
            warn += 1
        for missing in sorted(listed - actual):
            warn_(f"in roster, not in team:  {missing}")
            warn += 1

    if not quiet:
        print()
        if fatal:
            bad(f"{fatal} problem(s), {warn} warning(s)")
        elif warn:
            warn_(f"{warn} warning(s), no problems")
        else:
            ok(f"{C.GREEN}roster and team agree{C.OFF}")
    return fatal, warn


# ---------------------------------------------------------------- naming

def base_name(name: str | None) -> str:
    """
    --name assignment-3  ->  cs101-2026-autumn-assignment-3

    The course, year and term come from the roster, so the name is only the
    part that changes. Matches both shapes the old Classroom produced:
    assignment-8 and final-project.
    """
    if not name:
        sys.exit("Give --name, for example:  --name assignment-3")
    return f"{course_prefix(load_roster())}-{name}"


def repo_name(base: str, user: str) -> str:
    return f"{base}-{user}"


# ---------------------------------------------------------------- team

def team_exists(team: str) -> bool:
    return api(f"orgs/{org()}/teams/{team}", check=False) is not None


def cmd_team(do_it: bool) -> None:
    """
    Create the staff team if absent and make its membership match the roster.

    The team is what grants staff access to every student repo, so it is
    course structure rather than routine work: set up once, like the Canvas
    scaffold, not re-asserted on every push.
    """
    data = load_roster()
    team = data["team"]
    want = {str(p["github"]).lower(): p for p in data["staff"] if p.get("github")}

    exists = team_exists(team)
    have = {m["login"].lower() for m in
            (api(f"orgs/{org()}/teams/{team}/members?per_page=100", check=False) or [])}

    head(f"\U0001F465  team '{team}'  {C.DIM}in {org()}{C.OFF}")
    (ok if exists else warn_)("exists" if exists else "does not exist, will be created")
    for u in sorted(want - have if isinstance(want, set) else set(want) - have):
        print(f"  {C.GREEN}+{C.OFF}  add     {u}")
    for u in sorted(have - set(want)):
        print(f"  {C.RED}-{C.OFF}  remove  {u}")
    if exists and not (set(want) - have) and not (have - set(want)):
        ok("membership already matches the roster")

    if not do_it:
        print(f"\n  {C.DIM}Dry run. Nothing was changed. "
              f"Drop --dry-run to execute.{C.OFF}")
        return

    if not exists:
        api(f"orgs/{org()}/teams", "POST", name=team,
            description=f"{data['course']} staff", privacy="closed")
        ok(f"created team '{team}'")

    for u in sorted(set(want) - have):
        api(f"orgs/{org()}/teams/{team}/memberships/{want[u]['github']}", "PUT",
            role="maintainer" if want[u].get("role") == "instructor" else "member",
            check=False)
        ok(f"added   {want[u]['github']}")
    for u in sorted(have - set(want)):
        api(f"orgs/{org()}/teams/{team}/memberships/{u}", "DELETE", check=False)
        ok(f"removed {u}")


# ---------------------------------------------------------------- create

def repo_exists(full: str) -> bool:
    return api(f"repos/{full}", check=False) is not None


def create_one(base: str, user: str, template: str | None, team: str) -> str:
    """Create one student repo. Returns what happened."""
    full = f"{org()}/{repo_name(base, user)}"

    # Never touch an existing repo. It may hold submitted work, and nothing
    # here should be able to destroy that.
    if repo_exists(full):
        return "exists, skipped"

    if template:
        made = api(f"repos/{org()}/{template}/generate", "POST",
                   owner=org(), name=repo_name(base, user), private=True)
        if made is None:
            return f"FAILED: could not generate from {template}"
    else:
        # auto_init so the first clone is not a bare repo.
        made = api(f"orgs/{org()}/repos", "POST",
                   name=repo_name(base, user), private=True, auto_init=True)
        if made is None:
            return "FAILED: could not create"

    # The student: push, not admin, so they cannot delete their own submission.
    api(f"repos/{full}/collaborators/{user}", "PUT", permission="push", check=False)

    # Staff via the team, so adding or removing a TA is one membership change
    # rather than a loop over every repo in the course.
    granted = api(f"orgs/{org()}/teams/{team}/repos/{full}", "PUT",
                  permission="push", check=False)
    if granted is None and not team_exists(team):
        # Should be unreachable: cmd_create checks first. Never leave a repo
        # with no staff access and no warning.
        return "created, BUT STAFF TEAM GRANT FAILED"

    return "created" + (f" from {template}" if template else " empty")


def cmd_create(base: str, template: str | None, do_it: bool,
               only: str | None = None) -> None:
    data = load_roster()
    rows, team = students(only), data["team"]

    # Validate before making thirty repos from a bad roster.
    head("\U0001F50D  checking the roster")
    fatal, warn = check_roster(quiet=True)
    if fatal:
        sys.exit("\n  Roster has problems. Run --roster to see them in full.\n"
                 "  Nothing was created.")
    if warn:
        warn_(f"{warn} warning(s); run --roster for detail")
    else:
        ok("roster ok")

    if template and not repo_exists(f"{org()}/{template}"):
        sys.exit(f"No template repo {org()}/{template}")

    # Without the team, every repo would be created with no staff access and
    # the failure would be silent.
    if not team_exists(team):
        sys.exit(f"No team '{team}' in {org()}.\n"
                 f"  Run:  python3 {Path(__file__).name} --team")

    head(f"\U0001F4E6  {len(rows)} repo(s): {C.CYAN}{base}-<username>{C.OFF}")
    note(f"from      {template or 'empty repo with a README'}")
    note(f"student   collaborator, push")
    note(f"staff     team '{team}', push")
    note(f"private   yes")
    print()

    for r in rows:
        note(f"{r['github']:<20} {repo_name(base, r['github'])}")

    if not do_it:
        print(f"\n  {C.DIM}Dry run. Nothing was created. "
              f"Drop --dry-run to execute.{C.OFF}")
        return

    print()
    counts: dict[str, int] = {}
    for r in rows:
        what = create_one(base, r["github"], template, team)
        counts[what.split(":")[0]] = counts.get(what.split(":")[0], 0) + 1
        (bad if "FAIL" in what else ok if "created" in what else note)(
            f"{r['github']:<20} {what}")
    print()
    ok(", ".join(f"{v} {k}" for k, v in counts.items()))


# ---------------------------------------------------------------- status

def cmd_status(base: str, only: str | None = None) -> None:
    rows = students(only)
    head(f"\U0001F4CA  {C.CYAN}{base}-<username>{C.OFF}")
    print()

    for r in rows:
        user = r["github"]
        full = f"{org()}/{repo_name(base, user)}"
        info = api(f"repos/{full}", check=False)
        if info is None:
            bad(f"{user:<20} no repo")
            continue

        commits = api(f"repos/{full}/commits?per_page=100", check=False) or []
        n = len(commits)
        last = commits[0]["commit"]["author"]["date"] if commits else None

        invited = api(f"repos/{full}/invitations", check=False) or []
        pending = any(i.get("invitee", {}).get("login", "").lower() == user.lower()
                      for i in invited)

        flags = []
        if pending:
            flags.append("invite not accepted")
        if n <= 1:
            flags.append("nothing pushed")
        when = last[:16].replace("T", " ") if last else "-"
        line = (f"{user:<20} {C.BOLD}{n:>3}{C.OFF} commits   "
                f"{C.DIM}last {when}{C.OFF}")
        if flags:
            warn_(f"{line}   {'  '.join(flags)}")
        else:
            ok(line)


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="classroom.py", description=colour_help(__doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter)

    cmd = ap.add_mutually_exclusive_group(required=True)
    cmd.add_argument("--roster", action="store_true",
                     help="validate the roster against GitHub; changes nothing")
    cmd.add_argument("--team", action="store_true",
                     help="create the staff team and sync it to the roster")
    cmd.add_argument("--create", action="store_true",
                     help="create one private repo per student")
    cmd.add_argument("--status", action="store_true",
                     help="who has accepted and pushed")

    ap.add_argument("--name", metavar="NAME",
                    help="what this is, e.g. assignment-3 or final-project. "
                         "The course, year and term are prepended from the roster "
                         "and the student's username appended")
    ap.add_argument("--template", metavar="REPO",
                    help="with --create: template to generate from; omit for empty")
    ap.add_argument("--only", metavar="USER",
                    help="act on one person from the roster, staff included. "
                         "Use it to create a throwaway repo for yourself and "
                         "check the whole path works before running a class")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and change nothing")
    ap.add_argument("--roster-file", metavar="PATH", type=Path,
                    help="roster to use instead of roster.yml beside the script")
    a = ap.parse_args()

    global ROSTER
    if a.roster_file:
        ROSTER = a.roster_file

    if a.roster:
        sys.exit(1 if check_roster()[0] else 0)
    elif a.team:
        cmd_team(not a.dry_run)
    else:
        base = base_name(a.name)
        if a.create:
            cmd_create(base, a.template, not a.dry_run, a.only)
        elif a.status:
            cmd_status(base, a.only)


if __name__ == "__main__":
    main()
