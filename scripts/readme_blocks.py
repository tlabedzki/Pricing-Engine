"""
README numbers: the text between `<!-- generated:<name> -->` markers, in Polish or English. Called by make_charts.py,
which computes the results once for the charts and the text, so the numbers in both always match.
"""
from __future__ import annotations

import pandas as pd

PL_CATEGORY = {
    "Automotive": "Motoryzacja", "Baby & Kids": "Dziecko", "Beauty": "Uroda", "Books & Media": "Książki i media",
    "Clothing": "Odzież", "DIY Tools": "Narzędzia", "Electronics": "Elektronika", "Furniture": "Meble",
    "Health": "Zdrowie", "Home & Garden": "Dom i ogród", "Jewelry & Accessories": "Biżuteria", "Office": "Biuro",
    "Pet Supplies": "Zwierzęta", "Sports": "Sport", "Toys": "Zabawki",
}


def _pl_losers(names: list[str]) -> str:
    if not names:
        return "żadna kategoria nie traci"
    if len(names) == 1:
        return f"traci {names[0]}"
    return f"tracą {', '.join(names[:-1])} oraz {names[-1]}"


def _mae(table: pd.DataFrame, column: str) -> float:
    rows = table[column].notna()
    return float((table.loc[rows, column] - table.loc[rows, "true_elasticity"]).abs().mean())


