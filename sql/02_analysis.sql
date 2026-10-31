-- ============================================================================
-- 02_analysis.sql
-- Named queries. run_analysis.py runs each block and saves it to results/<name>.csv.
-- Thresholds come in as named parameters (:min_side, :min_airport, :min_route) so that the
-- same file works on the 3% sample and on the full 5.8M-row file.
--
-- Definitions used everywhere:
--   late_pct      = share of COMPLETED flights (not cancelled, not diverted) that arrived 15+ min late
--   cancel_pct    = share of ALL scheduled flights that were cancelled
--   divert_pct    = share of ALL scheduled flights that were diverted
--   problem_pct   = share of ALL scheduled flights that were cancelled, diverted or 15+ min late
-- ============================================================================

-- name: q01_overview
SELECT
    COUNT(*)                                                          AS scheduled_flights,
    SUM(completed)                                                    AS completed_flights,
    SUM(late15)                                                       AS late_flights,
    ROUND(100.0 * SUM(late15)    / SUM(completed), 2)                 AS late_pct,
    ROUND(100.0 * SUM(late30)    / SUM(completed), 2)                 AS late30_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(diverted)  / COUNT(*), 2)                       AS divert_pct,
    ROUND(100.0 * SUM(problem)   / COUNT(*), 2)                       AS problem_pct,
    ROUND(AVG(arr_delay), 2)                                          AS mean_arrival_delay_min,
    ROUND(100.0 * SUM(CASE WHEN completed = 1 AND arr_delay < 0 THEN 1 ELSE 0 END)
          / SUM(completed), 2)                                        AS early_arrival_pct
FROM flights;

-- name: q02_monthly
SELECT
    month,
    COUNT(*)                                                          AS scheduled_flights,
    ROUND(100.0 * SUM(late15)    / SUM(completed), 2)                 AS late_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(diverted)  / COUNT(*), 3)                       AS divert_pct,
    ROUND(100.0 * SUM(problem)   / COUNT(*), 2)                       AS problem_pct,
    ROUND(AVG(arr_delay), 2)                                          AS mean_arrival_delay_min
FROM flights
GROUP BY month
ORDER BY month;

-- name: q03_weekday
SELECT
    day_of_week,
    CASE day_of_week WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue' WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu'
                     WHEN 5 THEN 'Fri' WHEN 6 THEN 'Sat' ELSE 'Sun' END AS weekday,
    COUNT(*)                                                          AS scheduled_flights,
    ROUND(100.0 * SUM(late15)    / SUM(completed), 2)                 AS late_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(problem)   / COUNT(*), 2)                       AS problem_pct
FROM flights
GROUP BY day_of_week
ORDER BY day_of_week;

-- name: q04_hourly
-- Delays snowball through the day: the share of late flights blamed mainly on the previous
-- flight of the same aircraft ("late aircraft") grows hour by hour.
SELECT
    sched_hour                                                        AS scheduled_hour,
    COUNT(*)                                                          AS scheduled_flights,
    ROUND(100.0 * SUM(late15)    / SUM(completed), 2)                 AS late_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(dep_late15) / SUM(dep_valid), 2)                AS departed_late_pct,
    ROUND(100.0 * SUM(CASE WHEN primary_cause = 'Late aircraft' THEN 1 ELSE 0 END)
          / NULLIF(SUM(late15), 0), 2)                                AS late_aircraft_share_of_late_pct
FROM flights
GROUP BY sched_hour
ORDER BY sched_hour;

-- name: q05_airline_raw
-- Raw, unadjusted comparison. Airlines fly different routes, so see q06 for the fair version.
SELECT
    f.airline,
    COALESCE(a.AIRLINE, f.airline)                                    AS airline_name,
    COUNT(*)                                                          AS scheduled_flights,
    SUM(f.completed)                                                  AS completed_flights,
    ROUND(100.0 * SUM(f.late15)    / SUM(f.completed), 2)             AS late_pct,
    ROUND(100.0 * SUM(f.cancelled) / COUNT(*), 2)                     AS cancel_pct,
    ROUND(100.0 * SUM(f.diverted)  / COUNT(*), 3)                     AS divert_pct,
    ROUND(100.0 * SUM(f.problem)   / COUNT(*), 2)                     AS problem_pct,
    ROUND(AVG(f.arr_delay), 2)                                        AS mean_arrival_delay_min,
    ROUND(AVG(f.distance), 0)                                         AS avg_distance_mi,
    RANK() OVER (ORDER BY 1.0 * SUM(f.late15) / SUM(f.completed))     AS raw_rank_late
