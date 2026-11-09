# Bee swarm sting: the swarm squashes back, then stretches into a dart with streaks.
from handedit import swarm_attack

DIAG = 0.7071
_e, _he = swarm_attack(1, 0, pad=16)
_se, _hse = swarm_attack(DIAG, DIAG, pad=16)
DIRS = {"east": _e, "south-east": _se}
HIT = {"east": _he, "south-east": _hse}
