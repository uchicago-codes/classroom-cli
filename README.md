# classroom.py

A small replacement for the parts of GitHub Classroom most courses actually
used: one private repository per student per assignment, created from a
template or empty, with teaching staff given access through a GitHub team.

GitHub Classroom was decommissioned on 28 August 2026 and its data deleted on
4 September. This is not a replacement for all of it. There is no web UI, no
autograding, and no student-facing "accept assignment" link. What it does is
the repository administration, from one file you control.

Two files, no service to run, no account to create:

```
classroom.py     the script
roster.yml       your course, staff and students
```

## Install

```bash
git clone https://github.com/uchicago-codes/classroom-cli.git
cd classroom-cli
pip install -r requirements.txt
cp roster.example.yml roster.yml     # then edit it
```

## What it does

| Command | Reads or writes | |
|---|---|---|
| `--roster` | reads | Validates the roster and reconciles it against GitHub |
| `--team` | writes | Creates the staff team, syncs its membership to the roster |
| `--create` | writes | One private repo per student, template or empty |
| `--status` | reads | Who accepted the invite, who has pushed, and when |

## Requirements

- **Python 3.10+** with `PyYAML` (`pip install pyyaml`)
- **The `gh` CLI**, authenticated: `gh auth login`. The script shells out to
  `gh`, so there is no second token to manage.
- **Admin on a GitHub organisation.** Student repos are created there.

### A note on cost

Private repositories are free on any plan, but **outside collaborators with
access to them normally consume a paid seat** on GitHub Team. At $4 per user
per month, a class of 30 is around $120 a month, and it scales with every
cohort you add.

Check before you run this on a departmental or personal organisation:

```
https://github.com/organizations/YOUR-ORG/settings/billing
```

Many universities have a GitHub Education or Campus arrangement that covers
this. The organisation this was written for shows GitHub Team at 100% off, so
it costs nothing — which is exactly the kind of thing that is invisible until
someone else tries it on an org without the grant.

There is no API that reports Education status; the billing page is the only
place to look.

## Setup

**1. Check your organisation's default permission.**

```bash
gh api orgs/YOUR-ORG --jq .default_repository_permission
```

This must be `none`. Anything else grants every org member access to every
repository, which means students could read each other's work. This is the
single most important setting here and the easiest to get wrong.

**2. Write `roster.yml`, beside the script.** Start from
`roster.example.yml`. `org`, `course`, `year` and `term` are required; the
script refuses to run without them rather than guess where to create repos. To
keep the roster somewhere else, such as a course repository, pass
`--roster-file path/to/roster.yml` on every command.

```yaml
org: your-github-org
course: cs101
year: 2026
term: autumn
team: cs101-staff-2026-autumn

staff:
  - github: yourhandle
    name: Your Name
    role: instructor
  - github: ta-handle
    name: A TA
    role: ta

students:
  - cnetid: jdoe
    name: Jane Doe
    github: jdoe-gh
```

`cnetid` is whatever internal identifier your institution uses; the script only
checks it is present. `github` must be the student's actual GitHub username.

**3. Keep the roster out of version control.** Student names paired with
identifiers are educational records. `roster.yml` is already in this repo's
`.gitignore`; if you keep it elsewhere, ignore it there too.

## Typical use

```bash
# Once a quarter, and when a TA joins or leaves
python3 classroom.py --team

# Look before you leap
python3 classroom.py --roster

# One throwaway repo for yourself, to confirm it all works
python3 classroom.py --create --name apitest --only yourhandle

# Per assignment
python3 classroom.py --create --name assignment-3
python3 classroom.py --create --name assignment-3 --template starter-repo
python3 classroom.py --status --name assignment-3
```

`--dry-run` works on `--team` and `--create`.

Repositories are named `<course>-<year>-<term>-<name>-<github username>`, so
`--name assignment-3` gives `cs101-2026-autumn-assignment-3-jdoe-gh`. `--name`
takes anything: `final-project`, `midterm`, `lab-2`.

## How students get access

Each student is added to their own repository as a collaborator with **push**,
not admin, so they cannot delete their own submission. GitHub emails them an
invitation they must accept before they can see it.

That invitation is the closest thing to Classroom's accept link, and it is the
most common first-week problem. `--status` reports who has not accepted.

**You need students' GitHub usernames before you can create anything.**
Classroom collected these through its accept flow. Without it, you have to ask
— an LMS survey on day one works.

## How staff get access

Through the team named in `roster.yml`, not by adding people to each
repository. `--team` creates it and keeps its membership matching the file.

This matters more than it sounds. A course with 30 students and 8 assignments
is 240 repositories. Adding a TA in week four means one membership change, not
240 collaborator invitations — and removing one at the end of term actually
revokes access rather than leaving 240 stale grants behind.

`--roster` reports drift in both directions: someone in the team who is not in
the file, and someone in the file who is not in the team.

## What it will not do

**It cannot delete or overwrite a repository.** `--create` skips any repo that
already exists and there is no force flag. A student repository may hold
submitted work, and no convenience is worth risking that. Delete by hand, in
the GitHub UI, if you really mean to.

**It does not collect submissions.** Cloning everything for grading is a
different job with different needs — every branch, feedback pushed back,
rubrics — and belongs in its own tool.

**It does not do autograding.** Put a GitHub Actions workflow in your template
repository; every generated repo inherits it.

**It has no accept link.** See above.

## Safety

The checks exist because the failure modes are quiet rather than loud.

- `--create` validates the roster first. A GitHub username that does not exist,
  a blank field, or someone listed twice blocks the run. A typo would otherwise
  create a repository nobody can reach, and you would find out in week three.
- Team membership drift warns but does not block. It is worth knowing about and
  does not make new repositories wrong.
- A missing team blocks. Without it, every repository would be created with no
  staff access at all, silently.
- `--dry-run` prints the full plan and sends nothing.

Colour output respects `NO_COLOR` and turns itself off when piped.

## Adapting it

Everything course-specific is in `roster.yml`, including the organisation, so
the script should not need editing. If your institution uses a different
identifier than `cnetid`, that field is not validated beyond being present.

## License

MIT. See [LICENSE](LICENSE).
