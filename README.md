# qtRequestory

Un solo file, `qtRequestory.exe`. Tiene una copia locale dei log giornalieri
delle chiamate al document generator e ti permette di ritrovare — e tirare
fuori — il body JSON di una singola chiamata, per FDI (il `correlation_id`
della pratica) o per template key.

Serve perché **sul server i log restano circa un giorno**: se nessuno li scarica
vanno persi. L'attività pianificata ci pensa da sola una volta al giorno, con
tentativi ogni ora; l'archivio locale è l'unico che resta.

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
   riscaricati.
2. **Ambienti** — nome e indirizzo di ciascun ambiente (vedi sotto).
3. **Automazione** — se registrare l'attività pianificata che scarica i log
   ogni giorno e se fare subito la prima sincronizzazione. Se sul PC c'è ancora
   la vecchia attività `NginxLogSync`, **resta dov'è** a meno che tu non spunti
   «Rimuovi il vecchio task NginxLogSync» (vedi più sotto).

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

In alto ci sono le due pagine principali, **Ricerca** (`Ctrl+1`) e
**Sincronizzazione** (`Ctrl+2`); a destra lo stato della sincronizzazione di
ogni ambiente (cliccalo per aprire la pagina) e le icone di **Impostazioni**
(`Ctrl+,`) e **Info** (`F1`).

- **Sincronizzazione** — dice se la sincronizzazione automatica è attiva, se
  nell'archivio manca qualche giorno (un calendario degli ultimi 30 giorni per
  ambiente) e permette di scaricare subito con *Sincronizza ora*
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
(vengono ripuliti dopo un giorno). Se ti servono, salvali altrove.

Le chiamate di oggi non ci sono ancora: sul server vengono compattate nel file
del giorno la sera, quindi arrivano con la sincronizzazione del giorno dopo.

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

`--find` fa quello che faceva il vecchio `nginx/find-call.py`, con due
differenze:

- il file estratto usa a capo LF e **finisce con un a capo**; il vecchio script
  scriveva CRLF e nessun a capo finale. Il JSON è identico: Postman, curl e
  qualsiasi parser li leggono allo stesso modo;
- estrarre **la stessa chiamata due volte non sovrascrive** il primo file: il
  secondo si chiama `..._<id chiamata>.json`, così un file ancora aperto
  nell'editor non cambia sotto le mani. La cartella non viene svuotata a ogni
  esecuzione: i file più vecchi di un giorno vengono ripuliti.

---

## Dove finiscono le cose

| Cosa | Dove |
|---|---|
| Configurazione | `%LOCALAPPDATA%\qtRequestory\config.json` |
| Log del programma | `%LOCALAPPDATA%\qtRequestory\logs\app.log` |
| Log delle sincronizzazioni | `%LOCALAPPDATA%\qtRequestory\logs\sync.log` |
| Archivio dei log scaricati | la cartella scelta al primo avvio, in `<ambiente>\AAAA\MM\AAAAMMGG.txt` |
| Indice di ricerca | `<archivio>\.qtrequestory\index.sqlite` |
| File estratti | `%TEMP%\qtrequestory-calls\` (temporanei) |
| Preferenze della finestra (tema, ricerche recenti…) | registro utente, `HKCU\Software\qtRequestory` |

La pagina **Info** mostra tutti questi percorsi, con i pulsanti per copiarli e
aprirli, e le ultime righe del log del programma.

Nell'archivio e nell'indice ci sono **dati reali di clienti**: trattali come
tali, non copiarli fuori dal PC aziendale.

---

## Cosa fare se…

**…la sincronizzazione dice che l'ambiente non è raggiungibile.**
È quasi sempre la VPN. Accendi il Cisco Secure Client (e spegni eventuali altre
VPN), poi premi *Sincronizza ora*. Non è un problema se salti qualche ora:
l'attività pianificata riprova ogni ora fino a sera e un ambiente irraggiungibile
non blocca l'altro. Se resti scollegato per giorni, però, i giorni scoperti si
perdono: il server tiene i log circa un giorno. La pagina Sincronizzazione (e
la Ricerca) ti avvisano se nell'archivio manca un giorno feriale.

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

Progetto Python 3.12, src-layout, nessuna dipendenza a runtime oltre a PySide6.
Il cuore (`qtrequestory.core`) usa solo la libreria standard; solo
`qtrequestory.ui` importa Qt.

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
