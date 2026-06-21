---
name: gh-release
description: Create a new version release. Use when user asks to create a release, bump version, or publish a new version.
---
# Release Workflow

## Overview

Create a new version release by bumping the version, committing changes, creating a git tag, and pushing to remote. The CI/CD pipeline (`.github/workflows/ci.yml`) will automatically create the GitHub release.

## Prerequisites

- `uv` installed for version management
- Git repository with remote access
- CI workflow configured for release automation

## Workflow

### 1. Bump Version

Use `uv` to bump the version (major, minor, or patch):

```bash
# Bump minor version (0.6.0 -> 0.7.0)
uv version --bump minor

# Other options:
# uv version --bump major  # 0.6.0 -> 1.0.0
# uv version --bump patch  # 0.6.0 -> 0.6.1
```

This updates:
- `pyproject.toml` version field
- `uv.lock` lockfile

### 2. Commit Version Changes

Stage and commit the version bump:

```bash
git add -A
git commit -m "chore: bump version to X.Y.Z"
```

### 3. Create Git Tag

Create an annotated tag matching the version:

```bash
git tag vX.Y.Z
```

### 4. Push to Remote

Push both the commit and the tag:

```bash
# Push the commit
git push origin main

# Push the tag (triggers CI release)
git push origin vX.Y.Z
```

## Version Format

Follow Semantic Versioning (SemVer):

| Command | Result | When to use |
|---------|--------|-------------|
| `--bump major` | v1.2.3 → v2.0.0 | Breaking changes |
| `--bump minor` | v1.2.3 → v1.3.0 | New features |
| `--bump patch` | v1.2.3 → v1.2.4 | Bug fixes |

## Safety Checks

- Ensure working directory is clean before starting
- Verify the tag doesn't already exist: `git tag -l "vX.Y.Z"`
