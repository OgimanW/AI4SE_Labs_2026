# Úloha 3: Porovnanie promptov pomocou makro F1

## Metrika

Tento ukazovateľ je vhodný, pretože úloha vyhodnocuje SQL dopyty na základe riadkov, ktoré vrátia. Udeľuje čiastočný kredit, ak predpovedaný výsledok obsahuje niektoré, ale nie všetky očakávané riadky. Poradie riadkov nemá vplyv na správnosť, zatiaľ čo duplicitné riadky sa započítavajú.

Pre každú otázku sa výsledné riadky porovnávajú ako multimnožiny: na poradí riadkov nezáleží, ale duplicitné riadky sa berú do úvahy. Presnosť (precision) je podiel predpovedaných riadkov, ktoré sú správne; návratnosť (recall) je podiel očakávaných riadkov, ktoré sa našli. Skóre F1 je ich harmonickým priemerom. Uvádzané makro hodnoty sú nevážené priemery naprieč všetkými otázkami.

Ak sú očakávané aj predpovedané výsledky prázdne, presnosť, návratnosť aj F1 majú hodnotu 1. Ak je prázdny presne jeden z nich, ich hodnota je 0. Chyba pri vykonávaní SQL dopytu získa vo všetkých troch ukazovateľoch nulové skóre. Pre porovnanie s metrikou „všetko alebo nic“ z Úlohy 2 je zahrnutá aj presná presnosť (exact accuracy).

F1 dopĺňa, namiesto toho aby nahradzovala, presnú presnosť (exact accuracy): F1 poskytuje čiastočný kredit, keď sú niektoré výsledné riadky správne, zatiaľ čo presná presnosť započítava iba úplne sa zhodujúce množiny výsledkov.

## Výsledky

| Prompt | Otázky | Makro presnosť | Makro návratnosť | Makro F1 | Presná presnosť | SQL chyby |
|---|---:|---:|---:|---:|---:|---:|
| CO-STAR | 155 | 0.2774 | 0.2774 | 0.2774 | 0.2774 | 0 |
| RTF | 155 | 0.1742 | 0.1742 | 0.1742 | 0.1742 | 0 |
| RACE | 155 | 0.2774 | 0.2774 | 0.2774 | 0.2774 | 0 |

V tomto spustení získala čiastočné neprázdne skóre F1 nižšie ako 1 presne 0 otázka/otázok. Preto sa pre tieto súbory predikcií makro F1 rovná presnej presnosti: každá odpoveď bola buď presnou zhodou, alebo nemala žiadne prekrývajúce sa riadky výsledkov. F1 je však stále užitočnou doplnkovou metrikou, ak dochádza k čiastočnému prekrývaniu riadkov.

Makro F1 neváži otázky podľa toho, koľko riadkov obsahujú ich správne odpovede. Skóre pre jednotlivé otázky sú k dispozícii v súbore `f1_per_question.csv`; agregované hodnoty sa nachádzajú v `f1_results.csv`.

Spustite `python calculate_f1.py` z tohto adresára pre prepočet výsledkov zo súborov CSV z Úlohy 2.