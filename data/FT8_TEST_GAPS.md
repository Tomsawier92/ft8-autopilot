# FT8 — hiányzó / jövőben kritikus tesztek

**Állapot:** ~150+ automata teszt + 38 stressz forgatókönyv. Ez a lista ami **kimaradt** vagy **részleges**.

## 🔴 Kritikus (éles QSO-színtű)

| # | Terület | Miért fontos | Státusz |
|---|---------|--------------|---------|
| 1 | **QSO után RR73/73 echo** | Lezárt QSO után `IK4LZH N0CALL RR73` új QSO-t indíthat (intel grid) | ✅ teszt + javítás |
| 2 | **Dupla naplózás** | Két RR73 / két 73 → két `qso.jsonl` sor | ✅ teszt |
| 3 | **engage_call aktív QSO alatt** | Operátor kényszerítés — felülírja-e? | ✅ teszt |
| 4 | **Szál-biztonság** | `on_decode` + `on_cycle` párhuzamosan | ✅ teszt |
| 5 | **TX worker shutdown** | GUI bezárás — nem akad el | ✅ teszt |
| 6 | **PTT hiba → TX nem OK** | Élesben PTT_FAIL ne legyen „sikeres” | ✅ teszt |
| 7 | **Hz lock teljes QSO** | Remote más Hz-en küld — mi nem követjük | ✅ teszt |
| 8 | **Napló worked cache** | Ma worked → CQ skip, restart után is | ✅ teszt |
| 9 | **ADIF / naplo.txt formátum** | LoTW/QRZ import | ✅ teszt |
| 10 | **atomic qso.jsonl** | Áramszünet közben írás | ✅ teszt |

## 🟠 Fontos (következő sprint)

| # | Terület | Miért |
|---|---------|-------|
| 11 | **PRO DISTANCE vs WEAK_DX** | Más CQ-t választ defer módban |
| 12 | **min_distance_km** | Túl közeli állomás kihagyása |
| 13 | **CQ EU / DX szűrés** | Irányított CQ |
| 14 | **Intel cache** | Rövid üzenet → grid cache-ből |
| 15 | **Engine decode dedup** | Ugyanaz a sor 2× ne triggereljen 2 TX-et |
| 16 | **RX pause TX alatt** | `set_rx_paused` integráció GUI-val |
| 17 | **Future cycle dekód** | Óra előre — `decode_is_fresh` viselkedés |
| 18 | **Band váltás** | 40m→20m közben aktív QSO |
| 19 | **Napi log replay regresszió** | Tegnapi jsonl → ugyanaz a TX sor |
| 20 | **Worked csak bandre** | Ma 40m worked, 20m még nem | ✅ teszt |

## 🟡 Integráció / hardver (kézi vagy mock)

| # | Terület |
|---|---------|
| 21 | Teljes `Ft8Engine` → operátor lánc (nem csak `on_decode`) |
| 22 | `wait_for_tx_period` + valós óra (mock time) |
| 23 | ESP32 PTT soros timeout / reconnect |
| 24 | Mono L+R + valós Pulse sink |
| 25 | Line-in clip (RMS>0.95) — AGC viselkedés |
| 26 | Két rádió self-spill valós környezet |
| 27 | `start_auto_ft8.sh` end-to-end smoke |
| 28 | GUI `operator_in.txt` parancsok (ABORT, CALL) |

## 🔵 Fuzz / hosszú táv

| # | Terület |
|---|---------|
| 29 | Hypothesis: `message_triplet` random stringek |
| 30 | 24 órás stressz (nem csak 10 perc) |
| 31 | Log-mined fixture-ök minden napra automatikus |
| 32 | Property: minden TX 3 token, call_b=N0CALL |
| 33 | Memory leak: 100k szimulált dekód |

---

**Futtatás (gap tesztek):**
```bash
cd ~/ai/cw-discover
PYTHONPATH=. .venv/bin/pytest tests/test_ft8_future_gaps.py -v
```
