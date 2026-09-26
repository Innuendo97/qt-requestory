# qtRequestory

Un solo file, `qtRequestory.exe`. Tiene una copia locale dei log giornalieri
delle chiamate al document generator e ti permette di ritrovare — e tirare
fuori — il body JSON di una singola chiamata, per FDI (il `correlation_id`
della pratica) o per template key.

Serve perché **sul server i log restano solo fino alla prossima pulizia**: chi
gestisce il server la fa a mano dal terminale OCP, e la pulizia **cancella** i
file. Quello che non è stato scaricato prima di una pulizia è perso: l'archivio
locale è l'unica copia che resta. L'attività pianificata scarica i log una volta
al giorno, con tentativi ogni ora; un giorno che manca in locale ma è ancora sul
server si recupera con *Sincronizza ora*.

---

## Installazione

1. Copia `qtRequestory.exe` in una cartella **stabile**, tua. Va benissimo
   `C:\Users\<tuo utente>\AppData\Local\qtRequestory\bin\`.
   Non lasciarlo in `Download`, in `%TEMP%`, in OneDrive o su un disco di rete:
   l'attività pianificata punta al percorso del file, e se il file sparisce o
   viene spostato la sincronizzazione smette di funzionare in silenzio (il
   programma ti avvisa se provi a pianificarlo da una di queste cartelle).
2. Doppio clic.

### «Windows ha protetto il PC» (SmartScreen)

Al primo avvio Windows può mostrare una finestra blu: l'eseguibile non è
firmato. Clicca **Ulteriori informazioni** e poi **Esegui comunque**. Succede
una volta sola per ogni versione dell'eseguibile.

Se invece l'antivirus lo mette in quarantena, segnalalo: l'eseguibile non è
compresso proprio per ridurre questi falsi positivi.

### Primo avvio

Parte una configurazione iniziale in tre passi:

1. **Archivio e strumenti** — dove tenere l'archivio locale dei log e dove si
   trova Notepad++ (se non c'è, i file si aprono con l'applicazione predefinita).
   L'archivio cresce nel tempo: mettilo su un disco con spazio e non dentro una
   cartella sincronizzata sul cloud. Se ci sono già dei log (per esempio quelli
   della vecchia sincronizzazione PowerShell) vengono indicizzati, non
   riscaricati. Se nella cartella ci sono log sistemati in un altro modo, o ne
   hai altrove («Hai già dei log altrove? *Scegli cartella…*»), la procedura li
   **importa alla fine** (vedi [Importare log da altre cartelle](#importare-log-da-altre-cartelle)).
2. **Ambienti** — nome e indirizzo di ciascun ambiente (vedi sotto).
3. **Automazione** — se registrare l'attività pianificata che scarica i log
   ogni giorno e se fare subito la prima sincronizzazione. Se sul PC c'è ancora
   la vecchia attività `NginxLogSync`, **resta dov'è** a meno che tu non spunti
   «Rimuovi il vecchio task NginxLogSync» (vedi più sotto).
   **La prima sincronizzazione scarica tutto lo storico ancora presente sul
   server**, fino all'ultima pulizia: possono essere diversi GB e richiedere
   parecchio tempo.

Se chiudi la configurazione iniziale con Annulla non viene salvato nulla: al
prossimo avvio ripartirà da capo.

Puoi rivedere tutto in seguito dalla pagina **Impostazioni**, che permette anche
di rieseguire questa configurazione iniziale.

### I due modi per inserire gli ambienti

Gli indirizzi degli ambienti non sono dentro il programma. Puoi darglieli così:

1. **Dalla procedura iniziale** (o da Impostazioni): li scrivi a mano, uno per
   ambiente.
2. **Con un file `environments.json` accanto all'eseguibile**: se lo trovi già
   pronto da un collega, mettilo nella stessa cartella di `qtRequestory.exe` e
   al primo avvio il programma lo propone. È il modo comodo per distribuire la
   stessa configurazione a tutti. Il formato è quello di
   `environments.example.json`:

   ```json
   [
     { "name": "svil", "url": "https://<indirizzo-sviluppo>/AutoDeploy/Input/", "enabled": true },
     { "name": "coll", "url": "https://<indirizzo-collaudo>/AutoDeploy/Input/", "enabled": true }
   ]
   ```

   Chiedi gli indirizzi veri a chi ti ha passato il programma: non stanno qui e
   non stanno nel repository.

> Gli ambienti sono raggiungibili **solo da rete aziendale o con la VPN attiva**
> (e senza altre VPN accese).

---

## Uso normale

In alto ci sono le pagine principali, **Ricerca** (`Ctrl+1`),
**Sincronizzazione** (`Ctrl+2`) e **Officina** (`Ctrl+3`, vedi
[Officina](#officina)); a destra lo stato della sincronizzazione di ogni
ambiente (cliccalo per aprire la pagina) e le icone di **Impostazioni**
(`Ctrl+,`) e **Info** (`F1`).

- **Sincronizzazione** — dice se la sincronizzazione automatica è attiva, se
  nell'archivio manca qualche giorno (un calendario degli ultimi 30 giorni per
  ambiente, vedi sotto) e permette di scaricare subito con *Sincronizza ora*
  (`Ctrl+Shift+S`). Normalmente non serve: ci pensa l'attività pianificata, e
  all'apertura il programma aggiorna da solo l'indice e fa una
  sincronizzazione se ce n'è bisogno.
- **Ricerca** — scegli l'ambiente e incolla nel campo di ricerca un FDI (basta
  l'inizio), una template key o direttamente il nome di una chiamata copiato dal
  log (`<fdi>_<KEY>_<id>.json`: compila FDI e key insieme). Scegli il periodo
  (7 / 30 / 90 giorni o un intervallo dal calendario) e premi `Invio`.
  La template key si confronta in modo **esatto**; passa a «contiene» per
  cercarne solo una parte. Dai risultati apri l'anteprima del body, copialo
  (`Ctrl+C`), salvalo (`Ctrl+S`), aprilo nell'editor (`Invio` o doppio clic)
  oppure trascina la riga dove ti serve il file.

Un FDI identifica **una pratica**, che fa **più chiamate** al document generator
(una per template principale). I risultati sono raggruppati per FDI (si può
disattivare con «Raggruppa per FDI»). Cercando solo per FDI viene selezionata
la chiamata con **più documenti** del giorno più recente — quella che contiene
tutta la pratica; aggiungi la template key per isolarne un'altra.

I file estratti finiscono in `%TEMP%\qtrequestory-calls\` e sono **temporanei**
(vengono ripuliti dopo 24 ore). Se ti servono, salvali altrove. Per lo stesso
motivo la cartella dei file estratti (Impostazioni › Archivio) **non può essere
la cartella dei log, stare dentro di essa o contenerla**: le impostazioni lo
rifiutano, e la pulizia non parte comunque se le due cartelle si
sovrappongono.

Le chiamate di oggi non ci sono ancora: sul server vengono compattate nel file
del giorno la sera, quindi arrivano con la sincronizzazione del giorno dopo.

### Il calendario della Sincronizzazione

Ogni ambiente ha un quadratino per ciascuno degli ultimi 30 giorni. La legenda
sotto le schede mostra solo i tipi che compaiono davvero:

| Quadratino | Significa |
|---|---|
| **presente** (verde) | il log del giorno è nell'archivio |
| **nessuna chiamata** (grigio pieno) | il server ha pubblicato il giorno vuoto (0 byte): quel giorno nessuno ha chiamato. Succede nei weekend, nei festivi e spesso su svil |
| **da scaricare** (ambra) | il giorno è ancora sul server ma non in locale: *Sincronizza ora* lo scarica |
| **perso** (rosso, «ripulito dal server») | il server lo elencava, ma è stato ripulito prima che venisse scaricato: non si può più recuperare, se non da una copia di un collega (vedi sotto) |
| **non verificabile** (bordo tratteggiato) | un giorno feriale che manca in locale e di cui il programma non sa nulla: è di prima che iniziasse a ricordare cosa c'è sul server |
| **weekend** | un sabato o una domenica di cui non si sa nulla |
| **oggi** | il log di oggi arriva domani |

Un giorno vuoto conta come «nessuna chiamata» solo quando il server lo ha
elencato **in un giorno successivo** (la sera stessa la compattazione potrebbe
non essere ancora avvenuta). Se un giorno è da scaricare compare un avviso con
il suo pulsante *Sincronizza ora*; se è perso, un avviso rosso. Anche la
Ricerca avvisa («2 giorni da scaricare in coll · 1 giorno non recuperabile»)
con *Vai a Sincronizzazione*. Dopo l'aggiornamento alla 1.1.0 i giorni vecchi
restano «non verificabile» o «weekend» finché la prima sincronizzazione non ha
letto l'elenco del server.
Se dopo la compattazione serale il server elenca il giorno di oggi vuoto, la
scheda dell'ambiente resta «aggiornato» (il suggerimento spiega che oggi non ci
sono state chiamate e che il giorno verrà confermato con la sincronizzazione di domani).

### Importare log da altre cartelle

Se tu o un collega avete log salvati altrove, in qualsiasi struttura di
cartelle, il programma li **copia** nell'archivio (in
`<ambiente>\AAAA\MM\AAAAMMGG.txt`): non li indicizza mai dove sono. In
Impostazioni › Archivio la riga «Log» dice quanti log ci sono in archivio e
quanti sono da importare, da assegnare o ignorati; *Dettagli…* apre
l'importazione sulla cartella dei log, *Importa log da una cartella…* su una
cartella che scegli. Se nella cartella dei log stessa ci sono file fuori
struttura, Ricerca e Sincronizzazione mostrano «Trovati N log fuori dalla
struttura dell'archivio» con il pulsante *Importa*.

Cosa riconosce:

- **la data** nel nome del file o, se non c'è, nelle cartelle sopra:
  `20260922`, `2026-09-22` (anche con `_` o `.`), le date italiane
  `22092026` e `22-09-2026`, e la struttura `2026\09\22.txt`. Due date diverse
  nello stesso nome, o un numero lungo che non è una data valida, danno «data
  ambigua» e il file viene saltato: niente tentativi;
- **l'ambiente** dal percorso, confrontandolo con i nomi degli ambienti che hai
  configurato (qualsiasi nome, maiuscole o minuscole, come parola intera:
  `coll_22-09-2026.txt`, `log svil\…`). Con un solo ambiente configurato è
  quello. Se il percorso non lo dice, l'importazione chiede **una volta per
  cartella** (gli ambienti configurati oppure «Ignora») e ricorda la scelta:
  finché l'ambiente non è noto quei file non vengono copiati;
- solo **log di chiamate** (la prima riga è `### <nome>.json`); un file vuoto
  vale come giorno senza chiamate solo se è un `.txt` con la data nel nome;
