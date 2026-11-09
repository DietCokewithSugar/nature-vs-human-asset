# Mammoth goring thrust: heavy - longer wind-up and hit hold, tusk-coloured smear.
from handedit import lunge_attack

TUSK = (244, 234, 207, 255)
TUSK2 = (214, 196, 160, 255)
DIAG = 0.7071
_e, _he = lunge_attack(1, 0, head=(26, 3, 50, 47), front=(27, 44, 42, 63), pad=32, mag=1.6, heavy=True,
                       smear_colors=(TUSK, TUSK2), smear_from=(44, 26), smear_to=(46, 46))
_se, _hse = lunge_attack(DIAG, DIAG, head=(22, 3, 62, 52), front=(26, 46, 42, 63), pad=32, mag=1.6, heavy=True,
                         smear_colors=(TUSK, TUSK2), smear_from=(56, 30), smear_to=(58, 46))
DIRS = {"east": _e, "south-east": _se}
HIT = {"east": _he, "south-east": _hse}
