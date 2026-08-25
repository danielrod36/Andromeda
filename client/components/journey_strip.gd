class_name JourneyStrip
extends HBoxContainer
## The chargen journey strip (mockup 06 .journey): ORIGIN·POOL·ASSIGN·…
## Seven segments; past segments are dimmed, the current one wears a ▸
## marker in accent, future segments sit at 55%. Player-facing names only —
## the server's phase keys are mapped here and never shown (spec pin 5).

const SEGMENTS: Array[String] = [
	"ORIGIN", "POOL", "ASSIGN", "BACKGROUND", "CAREER", "TERMS", "MUSTER"
]

## Phase → journey segment (plan §phase table). ORIGIN is the Ceremony —
## it precedes the shell, so it is done for every chargen phase.
const SEGMENT_BY_PHASE := {
	"roll_characteristics": "POOL",
	"assign_characteristics": "ASSIGN",
	"choose_background_skills": "BACKGROUND",
	"choose_career": "CAREER",
	"choose_qualification_fallback": "CAREER",
	"choose_career_change": "CAREER",
	"run_survival": "TERMS",
	"choose_commission": "TERMS",
	"choose_advancement": "TERMS",
	"choose_skills": "TERMS",
	"choose_specialization": "TERMS",
	"choose_basic_training_skill": "TERMS",
	"run_aging": "TERMS",
	"choose_aging_reduction": "TERMS",
	"mishap_roll": "TERMS",
	"choose_injury_stat": "TERMS",
	"choose_crisis_resolution": "TERMS",
	"re_enlist": "TERMS",
	"mustering_out": "MUSTER",
	"muster_out_allocate": "MUSTER",
}

var _theme: PackTheme


func setup(t: PackTheme) -> void:
	_theme = t
	add_theme_constant_override("separation", 0)


## Redraws the strip for a session phase. Unknown phases and "complete"
## show the whole journey as done.
func set_phase(phase: String) -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()
	var done_count := _done_count(phase)
	for i: int in SEGMENTS.size():
		if i > 0:
			add_child(Fonts.label("\u00B7", Fonts.micro_tracked(), 12, _theme.muted))
		var seg := SEGMENTS[i]
		var label := _segment_label(seg, i, done_count)
		add_child(label)


static func _done_count(phase: String) -> int:
	if not SEGMENT_BY_PHASE.has(phase):
		return SEGMENTS.size()  # unknown or complete — the journey is done
	return SEGMENTS.find(str(SEGMENT_BY_PHASE[phase]))


func _segment_label(seg: String, index: int, done_count: int) -> Label:
	if index < done_count:
		var past := Fonts.label(seg, Fonts.micro_tracked(), 12, _theme.ink)
		past.modulate.a = 0.55
		return past
	if index == done_count:
		return Fonts.label("\u25B8 %s" % seg, Fonts.micro_tracked(), 12, _theme.accent)
	var future := Fonts.label(seg, Fonts.micro_tracked(), 12, _theme.muted)
	future.modulate.a = 0.55
	return future
