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

1. **Cartella dei log** — dove tenere l'archivio locale. Cresce nel tempo:
   mettila su un disco con spazio e non dentro una cartella sincronizzata sul
   cloud. Se ci sono già dei log (per esempio quelli della vecchia
   sincronizzazione PowerShell) vengono indicizzati, non riscaricati.
2. **Ambienti** — nome e indirizzo di ciascun ambiente (vedi sotto).
3. **Automazione** — se registrare l'attività pianificata che scarica i log
   ogni giorno, il percorso dell'editor per i file estratti e se fare subito la
   prima sincronizzazione.

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

- **Sincronizzazione** — mostra lo stato di ogni ambiente e permette di
  scaricare subito. Normalmente non serve: ci pensa l'attività pianificata.
- **Ricerca** — scegli l'ambiente, incolla l'FDI (basta l'inizio) e/o scegli la
  template key, scegli il periodo, `Invio`. Dai risultati apri l'anteprima del
  body, copialo, salvalo o aprilo nell'editor.

Un FDI identifica **una pratica**, che fa **più chiamate** al document generator
(una per template principale). Cercando solo per FDI ti viene proposta la
chiamata con più documenti — quella che contiene tutta la pratica — e ti viene
detto quante altre entry dello stesso giorno corrispondono. Aggiungi la template
key per isolarne una.

I file estratti finiscono in `%TEMP%\qtrequestory-calls\` e sono **temporanei**
(vengono ripuliti). Se ti servono, salvali altrove.

Le chiamate di oggi non ci sono ancora: sul server vengono compattate nel file
del giorno la sera, quindi arrivano con la sincronizzazione del giorno dopo.

### Da riga di comando

Le stesse cose, senza finestra (utile negli script):

```powershell
qtRequestory.exe --sync                      # scarica e aggiorna l'indice
qtRequestory.exe --index --rebuild           # ricostruisce l'indice da zero
qtRequestory.exe --find -e coll -f aaaaaaaa  # estrae una chiamata per FDI
qtRequestory.exe --find -e coll -k MOD_TEST_EMAIL_GAS --days 90
qtRequestory.exe --task install|status|run|remove
qtRequestory.exe --version
```

Codici di uscita di `--sync`: `0` tutto ok o niente da fare, `1` errori su
qualche file, `2` nessun ambiente raggiungibile (tipicamente VPN giù), `3`
interrotto.

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

Nell'archivio e nell'indice ci sono **dati reali di clienti**: trattali come
tali, non copiarli fuori dal PC aziendale.

---

## Cosa fare se…

**…la sincronizzazione dice che l'ambiente non è raggiungibile.**
È quasi sempre la VPN. Accendi il Cisco Secure Client (e spegni eventuali altre
VPN), poi premi *Sincronizza ora*. Non è un problema se salti qualche ora:
l'attività pianificata riprova ogni ora fino a sera e un ambiente irraggiungibile
non blocca l'altro. Se resti scollegato per giorni, però, i giorni scoperti si
perdono: il server tiene i log circa un giorno.

**…la ricerca non trova qualcosa che dovrebbe esserci.**
Prima allarga il periodo. Se il file c'è nell'archivio ma non nei risultati,
l'indice è rimasto indietro: ricostruiscilo con

```powershell
qtRequestory.exe --index --rebuild
```

Rileggere tutto l'archivio richiede qualche minuto; l'indice si può cancellare
senza paura (`index.sqlite`), viene ricreato.

**…ho spostato l'eseguibile e non sincronizza più.**
L'attività pianificata contiene il percorso vecchio. Dalla cartella nuova:

```powershell
qtRequestory.exe --task status     # dice dove punta l'attività
qtRequestory.exe --task install    # la riscrive sul percorso attuale
```

La pagina Impostazioni segnala da sola quando l'attività punta a un eseguibile
diverso da quello che stai usando.

**…voglio vedere se l'attività pianificata ha funzionato.**
`qtRequestory.exe --task status`, oppure guarda le ultime righe di
`sync.log`. Di serie l'attività gira alle 09:00 e riprova ogni ora fino alle
18:00; se il PC è spento alle 09:00 parte all'accensione. Gira come te (senza
password salvate), quindi la VPN disponibile è la tua.

**…parte lento.**
Il primo avvio richiede qualche secondo (~5 s su un portatile aziendale):
l'eseguibile è un file unico che si scompatta a ogni avvio, e l'antivirus lo
ispeziona. È il prezzo dell'avere un solo file da copiare. Non influisce sulla
ricerca, che una volta aperta la finestra è immediata.

**…convivono la vecchia sincronizzazione PowerShell e questa?**
Sì, e nella fase di passaggio conviene tenerle entrambe. Le due attività
pianificate (`NginxLogSync` e `qtRequestory Sync`) saltano entrambe i file già
presenti in locale con la stessa dimensione e scaricano entrambe su file
`.part` rinominati solo a download finito, quindi non si rovinano il lavoro a
vicenda nemmeno puntando alla stessa cartella. La vecchia si toglie quando la
nuova ha dimostrato di funzionare per qualche giorno, con
`.\install-task.ps1 -Uninstall` nella vecchia cartella.

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
```

Build dell'eseguibile (esegue i test, impacchetta, prova l'exe prodotto):

```powershell
.\scripts\build.ps1
```

Vedi `docs/DESIGN-core.md` (compreso §Packaging) e `docs/DESIGN-ui.md`.
`environments.json` non si committa mai: è in `.gitignore`.