FROM flights f
LEFT JOIN airlines a ON a.IATA_CODE = f.airline
GROUP BY f.airline
ORDER BY late_pct;

-- name: q06_airline_fair
-- Fair comparison. Inside every cell "same route (origin -> destination) in the same month",
-- compare an airline with ALL OTHER airlines flying that cell, then average those gaps
-- weighted by the airline's own flights. Cells where the airline or the others have fewer than
-- :min_side completed flights are skipped (coverage_pct says how much of the airline is left).
-- diff_* are percentage points: negative = better than the others on the same routes.
-- The cancellation / diversion-aware version (problem_*) uses all scheduled flights.
WITH rm AS (
    SELECT month, origin_key, dest_key, airline,
           SUM(n_sched) AS sched, SUM(n_completed) AS comp,
           SUM(n_late)  AS late,  SUM(n_problem)   AS prob
    FROM cell_airline
    GROUP BY month, origin_key, dest_key, airline
),
tot AS (
    SELECT month, origin_key, dest_key,
           SUM(sched) AS sched, SUM(comp) AS comp, SUM(late) AS late, SUM(prob) AS prob
    FROM rm
    GROUP BY month, origin_key, dest_key
),
x AS (
    SELECT rm.airline,
           rm.sched, rm.comp, rm.late, rm.prob,
           tot.sched - rm.sched AS o_sched, tot.comp - rm.comp AS o_comp,
           tot.late  - rm.late  AS o_late,  tot.prob - rm.prob AS o_prob
    FROM rm
    JOIN tot ON tot.month = rm.month AND tot.origin_key = rm.origin_key AND tot.dest_key = rm.dest_key
),
own AS (
    SELECT airline, SUM(sched) AS sched, SUM(comp) AS comp, SUM(late) AS late FROM rm GROUP BY airline
),
cmp AS (
    SELECT airline,
           SUM(comp)                                  AS comp,
           SUM(late)                                  AS late,
           SUM(1.0 * comp * o_late / o_comp)          AS exp_late,
           SUM(sched)                                 AS sched,
           SUM(prob)                                  AS prob,
           SUM(1.0 * sched * o_prob / o_sched)        AS exp_prob
    FROM x
    WHERE comp >= :min_side AND o_comp >= :min_side
    GROUP BY airline
)
SELECT
    o.airline,
    COALESCE(a.AIRLINE, o.airline)                                          AS airline_name,
    o.sched                                                                 AS scheduled_flights,
    c.comp                                                                  AS comparable_completed_flights,
    ROUND(100.0 * c.comp / o.comp, 1)                                       AS coverage_pct,
    ROUND(100.0 * o.late / o.comp, 2)                                       AS raw_late_pct,
    ROUND(100.0 * c.late / c.comp, 2)                                       AS own_late_pct,
    ROUND(100.0 * c.exp_late / c.comp, 2)                                   AS others_late_pct,
    ROUND(100.0 * (c.late - c.exp_late) / c.comp, 2)                        AS diff_late_pp,
    ROUND(100.0 * c.prob / c.sched, 2)                                      AS own_problem_pct,
    ROUND(100.0 * c.exp_prob / c.sched, 2)                                  AS others_problem_pct,
    ROUND(100.0 * (c.prob - c.exp_prob) / c.sched, 2)                       AS diff_problem_pp,
    RANK() OVER (ORDER BY (c.late - c.exp_late) / c.comp)                   AS fair_rank_late,
    RANK() OVER (ORDER BY (c.prob - c.exp_prob) / c.sched)                  AS fair_rank_problem
FROM own o
JOIN cmp c ON c.airline = o.airline
LEFT JOIN airlines a ON a.IATA_CODE = o.airline
ORDER BY diff_late_pp;