- i file **compressi** (`.zip`, `.gz`, `.7z`…) non vengono aperti: «archivio
  compresso: estrailo nella cartella», poi rifai la ricerca.

Ogni copia viene **verificata** (dimensione e contenuto) prima di entrare
nell'archivio. Un giorno già in archivio non viene mai sovrascritto, a meno che
la copia importata non sia la stessa più completa; due copie diverse dello
stesso giorno sono un **conflitto** e restano dove sono (anche una copia con
gli a capo convertiti in CRLF, se l'archivio ha già quel giorno).

Alla fine il programma chiede **«Vuoi cancellare gli originali?»**. Con
*Cancella originali* finiscono nel **Cestino** di Windows (si possono
ripristinare) **solo gli originali verificati**, cioè quelli il cui contenuto è
davvero nell'archivio, ricontrollati un'ultima volta; **nulla dentro la
cartella dei log viene mai cancellato**, e sui dischi di rete o rimovibili,
che non hanno Cestino, non si cancella nulla. Con *Tienili* non si tocca
niente. Poi l'indice si aggiorna da solo.

**Tema**: in Impostazioni › Aspetto puoi scegliere *Sistema* (segue Windows),
*Chiaro* o *Scuro*; si applica subito.

### Da riga di comando

Le stesse cose, senza finestra (utile negli script):

```powershell
qtRequestory.exe --sync                      # scarica e aggiorna l'indice
qtRequestory.exe --sync --dry-run            # elenca cosa scaricherebbe, senza scaricare
qtRequestory.exe --index                     # indicizza i log già presenti in locale
qtRequestory.exe --index --rebuild           # ricostruisce l'indice da zero
qtRequestory.exe --find -e coll -f aaaaaaaa  # estrae una chiamata per FDI
qtRequestory.exe --find -e coll -k MOD_TEST_A --days 90
qtRequestory.exe --task install|status|run|remove
qtRequestory.exe --archivio                  # log fuori struttura nella cartella dei log (non modifica nulla)
qtRequestory.exe --archivio D:\vecchi-log    # cosa farebbe l'importazione di un'altra cartella
qtRequestory.exe --import D:\vecchi-log      # copia e verifica, poi aggiorna l'indice
qtRequestory.exe --import D:\vecchi-log --env-for "log vecchi=coll" --env-for scarti=ignora
qtRequestory.exe --import D:\vecchi-log --delete-originals   # poi gli originali verificati nel Cestino
qtRequestory.exe --version
```

L'output compare nel terminale da cui lanci il comando. L'eseguibile però è un
programma "a finestra", quindi PowerShell non ne aspetta la fine: il prompt
torna subito e le righe arrivano dopo. Se ti serve aspettarlo o leggerne il
codice di uscita:

```powershell
$p = Start-Process .\qtRequestory.exe -ArgumentList '--sync' -NoNewWindow -Wait -PassThru
$p.ExitCode
```

Codici di uscita di `--sync`: `0` tutto ok, niente da fare, oppure una
sincronizzazione già in corso; `1` errori su qualche file; `2` nessun ambiente
raggiungibile (tipicamente VPN giù) **oppure** un problema di configurazione
(ambiente `-e` sconosciuto, cartella dei log non impostata): in quel caso il
messaggio stampato comincia con «Errore»; `3` interrotto. `--find` esce con `1`
se non trova nulla e con `2` per un ambiente sconosciuto.

`--archivio` elenca ogni file trovato con il suo stato (da importare, già
presenti, da assegnare, conflitti, ignorati) e il motivo; esce con `1` se
qualche file aspetta un ambiente o è in conflitto, altrimenti con `0`.
`--import` fa lo stesso elenco, copia e verifica, poi indicizza gli ambienti
toccati. `--env-for CARTELLA=AMBIENTE` (ripetibile; la cartella è relativa a
quella importata oppure assoluta; `ignora` la salta) vale solo per quel
comando e non viene salvato. Gli originali vanno nel Cestino solo con
`--delete-originals`, e solo quelli verificati fuori dalla cartella dei log.
Codici di uscita di `--import`: `0` tutto a posto; `1` errori, conflitti, file
ancora senza ambiente, originali non spostati nel Cestino, oppure una
sincronizzazione in corso (riprova quando è finita); `2` cartella inesistente,
ambiente di `--env-for` sconosciuto o cartella dei log non impostata; `3`
interrotto con Ctrl+C (in quel caso nessun originale viene cancellato).

`--find` fa quello che faceva il vecchio `nginx/find-call.py`, con due
differenze:

- il file estratto usa a capo LF e **finisce con un a capo**; il vecchio script
  scriveva CRLF e nessun a capo finale. Il JSON è identico: Postman, curl e
  qualsiasi parser li leggono allo stesso modo;
- estrarre **la stessa chiamata due volte non sovrascrive** il primo file: il
  secondo si chiama `..._<id chiamata>.json`, così un file ancora aperto
  nell'editor non cambia sotto le mani. La cartella non viene svuotata a ogni
  esecuzione: i file più vecchi di 24 ore vengono ripuliti.

---

## Officina

L'**Officina** (`Ctrl+3`) serve a chi modifica i template: porta un documento
dal suo stato attuale al **target**, cioè il PDF o l'HTML che il cliente ha
fornito come riferimento. Sostituisce, per questo lavoro, Postman più un
confronto a mano più le cartelle preparate a mano per i tester: genera i
documenti con gli header giusti, li mette accanto al target, dice per ogni
differenza se è **fatta, da fare, in corso o una regressione** rispetto a
com'era prima delle tue modifiche, e prepara la cartella di consegna.

Usala quando devi far combaciare uno o più documenti con quelli attesi dal
cliente (una richiesta di modifica, un aggiornamento dei testi…) e poi
consegnarli ai tester.

Le parole che usa:

- **Iniziativa** — un gruppo di documenti da consegnare insieme, per esempio
  tutti i moduli toccati da una stessa richiesta. È una cartella.
- **Caso** — un documento da portare al target: una template key, con
  eventualmente una **variante** (es. «abilitato») quando più casi hanno la
  stessa key con payload diversi. Ogni caso ha il suo payload e i suoi header.
- **TARGET** — il file del cliente, tenuto con il suo nome originale.
- **AS-IS** — il documento generato con il template di oggi, prima delle
  modifiche. Si genera una volta e resta fermo: è la base del confronto.
- **TO-BE** — il documento generato dopo ogni modifica, in versioni numerate
  `v1`, `v2`, … che restano tutte.

### Prima configurazione

1. **Impostazioni › Officina › Cartella dell'Officina**: scegli una cartella
   **locale**, sul tuo PC (es. `C:\Users\<tuo utente>\Officina`). Ci finiscono
   payload e documenti con **dati reali dei clienti**: non una cartella dentro
   un repository e, se puoi, non OneDrive né un disco di rete (sono ammessi, ma
   il programma lo segnala). Non può coincidere con la cartella dei log o con
   quella dei file estratti, né stare dentro di esse o contenerle. La stessa scelta si fa
   anche dalla scheda Officina la prima volta che la apri.
2. **Generatori**: aggiungi una riga per ogni document generator da chiamare
   (nome, URL, attivo), per esempio `svil`. Gli indirizzi veri chiedili a chi ti
   ha passato il programma: non stanno qui. Solo `https`; un nome o un URL che
   contiene `prod`, o `prd` come parola a sé (es. `svil-prd`), viene rifiutato
   (vedi [Sicurezza](#sicurezza)).
   **Generatore predefinito**: quello usato dai casi nuovi (di solito `svil`).
3. **Postman-Token predefinito**: già compilato; lascialo non vuoto (vedi
   sotto).
4. **Profilo intestazioni**: `service_number`, `office_id`, `branch_id` con i
   valori delle collection Postman del team. Vengono inviati a ogni generazione.
5. **Timeout di generazione**: 120 secondi di serie.

### Il ciclo di lavoro

1. **Crea un'iniziativa** (*Nuova iniziativa*) e aggiungi i casi:
   - da **Ricerca**: cerca la chiamata, tasto destro sulla riga ›
     **Aggiungi all'Officina…**, scegli l'iniziativa (o creane una) e, se serve,
     la variante. Payload, template key e FDI vengono dalla chiamata;
   - da un **file JSON** (*+ Caso da file…*): la key viene proposta dal payload.
2. **Target…**: scegli il file del cliente (PDF o HTML).
3. **Genera AS-IS** da svil, con il template com'è oggi. Sulla bacheca
   dell'iniziativa *Genera AS-IS mancanti* lo fa per tutti i casi che non ce
   l'hanno. L'AS-IS si può rigenerare (*Rigenera AS-IS…*) solo scrivendo una
   nota con il motivo; quello vecchio resta conservato nella cartella del caso.
4. **Confronta con il target**: nel caso, il target è a sinistra e il documento
   generato a destra; ogni differenza è evidenziata con il colore del suo
   **verdetto** e ha una riga nell'elenco a destra (vedi
   [Leggere il confronto](#leggere-il-confronto)). Cliccando una differenza,
   nell'elenco o sulla pagina, entrambi i documenti ci vanno; scorrimento e
   zoom (`Ctrl`+rotella) restano allineati. Sopra il documento di destra scegli
   cosa vedere: AS-IS, `v1`, `v2`, …. Con un TO-BE hai i verdetti; con l'AS-IS
   vedi, senza verdetto, le sue differenze dal target che il profilo del caso
   conta (ogni riga dice che tipo di differenza è: «cambiato · stile»,
   «(stesse parole)»…).
5. **Modifica in Designer** template, master template, data master o
   workflow, e **pubblica** su svil. Mentre lavori, segna con `F` le
   differenze che hai corretto (**segna fatta**): la prossima rigenerazione le
   verifica.
6. **Rigenera il TO-BE** con `F5` (o *Rigenera TO-BE (F5)*): stesso payload,
   stessi header, una nuova versione. Il confronto si aggiorna da solo. Dalla
   bacheca, *Rigenera TO-BE selezionati* rigenera più casi insieme (al massimo
   tre alla volta; un caso che fallisce non ferma gli altri; *Annulla
   generazioni* toglie quelli ancora in coda).
7. Ripeti 5–6 finché non resta niente da fare, poi **Segna accettato**. Se
   restano differenze aperte il programma le riassume e chiede conferma
   («Restano 1 regressione, 2 da fare, 1 da verificare. Segnare il caso
   accettato lo stesso?»); non lo impedisce.
   L'accettazione vale per **quella** versione del TO-BE: se poi arriva un nuovo
   TO-BE o un nuovo AS-IS il caso torna aperto con l'avviso «Nuova versione
   dopo l'accettazione: da ricontrollare» (sulla bacheca: *da ricontrollare*).
   *Riapri* riporta il caso in lavorazione se arriva una correzione.

Durante l'invio il caso e la bacheca dicono su quale generatore sta andando
(«Generazione su svil…»); l'intestazione del caso mostra sempre il suo
generatore.

*Payload e header…* apre il payload (JSON, con controllo di validità e
*Formatta*) e le impostazioni di invio del caso: il generatore, il
`correlation_id` (nuovo a ogni invio, l'FDI della chiamata di origine, oppure un
valore fisso), cosa fare dei link di upload e gli header del caso. Gli header si
compongono in quest'ordine, e ogni livello prevale su quelli prima:

1. **automatici**: `template_key` (la key del caso), `current_timestamp` (ora,
   in millisecondi), `correlation_id`, `Postman-Token`;
2. il **profilo** di Impostazioni;
3. i **predefiniti dell'iniziativa** (per ora si scrivono a mano in
   `header_defaults` dentro `iniziativa.json`);
4. le righe del **caso**, che prevalgono su tutto: così puoi fissare, per
   esempio, un `current_timestamp` preciso o aggiungere un header proprio dell'iniziativa.

Un header con valore vuoto non viene inviato. `Postman-Token` si toglie solo
con l'opzione esplicita *Non inviare Postman-Token*.

La bacheca dell'iniziativa mostra per ogni caso quali documenti ci sono
(T, A, `vN`; «—» se manca, in rosso se il file è sparito dal disco), la
pillola «TO-BE contro target», l'ultima generazione (o il motivo per cui è
fallita) e lo stato. `Invio` o doppio clic apre il caso. La pillola dice lo
**stato peggiore** del caso con il suo conteggio e l'avanzamento («▲ 1
regressione · 60%»; il tooltip ha la ripartizione completa). È quella
dell'ultimo confronto fatto: se nel frattempo sono arrivati un TO-BE, un
AS-IS o un target nuovi dice «v3 · da riconfrontare», e «da confrontare» se
il caso non è mai stato aperto con un TO-BE. La bacheca non confronta niente
da sola: apri il caso per aggiornarla.

Un'iniziativa è la sua **cartella**: se ne copi una in Esplora risorse, la
copia è un'iniziativa a sé (nell'elenco, due iniziative con lo stesso nome
mostrano anche la cartella, es. «Banco (Banco - Copia)»), e la consegna va in
una cartella con il nome della sua cartella.

