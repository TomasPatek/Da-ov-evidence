# Aplikace v mobilu

## K čemu slouží

Aplikaci můžete mít na ploše iPhonu jako ikonu a fotit účtenky přímo do fronty *Ke kontrole*.

## Co je potřeba předem

- iPhone ve stejné Wi-Fi jako server (aplikace je dostupná jen v lokální síti).
- Adresa aplikace, např. `http://192.168.1.52:8000`.

## Postup

1. V Safari otevřete adresu aplikace a přihlaste se.
2. Klepněte na *Sdílet* (čtvereček se šipkou) → *Přidat na plochu* → *Přidat*.
3. Aplikace se od teď otevírá z ikony *Evidence* přes celou obrazovku.
4. Účtenku vyfotíte na *Přehledu* nebo v *Dokladech* tlačítkem *Vyfotit účtenku*. Po vyfocení
   se sama nahraje, přečte (QR kód, u fotky bez QR rozpoznání textu) a otevře se ke kontrole.

Aplikace běží přes `http` jen v lokální síti, proto nemá offline režim: bez spojení se
serverem se neotevře. Data jsou vždy jen na vašem serveru.

## Jak ověřit, že to funguje

Po vyfocení účtenky se otevře formulář s náhledem fotky a předvyplněnými údaji; zvýrazněná
pole zkontrolujte.

## Časté problémy

- **Ikona otevírá prázdnou stránku:** telefon není v domácí Wi-Fi.
- **Z fotky se nic nepřečetlo:** foťte zblízka, rovně a na tmavém podkladu; údaje případně
  doplňte ručně.
