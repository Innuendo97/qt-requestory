# Genera — generazione singola e massiva di documenti (design)

Data: 2026-11-10 · Versione di destinazione: 1.5.0

## Intento

Oggi per ottenere un PDF da svil o coll bisogna passare da un caso dell'Officina
(o da Postman). Serve un modo diretto: scrivo una o più template key, oppure
carico l'elenco Quadient, oppure indico un FDI, scelgo l'ambiente, premo
**Genera** e trovo i documenti in cartelle ordinate per package name.
La priorità dichiarata è la semplicità d'uso: una schermata, un pulsante.

## Obiettivi

- Generare da: template key (una o più, scritte a mano), elenco CSV Quadient
  (tutti i package o una selezione), FDI interi (uno o più).
- Ambiente a scelta fra i generatori abilitati (svil, coll). PROD resta escluso.
- Header della chiamata modificabili per la singola generazione: cambiare un
  valore, aggiungere una riga, eliminare una riga (anche quelle automatiche).
- Salvataggio in `<destinazione>\<ambiente>_<AAAAMMGG-HHMMSS>\<cartella>\<TK>.<ext>`
  dove `<cartella>` è il package name (elenco), l'FDI (modalità FDI) o
  `_senza_pacchetto`.
- Opzione zip (uno per cartella) e opzione "salva anche gli HTML".
- Nessun errore ferma il lotto; ogni esito è visibile in tabella e in `esito.csv`.
- "Riprova i non riusciti" senza reimpostare nulla.

## Non obiettivi

- Nessun confronto AS-IS/TO-BE, nessun caso dell'Officina creato.
- Nessun retry automatico, nessuna pianificazione, nessuna CLI.
- Nessun download da `attachmentUrl`: il documento è la risposta HTTP.
- Nessuna modifica del payload: parte com'è nei log.

## Anti-obiettivi

- Una chiamata verso PROD, in qualunque forma.
- Payload, header o link firmati nei log dell'app o in `esito.csv`.
- Un lotto da centinaia di chiamate partito per un clic sbagliato.
- Percorsi o hostname reali nel repository (è pubblico).

## Comportamento

**Sorgente delle chiamate.** Per una template key: la chiamata più recente nei
log dell'ambiente "Chiamate da" (predefinito: lo stesso nome del generatore
scelto; modificabile, così un payload di coll può essere inviato a svil).
Confronto esatto, senza distinzione fra maiuscole e minuscole. Per un FDI: fra
tutte le sue chiamate, la più recente per ciascuna template key.
Nessuna chiamata trovata → esito "nessuna chiamata nei log", nessun ripiego.

**Header.** La tabella è l'insieme completo degli header inviati. Parte con le
righe automatiche (`template_key`, `current_timestamp`, `correlation_id`,
`Postman-Token`) a valore vuoto, mostrato come "automatico", più il profilo di
Impostazioni. Valore vuoto su un nome automatico = valore calcolato
(`correlation_id` = nuovo UUID per ogni chiamata, anche in modalità FDI).
Riga eliminata = header non inviato. Le modifiche durano finché l'app è aperta;
"Ripristina" torna al profilo. Non vengono salvate su disco.

**HTML.** Il tipo si conosce solo dalla risposta (`%PDF-` / markup). Con
"Salva anche gli HTML" spento, un HTML ricevuto non viene salvato (esito
"saltato: HTML") e la template key viene ricordata; alle generazioni successive
le template key ricordate non vengono chiamate. Con l'opzione accesa si chiamano
tutte e la memoria si aggiorna (una key che ora dà PDF esce dalla memoria).

**Elenco CSV.** Separatore `;`, codifica UTF-8 (con o senza BOM) con ripiego
su cp1252. Colonne riconosciute dall'intestazione "Template key" e
"package name" (spazi e maiuscole ignorati); senza intestazione: colonne 1 e 5.
Valori ripuliti dagli spazi. Riga senza template key: scartata e contata.
Package vuoto: `_senza_pacchetto`. Una template key in più package si genera
una volta e il file viene scritto in ogni cartella. Il percorso dell'elenco si
sceglie con Sfoglia e viene ricordato.

**Template key scritte a mano.** Separatori: spazio, virgola, punto e virgola,
a capo. Doppioni ignorati. Se un elenco è caricato la cartella è il package
dell'elenco, altrimenti `_senza_pacchetto`.

**Esecuzione.** 3 chiamate in parallelo. Timeout quello dell'Officina.
Interrompi: le chiamate già partite finiscono, le altre diventano "annullato".
Sopra le 20 chiamate, conferma prima di partire con numero e ambiente.

**Esiti.** `ok`, `saltato: HTML`, `nessuna chiamata nei log`, `non riuscito`
(con motivo: HTTP ≥ 400, risposta non riconosciuta, tempo scaduto, header non
valido, payload illeggibile, scrittura non riuscita), `annullato`.
`esito.csv` nella cartella della generazione: `;`, UTF-8 con BOM, colonne
`template_key;cartella;fdi;esito;tipo;file;durata_ms;stato_http;motivo`.

**Nomi su disco.** Ogni componente passa da `safe_component`. Stesso nome nella
stessa cartella → suffisso `_2`, `_3`. Scritture atomiche (`.part`).
Zip: `<cartella>.zip` accanto alla cartella, che resta.

## Vincoli

- Layer: `core` stdlib, `officina` senza Qt, solo `ui` importa PySide6; la UI
  usa i Protocol di `ui/contracts.py`.
- Stringhe utente in italiano in `ui/strings/`; identificatori in inglese.
- Nessun colore o QSS fuori da `theme*.py`. Moduli ≲ 400 righe.
- Dati di test solo sintetici (`MOD_TEST_*`, FDI `aaaaaaaa-1111-…`).

## Scelte dell'autore (non confermate dall'utente una per una)

Nessun ripiego automatico su un altro ambiente; memoria delle key HTML;
3 corsie senza retry; header non persistiti; soglia di conferma a 20;
`correlation_id` sempre nuovo; scheda separata "Genera" con Ctrl+4.

## Lasciato a chi costruisce

Disposizione fine dei widget entro lo schema descritto nel piano, testi
esatti delle stringhe (tono dell'app), scelta dell'icona Fluent.