Se `iniziativa.json` o il `caso.json` di un caso si rovinano (una modifica a
mano sbagliata), il programma lo dice sulla bacheca o nel caso e **non li
riscrive mai**: con `iniziativa.json` illeggibile non si genera niente (gli
header predefiniti non sono noti); un caso con `caso.json` illeggibile si può
guardare ma non modificare, accettare né generare. Correggi o ripristina il
file e riapri.

### Leggere il confronto

Per il TO-BE scelto il programma fa due confronti, AS-IS contro target e TO-BE
contro target, e li mette insieme. Ogni differenza ha un **verdetto**, sempre
con colore, simbolo e parola:

| Verdetto | Sul documento | Vuol dire |
|---|---|---|
| ▲ **regressione** | riempimento rosso | nell'AS-IS era uguale al target, ora no: l'hai introdotta tu |
| ○ **da fare** | riempimento ambra | c'era già nell'AS-IS, identica: nessuno l'ha ancora toccata |
| ◐ **in corso** | riempimento azzurro | c'era nell'AS-IS, ora il testo generato è un altro ma è ancora diverso dal target («Prima … → ora …») |
| ✓? **da verificare** | bordo verde tratteggiato | l'hai segnata fatta: la verifica la prossima rigenerazione |
| ✓ **fatta** | sottolineatura verde sul target, con *Mostra fatte* | c'era nell'AS-IS e ora non c'è più |
| ⊘ **tollerata** | bordo grigio tratteggiato | non conta: per il profilo o perché l'hai tollerata tu |
| {x} **variabile** | sottolineatura viola | un dato del cliente dove il target ha un buco (vedi sotto) |
| ~ **rumore** | bordo grigio tratteggiato | testo coperto da una regola di rumore |

