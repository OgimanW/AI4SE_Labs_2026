# Teamify – poznámky k architektúre

Oct 29, 2026 · @Ogi

## Kontext

Univerzitné zadanie: navrhnúť architektúru pre systém Teamify podľa súboru s požiadavkami (Teamify.txt, 31 user stories). Cieľ diskusie je pochopiť 3 naozaj odlišné architektúry, ich trade-offy a náročné časti implementácie. Postup: najprv zhrnutie systému, architektúry až na vyžiadanie.

## Zhrnutie systému

Teamify je aplikácia na osobnú správu úloh a tímovú spoluprácu: osobná agenda, tímy so zdieľanou agendou, real-time chat, ankety a real-time notifikácie.

| Oblasť | User stories | Čo obsahuje |
| --- | --- | --- |
| Účet a autentifikácia | 1–7 | registrácia, login/logout, profil, reset hesla, zmazanie účtu |
| Osobné úlohy | 9, 11–14 | osobná agenda, CRUD úloh, označenie splnenia |
| Tímy a roly | 15–20, 25–26 | vytvorenie, pripojenie, opustenie, úprava a zmazanie tímu; povýšenie/odobratie admina |
| Tímové udalosti | 10, 27–31 | zdieľaná agenda, CRUD udalostí (admin), prijatie/odmietnutie pozvánky, splnenie |
| Komunikácia | 8, 21 | sekcia notifikácií, skupinový chat v tíme |
| Ankety | 22–24 | admin vytvára, členovia hlasujú a vidia výsledky |

Kľúčové vlastnosti:

- Dve roly v tíme: člen a administrátor; admin môže mať viac ľudí, práva sa menia za behu.
- Real-time požiadavky: chat a notifikácie, teda push zo servera ku klientovi.
- Udalosť je tímová obdoba osobnej úlohy, navyše s účasťou (RSVP).
- Nejasnosti v zadaní: ako presne funguje pripojenie k tímu (pozvánka vs. žiadosť vs. kód), čo sa stane s tímom, keď ho opustí posledný admin, a čo sa stane s dátami pri zmazaní účtu.

## A: Modulárny monolit

Jedna nasaditeľná aplikácia rozdelená vnútri na moduly (Účty, Tímy, Úlohy a udalosti, Chat, Ankety, Notifikácie), jedna relačná databáza. Klient je SPA, ktoré volá REST API a pre chat a notifikácie drží WebSocket spojenie na ten istý server.

- **Výhody:** najjednoduchšie na vývoj, testovanie a nasadenie; transakcie cez viac modulov sú triviálne (napr. zmazanie tímu aj s udalosťami a anketami); oprávnenia sú jeden kód na jednom mieste.
- **Nevýhody:** škáluje sa len celá aplikácia naraz; WebSocket spojenia viažu používateľa na konkrétnu inštanciu, takže pri viacerých inštanciách treba pub/sub (napr. Redis); hranice modulov sa časom rozmazávajú, ak ich nikto nestráži.
- **Náročné časti:** udržať disciplínu medzi modulmi (moduly sa volajú cez rozhrania, nie priamo cez tabuľky iných); real-time vrstva na tom istom serveri ako REST; doručenie notifikácie používateľovi, ktorý je práve offline (uložiť do DB a zobraziť po prihlásení).

## B: Mikroslužby s event busom

Samostatné služby (Auth, Používatelia a tímy, Úlohy a udalosti, Chat, Ankety, Notifikácie), každá s vlastnou databázou. Klient ide cez API gateway. Služby si posielajú udalosti cez message broker (RabbitMQ alebo Kafka), napr. `EventCreated` alebo `MemberLeftTeam`. Notifikačná služba tieto udalosti počúva a posiela ich klientom cez WebSocket.

- **Výhody:** služby sa dajú škálovať a nasadzovať nezávisle (chat môže mať 5 inštancií, ankety jednu); notifikácie sú prirodzene oddelené od zvyšku; pridanie novej reakcie na udalosť nevyžaduje zásah do pôvodnej služby.
- **Nevýhody:** pre projekt takejto veľkosti výrazný overhead (infraštruktúra, Docker/Kubernetes, monitoring, distribuované logovanie); chyby sa ladia ťažko, lebo požiadavka prechádza cez viac služieb; tím študentov strávi viac času infraštruktúrou než funkcionalitou.
- **Náročné časti:** dáta sú rozdelené, takže operácia ako zmazanie tímu alebo účtu sa musí rozbehnúť cez viac služieb (saga, eventual consistency); každá služba musí poznať rolu používateľa v tíme bez priameho prístupu k tabuľke tímov (token s claimami alebo lokálna kópia); poradie a duplicita správ z brokera (idempotentní konzumenti).

