# Football Edge AI

An explainable 1X/X2 dashboard built from real fixture and score feeds. The dashboard is a static rendering of a data and model snapshot. Python performs ingestion, training, calibration, evaluation and forecast generation before publication.

## Run locally

1. Install Python 3.12 and run `pip install -r requirements.txt`.
2. Run `python fetch_data.py` and `python results_feed.py` to refresh the sources. An existing successful local file is retained on request failure.
3. Run `python build.py`.
4. Run `python -m http.server 8000 --directory dist` and open http://localhost:8000.

The [competition coverage matrix](COVERAGE.md) records the initial feed checks. The application has live coverage indicators for its loaded snapshot.

## Sources and interpretation

[OpenFootball](https://github.com/openfootball/football.json) provides public-domain fixtures and historical scores. [Football-Data.co.uk](https://www.football-data.co.uk/data.php) provides additional free results. Only dates, teams and final scores are extracted from those CSV files. Scores are combined with fixtures only when a one-to-one alias mapping is supported by overlapping results. Competition/team identity across seasons depends on stable source names. The feed can contain provisional times or rescheduled matches. Lisbon kickoff conversion assumes the published time is local to the league's principal timezone.

[Football-data.org](https://www.football-data.org/coverage) lists eight requested competitions on its free plan and requires a token for match and table access. This build uses token-free feeds. API-Football integration and account-level coverage were not verified. Standings are calculated from results, with points, goal difference and goals scored as sort keys. Deductions and special phase rules are outside this version. Only covered league matches enter team form.

## Model

Daily cutoff is midnight Lisbon, conservatively excluding same-day results. The build uses the current season and two preceding seasons per league. Models use Elo differential, prior opponents' Elo, reconstructed league position, home and away records, and recent form. Logistic regression and histogram gradient boosting compete on a chronological validation split, with a separate later evaluation period. Temperature scaling keeps the three outcome probabilities coherent. The explanation varies one feature at a time relative to its training median.

A forecast needs five prior league results and three current-season matches per team. Rankings require the current fixture file to have been fetched successfully within 48 hours, the league to have a result in the last 21 days, and neither team to have a scheduled match with an unresolved score in the preceding 14 days. Fetch timestamps indicate when the provider was checked, not when the provider last updated its underlying data. Histórico preserves the first qualifying published pick per fixture and shows it after an exact-match final score is available. The daily build keeps the ledger in the existing SQLite cache and exports it to `dist/history.json`.

### Player input

The current free feeds lack verified player-level data. The optional `data/player_snapshots.json` input expects a verified pre-match archive keyed by the exact fixture ID, then team name. Each team entry contains `source`, timezone-aware ISO `observedAt`, and a `players` list with player `name`, recent `rating` from 0 to 10, `minutesShare` from 0 to 1, and `status` of `available`, `injured`, `suspended`, `doubtful`, or `unknown`. Use confirmed competition suspensions, including those from red cards. The pipeline accepts data from the 48 hours before the prediction cutoff. It displays available reports, and applies player effects only with verified coverage for both sides and enough chronological training, calibration and test samples. It selects the player model only if it improves validation log loss against the team-only model on the same covered validation fixtures. A provider and historical archive still need to be connected.

## Scheduled hosting

The bundled GitHub Actions workflow is configured for daily refresh at 06:00 Europe/Lisbon. To activate on a GitHub repository, copy the project into the default branch, enable Actions, set Settings → Pages → Source to GitHub Actions, and manually run **Daily football forecasts** once. Confirm the deployed Pages URL and review the next scheduled run in Actions. The workflow uses standard hosted runners and preserves SQLite history through Actions cache on a best-effort basis. Keep a separate durable copy if long-term retention is required. The Sites deployment is an initial snapshot. This workflow refreshes the GitHub Pages deployment after setup.

## Scope of this version

There is no connected player or xG provider. The team evaluation uses one chronological holdout and two model candidates. Rolling-origin evaluation, Poisson and Dixon–Coles comparisons, and league-specific model selection remain open. Forecast settlement is available in SQLite. The dashboard presents backtest results.

## Dashboard

The front page starts on today, with an optional jump to the next matchday with qualifying picks. The three additional dates can be selected individually. Each day shows all qualifying forecasts with probability above 75%. Major leagues are listed first, then picks are ranked by probability within each group. Club crests are sourced from [Football Team Logos](https://github.com/luukhopman/football-logos) and fall back to initials when unavailable.

## International competitions

The 2026–27 Nations League group fixtures and scores come from [UEFA's public match schedule](https://www.uefa.com/uefanationsleague/news/02a2-1fea18abbcbc-456e846509e7-1000--2026-27-uefa-nations-league-all-the-league-phase-fixtures-a/). The national-team model is trained separately on the most recent three years of international friendlies and Nations League group scores from the [open international results dataset](https://github.com/martj42/international_results) and UEFA. Historical knockout scores are excluded from training because regulation-time results are not consistently available. Euro, World Cup, qualifiers and the other displayed international competitions have historical coverage only until a verified fixture feed is connected. The editorial source is specific to this Nations League edition.

## Standings and coverage

League cards show a compact standings preview, then expand to all available teams, goals, points and last-five form. Tables are calculated from published scores and labeled by season. Official tie-breaks, deductions, split tables and qualification places can differ. Player ratings are omitted where unavailable.

Football-Data.co.uk's additional score files cover Denmark, Poland, Sweden, Switzerland and MLS. OpenFootball text archives provide historical results for Liga Portugal 2, Hungary and the league phases of the UEFA Champions League, Europa League and Conference League. These supplementary sources are scores-only in the app. The three UEFA cups link to their official fixture pages while an upcoming fixture feed is unavailable.

Each match's expanded analysis shows its league's held-out sample size and selected hit rate. Rates below 70% carry a red warning. The hit rate measures historical accuracy across evaluated picks and is separate from a match's forecast probability.
