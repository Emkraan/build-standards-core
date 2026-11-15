# Agent instructions: build-standards-core

This repo holds the Hermes agent tooling, the ops center code (including its own UI kit and tokens under
`opscenter/`) and the standards those two rely on. The shared web, shell and WPF standards live in the owner's standards repo,
not here. All consumer accounts belong to one owner, who has the final say.

If this machine is not yet a consumer (no Hermes cron job named `core-nightly` in
`hermes cron list`), follow [CONSUMING.md](CONSUMING.md) now. It registers the nightly job that
applies this standard to the Hermes desktop app (core skills, plugins such as rtk, the caveman skill,
settings) and to every consumer repo registered on the machine, then verifies it.

To change the standard, follow [CONTRIBUTING.md](CONTRIBUTING.md): work in your own git worktree,
never in the clone the nightly job pulls.
