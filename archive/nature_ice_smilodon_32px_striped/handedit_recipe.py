# Smilodon pounce-bite, keyed by hand on the east and south-east base poses.
# Rects are (x0, y0, x1, y1) in the 32px base pose; see scripts/handedit.py.
from handedit import lunge_attack

FANG = (246, 245, 236, 255)
DIAG = 0.7071
_e, _he = lunge_attack(1, 0, head=(17, 0, 32, 24), front=(14, 22, 25, 29), pad=16,
                       smear_colors=(FANG,), smear_from=(26, 12), smear_to=(28, 24))
_se, _hse = lunge_attack(DIAG, DIAG, head=(15, 0, 30, 25), front=(13, 22, 27, 29), pad=16,
                         smear_colors=(FANG,), smear_from=(24, 13), smear_to=(26, 25))
DIRS = {"east": _e, "south-east": _se}
HIT = {"east": _he, "south-east": _hse}
