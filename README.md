# Countdown WoW Forever — Orda Florentiae

GIF animata con il conto alla rovescia al lancio di WoW Forever (mezzanotte 4→5 novembre 2026), aggiornata ogni ora in un messaggio Discord tramite webhook.

- `countdown.py render out.gif [--at 2026-11-05T00:00:00Z]`: genera la GIF in locale.
- `countdown.py update`: genera la GIF e aggiorna il messaggio (serve `WEBHOOK_URL`). Lo stato (ID del messaggio, lancio avvenuto) è in `state.json`.
- Al lancio la GIF diventa "Il portale è aperto". Se esiste `annuncio-lancio.txt`, il suo testo viene pubblicato con @everyone. Poi il workflow si disattiva da solo.

Il portale è la schermata di login del 2004. L'energia verde è ricostruita dal modello di gioco `hellfire_darkportal_fx.m2`: mesh, texture, fusione additiva e velocità di scorrimento sono quelle originali, scaricate da wago.tools. Font: Morpheus (Kiwi Media).