-- name: q07_airport_departures
-- Departure side only (a late arrival also reflects the airport you left). Airports with a
-- numeric October ID that could not be mapped are left out. 'departed_late' = 15+ min after schedule.
SELECT
    f.origin                                                          AS airport,
    ap.AIRPORT                                                        AS airport_name,
    ap.CITY                                                           AS city,
    ap.STATE                                                          AS state,
    COUNT(*)                                                          AS scheduled_departures,
    ROUND(100.0 * SUM(f.dep_late15) / SUM(f.dep_valid), 2)            AS departed_late_pct,
    ROUND(100.0 * SUM(f.cancelled)  / COUNT(*), 2)                    AS cancel_pct,
    ROUND(AVG(f.dep_delay), 2)                                        AS mean_departure_delay_min
FROM flights f
LEFT JOIN airports ap ON ap.IATA_CODE = f.origin
WHERE f.origin IS NOT NULL
GROUP BY f.origin
HAVING COUNT(*) >= :min_airport
ORDER BY departed_late_pct DESC;

-- name: q08_distance
SELECT
    distance_bucket,
    COUNT(*)                                                          AS scheduled_flights,
    ROUND(100.0 * SUM(late15)    / SUM(completed), 2)                 AS late_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(problem)   / COUNT(*), 2)                       AS problem_pct
FROM flights
GROUP BY distance_bucket
ORDER BY distance_bucket;

-- name: q09_make_up_time
-- Do planes make up time in the air? Arrival lateness by how late the flight pushed back.
SELECT
    CASE WHEN dep_delay >= 15 THEN '3. Left 15+ min late'
         WHEN dep_delay >= 0  THEN '2. Left 0-14 min late'
         ELSE                      '1. Left early' END                AS departure_status,
    COUNT(*)                                                          AS flights,
    ROUND(100.0 * SUM(late15) / COUNT(*), 2)                          AS arrived_late_pct,
    ROUND(AVG(arr_delay - dep_delay), 2)                              AS avg_minutes_gained_in_air,
    ROUND(AVG(dep_delay), 2)                                          AS avg_departure_delay_min,
    ROUND(AVG(arr_delay), 2)                                          AS avg_arrival_delay_min
FROM flights
WHERE completed = 1 AND dep_delay IS NOT NULL AND arr_delay IS NOT NULL
GROUP BY departure_status
ORDER BY departure_status;

-- name: q10_causes_overall
-- Where the delay MINUTES come from (only flights that arrived 15+ min late carry a cause).
WITH t AS (
    SELECT SUM(c_air_system) AS air_system, SUM(c_security) AS security, SUM(c_airline) AS airline,
           SUM(c_late_aircraft) AS late_aircraft, SUM(c_weather) AS weather, SUM(c_total) AS total
    FROM flights WHERE late15 = 1
)
SELECT 'Late aircraft (previous flight)' AS cause, late_aircraft AS minutes, ROUND(100.0 * late_aircraft / total, 2) AS share_pct FROM t
UNION ALL SELECT 'Air system (traffic control, volume)', air_system, ROUND(100.0 * air_system / total, 2) FROM t
UNION ALL SELECT 'Airline (crew, maintenance, cleaning)', airline, ROUND(100.0 * airline / total, 2) FROM t
UNION ALL SELECT 'Weather', weather, ROUND(100.0 * weather / total, 2) FROM t
UNION ALL SELECT 'Security', security, ROUND(100.0 * security / total, 2) FROM t;

-- name: q11_primary_cause
-- Same question counted in flights: the single biggest cause of each late flight.
SELECT
    primary_cause,
    COUNT(*)                                                          AS late_flights,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                AS share_pct,
    ROUND(AVG(arr_delay), 1)                                          AS avg_arrival_delay_min
FROM flights
WHERE late15 = 1
GROUP BY primary_cause
ORDER BY late_flights DESC;

-- name: q12_causes_by_month
SELECT
    month,
    SUM(late15)                                                       AS late_flights,
    ROUND(100.0 * SUM(c_late_aircraft) / SUM(c_total), 2)             AS late_aircraft_pct,
    ROUND(100.0 * SUM(c_air_system)    / SUM(c_total), 2)             AS air_system_pct,
    ROUND(100.0 * SUM(c_airline)       / SUM(c_total), 2)             AS airline_pct,
    ROUND(100.0 * SUM(c_weather)       / SUM(c_total), 2)             AS weather_pct,
    ROUND(100.0 * SUM(c_security)      / SUM(c_total), 2)             AS security_pct
