string STATE_IDLE=idle
string STATE_WAITING=waiting_for_motion
string STATE_RECORDING=recording
string STATE_PLAYING=playing

string TELEOP_UNKNOWN=unknown
string TELEOP_ENABLED=enabled
string TELEOP_PAUSED=paused
string TELEOP_UNAVAILABLE=unavailable

string state
string playing           # name of the motion being played, '' if none
float64 progress         # 0..1 while playing
float64 recording_time   # s while recording
bool has_draft
float64 draft_duration   # s
string teleop            # last known teleoperation state
