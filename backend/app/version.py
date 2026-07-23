"""Single source of the app's semantic version (keep in sync with pyproject.toml).

Release *identity* on a running instance is `version` + `git_sha` (the exact build),
surfaced by `/health` — see docs/deploy.md.
"""
__version__ = "0.1.0"