Dentro una parola, i **caratteri cambiati** sono in giallo, in grassetto e
sottolineati: «abilitat**a**» contro «abilitat**o**» si vede anche da lontano.
Variabili e rumore non hanno verdetto e non contano mai.

Sopra i documenti, la **barra dell'avanzamento**: la percentuale (fatte / (fatte
+ da fare + in corso + regressioni)), la versione confrontata («v3 contro
target»), una pillola per stato e una **striscia** con una tacca per differenza
in ordine di documento (clic = ci vai). Accanto a ciascun documento una
**minimappa** fa lo stesso lungo la barra di scorrimento. Senza AS-IS il
verdetto è **a due vie**: tutto ciò che conta è «da fare», niente regressioni;
la pillola «⚠ a due vie» lo dice e offre *Genera l'AS-IS*.

L'**elenco** ha sei schede con il conteggio: *Da guardare* (regressioni, non
risolte, da fare, in corso), *Da verificare*, *Fatte*, *Tollerate*,
*Variabili*, *Tutte* (anche il rumore). Sotto le schede, *Mostra fatte*
sottolinea in verde sul target (e nella minimappa) le differenze già fatte;
aprire la scheda *Fatte* lo accende. Ogni riga ha il verdetto, il tipo
(Aa testo, ▦ composizione — sezione mancante o in più, pagine —, ⇄ spostato,
¶ stile, ↔ spaziatura, 🔗 link), la pagina e un pezzo di testo attorno alla
differenza, con il testo del target barrato e quello generato in grassetto.

