# Agent instructions: build-standards-core

This repo is the shared build standard for every consumer account. All consumer accounts belong to
one owner, who has the final say.

If this machine is not yet a consumer (no Hermes cron job named `core-nightly` in
`hermes cron list`), follow [CONSUMING.md](CONSUMING.md) now. It registers the nightly job that
applies this standard to the Hermes desktop app (core skills, plugins such as rtk, the caveman skill,
settings) and to every UI consumer repo, then verifies it.

To change the standard, follow [CONTRIBUTING.md](CONTRIBUTING.md): work in your own git worktree,
never in the clone the nightly job pulls.
