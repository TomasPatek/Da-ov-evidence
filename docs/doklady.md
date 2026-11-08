# Přijaté doklady

## K čemu slouží

Návod popisuje evidenci nákupů: nahrání faktury nebo účtenky od dodavatele, kontrolu
přečtených údajů ve frontě *Ke kontrole*, přiřazení k zakázce a zápis úhrady do peněžního
deníku.

## Co je potřeba předem

- Nastavený začátek evidence a počáteční stavy (*Nastavení → Peněžní deník*). Bez nich se
  úhrady do deníku nezapisují.
- Doklad jako PDF, fotka (JPEG, PNG) nebo ISDOC. Doklad v cizí měně zatím přepočtěte na Kč.

## Postup

1. Otevřete *Doklady* a v části *Nahrát doklady* vyberte jeden nebo více souborů.
   Klikněte na *Nahrát a přečíst*.
2. Aplikace doklad přečte, a to v tomto pořadí:
   1. ISDOC (samostatný soubor nebo příloha uvnitř PDF): údaje se převezmou přesně.
   2. QR platba: účet, částka, variabilní symbol, splatnost.
   3. Text v PDF: IČO, DIČ, číslo dokladu, data, částka, účet, platba kartou.
   4. Šablona dodavatele: kategorie, popis a způsob úhrady z minule potvrzeného dokladu
      téhož dodavatele.

   Vše probíhá jen na vašem serveru, doklad se nikam neposílá.
3. Otevře se formulář: vlevo náhled dokladu, vpravo přečtené údaje. Pole, která aplikace
   přečetla nejistě nebo nenašla, jsou zvýrazněná a označená *zkontrolujte*.
4. Zkontrolujte dodavatele. Tlačítkem *Ověřit v ARES* doplníte název podle IČO.
5. Vyberte kategorii (sloupec ET 328, náhradní díly patří do *15 – materiál*) a zakázku.
   Aplikace zakázku navrhne podle adresy v dokladu, nebo nabídne jedinou rozpracovanou.
   Nákup bez zakázky je režie.
6. Pokud je doklad zaplacený (kartou, online, hotově), nechte zaškrtnuté *Už je zaplaceno*
   a zkontrolujte datum úhrady. U platby z účtu doplňte *Kód transakce* z notifikace banky,
   stane se číslem dokladu v deníku. Klikněte na *Potvrdit*. Otevře se další doklad ve frontě.
7. Nezaplacený doklad zaplaťte později: v detailu dokladu zadejte datum a způsob úhrady
   a klikněte na *Označit jako zaplacený*.

Doklad bez souboru (třeba papírovou účtenku) zadáte tlačítkem *Zadat ručně*.

Po potvrzení si aplikace zapamatuje pro dodavatele kategorii, popis a způsob úhrady
(soubor `sablony-dodavatelu.json`). Další doklad od něj už bude předvyplněný.

## Jak ověřit, že to funguje

- Potvrzený doklad má stav *potvrzen* nebo *uhrazen* a v *Peněžním deníku* je u uhrazeného
  výdaj s kódem transakce (bez něj s číslem `PD2027-001`), u hotovosti s číslem `VPD1/27`…
- V detailu zakázky je doklad v části *Náklady* a promítne se do *Rozdílu*.
- Soubor dokladu leží v `data/RRRR/doklady/` a jmenuje se podle čísla dokladu.

## Časté problémy

- **„Nepodporovaný typ souboru“:** nahrávat lze jen PDF, JPEG, PNG a ISDOC. Typ se pozná
  podle obsahu, ne podle přípony. Fotku z iPhonu ve formátu HEIC uložte jako JPEG.
- **Ze skenu se nic nepřečetlo:** sken nebo fotka bez QR kódu nemá text. Údaje vyplňte ručně;
  čtení textu z obrázku (OCR) přibude později.
- **Přečtená částka je bez DPH:** jako neplátce DPH zadávejte vždy částku včetně DPH.
- **Upozornění na částku nad 80 000 Kč:** hmotný majetek nad 80 000 Kč se neuplatní najednou,
  ale odpisy (sloupec 20 a později evidence majetku).
- **Chybně nahraný doklad:** dokud čeká na kontrolu, smažete ho tlačítkem *Smazat*.
  Potvrzený doklad už smazat nejde, jen opravit.