## C: Serverless / Backend-as-a-Service

Žiadny vlastný server. Klient (web alebo mobil) pracuje priamo s hotovou platformou, napr. Firebase alebo Supabase: autentifikácia, databáza s real-time odberom zmien a úložisko. Vlastná logika beží ako malé cloudové funkcie spúšťané udalosťami (napr. po vytvorení udalosti rozošli notifikácie). Oprávnenia sa definujú ako pravidlá priamo v databáze (security rules alebo row-level security).

- **Výhody:** registrácia, login, reset hesla a real-time chat sú takmer zadarmo; nulová správa serverov; veľmi rýchly vývoj prvej funkčnej verzie.
- **Nevýhody:** silná závislosť od jedného poskytovateľa (vendor lock-in); väčšina logiky sa presúva do klienta, čo sťažuje testovanie; pri univerzitnom zadaní môže vyučujúci namietať, že ste architektúru nenavrhli, ale prevzali; náklady pri raste ťažko predvídateľné.
- **Náročné časti:** oprávnenia vyjadrené ako databázové pravidlá (člen vs. admin, posledný admin) sú ťažko čitateľné a testovateľné a chyba v nich znamená únik dát; NoSQL variant (Firestore) vyžaduje denormalizáciu, napr. agenda zložená z osobných úloh a udalostí viacerých tímov; studený štart cloudových funkcií.

## Porovnanie

Pre univerzitné zadanie s malým tímom je najrozumnejší modulárny monolit; mikroslužby dávajú zmysel len vtedy, ak je cieľom predmetu práve distribuovaný systém.

| Kritérium | A: Monolit | B: Mikroslužby | C: Serverless/BaaS |
| --- | --- | --- | --- |
| Rýchlosť vývoja | stredná | nízka | vysoká |
| Škálovanie | celok naraz | po službách | automatické |
| Konzistencia dát | transakcie | eventual | závisí od platformy |
| Real-time | WebSocket na serveri | notifikačná služba + broker | vstavané odbery |
| Prevádzková náročnosť | nízka | vysoká | takmer nulová |
| Hlavné riziko | rozmazané moduly | infraštruktúra zje čas | lock-in, logika v pravidlách |

Spoločné náročné časti bez ohľadu na architektúru:

- Oprávnenia viazané na rolu v konkrétnom tíme a pravidlo, že tím nesmie ostať bez admina.
- Notifikácie pre offline používateľov: uložiť a doručiť neskôr, nielen poslať cez WebSocket.
- Zmazanie účtu alebo tímu: čo s jeho správami v chate, hlasmi v anketách a udalosťami.
- Agenda spájajúca osobné úlohy a udalosti zo všetkých tímov, vrátane časových pásiem.

## Vysvetlenia k doplňujúcim otázkam

- **REST vs. WebSocket:** REST = klient sa pýta, server odpovie a spojenie končí (pull). WebSocket = otvorené spojenie, cez ktoré server sám pošle novú správu (push). Chat a notifikácie potrebujú push, ostatné operácie stačí cez REST.
- **Offline:** zadanie offline režim nevyžaduje; real-time chat aj notifikácie predpokladajú pripojenie na internet. Používateľ, ktorý práve nie je pripojený, nájde notifikácie uložené v DB po prihlásení. Plný offline režim (offline-first) by bol veľká extra práca so synchronizáciou a konfliktmi.
- **Databáza na službu:** nie je to jediný ani najlepší spôsob pre tento projekt. Dôvod v čistých mikroslužbách: služby nesmú byť zviazané cez spoločné tabuľky. Kompromis: jedna DB server, oddelené schémy, každá služba siaha len na svoju.
- **Message broker:** sprostredkovateľ správ medzi službami, funguje ako pošta. Služba odošle udalosť (napr. vytvorená udalosť v tíme) a nečaká; kto sa zaujíma, dostane kópiu. RabbitMQ = fronty, správa sa po spracovaní zmaže. Kafka = trvalý denník udalostí, čitatelia si ho čítajú vlastným tempom a môžu ho prečítať znova.
- **Serverless neznamená bez servera ani bez internetu:** servery existujú, ale prevádzkuje ich poskytovateľ v cloude (Google, AWS, Supabase). Aplikácia funguje cez internet pre kohokoľvek, nie iba v rámci firmy. Chat: klient zapíše správu do cloudovej DB, ostatní členovia majú na ňu odber a dostanú ju okamžite.