FROM flights
WHERE late15 = 1
GROUP BY month
ORDER BY month;

-- name: q13_causes_by_airline
SELECT
    f.airline,
    COALESCE(a.AIRLINE, f.airline)                                    AS airline_name,
    SUM(f.late15)                                                     AS late_flights,
    ROUND(100.0 * SUM(f.c_late_aircraft) / SUM(f.c_total), 2)         AS late_aircraft_pct,
    ROUND(100.0 * SUM(f.c_air_system)    / SUM(f.c_total), 2)         AS air_system_pct,
    ROUND(100.0 * SUM(f.c_airline)       / SUM(f.c_total), 2)         AS airline_pct,
    ROUND(100.0 * SUM(f.c_weather)       / SUM(f.c_total), 2)         AS weather_pct,
    ROUND(100.0 * SUM(f.c_security)      / SUM(f.c_total), 2)         AS security_pct
FROM flights f
LEFT JOIN airlines a ON a.IATA_CODE = f.airline
WHERE f.late15 = 1
GROUP BY f.airline
ORDER BY airline_pct DESC;

-- name: q14_cancel_reasons
SELECT
    CASE cancel_reason WHEN 'A' THEN 'Airline / carrier' WHEN 'B' THEN 'Weather'
                       WHEN 'C' THEN 'National air system' WHEN 'D' THEN 'Security' END AS reason,
    COUNT(*)                                                          AS cancelled_flights,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                AS share_pct
FROM flights
WHERE cancelled = 1
GROUP BY cancel_reason
ORDER BY cancelled_flights DESC;

-- name: q15_cancel_by_month_reason
SELECT
    month,
    COUNT(*)                                                          AS scheduled_flights,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 3)                       AS cancel_pct,
    ROUND(100.0 * SUM(CASE WHEN cancel_reason = 'B' THEN 1 ELSE 0 END) / COUNT(*), 3) AS weather_pct,
    ROUND(100.0 * SUM(CASE WHEN cancel_reason = 'A' THEN 1 ELSE 0 END) / COUNT(*), 3) AS airline_pct,
    ROUND(100.0 * SUM(CASE WHEN cancel_reason = 'C' THEN 1 ELSE 0 END) / COUNT(*), 3) AS air_system_pct,
    ROUND(100.0 * SUM(CASE WHEN cancel_reason = 'D' THEN 1 ELSE 0 END) / COUNT(*), 3) AS security_pct
FROM flights
GROUP BY month
ORDER BY month;

-- name: q16_daily
-- One row per day (365). The chart picks out the worst days.
SELECT
    flight_date,
    month,
    COUNT(*)                                                          AS scheduled_flights,
    ROUND(100.0 * SUM(late15)    / NULLIF(SUM(completed), 0), 2)      AS late_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(problem)   / COUNT(*), 2)                       AS problem_pct
FROM flights
GROUP BY flight_date
ORDER BY flight_date;

-- name: q17_routes
-- Directional routes with enough flights; both airports known.
SELECT
    origin || ' -> ' || dest                                          AS route,
    origin, dest,
    COUNT(*)                                                          AS scheduled_flights,
    COUNT(DISTINCT airline)                                           AS airlines,
    ROUND(100.0 * SUM(late15)    / SUM(completed), 2)                 AS late_pct,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)                       AS cancel_pct,
    ROUND(100.0 * SUM(problem)   / COUNT(*), 2)                       AS problem_pct
FROM flights
WHERE origin IS NOT NULL AND dest IS NOT NULL
GROUP BY origin, dest
HAVING COUNT(*) >= :min_route
ORDER BY late_pct DESC;

