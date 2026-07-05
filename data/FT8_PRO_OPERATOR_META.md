# FT8 PRO operátor — meta-elemzés (2026)

Összeállítva: fórumok, WSJT-X dokumentáció, Auto-FT8, WSJT-Z, KK5JY, cw-discover 31k decode log.

## Mit tanultunk más programokból?

| Forrás | Kulcs ötlet |
|--------|-------------|
| **WSJT-X Fox/Hound** | Gyenge állomás = cél (Max dB szűrő); erős = lokális QRM; távolság szerinti sor |
| **WSJT-Z Auto Call** | Priority: Distance / Signal / Last decoded; min SNR; új DXCC szűrő |
| **Hamilton Auto FT8** | min_snr -18, max_snr +3 (felette lokál); LoTW szűrő; dupe block |
| **KK5JY (FT8 automation)** | Grid cache rövid üzenetekhez; távolság+SNR statisztika; operátor jelen kell legyen |
| **cw-discover logok** | CQ grid 97%; QSO median 2 ciklus; ugyanazon Hz 100%; feladás p75 = 3 ciklus |

## Gyenge = messzi? (értékes QSO)

- FT8 **-20 dB SNR-ig** megbízható (WSJT-X Fox guide).
- **Túl erős jel (+3 dB felett)** gyakran szomszéd / QRM — Auto-FT8 alapból kiszűri.
- **Gyenge + messzi grid** = DX esély; a PRO `weak_dx` mód ezt preferálja.
- **Erős közeli** = gyors QSO (`strong_fast` mód), de kevésbé „érték” award szempontból.

## Prioritási sorrend (implementált)

1. **Aktív QSO** folytatása (73-ig) — minden program így csinálja.
2. **Bejövő hívás** (téged szólítanak) — mindig előbb, mint CQ vadászat.
3. **PRO: CQ jelöltek gyűjtése** egy 15 s ciklusban → legjobb pontszám.
4. **Saját CQ** üresjáratban (~30 s).

## PRO mód vs alap

| | Alap | PRO |
|---|------|-----|
| CQ válasz | Első megfelelő SNR | **Rangsorolt** (táv / gyenge-DX / kiegyensúlyozott) |
| SNR ablak | min -15 | **-20 … +3** (konfigurálható) |
| Dupe | ma már worked | + cache grid |
| Irányított CQ | mind | CQ DX / CQ EU szűrés |

## Operátori felelősség

Az automatizálás **megengedett**, az **felügyelet nélküli** működés nem (USA FCC / magyar gyakorlat: control operator jelenléte). A PTT gomb = „autopilot”, nem „autópilóta nélkül”.

## Konfiguráció

`forgalminaplo/station.json` → `pro_operator` blokk, GUI: **PRO operátor** kapcsoló.