Il programma riconosce da solo:

- le **variabili** del target: righe di puntini o trattini bassi
  (`Località ..........`) ed etichette seguite dal vuoto (`CAP:` a fine riga,
  `Città, ` in testa a una lettera). Quello che il documento generato ci mette è
  una *variabile*; un'etichetta «probabile» accetta al massimo un valore corto
  (6 parole, una riga), oltre resta una differenza normale;
- **caselle** e **campi a caselle**: `❏`, `☐` o una `q` Wingdings contro `[ ]`,
  `[x]` contro `☒`, un IBAN scritto una lettera per casella;
- **sezioni** mancanti o in più (una differenza sola, non un muro di parole),
  **blocchi spostati**, un numero di **pagine** diverso; il testo andato a capo
  in un altro punto o su un'altra pagina non conta.

### Segna fatta, tollera, non è una variabile

Dall'elenco o dal documento, sulla differenza selezionata:

| Azione | Tastiera | Mouse |
|---|---|---|
| **Segna fatta** / togli il segno | `F` | doppio clic, o *✓ Fatta* nella mini-barra |
| **Tollera** (senza nota) / non tollerare più | `T` | *⊘ Tollera* nella mini-barra |
| **Tollera…** con una nota | — | clic destro › *Tollera…* |
| **Non è una variabile** / di nuovo variabile | `V` | clic destro |
| Copia testo del target / generato | — | clic destro |
| Annulla l'ultima azione | `Ctrl+Z` | *Annulla* nel messaggio |

