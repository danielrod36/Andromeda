class_name EngineResult
extends RefCounted
## The result of one EngineClient call. On HTTP success: ok=true, data = the
## parsed body. On any failure: ok=false with the server's error envelope
## (§A1) parsed into error_code/error_message — transport failures use
## error_code "transport_error" and a fixed cockpit-voice message.

var ok := false
var status := 0
var data: Dictionary = {}
var error_code := ""
var error_message := ""


static func ok_result(p_status: int, p_data: Dictionary) -> EngineResult:
	var r := EngineResult.new()
	r.ok = true
	r.status = p_status
	r.data = p_data
	return r


static func err_result(p_status: int, p_code: String, p_message: String) -> EngineResult:
	var r := EngineResult.new()
	r.ok = false
	r.status = p_status
	r.error_code = p_code
	r.error_message = p_message
	return r
