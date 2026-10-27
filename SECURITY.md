# Sicurezza e dati personali

Non aprire issue contenenti password, cookie, file HAR, URL firmati delle foto o sessioni.
Le sessioni Vinted permettono di agire sul tuo account: trattale come password.
Revoca la sessione da Vinted se viene esposta; cambia anche il segreto del server MCP.

Il codice è pubblicabile; ogni utente deve eseguire una propria istanza con i propri dati.
Non è un servizio multiutente. Tutti i client OAuth autorizzati operano sullo stesso account.
Il proprietario autorizza un client tramite segreto locale; i token durano 24 ore,
non hanno refresh e sono revocati tutti al riavvio. I codici OAuth sono monouso e durano 60 secondi.
L'SDK MCP verifica PKCE S256, client, redirect e risorsa. I grant sono in memoria: usare un solo worker.

Il pulsante è il confine di conferma offerto dall'host MCP Apps. Il tool di pubblicazione
è visibile solo all'app negli host che rispettano i metadati di visibilità. Non è una prova
crittografica che una persona abbia cliccato: un client MCP autorizzato e modificato può
invocare direttamente i tool. Collega solo client fidati. Per una garanzia indipendente
dall'host occorre un secondo fattore o una pagina di approvazione separata.

Di default i dati sono in LocalAppData (Windows) o XDG data home (Linux), fuori dal repo.
Non sono cifrati dall'app: proteggi il profilo utente, usa cifratura disco e permessi privati.
Non collocarli in OneDrive, Dropbox o backup cloud se non vuoi sincronizzarli.
`.gitignore` impedisce inclusioni accidentali, ma non può impedire commit forzati o sincronizzazione cloud.
Il server non invia sessioni a OpenAI. Foto, testo dell'annuncio e riepilogo passano da ChatGPT;
le foto approvate e l'annuncio sono inviati a Vinted. I download non ricevono i cookie Vinted.

Download allegati: solo HTTPS, host esatti configurati, DNS pubblico, nessun redirect o proxy ambiente,
massimo 10 MB e 24 megapixel; JPEG/PNG/WebP ricodificati senza EXIF/GPS. Non aggiungere host controllati
da terzi: il controllo DNS prima della connessione non elimina da solo il rischio di DNS rebinding.
In produzione limita anche l'egress di rete alle destinazioni necessarie.

Gli invii sono prenotati atomicamente in SQLite prima della rete. Timeout, crash o errori
non vengono riprovati automaticamente. Verifica bozze e annunci su Vinted prima di creare
un nuovo tentativo. Questo riduce i duplicati ma non garantisce exactly-once fra sistemi diversi.
Un blocco persistente ferma gli invii live su errori; lo sblocco è solo locale, non esposto come tool.

Disabilita i log di query/header nel reverse proxy e nel tunnel: OAuth usa codici nei redirect.
Non esporre i file di dati con un web server. Non usare `--reload` o più worker per il servizio remoto.
Il segreto del proprietario va digitato solo nella pagina del tuo dominio, mai nella chat.

Per vulnerabilità usa un canale privato concordato col manutentore, fornendo una riproduzione
con dati sintetici. In assenza di un canale privato, apri solo una richiesta di contatto senza dettagli sensibili.