Un clic su un'evidenziazione la seleziona e apre la **mini-barra**
(«✓ Fatta F · ⊘ Tollera T · ⋯»). `↑`/`↓` scorrono l'elenco, `Invio` porta alla
differenza in entrambi i documenti. `F`, `T` e `V` passano subito alla riga
dopo, quindi `F` `F` `F` segna tre righe di fila; le azioni vanno in coda e si
applicano in ordine, anche mentre il caso si sta riconfrontando.

- **Segna fatta** serve mentre lavori in Designer: la differenza passa a «da
  verificare» e una striscia lo ricorda («2 modifiche da verificare: pubblica
  su svil e rigenera il TO-BE (F5)», con *Annulla i segni*). Al primo TO-BE più
  nuovo di quelli che c'erano quando hai segnato (anche se stavi guardando una
  versione più vecchia) il programma verifica ogni segno: sparita → **fatta**; ancora lì,
  uguale → torna al suo verdetto con il contrassegno **non risolta**, in cima
  all'elenco («Segnata fatta in v3, ma in v4 è ancora qui.»); ancora lì ma
  cambiata → **in corso**. L'esito resta in una striscia («v4: verificate 3
  modifiche segnate — 2 risolte, 1 non risolta») finché non fai altro. Una
  regressione non risolta resta una regressione («regressione · non risolta»)
  e conta in tutti e due i totali. Un segno su una differenza
  che al momento non conta (tollerata) resta fermo finché non torna a contare.
- **Tollera** vale solo per quel caso e sopravvive alle rigenerazioni finché
  il testo generato in quel punto resta lo stesso; se cambia, la differenza
  torna a contare. Non passa ad altri casi né ad altre iniziative. *⋯ ›
  Azzera tolleranze…* nell'intestazione del caso toglie, dopo una conferma,
  tutte le tolleranze a mano e le correzioni «non è una variabile» del caso
  (non si annulla).
- **Non è una variabile**: quando il programma ha preso per variabile un punto
  che non lo è, `V` lo fa contare come differenza di testo; `V` di nuovo lo
  riporta variabile.

*Segna accettato* chiede conferma con il riepilogo di cosa resta nell'ultimo
TO-BE (o dice che non è ancora stato confrontato, o che un lato non ha testo
estraibile), ma non blocca. Sostituire il **target** di un caso che ha segni o un riepilogo
chiede conferma: segni, «non risolte» e riepilogo si azzerano; tolleranze e
«non è una variabile» restano, ma valgono solo dove il testo coincide ancora
(la scheda *Tutte* dice quante non si applicano più: «Tutte 7 ⊘1»).

### Profili e regole di rumore

Il **profilo** decide che cosa conta; si sceglie nell'intestazione del caso
(*Profilo: … ▾*):

| Profilo | Contano | Tollerate da sole |
|---|---|---|
| **Tollerante** (predefinito) | testo, composizione, link | stile (dimensione e grassetto), spaziatura |
| **Stretto** | anche stile e spaziatura | — |
| **Solo testo** | solo il testo | tutto il resto |

«Come l'iniziativa» segue il profilo dell'iniziativa (`profilo` in
`iniziativa.json`, di serie `tollerante`).

Le **regole di rumore** (*Regole di rumore…*, sulla bacheca per l'iniziativa e
nell'intestazione del caso) tolgono dal conteggio il testo che cambia a ogni
generazione. Ci sono dei **preset**, tutti spenti finché non li accendi:
numero di pagina, data, IBAN, codice fiscale, CAP, importo, marcatore di firma,
parametri di tracciamento nei link. Puoi aggiungere regole tue (un nome e
un'espressione regolare, per esempio `PR-\d{6}` per un numero di pratica):
prima di salvare, ogni regola mostra quante volte la trova nel target e
nell'ultimo TO-BE, e un'espressione sbagliata è segnata in rosso sulla sua
riga. Le regole cercano nel testo normalizzato (virgolette e trattini
uniformati). Le regole del caso si sommano a quelle dell'iniziativa; i preset
valgono per tutta l'iniziativa; due regole non possono avere lo stesso nome.
*Salva e riconfronta* rifà il confronto.

Un'espressione che rischia di bloccare il programma viene rifiutata con
«espressione potenzialmente troppo lenta: semplificala». Le regole tue non
girano mai dentro il programma: le cerca un processo a parte, sullo stesso
testo che il confronto usa, con un limite di 2 secondi; una che lo supera (o
che non si può usare) resta fuori dal confronto, e una nota lo dice.

### Casi HTML

Un'email HTML si confronta attraverso il suo **DOM** (il testo visibile, senza
commenti, stili, script ed elementi nascosti), con le stesse regole dei PDF:
variabili, rumore, sezioni, verdetti, segni. Si confrontano anche **link e
immagini**: `href`, `src` e `alt` devono coincidere (con il preset dei
parametri di tracciamento acceso, `utm_*` e simili non contano). Il
documento resta mostrato come stampa PDF di Microsoft Edge; il selettore
*Documenti | DOM* apre la scheda **DOM**: i blocchi del target con il loro
verdetto e i due sorgenti affiancati, con le righe che differiscono
evidenziate. Una differenza che non si vede sulla pagina (un link) sta
nell'elenco e nella scheda DOM. Senza Microsoft Edge (o se la stampa non
riesce) un TO-BE HTML si confronta lo stesso dal DOM: i documenti dicono
«Stampa dell'HTML non disponibile (…)», la scheda DOM diventa la vista
principale, elenco, verdetti e azioni funzionano. La vista AS-IS di un caso
HTML, invece, ha bisogno della stampa.

### La consegna ai tester

*Consegna…* (sulla bacheca) copia i documenti in una cartella di destinazione,
di solito quella condivisa con i tester. Sono già spuntati i casi accettati
sull'ultimo TO-BE; se aggiungi casi non accettati, o il cui ultimo TO-BE non è
quello accettato, il programma lo dice. La destinazione proposta è l'ultima
usata per quell'iniziativa. Il risultato è:

