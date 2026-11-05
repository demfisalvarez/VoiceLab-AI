"""Comprueba en Windows real las llamadas COM del micrófono predeterminado.

Lista los micrófonos, lee el predeterminado y, si está VB-CABLE, lo pone como
predeterminado y lo restaura con ``SystemMic``. Sin dispositivos, al menos
comprueba que las llamadas no rompen el proceso.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from voicelab.audio import winmic  # noqa: E402
from voicelab.audio.systemmic import SystemMic  # noqa: E402

devs = winmic.capture_devices()
print("micrófonos:", devs)
print("predeterminado:", [winmic.default_capture(r) for r in (0, 1, 2)])
try:
    winmic.set_default_capture("{0.0.1.00000000}.{00000000-0000-0000-0000-000000000000}", roles=(0,))
    print("id inventado: aceptado (raro)")
except winmic.WinMicError as exc:
    print("id inventado: rechazado como se espera:", exc)
sm = SystemMic(state_file=Path(tempfile.mkdtemp()) / "estado.json")
cable = sm.find_cable("CABLE Input (VB-Audio Virtual Cable)")
print("cable:", cable)
if cable:
    st = sm.engage("CABLE Input (VB-Audio Virtual Cable)")
    print("activar:", st)
    now = winmic.default_capture(0)
    print("predeterminado ahora:", now)
    assert st["engaged"] and now == cable["id"], "no se cambió el predeterminado"
    print("restaurar:", sm.release())
print("OK")
