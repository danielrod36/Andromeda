extends Node
## Autoload: ClientSettings — client-local prefs in user://settings.cfg
## (spec §6). Client-owned only: never game truth, never server-owned values.

signal changed(key: String, value: Variant)

const PATH := "user://settings.cfg"

const DEFAULTS := {
	"reading/text_speed": "medium",  # slow | medium | fast | instant
	"reading/ambient_life": true,
	"reading/reduced_motion": false,
	"audio/master": 0.7,
	"audio/music": 0.55,
	"audio/effects": 0.8,
	"ui/last_played_pack": "",
}

var _cfg := ConfigFile.new()


func _ready() -> void:
	_cfg.load(PATH)  # missing file is fine — defaults apply


func get_value(key: String) -> Variant:
	var parts := key.split("/")
	return _cfg.get_value(parts[0], parts[1], DEFAULTS.get(key))


func set_value(key: String, value: Variant) -> void:
	var parts := key.split("/")
	_cfg.set_value(parts[0], parts[1], value)
	_cfg.save(PATH)
	changed.emit(key, value)
