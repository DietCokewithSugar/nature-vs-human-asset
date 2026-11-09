# Pika pounce-bite: a round body sells the motion through squash and stretch.
from handedit import lunge_attack

TOOTH = (255, 250, 235, 255)
DIAG = 0.7071
_e, _he = lunge_attack(1, 0, head=(14, 0, 30, 20), pad=16, mag=1.2,
                       smear_colors=(TOOTH,), smear_from=(26, 10), smear_to=(27, 19))
_se, _hse = lunge_attack(DIAG, DIAG, head=(13, 0, 30, 23), pad=16, mag=1.2,
                         smear_colors=(TOOTH,), smear_from=(24, 12), smear_to=(26, 22))
DIRS = {"east": _e, "south-east": _se}
HIT = {"east": _he, "south-east": _hse}
