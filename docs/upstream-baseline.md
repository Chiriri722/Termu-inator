# Verify the Termu-inator upstream baseline

Termu-inator preserves a reproducible copy of Termux Browser Pilot before the
fork begins its architectural changes. Use the full commit ID below instead of
the README version label, because the upstream repository did not publish a
matching Git tag or GitHub release.

## Pinned baseline

| Item | Value |
| --- | --- |
| Fork | [`Chiriri722/Termu-inator`](https://github.com/Chiriri722/Termu-inator) |
| Upstream | [`salviz/termux-browser-pilot`](https://github.com/salviz/termux-browser-pilot) |
| Upstream branch | `main` |
| Baseline commit | `b95eccd3d1abc188c3aa488a23c519ebacc99fcf` |
| Baseline commit date | 2026-03-08 |
| Verification date | 2026-08-15 |
| Upstream tag or release | None published at verification time |
| Fork-owned local tag | `upstream-baseline/2026-03-08` |

On the verification date, local `upstream/main` and the live GitHub
`refs/heads/main` both resolved to the pinned commit. GitHub also reported
`Chiriri722/Termu-inator` as a public fork of `salviz/termux-browser-pilot` with
`main` as its default branch and MIT as its detected license.

The first fork-only commit was
`09b636a97a35042acb0de7f41858d965bc59963f` (`Work Plan add`). At the audit
snapshot, the baseline-to-fork relationship was zero upstream-only commits and
one fork-only commit. Later Termu-inator commits will increase the second
number; they don't change the pinned baseline.

## Verify the remote and commit

Run these commands from the repository root:

```bash
git remote get-url upstream
git ls-remote --symref upstream HEAD refs/heads/main 'refs/tags/*'
git cat-file -e b95eccd3d1abc188c3aa488a23c519ebacc99fcf^{commit}
git merge-base --is-ancestor \
  b95eccd3d1abc188c3aa488a23c519ebacc99fcf HEAD
git rev-list --left-right --count \
  b95eccd3d1abc188c3aa488a23c519ebacc99fcf...HEAD
```

The remote query should show both `HEAD` and `refs/heads/main` at
`b95eccd3d1abc188c3aa488a23c519ebacc99fcf`. An empty upstream tag section is
expected unless upstream publishes tags after the verification date. The fork
keeps its own annotated baseline tag. Verify its peeled target with:

```bash
git cat-file -t refs/tags/upstream-baseline/2026-03-08
git rev-parse upstream-baseline/2026-03-08^{}
```

The first command must print `tag`, and the second must print the full baseline
commit ID. The earlier `cat-file` and `merge-base` commands exit successfully
when the baseline object exists and is an ancestor of the current fork.

To review every fork change without checking out or overwriting files, run:

```bash
git diff --stat \
  b95eccd3d1abc188c3aa488a23c519ebacc99fcf..HEAD
git log --oneline --decorate \
  b95eccd3d1abc188c3aa488a23c519ebacc99fcf..HEAD
```

To confirm the GitHub fork relationship when the GitHub CLI is authenticated,
run:

```bash
gh repo view Chiriri722/Termu-inator \
  --json nameWithOwner,isFork,parent,defaultBranchRef,licenseInfo
```

These commands only inspect repository state. `git ls-remote` and `gh repo
view` require network access; the remaining commands use local objects.

## Treat the current version labels as upstream inconsistencies

The preserved upstream files disagree about the baseline version:

- `README.md` identifies the project as `Termux Browser Pilot v0.17.1`.
- `pyproject.toml` declares package version `0.1.0a1`.
- The initial upstream commit message calls the release `v0.1.0-alpha`.
- Upstream had no Git tags and no GitHub release at verification time.

Don't infer a release tag from any of those labels. Until the fork publishes
its own release, the full baseline commit ID is the reproducible identifier.
The fork-owned `upstream-baseline/2026-03-08` tag intentionally avoids
inventing an upstream semantic version. It is a local verification ref until
it is deliberately published to the fork remote.

The preserved baseline also retains the package name `termux-browser-pilot`,
the `tbp` and `tbp-mcp` commands, and the upstream README's Cloudflare and
stealth claims. They describe the inherited code and compatibility surface;
they aren't proof that Termu-inator has independently validated those claims.
Branding and compatibility changes should be documented as fork changes after
this baseline.

## Preserve upstream attribution

The upstream MIT license and its copyright notice remain unchanged in
[`LICENSE`](../LICENSE). [`NOTICE.md`](../NOTICE.md) records the fork source and
baseline so attribution stays visible in clones and source distributions, not
only on the GitHub fork page.