## Cesta jednej chat správy

Príklad: Jano pošle správu do tímového chatu, Mária a Peter ju majú dostať okamžite.

1. **A, monolit:** Jano → REST → server (chat modul) → uloží do DB → server pošle cez WebSocket Márii a Petrovi. 3 kroky, jedno miesto.
2. **B, mikroslužby:** Jano → API gateway → chat služba → vlastná DB chatu; chat služba pošle udalosť do brokera → notifikačná služba ju prevezme → WebSocket k Márii a Petrovi. Najviac krokov, služby o sebe nevedia.
3. **C, serverless:** Jano zapíše priamo do cloudovej DB → Mária a Peter majú odber a dostanú zmenu automaticky; cloudová funkcia voliteľne pošle push na mobil. Real-time je hotový od poskytovateľa.

## Najväčšie pains pri implementácii a trade-offy

Najťažšie nie sú CRUD operácie, ale real-time doručovanie, súbežnosť a pravidlá typu „tím nesmie ostať bez admina".

|  | A: Monolit | B: Mikroslužby | C: Serverless |
| --- | --- | --- | --- |
| Najväčší pain | správa WebSocket spojení (viac zariadení, reconnect, zmeškané správy) | dual write: uložiť do DB a poslať do brokera atomicky (outbox pattern) | pravidlo posledného admina a kaskádové mazanie v security rules |
| Oprávnenia | jeden middleware, ľahko sa však zabudne na endpoint | rola v JWT tokene môže byť zastaraná, kým token nevyprší | databázové pravidlá, ťažko testovateľné |
| Súbežnosť | 2 admini sa naraz zbavia práv → transakcia so zámkom | duplicitné a neusporiadané správy → idempotentní konzumenti | počítadlo hlasov → transakcie alebo funkcia |
| Mazanie účtu/tímu | jedna transakcia, kaskáda v DB | saga cez viac služieb s kompenzáciami | NoSQL nemaže podkolekcie, treba funkciu |
| Hlavný trade-off | jednoduchosť za cenu škálovania (pri 2+ inštanciách Redis pub/sub) | nezávislosť služieb za cenu konzistencie (člen, ktorý odišiel, chvíľu ešte dostáva správy) | rýchlosť vývoja za cenu kontroly a lock-inu |

Spoločné pre všetky: unikátne obmedzenie (anketa, používateľ) proti dvojitému hlasovaniu; zmazaný používateľ v chate ako „Zmazaný používateľ" namiesto mazania správ; ukladať časy v UTC.

## Odporúčanie

Najjednoduchšia funkčná voľba je A, modulárny monolit: jeden server, jedna PostgreSQL databáza, REST + WebSocket.

- Väčšina pains z B (outbox, sagy, zastarané tokeny, duplicity) vôbec nevznikne.
- Pains z C (posledný admin, kaskádové mazanie, počítadlá) sa riešia bežnou transakciou a obmedzeniami v DB.
- Zostávajú dve ťažšie veci: WebSocket spojenia (reconnect + dotiahnutie zmeškaných správ) a race condition pri adminoch (transakcia so zámkom).
- Zjednodušenia: jedna inštancia servera (bez Redisu), notifikácie uložené v DB a zároveň poslané cez WebSocket, pripojenie k tímu cez pozývací kód.
- Kedy C namiesto A: ak predmet nehodnotí návrh backendu a hlavné je rýchlo mať funkčnú aplikáciu; vtedy skôr Supabase než Firestore.

## Otvorené otázky a ďalšie kroky

- [x] Zhrnutie systému
- [x] 3 odlišné architektúry, trade-offy, náročné časti
- [ ] Výber architektúry: odporúčaný modulárny monolit, čaká na rozhodnutie Lukáša
- [ ] Ujasniť nejasnosti zo zadania: pripojenie k tímu, posledný admin, zmazanie účtu
