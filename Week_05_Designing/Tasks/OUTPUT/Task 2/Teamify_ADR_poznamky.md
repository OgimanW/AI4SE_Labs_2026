# Teamify – poznámky ku konverzácii o ADR

29. 10. 2026 · Lukáš × Claude

## Kontext

Nadväzuje na predošlú diskusiu o architektúre Teamify (podklady: `Teamify_konverzacia.pdf` a `Teamify – poznámky k architektúre.md`). Cieľ tejto konverzácie: z tej diskusie spraviť záznam o architektonickom rozhodnutí (ADR).

## Výstup

Claude Doc **ADR-001: Architektúra systému Teamify**: https://claude.ai/artifact/FGPM6ciajGQAtXRwUBtzH2

Štruktúra ADR:

- **Metadáta:** stav *Navrhnuté*, dátum, rozhodovatelia (Lukáš + tím), rozsah, podklady.
- **Schéma systému:** klient (React SPA) → REST a WebSocket → server s 6 modulmi a centrálnymi oprávneniami → PostgreSQL.
- **Kontext:** univerzitné zadanie, 31 user stories; rozhodujú real-time, roly v tíme a kaskádové mazanie; obmedzenia tímu a času.
- **Rozhodnutie:** variant A, modulárny monolit (klient, oprávnenia, stack, zjednodušenia).
- **Zvažované možnosti:** porovnávacia tabuľka A / B / C, dôvody zamietnutia B a C.
- **Dôsledky:** tabuľka „Získame / Platíme“.
- **Riziká a mitigácie:** WebSocket spojenia, race condition adminov, oprávnenia, dvojité hlasovanie, zmazanie účtu, časové pásma, hranice modulov.
- **Otvorené otázky a prehodnotenie:** nejasnosti zo zadania, podmienky na prechod na B alebo C, ďalšie kroky.

## Úpravy na základe spätnej väzby

- Pridaná vizualizácia systému (schéma), lebo dokument bol príliš textový.
- Skrátené Kontext, Rozhodnutie a dôvody zamietnutia B/C; Dôsledky zmenené z dvoch zoznamov na tabuľku.
- Slovník pojmov bol pridaný a potom **odstránený**: do ADR nepatrí, vysvetlenia ostali v chate.
- Opravená omylom pridaná pomlčka v odseku „Obmedzenia“.

## Vysvetlené pojmy

- **SPA (Single Page Application):** webová aplikácia načítaná raz ako jedna stránka, potom už len mení obsah a pýta si dáta zo servera (napr. Gmail).
- **Outbox pattern:** riešenie „dual write“ (zápis do DB aj do brokera); udalosť sa uloží do tabuľky outbox v tej istej transakcii a odošle ju samostatný proces.
- **Saga:** dlhá operácia cez viac služieb krok za krokom; pri zlyhaní sa predošlé kroky vrátia opačnými akciami.
- **JWT (JSON Web Token):** podpísaný preukaz po prihlásení, posiela sa s každou požiadavkou; rola v ňom môže byť zastaraná, kým token nevyprší.
- **Vendor lock-in:** závislosť od jedného poskytovateľa; prechod inam znamená prepísať veľkú časť aplikácie.

## Otvorené body

- [ ] Schváliť ADR v tíme a zmeniť stav z *Navrhnuté* na *Prijaté*.
- [ ] Ujasniť s vyučujúcim: pripojenie k tímu, posledný admin, zmazanie účtu.
- [ ] Ďalšie kroky: diagram modulov monolitu a ich prepojení, návrh databázovej schémy.
