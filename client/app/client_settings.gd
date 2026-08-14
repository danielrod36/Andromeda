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
var _path := PATH


func _ready() -> void:
	_cfg.load(_path)  # missing file is fine — defaults apply


## Tests redirect every read/write to a throwaway file so the developer's
## real user://settings.cfg is never touched.
func use_test_path() -> void:
	_path = "user://settings-test.cfg"
	_cfg = ConfigFile.new()
	_cfg.load(_path)


func get_value(key: String) -> Variant:
	var parts := key.split("/")
	if parts.size() < 2:
		push_warning("ClientSettings: malformed key '%s'" % key)
		return DEFAULTS.get(key)
	return _cfg.get_value(parts[0], parts[1], DEFAULTS.get(key))


func set_value(key: String, value: Variant) -> void:
	var parts := key.split("/")
	if parts.size() < 2:
		push_warning("ClientSettings: malformed key '%s'" % key)
		return
	_cfg.set_value(parts[0], parts[1], value)
	_save()
	changed.emit(key, value)


## Atomic save: write the whole document to a sibling tmp, then swap it in —
## a crash mid-write can never leave a truncated settings.cfg behind.
func _save() -> void:
	var tmp := _path + ".tmp"
	if _cfg.save(tmp) == OK and DirAccess.rename_absolute(tmp, _path) == OK:
		return
	_cfg.save(_path)  # tmp write or rename failed — a direct save beats none