def blocks(lang, fmt, shop, table, snap, proposals, frame, truth, spread, by_category, facts) -> dict[str, str]:
    pl = lang == "pl"
    cat = (lambda c: PL_CATEGORY.get(c, c)) if pl else (lambda c: c)
    n = fmt.number
    pct = fmt.pct
    scen = frame.set_index("scenario")
    base, cautious, bold = scen.loc["base"], scen.loc["cautious"], scen.loc["bold"]
    e = facts["elasticity"]
    low, high = spread["profit_change"].quantile([0.05, 0.95])
    mae = {k: _mae(table, k) for k in ("list_price", "discount", "elasticity")}
    within_before, within_after = facts["index"]["within_before"], facts["index"]["within_after"]
    counts = facts["rules"]["rule_counts"]
    guard = counts.get("market_cap", 0) + counts.get("step_up", 0) + counts.get("step_down", 0)
    optimum = counts.get("profit_optimum", 0)
    conflict = counts.get("market_conflict", 0) + counts.get("margin_conflict", 0)
    total = len(proposals)
    negative = [cat(c) for c in facts["categories"]["negative"]]
    t = table.set_index("category")
    misses = e["misses"]
    changed = int(base["raise"] + base["lower"])
    gap = abs(base["profit_change"] - truth["profit_change"])
    shown = misses + [c for c in ("Clothing", "Beauty") if c not in misses]
    others = e["n"] - len(shown)

    def miss_list() -> str:
        return ", ".join(f"{cat(c)} ({n(t.loc[c, 'elasticity'], 2)} {'zamiast' if pl else 'vs'} "
                         f"{n(t.loc[c, 'true_elasticity'], 2)})" for c in misses)

    out: dict[str, str] = {}
    if "demo" in facts:
        first, last = facts["demo"]["base"], facts["demo"]["bold"]

        def money(text: str) -> str:
            return f"{n(float(text[:-1]), 2)} mln zł" if pl else f"PLN {text}"

        if pl:
            alt = (f"Animacja aplikacji: kursor przesuwa próg nad medianą konkurencji z +5% na +10% i maksymalny krok "
                   f"z 10% na 15%; roczny zysk brutto rośnie z {money(first['profit'])} "
                   f"({pct(first['profit_change'])}) do {money(last['profit'])} ({pct(last['profit_change'])}), "
                   f"a tabela propozycji się odświeża")
        else:
            alt = (f"The app, animated: the cursor drags the limit over the competitor median from +5% to +10% and the "
                   f"largest step from 10% to 15%; yearly gross profit moves from {money(first['profit'])} "
                   f"({pct(first['profit_change'])}) to {money(last['profit'])} ({pct(last['profit_change'])}) and "
                   f"the proposals table updates")
        out["hero"] = ('<picture>\n'
                       '  <source media="(prefers-color-scheme: dark)" srcset="docs/img/app-demo-dark.svg">\n'
                       f'  <img alt="{alt}" src="docs/img/app-demo.svg">\n'
                       '</picture>')
    if pl:
        out["result"] = (
            f"**Wynik.** Silnik sprawdza ceny {n(total)} produktów i zmienia {n(changed)} z nich; w scenariuszu "
            f"bazowym roczny zysk brutto rośnie o {pct(base['profit_change'])} przy {pct(base['revenue_change'])} "
            f"obrotu. "
            f"Przeliczenie tych samych cen z prawdziwą elastycznością daje {pct(truth['profit_change'])}, "
            f"a szacunek elastyczności trafia w prawdę w {e['hits']} z {e['n']} kategorii.")
        out["summary"] = (
            f"- **Trafione:** zysk przewidziany z danych ({pct(base['profit_change'])}) różni się od zysku przy "
            f"prawdziwej elastyczności ({pct(truth['profit_change'])}) o "
            f"{n(abs(base['profit_change'] - truth['profit_change']) * 100, 1)} pkt proc.; rabaty i zmiany cen razem "
            f"dają średni błąd elastyczności {n(mae['elasticity'], 2)}.\n"
            f"- **Chybione:** w {len(misses)} kategoriach prawda leży poza przedziałem szacunku: {miss_list()}; "
            f"{pct(1 - within_after, 0, sign=False)} produktów zostaje ponad "
            f"progiem konkurencji, bo jeden krok to za mało albo nie pozwala na to minimalna marża.")
        out["elasticity"] = (
            f"Sam sygnał ze zmian cen katalogowych myli się średnio o {n(mae['list_price'], 2)}, sam sygnał z rabatów "
            f"o {n(mae['discount'], 2)}, a połączenie z przyciąganiem do średniej o {n(mae['elasticity'], 2)}. "
            f"Prawdziwa wartość leży w 90% przedziale w {e['hits']} z {e['n']} kategorii.\n\n"
            f"![Szacunek elastyczności trafia w prawdę w {e['hits']} z {e['n']} kategorii]"
            f"(docs/img/elasticity-vs-truth.png)\n\n"
            f"Na czerwono kategorie, w których prawda wypada poza przedziałem: {miss_list()}.")
        out["proposals"] = (
            f"Na {n(total)} produktów w sprzedaży silnik podnosi {n(base['raise'])} cen, obniża {n(base['lower'])} "
            f"i zostawia {n(base['keep'])}. W progu +5% nad medianą konkurencji mieści się dziś "
            f"{pct(within_before, 0, sign=False)} produktów z ofertą konkurencji, po zmianach "
            f"{pct(within_after, 0, sign=False)}.\n\n"
            f"![Po zmianach {pct(within_after, 0, sign=False)} produktów mieści się w progu +5% nad konkurencją]"
            f"(docs/img/price-index.png)\n\n"
            f"O {n(guard)} propozycjach ({pct(guard / total, 0, sign=False)}) decyduje próg konkurencji albo "
            f"maksymalny krok, o {n(conflict)} konflikt marży z rynkiem, a tylko o {n(optimum)} sam rachunek zysku.\n\n"
            f"![Cenę najczęściej zatrzymuje próg konkurencji albo maksymalny krok](docs/img/decision-rules.png)")
        out["scenarios"] = (
            f"| Scenariusz | Reguły | Zysk brutto | Obrót netto | Sztuki | Podwyżki / obniżki |\n"
            f"|---|---|---|---|---|---|\n"
            f"| ostrożny | do mediany konkurencji, krok 5%, popyt czulszy o 1,64 błędu | "
            f"{pct(cautious['profit_change'])} | {pct(cautious['revenue_change'])} | "
            f"{pct(cautious['units_change'])} | {n(cautious['raise'])} / {n(cautious['lower'])} |\n"
            f"| bazowy | +5% nad medianą, krok 10% | {pct(base['profit_change'])} | {pct(base['revenue_change'])} | "
            f"{pct(base['units_change'])} | {n(base['raise'])} / {n(base['lower'])} |\n"
            f"| odważny | +10% nad medianą, krok 15% | {pct(bold['profit_change'])} | {pct(bold['revenue_change'])} | "
            f"{pct(bold['units_change'])} | {n(bold['raise'])} / {n(bold['lower'])} |\n\n"
            f"![Scenariusz bazowy: {pct(base['profit_change'])} zysku brutto przy {pct(base['revenue_change'])} "
            f"obrotu](docs/img/scenarios.png)\n\n"
            f"Przy losowaniu elastyczności z jej przedziałów zmiana zysku w scenariuszu bazowym mieści się w 90% "
            f"przypadków między {pct(low)} a {pct(high)}. Najwięcej zyskuje {cat(facts['categories']['top'])}, "
            f"{_pl_losers(negative)}.\n\n"
            f"![Najwięcej zyskuje {cat(facts['categories']['top'])}](docs/img/categories.png)")
        out["verdicts"] = (
            f"Elastyczność trafia w prawdę w {e['hits']} z {e['n']} kategorii, a zysk scenariusza bazowego "
            f"przewidziany z danych ({pct(base['profit_change'])}) "
            f"{'zgadza się z zyskiem' if gap <= 0.005 else 'różni się od zysku'} przy prawdziwej elastyczności "
            f"({pct(truth['profit_change'])}).\n\n"
            f"| Pytanie | Odpowiedź z danych | Prawda | Ocena |\n|---|---|---|---|\n"
            + "".join(
                f"| Elastyczność: {cat(c)} | {n(r.elasticity, 2)} "
                f"[{n(r.elasticity - 1.645 * r.elasticity_se, 2)}; {n(r.elasticity + 1.645 * r.elasticity_se, 2)}] | "
                f"{n(r.true_elasticity, 2)} | {'chybione' if c in misses else 'trafione'} |\n"
                for c, r in t.loc[shown].iterrows())
            + f"| Pozostałe {others} kategorii | w przedziale | – | trafione |\n"
            f"| Zmiana zysku, scenariusz bazowy | {pct(base['profit_change'])} [{pct(low)}; {pct(high)}] | "
            f"{pct(truth['profit_change'])} | "
            f"{'trafione' if low <= truth['profit_change'] <= high else 'chybione, poza przedziałem'} |\n"
            f"| Zmiana obrotu, scenariusz bazowy | {pct(base['revenue_change'])} | "
            f"{pct(truth['revenue_change'])} | różnica "
            f"{n(abs(base['revenue_change'] - truth['revenue_change']) * 100, 1)} pkt proc. |")
    else:
        out["result"] = (
            f"**Result.** The engine checks the prices of {n(total)} products and changes {n(changed)}; in the base "
            f"scenario yearly gross profit grows by {pct(base['profit_change'])} at {pct(base['revenue_change'])} "
            f"revenue. The same prices judged with the true elasticity give {pct(truth['profit_change'])}, "
            f"and the elasticity estimate hits the "
            f"truth in {e['hits']} of {e['n']} categories.")
        out["summary"] = (
            f"- **What worked:** the profit predicted from the data ({pct(base['profit_change'])}) is "
            f"{n(abs(base['profit_change'] - truth['profit_change']) * 100, 1)} points from the profit with the true "
            f"elasticity ({pct(truth['profit_change'])}); discounts and list-price changes together give a mean "
            f"elasticity error of {n(mae['elasticity'], 2)}.\n"
            f"- **What missed:** in {len(misses)} categories the truth lies outside the estimate's interval: "
            f"{miss_list()}; "
            f"{pct(1 - within_after, 0, sign=False)} of products stay above the competitor limit, because one step "
            f"is not enough or the minimum margin does not allow it.")
        out["elasticity"] = (
            f"List-price changes alone miss by {n(mae['list_price'], 2)} on average, discounts alone by "
            f"{n(mae['discount'], 2)}, and both combined and pulled towards the average by {n(mae['elasticity'], 2)}. "
            f"The true value lies in the 90% interval in {e['hits']} of {e['n']} categories.\n\n"
            f"![The elasticity estimate hits the truth in {e['hits']} of {e['n']} categories]"
            f"(docs/img/elasticity-vs-truth.png)\n\n"
            f"In red, the categories whose truth falls outside the interval: {miss_list()}.")
        out["proposals"] = (
            f"Of {n(total)} products on sale the engine raises {n(base['raise'])} prices, lowers {n(base['lower'])} "
            f"and keeps {n(base['keep'])}. Within +5% of the competitor median today: "
            f"{pct(within_before, 0, sign=False)} of products with a competitor offer, after the changes "
            f"{pct(within_after, 0, sign=False)}.\n\n"
            f"![After the changes {pct(within_after, 0, sign=False)} of products sit within +5% of the competitors]"
            f"(docs/img/price-index.png)\n\n"
            f"The competitor limit or the largest step decides {n(guard)} proposals "
            f"({pct(guard / total, 0, sign=False)}), a margin-versus-market conflict {n(conflict)}, and the profit "
            f"calculation alone only {n(optimum)}.\n\n"
            f"![The competitor limit or the largest step stops most prices](docs/img/decision-rules.png)")
        out["scenarios"] = (
            f"| Scenario | Rules | Gross profit | Net revenue | Units | Raised / lowered |\n"
            f"|---|---|---|---|---|---|\n"
            f"| cautious | up to the competitor median, 5% steps, demand 1.64 SE more sensitive | "
            f"{pct(cautious['profit_change'])} | {pct(cautious['revenue_change'])} | "
            f"{pct(cautious['units_change'])} | {n(cautious['raise'])} / {n(cautious['lower'])} |\n"
            f"| base | +5% over the median, 10% steps | {pct(base['profit_change'])} | {pct(base['revenue_change'])} | "
            f"{pct(base['units_change'])} | {n(base['raise'])} / {n(base['lower'])} |\n"
            f"| bold | +10% over the median, 15% steps | {pct(bold['profit_change'])} | "
            f"{pct(bold['revenue_change'])} | "
            f"{pct(bold['units_change'])} | {n(bold['raise'])} / {n(bold['lower'])} |\n\n"
            f"![Base scenario: {pct(base['profit_change'])} gross profit at {pct(base['revenue_change'])} revenue]"
            f"(docs/img/scenarios.png)\n\n"
            f"Drawing the elasticity from its intervals, the base profit change stays between {pct(low)} and "
            f"{pct(high)} in 90% of draws. {cat(facts['categories']['top'])} gains the most; "
            f"{', '.join(negative) if negative else 'no category'} lose{'s' if len(negative) == 1 else ''}.\n\n"
            f"![{cat(facts['categories']['top'])} gains the most](docs/img/categories.png)")
        out["verdicts"] = (
            f"The elasticity hits the truth in {e['hits']} of {e['n']} categories, and the base profit predicted from "
            f"the data ({pct(base['profit_change'])}) {'matches' if gap <= 0.005 else 'differs from'} the profit with "
            f"the true elasticity "
            f"({pct(truth['profit_change'])}).\n\n"
            f"| Question | Answer from the data | Truth | Verdict |\n|---|---|---|---|\n"
            + "".join(
                f"| Elasticity: {c} | {n(r.elasticity, 2)} "
                f"[{n(r.elasticity - 1.645 * r.elasticity_se, 2)}, {n(r.elasticity + 1.645 * r.elasticity_se, 2)}] | "
                f"{n(r.true_elasticity, 2)} | {'miss' if c in misses else 'hit'} |\n"
                for c, r in t.loc[shown].iterrows())
            + f"| Other {others} categories | inside the interval | – | hit |\n"
            f"| Profit change, base scenario | {pct(base['profit_change'])} [{pct(low)}, {pct(high)}] | "
            f"{pct(truth['profit_change'])} | "
            f"{'hit' if low <= truth['profit_change'] <= high else 'miss, outside the interval'} |\n"
            f"| Revenue change, base scenario | {pct(base['revenue_change'])} | {pct(truth['revenue_change'])} | "
            f"{n(abs(base['revenue_change'] - truth['revenue_change']) * 100, 1)} points apart |")
    return out
