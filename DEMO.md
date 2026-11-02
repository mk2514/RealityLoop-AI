# MetroPT3 Historical Replay Demo

## Start locally

From the repository root:

```powershell
docker compose up --build
```

For local frontend-only development, use the existing backend/Vite commands documented in `README.md`. Do not commit or upload the full MetroPT3 CSV. The bounded source subset is kept under `backend/tests/fixtures/sensor-imports/metropt3_demo.csv`.

## Dataset selection

- The repository supplied one meaningful CSV, `MetroPT3.csv`.
- It has 1,516,948 source rows and timestamps from `2020-02-01 00:00:00` through `2020-09-01 03:59:50`.
- The bounded demo fixture preserves the original header and source-record index column, source-record IDs 1400 through 3570, 218 consecutive records, and timestamps from `2020-02-01 00:23:08` through `2020-02-01 00:58:58`.
- The unnamed first CSV column is a source-record ID, not elapsed seconds.
- These are recorded source values, not synthetic data. They do not include a fault label.
- A second unrelated CSV is not supplied in the repository or available workspace.

Columns:

`TP2`, `TP3`, `H1`, `DV_pressure`, and `Reservoirs`: bar; `Oil_temperature`: C; `Motor_current`: A; `COMP`, `DV_eletric`, `Towers`, `MPG`, `LPS`, `Pressure_switch`, `Oil_level`, and `Caudal_impulses`: discrete states.

`COMP=1` means no air intake. It does not prove that the motor is running.

## 90-second jury walkthrough

1. Sign in and open **Asset Registry**.
2. Select an existing saved compressor machine.
3. In **Import and replay compressor history**, choose the bounded CSV fixture.
4. Invalid timestamps stop with the source row and timestamp; valid files show the replay window and sensor mapping.
5. Map TP3, Motor current and COMP to the machine sensors, then select **Import mappings**.
6. Select **Replay window**. The chart shows synchronized measured pressure, current and operating state.
7. Point out the source row IDs and timestamps, plus the past-only 70% training / held-out window error.
8. Select **Analyze evidence with Gemini**. Numerical evidence remains visible if the key is missing, the worker is unavailable, or the provider times out.

## Local extraction command

```powershell
python -c "import csv; src='MetroPT3.csv'; dst='backend/tests/fixtures/sensor-imports/metropt3_demo.csv';\nwith open(src,'r',newline='',encoding='utf-8-sig') as fi, open(dst,'w',newline='',encoding='utf-8') as fo:\n r=csv.DictReader(fi); w=csv.DictWriter(fo,fieldnames=r.fieldnames); w.writeheader(); w.writerows(row for i,row in enumerate(r,1) if 141 <= i <= 358)"
```

## Network or hardware fallback

Keep the saved replay fixture available locally. The historical chart and numerical evidence continue to work without Gemini, internet access, Redis, hardware, or machine commands. No machine actuation is implemented.
