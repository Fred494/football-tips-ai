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

Training uses only results preceding each matchday. Both club and national models use only matches in the last two calendar years. Both models use up to ten previous matches per team, pre-match opponent Elo to weight the points earned, unbeaten rate, rest and home/away performance. Clubs also use current-season goal difference and reconstructed league position.

Logistic regression, histogram gradient boosting, Elo + Poisson and Elo + Dixon–Coles share date-based training, calibration and holdout partitions. The candidate set also includes an equal-weight blend of logistic regression and Elo + Poisson. An earlier portion of the validation period fits temperature scaling, pooled outcome offsets and regularized competition offsets. The later validation portion selects the model and calibration by log loss before the final test. The selected calibration is refitted on the full validation period. Competition offsets require at least 60 calibration matches. All versions preserve a coherent 1X2 distribution. Model Performance reports holdout Brier, log loss and calibration by competition and 1X/X2 market, alongside the existing rolling club competition hit rates. Club feature comparisons hold the date splits fixed. The national-team qualification experiment compares 0%, 5% and 10% relative win reductions on held-out fixtures with one qualified selection and a rival still in contention. The live rule uses 5% for verified qualified sides, with an equal split between draw and opponent win if one side has qualified, or transfers both adjustments to the draw if both have.

A club forecast requires ten prior league results and three current-season matches per team. The model uses verified snapshots when recent fixture and score availability passes the data checks. The archive keeps the original probability for each published fixture and market, recovers from the latest public archive if the Actions cache is unavailable, and reconciles final scores on each refresh. The Histórico page shows archived Top Picks after kickoff when their original probability was at least 87.5%. A listed pick is shown as pending until a final score is available. Earlier deployments could archive fixtures further than four days ahead. Those records are carried forward.

### Player input

The current free feeds lack verified player-level data. The optional `data/player_snapshots.json` input expects a verified pre-match archive keyed by the exact fixture ID, then team name. Each team entry contains `source`, timezone-aware ISO `observedAt`, and a `players` list with player `name`, recent `rating` from 0 to 10, `minutesShare` from 0 to 1, and `status` of `available`, `injured`, `suspended`, `doubtful`, or `unknown`. Use confirmed competition suspensions, including those from red cards. The pipeline accepts data from the 48 hours before the prediction cutoff. It displays available reports, and applies player effects only with verified coverage for both sides and enough chronological training, calibration and test samples. It selects the player model only if it improves validation log loss against the team-only model on the same covered validation fixtures. A provider and historical archive still need to be connected.

## Scheduled hosting

The bundled GitHub Actions workflow is configured for refresh every 30 minutes at minutes 17 and 47 in Europe/Lisbon. To activate on a GitHub repository, copy the project into the default branch, enable Actions, set Settings → Pages → Source to GitHub Actions, and manually run **Daily football forecasts** once. Confirm the deployed Pages URL and review the next scheduled run in Actions. The workflow uses standard hosted runners and preserves SQLite history through Actions cache and the deployed archive. The Sites deployment is an initial snapshot. This workflow refreshes the GitHub Pages deployment after setup.

## Scope of this version

The free model inputs do not include point-in-time xG or historical squad availability data. Elo goal rates predict scores from historical results and should not be described as shot-based xG. Verified player reports can be supplied using the input above.

## Dashboard

The four dates from today through three days ahead can be toggled individually. Standard picks require at least 87.5%, sorted by calibrated probability. A top-five home club facing a bottom-five visitor is always marked ARRISCADO and included using its calibrated 1X probability. At least ten ranked teams are required so the groups do not overlap. Published current-season tables are preferred when available. Other fixtures and standalone result lists are omitted from the homepage. Club crests use ESPN team lists, UEFA rankings and the existing Football Team Logos archive.

## International competitions

