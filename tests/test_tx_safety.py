"""TX biztonság — PTT watchdog + vonalkimenet guard."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from cw_discover.ft8.ptt_client import Esp32Ptt, NullPtt
from cw_discover.ft8.safety_manager import (
  SafetySnapshot,
  load_safety_state,
  mark_tripped,
  save_safety_state,
  status_summary,
)
from cw_discover.ft8.tx_safety import (
  LineOutGuard,
  PttWatchdog,
  WatchdogPtt,
  wrap_ptt_with_watchdog,
)


def test_watchdog_ptt_tracks_on_off() -> None:
  inner = NullPtt()
  wd = PttWatchdog(inner, enabled=True)
  ptt = WatchdogPtt(inner, wd)
  ptt.ptt_on()
  assert wd._ptt_on_since is not None
  ptt.ptt_off()
  assert wd._ptt_on_since is None


def test_watchdog_emergency_on_stuck_ptt() -> None:
  inner = MagicMock()
  inner.ptt_on.return_value = True
  inner.ptt_off.return_value = True
  fired: list[str] = []

  with patch("cw_discover.ft8.tx_safety.sd.stop"):
    wd = PttWatchdog(inner, enabled=True, on_emergency=fired.append)
    wd._emergency_stop(30.0)

  assert fired
  assert inner.ptt_off.call_count >= 1


def test_watchdog_disabled_never_fires() -> None:
  inner = MagicMock()
  wd = PttWatchdog(inner, enabled=False)
  fired: list[str] = []
  wd._on_emergency = fired.append
  wd._emergency_stop(99.0)
  assert not fired


def test_watchdog_reset_restarts() -> None:
  inner = NullPtt()
  wd = PttWatchdog(inner, enabled=True)
  wd.start()
  wd.stop()
  wd.reset()
  assert not wd._triggered


def test_line_guard_acquire_release() -> None:
  guard = LineOutGuard(enabled=True)
  with (
    patch("cw_discover.ft8.tx_safety._sink_index", return_value=484),
    patch("cw_discover.ft8.tx_safety._default_sink", return_value="alsa_output.pci-0000_00_1f.3.analog-stereo"),
    patch("cw_discover.ft8.tx_safety._fallback_sink", return_value="alsa_output.pci-0000_03_00.1.hdmi-stereo"),
    patch("cw_discover.ft8.tx_safety._pactl") as mock_pactl,
    patch("cw_discover.ft8.tx_safety._sink_input_rows", return_value=[]),
  ):
    guard.acquire()
    assert guard._active
    guard.release()
    assert not guard._active
    cmds = [c.args for c in mock_pactl.call_args_list]
    assert ("set-default-sink", "alsa_output.pci-0000_03_00.1.hdmi-stereo") in cmds
    assert ("set-default-sink", "alsa_output.pci-0000_00_1f.3.analog-stereo") in cmds


def test_line_guard_evicts_foreign_input() -> None:
  guard = LineOutGuard(enabled=True)
  guard._line_index = 484
  guard._fallback_sink = "hdmi"
  guard._pid = 1000
  row = {"index": 42, "sink": 484, "properties": {"application.process.id": "9999"}}
  with (
    patch("cw_discover.ft8.tx_safety._sink_input_rows", return_value=[row]),
    patch("cw_discover.ft8.tx_safety._pactl") as mock_pactl,
  ):
    ok = MagicMock(returncode=0)
    mock_pactl.return_value = ok
    guard._evict_foreign_inputs()
    mock_pactl.assert_called_with("move-sink-input", "42", "hdmi")


def test_wrap_ptt_with_watchdog() -> None:
  inner = NullPtt()
  wrapped, wd = wrap_ptt_with_watchdog(inner, enabled=True)
  assert isinstance(wrapped, WatchdogPtt)
  assert isinstance(wd, PttWatchdog)


def test_esp32_shutdown_resume() -> None:
  ptt = Esp32Ptt(port="/dev/null")
  with patch.object(ptt, "_cmd") as mock_cmd:
    mock_cmd.side_effect = [
      ["OK PTT 0"],
      ["OK PTT 0"],
      ["OK PTT 0"],
      ["OK SHUTDOWN"],
    ]
    ptt._ser = MagicMock()
    assert ptt.shutdown()
    mock_cmd.assert_any_call("SHUTDOWN")

  with patch.object(ptt, "_cmd", return_value=["OK RESUME"]):
    assert ptt.resume()


def test_safety_state_roundtrip(tmp_path) -> None:
  path = tmp_path / "safety.json"
  snap = SafetySnapshot()
  mark_tripped(snap, "teszt")
  save_safety_state(snap, path)
  loaded = load_safety_state(path)
  assert loaded.tripped
  assert loaded.reason == "teszt"
  assert "TILTVA" in status_summary(loaded)
