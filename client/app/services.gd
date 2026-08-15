extends Node
## Autoload: Services — the boot-time singletons (spec §6): SidecarProcess +
## EngineClient, set up by main.gd. Screens read Services.client.

var sidecar: SidecarProcess
var client: EngineClient
var overlay: OverlayLayer


func shutdown() -> void:
	if sidecar != null:
		sidecar.kill()
