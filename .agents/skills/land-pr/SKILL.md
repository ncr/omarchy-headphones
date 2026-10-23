---
name: land-pr
description: Review, repair and land Omaphones pull requests while preserving existing headphone behavior, owner evidence and release conventions. Use for /land-pr or requests to review or merge PRs in ncr/omarchy-headphones. A review request alone does not authorize publishing.
---

# Land an Omaphones PR

Nobody owns everybody else's headphones. Preserve each owner's working
conversation with their device. A green suite establishes the scenarios it
covers, not a guarantee against every regression.

This is the authoritative workflow for Codex and Claude. Read the current
repository `AGENTS.md`, `BRIDGE.md` and, for new models or brands,
`docs/CANONICAL-TESTS.md`. Repository paths below are relative to its root.
Read [history.md](references/history.md) when precedent or rationale matters;
historical exceptions do not override current rules.

## Scope and authorization

Identify the PR and requested endpoint: review, repair, merge/release, or
resuming owner testing. Without a number, list open PRs and start reviewing
the oldest unless context identifies another. Handle multiple PRs one at a
time against the base updated by the prior merge.

Investigation, an isolated checkout, checks, conflict rehearsal and concrete
drafts proceed immediately. If repairs are needed, present affected files,
behavior and validation before editing unless this session already authorizes
those repairs. Do not ask again for approved work.

Before publishing a merge, show the reviewed result, evidence limits and
intended version, and obtain the maintainer's go-ahead unless already given
for that result. Merge approval is separate from approval to post text: show
the exact public comment before posting and honor approval already given for
that wording. Permission to push a repair for testing is not permission to
merge it. Monitoring, marketplace issues, tags and GitHub Releases are not
automatic side effects.

## Review in isolation

The development path may resolve to the installed plugin. Check real paths,
branch, worktree status and remotes before writing. Every write under the
live plugin, including Git metadata or test output, can reload it. Prefer a
separate clone with its own Git metadata outside that directory. Do not check
out a PR or prepare a merge inside the running plugin.

Fetch the actual PR head and current upstream base. Record SHAs, author,
head repository/branch, maintainer-edit permission, comments, reviews and CI.
Do not assume `origin` is upstream in a fork or can push. Read the complete
diff from the merge base, then examine the resulting changes against current
upstream. Inspect binary screenshots visually. Rehearse conflict resolution
locally: a stale branch must not undo later fixes or lower the version.

Run `CHECK_BASE=<verified-upstream-base-ref> tools/check` in isolation.
Inspect failures and skipped lines. Check actual CI on the reviewed head:
a passing pin-owner workflow is not the test workflow passing; missing runs,
`action_required` and pending checks are not green.

Review what the command cannot establish:

- **Existing behavior:** compare model rows, startup queries, retries,
  fallback channels, delayed post-write queries, parser acceptance, process
  arguments and backend precedence. Full device UUID lists matter. A new
  model adds its own row and pin. Known models retain previous behavior;
  wider discovery belongs to `UNKNOWN`. Missing model information preserves
  legacy invocation behavior. Happy-path pins do not establish retry parity.
- **Owner contracts:** keep others' pins and captures intact. Inspect harness,
  assertion and test-selection changes: unchanged JSON cannot protect a
  weakened test. Structural refactoring must preserve inputs, expected
  outputs and checks. Changes to an existing model need tests of that change
  and owner confirmation; do not hide them in another model's PR or bypass
  the pin check.
- **Observed protocol:** trace parsed replies and advertised controls to the
  device's capture. Replay complete recorded RX frames where available rather
  than manufacturing them with the encoder under test. Label synthetic faults
  and boundary inputs separately. Do not invent missing/redacted bytes or
  promote unobserved vendor-table variants into support.
- **Coverage:** new models and brands follow applicable canonical scenarios:
  exposed controls, reported-state confirmation, battery shape, unsolicited
  reports, framing faults, silence/failure, reconnect and device isolation.
  Existing supported models do not owe a historical coverage retrofit.
  Identify unsupported and untested capabilities explicitly.
- **Shell integration:** check bridge exit/parking semantics, QML startup
  ordering, cleanup, keyboard handling and per-brand ranges/labels. Present
  changes affecting all users separately for the maintainer's decision. Use
  shell services instead of adding outside dependencies. The forbidden-command
  scan includes prose, comments and skills; do not add installation advice.
- **Product completeness:** README brands, model row, credits, gallery image,
  caption and links; manifest descriptions/aliases; protocol notes, contract
  and probe instructions. Battery wording must distinguish Fast Pair, bridge
  battery and BlueZ fallback. A screenshot proves visible UI, not wear
  detection, acoustic performance or hidden controls. Preserve real owner
  images and disclose cropping; never fabricate hardware evidence.

## Repair and obtain hardware evidence

