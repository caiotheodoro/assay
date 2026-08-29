# Changelog fragments

One file per workstream, merged into `../CHANGELOG.md` by
`scripts/merge_changelog.py`.

This exists because `CHANGELOG.md` is the file every workstream wants to append
to, which makes it the worst merge conflict in the repo — and the conflict
lands on the record of what was tried, which is the part a reader trusts.

Name fragments `NN-slug.md`, ordered by `NN`. Each row keeps the shape of the
main table:

```
| Stage | What was tried and why | Evidence | Decision / learning |
```

Evidence is a command someone else can run, or a path to a result file. Not a
description of a command.
