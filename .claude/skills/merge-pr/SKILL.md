---
name: merge-pr
description: Review and land a contributor's pull request to Omaphones — fetch it into a worktree, check it against the model invariant (a new model must not change what a working model is sent), fix it on the PR branch if needed, report and wait for the go-ahead, then merge with --no-ff in the house style, bump the version, deploy locally, and thank the contributor. Use when the user says "merge PR N", "we have new PRs", "check the pull requests", or invokes /merge-pr [N].
---

# Merge a pull request

`/merge-pr [N]` — without a number, `gh pr list` and take the oldest open one;
the user says which comes next.

The happy path is: review → fix on the PR branch → report → **wait for the
user's go-ahead** → merge → version → deploy → thank. Never merge or comment on
GitHub before the go-ahead, and never check a PR branch out in the plugin
directory — it is the live plugin and every file written there reloads it.

One fact shapes everything below: nobody has more than their own headphones.
The maintainer cannot test the contributor's model, the contributor cannot
test anybody else's, and every model in README's table works today on frames
that only its owner can retest. That is why the invariant exists, why a
review's own changes are always handed back to the contributor to confirm,
and why "ship only what the headset was seen to answer" is a rule and not a
preference.

Two rules that are not up for discussion in any PR: nothing a working model
is sent may change (check 1 below), and no `sudo`, `pacman`, `yay` or any
other install command or outside dependency lands anywhere in the repo —
not in README, not in a comment, not in an error message (checks 4 and 5).
A PR that has them is fixed on its branch, not merged as-is.

## 1. Fetch into a worktree

```bash
gh pr view N --json title,body,author,files
git fetch origin pull/N/head:pr-N
git worktree add "$SCRATCH/prN" pr-N        # $SCRATCH = the session scratchpad
```

Work in the worktree for everything until the merge itself.

## 2. Review

Read the whole diff (`git diff main pr-N -- . ':!docs/gallery'`), then run:

```bash
python3 -m unittest discover -s tests -p '*_test.py'
deno test --allow-read tests/model.test.js
python3 -m py_compile <every bridge the PR touched>
qmllint -I /usr/share/omarchy/shell DeviceFollower.qml Panel.qml   # Service.qml: typed IPC functions trip qmllint; ignore those lines
omarchy plugin validate .
grep -rn -i 'sudo\|pacman' --exclude-dir=.git .                    # must print nothing
```

Then check, in this order:

1. **The invariant** — a new model may not change what an existing one is
   sent. `git diff main -- tests/` must show only added cases: an edited frame
   in a pinned session (`tests/sony_bridge_test.py`,
   `tests/soundcore_bridge_test.py`) is the PR changing somebody's working
   headphones, and a PR that edits the pins to make its tests pass is the
   usual way this shows up. A new question to a headset (a new GET, a new
   query) belongs in a per-model row — `MODELS` in `soundcore-bridge` and
   `sony-bridge`, keyed by something known before the first frame goes out
   (vendor UUID suffix, reported name) — with the pinned models keeping their
   old row and `UNKNOWN` getting the wider behaviour. Prefer a list of
   known-safe models to gating on the new one.
2. **No guessed bytes** — a variant from a vendor table the headset never
   answered stays out of the code and of PROTOCOL.md. Comments that contradict
   each other about what was observed ("never asked for" next to "asked once")
   mean one of them was written before the hardware was; settle it.
3. **A pinned session for the new model**, asserting exact frames, in the
   bridge's test file, and a row in the README table plus a Gallery cell with a
   screenshot (`gallery-screenshot` skill).
4. **No new outside dependency** when the shell already has the thing:
   Quickshell services (`Quickshell.Services.Mpris`, `.Bluetooth`,
   `.Notifications`) over shelling out to a binary Omarchy does not install.
   Omarchy ships `python-gobject`, `python-dbus`, `bluez-utils`; nothing else
   may be assumed.
5. **Marketplace strings** — the listing's scanner greps literal `sudo` and
   `pacman` anywhere in the repo, README and comments included, and a hit
   forces manual review. Install instructions do not go in.
6. **Behaviour for everyone** — a change that applies to every device or every
   user (a new default-on setting, a new action on disconnect) is not covered
   by the invariant; name it in the report so the user decides.

## 3. Fix on the PR branch

Make the changes in the worktree and commit them on `pr-N` as one commit,
subject `Review: <what changed>`, body in the house style below, ending with
the `Co-Authored-By` and `Claude-Session` trailers. Do not rewrite the
contributor's commit. Rerun everything in step 2.

## 4. Report and wait

Tell the user: what the PR does, what was changed and why (the invariant
finding first), what could not be tested (their hardware), and anything from
check 6. Draft the merge commit message and the thank-you comment. Then stop
and wait for the go-ahead — this is the one step that must not be skipped.

## 5. Merge, version, deploy

In the plugin directory, on `main`:

```bash
git merge --no-ff pr-N -F msg           # subject: "Merge PR #N: <title in the house style>"
sed -i 's/"version": "X.Y.Z"/"version": "X.Y.Z+1"/' manifest.json   # the third number, always, unless the user says otherwise
git commit -am "Version X.Y.Z+1"
git push
omarchy restart shell
journalctl --user -n 50 | grep -i 'omaphones\|qml' # no QML errors
omarchy-shell omaphones status                       # the user's own devices still answer
git worktree remove "$SCRATCH/prN"; git branch -D pr-N
```

Pushing the merge marks the PR merged on GitHub. The version lives in
`manifest.json` only.

House style for the merge message (see `git log --merges`): first paragraph,
what lands and through which mechanism, with the contributor's handle;
then one paragraph per thing the PR decided that the merge does not, and why;
then what the tests pin; then the trailers. Plain sentences, no bullet lists.

## 6. Thank

Post the comment the user approved:

```bash
gh pr comment N --body-file thanks.md
```

A few sentences, addressed to the contributor by handle: what of theirs
landed, what was changed and the one-line reason, where it is now (the
version, `omarchy plugin update io.github.ncr.omaphones --yes`, `omarchy
restart shell`), and — always — a request to check it on their headphones,
naming exactly what to look for: the review changed code for a model nobody
here owns, so the contributor is the only test there is. Then, if the marketplace listing should follow, the verification
issue form on `HANCORE-linux/omarchy-plugin-marketplace` with the new
40-char SHA.