Make approved repairs in isolation while preserving contributor commits.
Prefer focused `Review: <concrete change>` commits without rewriting their
history. Keep unrelated cleanup separate. For stale PRs, take the useful
contribution against current main and inspect the complete resulting diff.
A superseded PR may contribute evidence or an image without its obsolete
implementation being merged; preserve credit and report its actual disposition.

Rerun `tools/check` after repairs and meaningful conflict resolution. CI-only
portability failures belong in test doubles where appropriate, not production
behavior. Do not weaken owner checks to obtain a green run.

If a repair changes how the contributor's hardware is contacted or controlled,
have the owner test the repaired head before landing. Push to their actual PR
branch only with authorization and access. Give the exact SHA and a short
checklist of affected controls, connect/reconnect, reported results and
restoration. Record what they did not test. An earlier test of different code
does not validate the repair; documentation-only changes afterward do not
automatically invalidate the hardware result.

For an unchanged, documented contribution, the contributor's evidence can
supply hardware validation; no fictitious independent test is required.
If evidence is missing, complete independent review and prepare the concrete
owner request. Leave the PR/version pending rather than silently substituting
replay results for a required hardware test.

Use connected maintainer JBL/Sony only when available and hardware testing
is authorized. `tools/check-live` documents prerequisites and restoration;
reconnect interrupts audio. Take measurements without concurrent live plugin
writes. Mode persistence across refresh does not prove fresh Fast Pair battery
delivery. Disconnected headphones mean a test was not performed, not a pass.

## Present the result, then land

Report what lands, concrete regressions found/fixed, invariant evidence,
checks/skips, owner-tested revision and limits, conflicts, any shared behavior
requiring a decision, and the proposed version. Prepare the merge message and
exact public draft before requesting outstanding approval. Explain a pause
by linking the relevant instruction and naming missing approval or evidence.

After approval, recheck PR head and upstream base. If either changed, inspect
the delta and validate the resulting tree. Renew approval or hardware testing
only where the change invalidates the existing decision or evidence.

Prepare a normal merge in isolation, preserving contributor ancestry. House
style is `Merge PR #N: <what lands>`, followed by concise prose describing the
contribution/author, material review changes and evidence. Use truthful
attribution under current repository conventions; do not fabricate an agent
identity or a Claude session trailer when running in Codex.

Increment **only the third version component** unless the user specifies
otherwise. The version lives in `manifest.json`; use a separate
`Version X.Y.Z` commit. Explicitly stage intended files. Check the final tree
and version before pushing. A failed merge/revert stops the release sequence;
never bump and push as if that failed change had succeeded.

Push only the intended branch, without force. If upstream moved, integrate
and revalidate rather than overwrite it. Verify remote SHA, PR merged state,
manifest version and release CI. Report merge, release, local deployment and
marketplace status separately: a push does not establish all four.

## Local deployment and thanks

When local deployment is in scope, inspect the installed branch and dirty
state first. Do not replace unrelated work or switch away from an active
development branch. Preserve settings and bar placement. Do not unload the
plugin with `omarchy plugin disable` / `enable`: for a bar widget, disable
deletes its bar layout entry in `~/.config/omarchy/shell.json`, with its
position and per-widget settings (`useFastPair`), and enable inserts a bare
entry at the default place. Update the verified revision, then load it with
`omarchy-shell shell rescanPlugins`, which clears the QML component cache and
restarts plugin services without touching the configuration. The shell's
file watcher does not follow a symlinked plugin directory, so writing the
files alone may load nothing, and a re-enable without a rescan keeps the
cached QML. Avoid broad destructive copies. Check logs since deployment and
IPC readiness. A gallery-only change does not require a shell restart merely
to satisfy a ritual.

Post only the approved text, using a structured body or `--body-file` with
real newlines. Keep it short, natural and warm: thank the contributor by
handle, say what landed and its version, mention material adjustments only
when useful. Include focused hardware follow-up if something remains to
check; don't bury thanks in protocol details or request a test already
confirmed. Example tone, with facts adapted before approval:

> Thank you @author!! Merged as X.Y.Z :) Thanks for testing it on your
> headphones and including the protocol notes, tests and screenshot.

A comment that asks the contributor to do something (a capture, a fix, a
rebase, a screenshot) ends with "Easiest: copy the prompt below into your
coding agent" and a fenced prompt: numbered steps with the files, commands
and bytes involved, what not to touch, and what to report back — written so
a person can follow it as well as an agent.

Check whether the user already posted to avoid duplicating their reply.
Marketplace verification is separate: if requested, inspect the current
process and use the final full SHA, with approval for public text.

Finish with PR disposition, released version/SHA, checks, local state and
specific outstanding owner action. Remove only your own clean temporary
branches/checkouts once their work is safely retained. Preserve unfinished
repairs and SHAs while waiting for the owner.
