class_name Paths
extends RefCounted
## Repo layout (spec §3): client/ is the Godot project; the repo root — where
## `uv run python -m src.server` runs — is its parent directory.


static func repo_root() -> String:
	return ProjectSettings.globalize_path("res://").path_join("..").simplify_path()
