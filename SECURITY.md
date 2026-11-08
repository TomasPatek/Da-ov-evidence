# Bezpečnost

## Jak nahlásit zranitelnost

Zranitelnosti hlaste **soukromě** přes GitHub
[Private vulnerability reporting](https://github.com/TomasPatek/Danova-evidence/security/advisories/new)
(záložka *Security* → *Report a vulnerability*). **Nezakládejte veřejné issue.**

Uveďte:

- které verze se chyba týká,
- jak ji vyvolat,
- jaký může mít dopad.

Nepřikládejte skutečné doklady ani osobní údaje. Odpověď můžete čekat do 7 dnů.

## Podporované verze

Opravy vycházejí pro poslední vydanou verzi.

## Bezpečnostní model

Aplikace je určená jen pro lokální síť, ale chová se, jako by v síti mohl být kdokoli:
přihlášení na všech stránkách, ochrana CSRF, omezení pokusů o přihlášení, kontrola nahrávaných
souborů a kontejner bez oprávnění roota se zapisovatelnými jen složkami `/data` a `/config`.