The 2026–27 Nations League group fixtures and scores come from [UEFA's public match schedule](https://www.uefa.com/uefanationsleague/news/02a2-1fea18abbcbc-456e846509e7-1000--2026-27-uefa-nations-league-all-the-league-phase-fixtures-a/). The national-team model is trained separately on the most recent two years of international friendlies and Nations League group scores from the [open international results dataset](https://github.com/martj42/international_results) and UEFA. Historical knockout scores are excluded from training because regulation-time results are not consistently available. Euro, World Cup, qualifiers and the other displayed international competitions have historical coverage only until a verified fixture feed is connected. The editorial source is specific to this Nations League edition.

## Standings and coverage

League cards show a compact standings preview, then expand to all available teams, goals, points and last-five form. Tables are calculated from published scores and labeled by season. Official tie-breaks, deductions, split tables and qualification places can differ. Player ratings are omitted where unavailable.

Football-Data.co.uk's additional score files cover Denmark, Poland, Sweden, Switzerland and MLS. OpenFootball text archives provide historical results for Liga Portugal 2, Hungary and the league phases of the UEFA Champions League, Europa League and Conference League. These supplementary sources are scores-only in the app. The three UEFA cups use verified official schedules with an ESPN verification fallback.

Each match's expanded analysis shows its league's held-out sample size and selected hit rate. Rates below 70% carry a red warning. The hit rate measures historical accuracy across evaluated picks and is separate from a match's forecast probability.

The open dashboard checks for new published forecasts and history every five minutes and when returning to the tab. Provider results become visible after the next successful build. GitHub scheduled runs may start late. Failed browser refreshes retain the last successful data.

## European club forecasts

The build refreshes the Champions League, Europa League and Conference League league-phase fixtures and regulation-time scores from UEFA's official season publications through `european_data.py`. Successful snapshots are committed as recovery copies. When UEFA blocks access, the adapter verifies the completed and next-seven-day schedule against ESPN scoreboards, requiring exact home/away identity matches for every scheduled game on each checked date. It updates regulation-time final scores and kickoff times after matching. Failed verification retains the previous snapshot and its original verification time.

European forecasts combine up to ten preceding domestic and European matches for recent form, opponent strength, Elo and home/away performance. Season points and position refer to the European competition being predicted. Domestic forecasts retain their own league context. Provider names are aligned using explicit aliases and normalized club names. Training features are computed before each matchday, and same-day results are excluded. A European forecast requires ten prior covered matches for each club and three current-season European matches. When verified rankings and the tested coefficient model support a forecast, missing full-team history can use that fallback. Only qualifying and ARRISCADO picks are displayed.

Fixture refresh timestamps, score availability and evaluation sample sizes are displayed in the dashboard. The historical evaluation still pools club models and includes European observations when sufficiently covered. Teams outside the available domestic leagues can have smaller usable samples.

## Frequent calendar and result refresh

The workflow runs at minutes 17 and 47 each hour. Each run refreshes calendars, recent final scores, training and forecasts, the original published pick archive, and standings, then publishes all dashboard files together. GitHub's scheduler may delay a run. The open dashboard checks for publication changes every five minutes and when returning to the tab.

`scoreboard_data.py` supplements domestic sources with ESPN near-term scoreboards. It matches provider identities to existing fixtures before settlement, accepts final scores only when the provider reports a completed match, and retains previously valid scores after partial failures. It also reconciles the verified Nations League and AFCON qualifier calendars with their scoreboards. Confirmed same-day results can settle Histórico immediately while training continues to use results from previous matchdays. Calendar check times and last verified result dates remain distinct.

When a provisional fixture date changes by up to seven days, a unique same-competition, same-season home/away pairing updates its archive settlement reference and actual match date. The original publication time and probability stay attached to the archived pick.

## Current selection and two-year analysis

All match-based model inputs, Elo initialization, feature construction, training, calibration and evaluation are restricted to the exact rolling two-calendar-year window before the build date. Club and national models retain a ten-match form window inside that period.

Standard Top Picks require at least 87.5%. Every predicted club fixture with a top-five host and bottom-five visitor is also included as ARRISCADO, using its 1X probability. These yellow picks can be below the normal threshold and are evaluated separately. The Histórico view only displays original published probabilities of 87.5% or higher, including qualifying yellow picks. Other games and the standalone AFCON results table are removed from the homepage.

A separate experimental logistic model uses official UEFA club coefficients and ranking positions to cover European fixtures lacking full team features. Season-end ranking archives include their source availability dates and are never applied to earlier matches. UEFA's coefficient is an external five-season ranking, while match inputs retain the two-year limit. The fallback must improve validation log loss over a class-frequency baseline and have at least 40 later test matches. Model Performance reports the independent test. No fixed percentage is assigned directly from a rank gap.

Team logos are reconciled by provider aliases using ESPN team lists, published tables and official UEFA ranking badges.

Supplementary badge sources for archived clubs include the official Liga Portugal asset catalogue, MLSZ club emblems and Zerozero. Existing team-name aliases keep their identities when applying a badge.
