"""Bemenet lista — Pulse monitorok (WebSDR) + sounddevice fallback."""
from __future__ import annotations

from dataclasses import dataclass

from cw_discover.audio.pulse_sources import list_pulse_sources, pick_recommended_monitor
from cw_discover.audio.source import CaptureSource

try:
  import sounddevice as sd
except ImportError:
  sd = None


@dataclass
class InputDevice:
  source: CaptureSource
  name: str
  is_default: bool = False
  recommended: bool = False
  hint: str = ""
  state: str = ""

  @property
  def label(self) -> str:
    star = " ★" if self.is_default else ""
    rec = " ◆ AJÁNLOTT" if self.recommended else ""
    st = f" [{self.state}]" if self.state else ""
    h = f" — {self.hint}" if self.hint else ""
    return f"{self.name}{st}{star}{rec}{h}"


def _hint_pulse(src_name: str, is_monitor: bool, is_mic: bool) -> str:
  n = src_name.lower()
  if is_monitor:
    if "analog-stereo" in n:
      return "PC hang / WebSDR (analóg kimenet monitor)"
    if "hdmi" in n:
      return "HDMI/TV kimenet monitor"
    if "ggmorse" in n:
      return "virtuális GGMorse monitor"
    return "rendszerhang monitor — WebSDR ide"
  if is_mic:
    return "⚠ mikrofon / line-in — NEM WebSDR!"
  return "Pulse forrás"


def list_input_devices() -> list[InputDevice]:
  out: list[InputDevice] = []
  pulse = list_pulse_sources()
  best = pick_recommended_monitor(pulse)

  for s in pulse:
    if s.is_mic:
      hint = _hint_pulse(s.name, False, True)
      prio = 2
    elif s.is_monitor:
      hint = _hint_pulse(s.name, True, False)
      prio = 0 if s.running else 1
    else:
      hint = _hint_pulse(s.name, False, False)
      prio = 1
    out.append(
      InputDevice(
        source=CaptureSource(kind="pulse", pulse_name=s.name),
        name=s.name,
        is_default=(best is not None and s.name == best.name),
        recommended=(best is not None and s.name == best.name),
        hint=hint,
        state=s.state,
      )
    )
    _ = prio  # sort below

  # Monitorok felül (futó előbb), mikrofonok alul
  def sort_key(d: InputDevice) -> tuple:
    s = d.source.pulse_name or ""
    n = s.lower()
    is_mic = "alsa_input" in n or d.hint.startswith("⚠")
    is_mon = ".monitor" in n or "monitor" in n
    running = 0 if d.state.upper() == "RUNNING" else 1
    return (is_mic, not is_mon, running, d.name)

  out.sort(key=sort_key)

  if sd is not None:
    try:
      default_in = sd.default.device[0] if sd.default.device else None
    except Exception:
      default_in = None
    for i, d in enumerate(sd.query_devices()):
      if d["max_input_channels"] < 1:
        continue
      name = str(d["name"])
      nlow = name.lower()
      if "monitor" in nlow:
        hint = "sounddevice — monitor"
      elif "pipewire" in nlow or "pulse" in nlow or name == "default":
        hint = "⚠ gyakran rossz forrás — válassz Pulse monitort fent"
      else:
        hint = "⚠ hardver bemenet / zaj — WebSDR-hez monitor kell"
      out.append(
        InputDevice(
          source=CaptureSource(kind="sd", sd_index=i),
          name=f"[SD {i}] {name}",
          hint=hint,
          state="",
        )
      )

  if not out:
    out.append(
      InputDevice(
        source=CaptureSource(kind="sd", sd_index=None),
        name="Alapértelmezett (sounddevice)",
        hint="pactl nem elérhető",
      )
    )
  return out


def default_capture_source() -> CaptureSource:
  pulse = list_pulse_sources()
  best = pick_recommended_monitor(pulse)
  if best is not None:
    return CaptureSource(kind="pulse", pulse_name=best.name)
  return CaptureSource(kind="sd", sd_index=None)


def source_label(source: CaptureSource | None) -> str:
  if source is None:
    return "—"
  for d in list_input_devices():
    if d.source.storage_key() == source.storage_key():
      return d.label
  if source.kind == "pulse" and source.pulse_name:
    return source.pulse_name
  if source.kind == "sd":
    return f"sounddevice #{source.sd_index}"
  return "—"


# régi API
def device_label(device: int | None) -> str:
  return source_label(CaptureSource(kind="sd", sd_index=device))
