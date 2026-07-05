# FT8 protokoll elemzés — cw-discover log

Generálva: 2026-07-01T15:18:59.679697+00:00
Dekódok: **31435**

## Összefoglaló

- Üzenettípusok: {'cq': 10648, '73': 4994, 'report': 8448, 'qso': 6914, 'other': 257, 'grid': 174}
- CQ üzenetek: 10648
- Hívójel→lokátor cache: 1996 állomás

## CQ szokások

- Grid a CQ-ban: **96.8%**
- Domináns formák: [('CQ [call]', 10177), ('CQ other', 344), ('CQ DX', 127)]
- CQ ismétlés p50: **30.009417295455933s**

## Hívás kitartás (empirikus)

- QSO kísérletek: **10443**
- Median ciklus/futam: **2** (1 ciklus ≈ 15 s)
- Median ciklus RR73-ig: **2** (p75: 3.0)
- Feladás 73 nélkül (p75): **3.0** ciklus
- Későbbi újrahívások: {2: 1161, 3: 244, 4: 62, 5: 23, 6: 12, 7: 4, 13: 3, 22: 2}

## Frekvencia (audio_hz)

- Pár-hívás Hz spread median: **0.0** Hz
- Ugyanazon tone bucket median: **100.0%**

## Döntési fa (vázlat)

### listen_cq
- **Ha:** üzenet CQ
  - grid kinyerés / call→grid cache
  - távolság + SNR rangsor
  - ha SNR>-15 és távolság cél szerint: válasz ugyanazon audio_hz-en

### first_response
- **Ha:** CQ hallva, válasz indul
  - tipikus ismétlés 30.009417295455933s
  - formátum: [saját_call] [cq_call] [saját_grid]
  - grid CQ-ban 96.8% esetben benne van

### report_exchange
- **Ha:** qso/report üzenet
  - SNR jelentés: -24..+9 tipikus
  - R prefix = már egyszer kapta (R-05, R+01)
  - R token arány: 48.4%

### persistence
- **Ha:** nincs válasz
  - ismételd max ~3 ciklust sikeres QSO-ig
  - addig ugyanazon Hz-en maradj (median spread 0 Hz)
  - ha nincs RR73/73 ~3 ciklus után hagyd (p75)

### close
- **Ha:** RR73 vagy 73
  - QSO zárva
  - ne hívd tovább
  - ADIF/JSONL log

## Saját QSO log (jövő)

- Formátum: **ADIF 3.1 (.adi) + JSONL mirror**
- Mezők: `qso_id, time_iso, call, grid, grid_source, mode, band, freq_hz, rst_sent, rst_rcvd, tx_audio_hz, distance_km, azimuth_deg, comment, adif_blob`
- Import: WSJT-X, N1MM, Log4OM, QRZ, LoTW, ClubLog