```
<destinazione>\<Iniziativa>\
  MOD_TEST_ESEMPIO\
    MOD_TEST_ESEMPIO_ASIS.pdf
    MOD_TEST_ESEMPIO_TOBE.pdf          l'ultima versione del TO-BE
    Nome originale del cliente.pdf     il target, con il suo nome
```

- Se consegni **più varianti della stessa key**, stanno nella stessa cartella
  come `<KEY>_<variante>_ASIS` / `<KEY>_<variante>_TOBE`; i target tengono il
  loro nome e, se due hanno lo stesso nome, prendono ` (<variante>)` prima
  dell'estensione. Un caso HTML consegna file `.html`.
- Un documento che manca (es. nessun TO-BE) viene saltato ed elencato, mai
  inventato.
- Un file già presente nella destinazione non viene mai sovrascritto senza
  chiedere: *Sostituisci*, *Mantieni entrambi* (il nuovo prende ` (2)`) o
  *Salta*, con *Applica a tutti*.
- **Crea anche lo zip** scrive anche `<destinazione>\<Iniziativa>.zip`, con i
  soli file di questa consegna. Se la consegna non è completa lo zip non viene
  creato.

### Sicurezza

- **Fuori dai log nginx**: ogni chiamata porta un `Postman-Token` non vuoto (di
  serie `qtRequestory`). Con quell'header il document generator non scrive la
  chiamata nei log nginx, così le prove non finiscono nell'archivio di nessuno.
  Si toglie solo dal singolo caso, con l'opzione esplicita.
- **Link di upload**: i payload presi dai log contengono gli `attachmentUrl`,
  link firmati dove il generatore scriverebbe il PDF, cioè il documento di un
  cliente vero. Di serie vengono **rimossi** prima dell'invio (il generatore
  restituisce comunque il documento). In alternativa *Lascia solo se tutti
  scaduti*. Un link firmato ancora valido, ovunque sia nel payload, **non viene
  mai inviato**: la generazione viene rifiutata e il motivo lo dice. Nei
  messaggi i link compaiono sempre mascherati (`…?sig=***`); nel log del
  programma resta solo il nome del server.
- **Mai PROD**: un generatore il cui nome o URL contiene `prod` (in qualsiasi
  forma), o `prd` come parola a sé, non si può salvare e non viene chiamato; si accetta solo `https` e i
  reindirizzamenti non vengono seguiti. Un caso può usare solo un generatore
  configurato e attivo.
- **Cartella locale**: payload e documenti restano nella cartella
  dell'Officina, mai nei log del programma. Tienila sul disco locale, non in
  OneDrive: il programma lo permette ma avvisa, perché tutto verrebbe copiato
  nel cloud.

### Limiti

- Si confronta il **testo**, con dimensione e grassetto delle parole. Le
  immagini, le tabelle cella per cella e lo stile carattere per carattere non
  sono confrontati.
- Un PDF senza testo (una scansione, o un TO-BE uscito vuoto) non si
  confronta: il programma dice che quel documento «non ha testo estraibile»,
  non dà verdetti e non aggiorna il riepilogo; i segni «fatta» non si
  verificano contro una versione senza testo e aspettano la prossima. Un
  AS-IS senza testo rende il verdetto «a due vie». Non c'è OCR.
