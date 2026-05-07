# standards

Shared development standards for all projects. Contains a single `CLAUDE.md` with universal rules that apply regardless of project domain or stack.

## Usage

Add this repo as a submodule at `.standards/` in any project:

```bash
git submodule add https://github.com/specie77/standards.git .standards
```

Then import it at the top of the project's `CLAUDE.md`:

```
@.standards/CLAUDE.md
```

Add any project-specific instructions below the import line.

## Updating standards

1. Edit `CLAUDE.md` in this repo and push to GitHub.
2. In each project repo that uses the submodule:

```bash
git submodule update --remote .standards
git add .standards
git commit -m "chore: update shared standards"
git push
```

Never edit `.standards/CLAUDE.md` directly from within a project repo.