-- name: q18_competition
-- Does a route with more airlines run more punctually? Month-level cells, grouped by how many
-- airlines flew the cell. (Descriptive: busy routes also differ in length and airports.)
WITH rm AS (
    SELECT month, origin_key, dest_key,
           COUNT(DISTINCT airline) AS airlines,
           SUM(n_sched) AS sched, SUM(n_completed) AS comp, SUM(n_late) AS late, SUM(n_cancelled) AS canc
    FROM cell_airline
    GROUP BY month, origin_key, dest_key
)
SELECT
    CASE WHEN airlines = 1 THEN '1 airline' WHEN airlines = 2 THEN '2 airlines'
         ELSE '3+ airlines' END                                       AS competition,
    COUNT(*)                                                          AS route_months,
    SUM(sched)                                                        AS scheduled_flights,
    ROUND(100.0 * SUM(late) / SUM(comp), 2)                           AS late_pct,
    ROUND(100.0 * SUM(canc) / SUM(sched), 2)                          AS cancel_pct
FROM rm
GROUP BY competition
ORDER BY competition;

-- name: q19_data_quality
-- Every line should match "expected" (or be explained in the README).
SELECT 'scheduled flights loaded' AS check_name, COUNT(*) AS value, NULL AS expected FROM flights
UNION ALL SELECT 'cancelled flights that still have an arrival delay', COUNT(*), 0
    FROM flights WHERE cancelled = 1 AND arr_delay IS NOT NULL
UNION ALL SELECT 'diverted flights that still have an arrival delay', COUNT(*), 0
    FROM flights WHERE diverted = 1 AND arr_delay IS NOT NULL
UNION ALL SELECT 'completed flights with NO arrival delay', COUNT(*), 0
    FROM flights WHERE completed = 1 AND arr_delay IS NULL
UNION ALL SELECT 'late flights whose five causes do not add up to the arrival delay', COUNT(*), 0
    FROM flights WHERE late15 = 1 AND c_total <> arr_delay
UNION ALL SELECT 'flights under 15 min late that still carry a cause', COUNT(*), 0
    FROM flights WHERE late15 = 0 AND c_total > 0
UNION ALL SELECT 'cancelled flights without a cancellation reason', COUNT(*), 0
    FROM flights WHERE cancelled = 1 AND cancel_reason IS NULL
UNION ALL SELECT 'flights both cancelled and diverted', COUNT(*), 0
    FROM flights WHERE cancelled = 1 AND diverted = 1
UNION ALL SELECT 'duplicate flights (same airline, number, date, route, scheduled time)',
    COALESCE(SUM(n - 1), 0), 0
    FROM (SELECT COUNT(*) AS n FROM flights
          GROUP BY airline, flight_number, flight_date, origin_key, dest_key, sched_dep HAVING COUNT(*) > 1)
UNION ALL SELECT 'October rows (numeric airport IDs)', COUNT(*), NULL FROM flights WHERE month = 10
UNION ALL SELECT 'numeric IDs mapped to an airport code', COUNT(*), NULL FROM airport_id_map
UNION ALL SELECT 'October rows with BOTH airports identified', COUNT(*), NULL
    FROM flights WHERE month = 10 AND origin IS NOT NULL AND dest IS NOT NULL
UNION ALL SELECT 'rows with an unidentified airport (all in October)', COUNT(*), NULL
    FROM flights WHERE origin IS NULL OR dest IS NULL
UNION ALL SELECT 'airport codes in flights but missing from airports.csv', COUNT(*), 0
    FROM (SELECT origin AS c FROM flights WHERE origin IS NOT NULL
          UNION SELECT dest FROM flights WHERE dest IS NOT NULL)
    WHERE c NOT IN (SELECT IATA_CODE FROM airports)
UNION ALL SELECT 'airline codes in flights but missing from airlines.csv', COUNT(*), 0
    FROM (SELECT DISTINCT airline FROM flights) WHERE airline NOT IN (SELECT IATA_CODE FROM airlines);

-- name: q20_airport_id_map
-- The derived map (numeric October ID -> airport code) with its evidence, for anyone who wants to audit it.
SELECT id AS october_id, iata AS airport_code,
       ROUND(top_votes, 1) AS votes_for_code, ROUND(total_votes, 1) AS total_votes,
       ROUND(vote_share, 3) AS vote_share
FROM airport_id_map
ORDER BY total_votes DESC;