- Il primo confronto di documenti lunghi richiede qualche secondo (due PDF di
  60 pagine circa 10 s la prima volta); poi le estrazioni restano in `cache\`
  nella cartella del caso, anche dopo un riavvio, e un nuovo confronto costa
  circa 2 s.
- Il profilo dell'iniziativa e i predefiniti degli header dell'iniziativa non
  hanno ancora una schermata: si scrivono in `iniziativa.json`.
- Dopo aver cambiato le regole di rumore la bacheca mostra il riepilogo
  vecchio di ogni caso finché non lo riapri.
- *Segna accettato* non è bloccato dalle differenze (è voluto); il motivo di
  una generazione fallita si perde alla chiusura del programma.

Gli altri punti aperti (immagini, tabelle, riepilogo in PDF nella consegna…)
sono in `docs/BACKLOG.md`.

---

## Dove finiscono le cose

| Cosa | Dove |
|---|---|
| Configurazione | `%LOCALAPPDATA%\qtRequestory\config.json` |
| Log del programma | `%LOCALAPPDATA%\qtRequestory\logs\app.log` |
| Log delle sincronizzazioni | `%LOCALAPPDATA%\qtRequestory\logs\sync.log` |
| Archivio dei log scaricati | la cartella scelta al primo avvio, in `<ambiente>\AAAA\MM\AAAAMMGG.txt` (un giorno senza chiamate è un file vuoto) |
| Indice di ricerca | `<archivio>\.qtrequestory\index.sqlite` |
| File estratti | `%TEMP%\qtrequestory-calls\` (temporanei) |
| Preferenze della finestra (tema, ricerche recenti…) | registro utente, `HKCU\Software\qtRequestory` |
| Officina (iniziative, casi, payload, documenti generati) | la cartella scelta in Impostazioni › Officina, vedi [Officina](#officina) |

La pagina **Info** mostra tutti questi percorsi, con i pulsanti per copiarli e
aprirli, e le ultime righe del log del programma.

Nell'archivio, nell'indice e nella cartella dell'Officina ci sono **dati reali
di clienti**: trattali come tali, non copiarli fuori dal PC aziendale.

---

## Cosa fare se…

**…la sincronizzazione dice che l'ambiente non è raggiungibile.**
È quasi sempre la VPN. Accendi il Cisco Secure Client (e spegni eventuali altre
VPN), poi premi *Sincronizza ora*. Non è un problema se salti qualche ora o
qualche giorno: l'attività pianificata riprova ogni ora fino a sera, un ambiente
irraggiungibile non blocca l'altro, e il server tiene i log fino alla prossima
pulizia manuale, quindi la sincronizzazione successiva scarica tutti i giorni
che mancano. Un giorno ripulito dal server prima di essere scaricato, invece, è
perso. La pagina Sincronizzazione (e la Ricerca) ti avvisano sia dei giorni da
scaricare sia di quelli persi.

**…un collega mi ha passato i suoi log vecchi.**
Mettili in una cartella qualsiasi (estrai gli zip) e usa Impostazioni ›
Archivio › *Importa log da una cartella…*, oppure `--import`: vedi
[Importare log da altre cartelle](#importare-log-da-altre-cartelle). I giorni
che a te mancano e che sono nei suoi log entrano così nell'archivio.

**…la ricerca non trova qualcosa che dovrebbe esserci.**
Prima allarga il periodo, e se cerchi una template key parziale passa a
«contiene». Se il file c'è nell'archivio ma non nei risultati, l'indice è
rimasto indietro: di solito basta

```powershell
qtRequestory.exe --index
```

che indicizza solo i file nuovi o cambiati — per esempio quelli scaricati dalla
vecchia attività PowerShell. Solo se qualcosa sembra ancora storto
ricostruiscilo da zero con `--index --rebuild` (o Impostazioni › Archivio ›
*Ricostruisci indice*): rilegge tutto l'archivio e richiede qualche minuto.
L'indice si può cancellare senza paura (`index.sqlite`), viene ricreato; se si
rovina, il programma lo mette da parte e ne crea uno nuovo da solo.

**…ho spostato l'eseguibile e non sincronizza più.**
L'attività pianificata contiene il percorso vecchio. Dalla cartella nuova:

```powershell
qtRequestory.exe --task status     # dice dove punta l'attività
qtRequestory.exe --task install    # la riscrive sul percorso attuale
```

La pagina Sincronizzazione segnala da sola quando l'attività punta a un
eseguibile diverso da quello che stai usando, con un pulsante *Aggiorna*.

**…voglio vedere se l'attività pianificata ha funzionato.**
Guarda la pagina Sincronizzazione (prossimo avvio, ultima esecuzione ed esito,
e il *Registro dell'ultima esecuzione*), oppure `qtRequestory.exe --task
status`, oppure le ultime righe di `sync.log`. Di serie l'attività gira alle
09:00 e riprova ogni ora fino alle 18:00, e anche al login; gli orari si
cambiano in Impostazioni › Sincronizzazione automatica. Se il PC è spento alle
09:00 parte all'accensione. Gira come te (senza password salvate), quindi la
VPN disponibile è la tua.

**…parte lento.**
Il primo avvio richiede qualche secondo (~5 s su un portatile aziendale):
l'eseguibile è un file unico che si scompatta a ogni avvio, e l'antivirus lo
ispeziona. È il prezzo dell'avere un solo file da copiare. Non influisce sulla
ricerca, che una volta aperta la finestra è immediata.

**…convivono la vecchia sincronizzazione PowerShell e questa?**
Sì, e nella fase di passaggio conviene tenerle entrambe: la configurazione
iniziale **non** rimuove la vecchia attività a meno che tu non lo chieda. Le
due attività pianificate (`NginxLogSync` e `qtRequestory Sync`) saltano
entrambe i file già presenti in locale con la stessa dimensione e scaricano
entrambe su file `.part` rinominati solo a download finito, quindi non si
rovinano il lavoro a vicenda nemmeno puntando alla stessa cartella. Partendo
entrambe alle 09:00 sulla stessa cartella, però, può capitare che una trovi un
file occupato dall'altra: in quel caso nel log compare **un errore di
condivisione per quel giro**, e il tentativo dell'ora successiva lo recupera.
Dopo che la vecchia ha scaricato qualcosa, `--index` (o semplicemente riaprire
il programma) lo rende ricercabile. La vecchia si toglie quando la nuova ha
dimostrato di funzionare per qualche giorno, con `.\install-task.ps1
-Uninstall` nella vecchia cartella, oppure rieseguendo la configurazione
iniziale e spuntando «Rimuovi il vecchio task NginxLogSync».

---

## Per chi sviluppa

Progetto Python 3.12, src-layout. Dipendenze a runtime: PySide6 e `pypdfium2`
(solo per l'Officina: la importa soltanto `qtrequestory.officina.pdf`, e mai la
`--sync` pianificata). Il cuore (`qtrequestory.core`) usa solo la libreria
standard; solo `qtrequestory.ui` importa Qt. Le licenze dei componenti di terzi
inclusi nell'eseguibile sono in `src/qtrequestory/THIRD-PARTY-NOTICES.md`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[ui,dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m qtrequestory            # GUI
.venv\Scripts\python -m qtrequestory --sync     # sincronizzazione headless
.venv\Scripts\python scripts\dev\shoot.py --size 1366x768 --out <cartella>   # screenshot, dati finti
```

Build dell'eseguibile (esegue i test, impacchetta, prova l'exe prodotto):

```powershell
.\scripts\build.ps1
```

Vedi `docs/DESIGN-core.md` (compreso §Packaging) e `docs/DESIGN-ui.md`, che
descrivono il codice com'è; i punti aperti sono in `docs/BACKLOG.md`.
`environments.json`, `config.json` e qualsiasi archivio di log non si
committano mai: sono in `.gitignore`. Il repository è pubblico: niente
indirizzi interni, FDI reali, template key dei clienti o estratti di log nei
test e nei documenti; gli screenshot, se mai servissero, solo con dati finti
(`scripts/dev/shoot.py`). Licenza MIT (`LICENSE`).
