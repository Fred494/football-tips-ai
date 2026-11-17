# Football Edge AI

An explainable 1X/X2 dashboard built from real fixture and score feeds. The dashboard is a static rendering of a data and model snapshot. Python performs ingestion, training, calibration, evaluation and forecast generation before publication.

## Run locally

1. Install Python 3.12 and run `pip install -r requirements.txt`.
2. Run `python fetch_data.py` then `python results_feed.py` and `python international_data.py` to refresh the sources. An existing successful local file is retained on request failure.
3. Run `python build.py`.
4. Run `python -m http.server 8000 --directory dist` and open http://localhost:8000.

The [competition coverage matrix](COVERAGE.md) records the initial feed checks. The application has live coverage indicators for its loaded snapshot.

## Sources and interpretation

[OpenFootball](https://github.com/openfootball/football.json) provides public-domain fixtures and historical scores. [Football-Data.co.uk](https://www.football-data.co.uk/data.php) provides additional free results. Only dates, teams and final scores are extracted from those CSV files. Scores are combined with fixtures only when a one-to-one alias mapping is supported by overlapping results. Competition/team identity across seasons depends on stable source names. The feed can contain provisional times or rescheduled matches. Lisbon kickoff conversion assumes the published time is local to the league's principal timezone.

[Football-data.org](https://www.football-data.org/coverage) lists eight requested competitions on its free plan and requires a token for match and table access. This build uses token-free feeds. API-Football integration and account-level coverage were not verified. Standings are calculated from results, with points, goal difference and goals scored as sort keys. Deductions and special phase rules are outside this version. Only covered league matches enter team form.

## Model

Training uses only results preceding each matchday. Clubs use the current season and two preceding seasons. Both models use up to ten previous matches per team, pre-match opponent Elo to weight the points earned, unbeaten rate, rest and home/away performance. Clubs also use current-season goal difference and reconstructed league position.

Logistic regression, histogram gradient boosting, Elo + Poisson and Elo + Dixon–Coles share date-based training, calibration and holdout partitions. The candidate set also includes an equal-weight blend of logistic regression and Elo + Poisson. An earlier portion of the validation period fits temperature scaling, pooled outcome offsets and regularized competition offsets. The later validation portion selects the model and calibration by log loss before the final test. The selected calibration is refitted on the full validation period. Competition offsets require at least 60 calibration matches. All versions preserve a coherent 1X2 distribution. Model Performance reports holdout Brier, log loss and calibration by competition and 1X/X2 market, alongside the existing rolling club competition hit rates. Club feature comparisons hold the date splits fixed. The national-team qualification experiment compares 0%, 5% and 10% relative win reductions on held-out fixtures with one qualified selection and a rival still in contention. The live rule uses 5% for verified qualified sides, with an equal split between draw and opponent win if one side has qualified, or transfers both adjustments to the draw if both have.

A club forecast requires ten prior league results and three current-season matches per team. The model uses verified snapshots when recent fixture and score availability passes the data checks. The archive keeps the original probability for each published fixture and market, recovers from the latest public archive if the Actions cache is unavailable, and reconciles final scores on each refresh. The Histórico page shows the archived Top Picks after kickoff, including exceptions and picks published under earlier probability thresholds. A listed pick is shown as pending until a final score is available. Earlier deployments could archive fixtures further than four days ahead. Those records are carried forward.

### Player input

The current free feeds lack verified player-level data. The optional `data/player_snapshots.json` input expects a verified pre-match archive keyed by the exact fixture ID, then team name. Each team entry contains `source`, timezone-aware ISO `observedAt`, and a `players` list with player `name`, recent `rating` from 0 to 10, `minutesShare` from 0 to 1, and `status` of `available`, `injured`, `suspended`, `doubtful`, or `unknown`. Use confirmed competition suspensions, including those from red cards. The pipeline accepts data from the 48 hours before the prediction cutoff. It displays available reports, and applies player effects only with verified coverage for both sides and enough chronological training, calibration and test samples. It selects the player model only if it improves validation log loss against the team-only model on the same covered validation fixtures. A provider and historical archive still need to be connected.

## Scheduled hosting

The bundled GitHub Actions workflow is configured for daily refresh at 00:00 Europe/Lisbon. To activate on a GitHub repository, copy the project into the default branch, enable Actions, set Settings → Pages → Source to GitHub Actions, and manually run **Daily football forecasts** once. Confirm the deployed Pages URL and review the next scheduled run in Actions. The workflow uses standard hosted runners and preserves SQLite history through Actions cache and the deployed archive. The Sites deployment is an initial snapshot. This workflow refreshes the GitHub Pages deployment after setup.

## Scope of this version

The free model inputs do not include point-in-time xG or historical squad availability data. Elo goal rates predict scores from historical results and should not be described as shot-based xG. Verified player reports can be supplied using the input above.

## Dashboard

The four dates from today through three days ahead can be toggled individually. Top Picks are ordered by calibrated probability within each calendar day, including forecasts at or above 85%. At most one 1X below 85% per day can qualify as a yellow exception. It must reach 80%, have a top-quarter host facing a bottom-quarter visitor, and have a host with at least 2.25 home points per game and a visitor with at most 1.00 away point per game, based on at least five games per side at the relevant venue. This exception requires at least eight ranked teams. Club crests are sourced from [Football Team Logos](https://github.com/luukhopman/football-logos) and fall back to initials when unavailable.

## International competitions

The 2026–27 Nations League group fixtures and scores come from [UEFA's public match schedule](https://www.uefa.com/uefanationsleague/news/02a2-1fea18abbcbc-456e846509e7-1000--2026-27-uefa-nations-league-all-the-league-phase-fixtures-a/). The national-team model is trained separately on the most recent three years of international friendlies and Nations League group scores from the [open international results dataset](https://github.com/martj42/international_results) and UEFA. Historical knockout scores are excluded from training because regulation-time results are not consistently available. Euro, World Cup, qualifiers and the other displayed international competitions have historical coverage only until a verified fixture feed is connected. The editorial source is specific to this Nations League edition.

## Standings and coverage

League cards show a compact standings preview, then expand to all available teams, goals, points and last-five form. Tables are calculated from published scores and labeled by season. Official tie-breaks, deductions, split tables and qualification places can differ. Player ratings are omitted where unavailable.

Football-Data.co.uk's additional score files cover Denmark, Poland, Sweden, Switzerland and MLS. OpenFootball text archives provide historical results for Liga Portugal 2, Hungary and the league phases of the UEFA Champions League, Europa League and Conference League. These supplementary sources are scores-only in the app. The three UEFA cups link to their official fixture pages while an upcoming fixture feed is unavailable.

Each match's expanded analysis shows its league's held-out sample size and selected hit rate. Rates below 70% carry a red warning. The hit rate measures historical accuracy across evaluated picks and is separate from a match's forecast probability.
