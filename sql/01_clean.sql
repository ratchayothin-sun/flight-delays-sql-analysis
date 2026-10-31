-- ============================================================================
-- 01_clean.sql
-- Input : raw_flights  (selected columns of flights.csv, loaded as text, untouched)
--         airlines, airports  (reference tables, loaded by run_analysis.py)
-- Output: airport_id_map  (numeric October airport ID -> IATA code, derived from the data)
--         flights         (one row per scheduled flight, typed, with flags)
--         cell_airline    (flight counts per route x month x time of day x airline)
--
-- Cleaning decisions:
--   * ALL of October 2015 (and nothing else) uses numeric airport IDs such as 10397 in
--     ORIGIN_AIRPORT / DESTINATION_AIRPORT instead of IATA codes such as ATL. The file ships
--     no lookup for them, so the map is derived from the data itself: a flight (same airline,
--     flight number, scheduled departure and distance) flies the same route in October as in
--     other months, so its October IDs "vote" for the IATA codes it has in other months.
--     A code is accepted only if >= 3 votes, >= 90% of them agree, and no other ID claims the
--     same code. Unmapped airports keep origin / dest = NULL: they stay in airline comparisons
--     (the numeric ID keeps a route together within October) but are left out of airport results.
--   * ARRIVAL_DELAY is empty for exactly the cancelled and diverted flights (checked in
--     q19_data_quality). Those flights are NOT dropped: they are counted as "problem" flights
--     and reported next to the late rate, so an airline cannot look punctual by cancelling.
--   * The five delay-cause columns are filled only when the flight arrived 15+ minutes late
--     (and then add up to the arrival delay).
--   * Late = arrival delay of 15 minutes or more (the US DOT definition), among flights that
--     completed (late30 = 30+ minutes, used as a robustness check; dep_late15 = departed 15+ min late,
--     used for airport results because an arrival delay also reflects the airport you left). Extreme delays (up to 1,971 min) are kept; rates, not means, carry the story.
--   * DAY_OF_WEEK: 1 = Monday (2015-01-01 was a Thursday, coded 4).
-- ============================================================================

DROP TABLE IF EXISTS airport_id_map;
DROP TABLE IF EXISTS flights;
DROP TABLE IF EXISTS cell_airline;
DROP TABLE IF EXISTS temp.oct_keys;
DROP TABLE IF EXISTS temp.non_keys;

-- ---------------------------------------------------------------------------
-- 1) October airport IDs -> IATA codes
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE oct_keys AS
SELECT AIRLINE AS a, CAST(FLIGHT_NUMBER AS INTEGER) AS f, CAST(SCHEDULED_DEPARTURE AS INTEGER) AS s,
       CAST(DISTANCE AS INTEGER) AS d,
       ORIGIN_AIRPORT AS o, DESTINATION_AIRPORT AS x, COUNT(*) AS n
FROM raw_flights
WHERE MONTH = '10'
GROUP BY 1, 2, 3, 4, 5, 6;

CREATE TEMP TABLE non_keys AS
SELECT AIRLINE AS a, CAST(FLIGHT_NUMBER AS INTEGER) AS f, CAST(SCHEDULED_DEPARTURE AS INTEGER) AS s,
       CAST(DISTANCE AS INTEGER) AS d,
       ORIGIN_AIRPORT AS o, DESTINATION_AIRPORT AS x, COUNT(*) AS n
FROM raw_flights
WHERE MONTH <> '10'
GROUP BY 1, 2, 3, 4, 5, 6;

CREATE INDEX temp.ix_non_keys ON non_keys (a, f, s, d);

CREATE TABLE airport_id_map AS
WITH non_w AS (   -- share of each IATA pair among the non-October rows of the same flight key
    SELECT a, f, s, d, o, x, n * 1.0 / SUM(n) OVER (PARTITION BY a, f, s, d) AS w
    FROM non_keys
),
pairs AS (
    SELECT oct_keys.o AS o_id, oct_keys.x AS x_id, non_w.o AS o_iata, non_w.x AS x_iata,
           oct_keys.n * non_w.w AS vote
    FROM oct_keys
    JOIN non_w ON oct_keys.a = non_w.a AND oct_keys.f = non_w.f
              AND oct_keys.s = non_w.s AND oct_keys.d = non_w.d
),
votes AS (        -- origin and destination columns share one ID space
    SELECT o_id AS id, o_iata AS iata, SUM(vote) AS v FROM pairs GROUP BY o_id, o_iata
    UNION ALL
    SELECT x_id,       x_iata,         SUM(vote)      FROM pairs GROUP BY x_id, x_iata
),
agg AS (
    SELECT id, iata, SUM(v) AS v FROM votes GROUP BY id, iata
),
ranked AS (
    SELECT id, iata, v,
           SUM(v) OVER (PARTITION BY id)                 AS total_votes,
           ROW_NUMBER() OVER (PARTITION BY id ORDER BY v DESC) AS rk
    FROM agg
),
best AS (
    SELECT id, iata, v AS top_votes, total_votes, v / total_votes AS vote_share
    FROM ranked
    WHERE rk = 1 AND total_votes >= 3 AND v / total_votes >= 0.9
)
SELECT id, iata, top_votes, total_votes, vote_share
FROM best
WHERE iata IN (SELECT iata FROM best GROUP BY iata HAVING COUNT(*) = 1);   -- one ID per code

CREATE UNIQUE INDEX idx_map_id ON airport_id_map (id);

DROP TABLE temp.oct_keys;
DROP TABLE temp.non_keys;

-- ---------------------------------------------------------------------------
-- 2) Typed flights table
-- ---------------------------------------------------------------------------
CREATE TABLE flights AS
WITH base AS (
    SELECT
        r.rowid                                                        AS flight_id,
        CAST(r.MONTH AS INTEGER)                                       AS month,
        CAST(r.DAY AS INTEGER)                                         AS day,
        CAST(r.DAY_OF_WEEK AS INTEGER)                                 AS day_of_week,
        date(printf('%04d-%02d-%02d', CAST(r.YEAR AS INTEGER),
                    CAST(r.MONTH AS INTEGER), CAST(r.DAY AS INTEGER))) AS flight_date,
        r.AIRLINE                                                      AS airline,
        CAST(r.FLIGHT_NUMBER AS INTEGER)                               AS flight_number,

        -- airports: IATA code, or NULL when an October ID could not be mapped
        CASE WHEN mo.iata IS NOT NULL THEN mo.iata
             WHEN r.ORIGIN_AIRPORT GLOB '[0-9]*' THEN NULL
             ELSE r.ORIGIN_AIRPORT END                                 AS origin,
        CASE WHEN md.iata IS NOT NULL THEN md.iata
             WHEN r.DESTINATION_AIRPORT GLOB '[0-9]*' THEN NULL
             ELSE r.DESTINATION_AIRPORT END                            AS dest,
        -- route key: the code if known, else the raw numeric ID (keeps a route together within a month)
        COALESCE(mo.iata, r.ORIGIN_AIRPORT)                            AS origin_key,
        COALESCE(md.iata, r.DESTINATION_AIRPORT)                       AS dest_key,

        CAST(r.SCHEDULED_DEPARTURE AS INTEGER)                         AS sched_dep,
        CAST(r.SCHEDULED_DEPARTURE AS INTEGER) / 100                   AS sched_hour,
        CAST(NULLIF(r.DEPARTURE_DELAY, '') AS INTEGER)                 AS dep_delay,
        CAST(NULLIF(r.ARRIVAL_DELAY, '') AS INTEGER)                   AS arr_delay,
        CAST(r.DISTANCE AS INTEGER)                                    AS distance,

        CASE WHEN r.CANCELLED = '1' THEN 1 ELSE 0 END                  AS cancelled,
        CASE WHEN r.DIVERTED = '1'  THEN 1 ELSE 0 END                  AS diverted,
        NULLIF(r.CANCELLATION_REASON, '')                              AS cancel_reason,   -- A airline, B weather, C air system, D security

        COALESCE(CAST(NULLIF(r.AIR_SYSTEM_DELAY, '')    AS INTEGER), 0) AS c_air_system,
        COALESCE(CAST(NULLIF(r.SECURITY_DELAY, '')      AS INTEGER), 0) AS c_security,
        COALESCE(CAST(NULLIF(r.AIRLINE_DELAY, '')       AS INTEGER), 0) AS c_airline,
        COALESCE(CAST(NULLIF(r.LATE_AIRCRAFT_DELAY, '') AS INTEGER), 0) AS c_late_aircraft,
        COALESCE(CAST(NULLIF(r.WEATHER_DELAY, '')       AS INTEGER), 0) AS c_weather
    FROM raw_flights r
    LEFT JOIN airport_id_map mo ON mo.id = r.ORIGIN_AIRPORT
    LEFT JOIN airport_id_map md ON md.id = r.DESTINATION_AIRPORT
),
flagged AS (
    SELECT
        base.*,
        CASE WHEN cancelled = 0 AND diverted = 0 THEN 1 ELSE 0 END                  AS completed,
        CASE WHEN cancelled = 0 AND diverted = 0 AND arr_delay >= 15 THEN 1 ELSE 0 END AS late15,
        CASE WHEN cancelled = 0 AND diverted = 0 AND arr_delay >= 30 THEN 1 ELSE 0 END AS late30,
        CASE WHEN cancelled = 0 AND dep_delay IS NOT NULL THEN 1 ELSE 0 END           AS dep_valid,
        CASE WHEN cancelled = 0 AND dep_delay >= 15 THEN 1 ELSE 0 END                 AS dep_late15,
        CASE WHEN cancelled = 1 OR diverted = 1 OR arr_delay >= 15 THEN 1 ELSE 0 END   AS problem,
        c_air_system + c_security + c_airline + c_late_aircraft + c_weather         AS c_total,
        MAX(c_air_system, c_security, c_airline, c_late_aircraft, c_weather)        AS c_max,
        CASE
            WHEN sched_hour <= 5  THEN '1. Night (00-05)'
            WHEN sched_hour <= 11 THEN '2. Morning (06-11)'
            WHEN sched_hour <= 17 THEN '3. Afternoon (12-17)'
            ELSE                       '4. Evening (18-23)'
        END                                                                          AS daypart,
        CASE
            WHEN distance < 500  THEN '1. Short (under 500 mi)'
            WHEN distance < 1500 THEN '2. Medium (500-1,499 mi)'
            ELSE                      '3. Long (1,500+ mi)'
        END                                                                          AS distance_bucket
    FROM base
)
SELECT
    flagged.*,
    -- the cause with the most delay minutes on a late flight ('Tie' when two or more are equal)
    CASE
        WHEN late15 = 0 THEN NULL
        WHEN (c_air_system = c_max) + (c_security = c_max) + (c_airline = c_max)
           + (c_late_aircraft = c_max) + (c_weather = c_max) > 1 THEN 'Tie'
        WHEN c_late_aircraft = c_max THEN 'Late aircraft'
        WHEN c_airline = c_max       THEN 'Airline'
        WHEN c_air_system = c_max    THEN 'Air system'
        WHEN c_weather = c_max       THEN 'Weather'
        ELSE                              'Security'
    END AS primary_cause
FROM flagged;

CREATE INDEX idx_flights_airline ON flights (airline);
CREATE INDEX idx_flights_month   ON flights (month);

-- ---------------------------------------------------------------------------
-- 3) Counts per route x month x time of day x airline (small; feeds the fair comparison
--    in 02_analysis.sql and the bootstrap in 03_robustness.py)
-- ---------------------------------------------------------------------------
CREATE TABLE cell_airline AS
SELECT
    month, origin_key, dest_key, daypart, airline,
    COUNT(*)        AS n_sched,
    SUM(completed)  AS n_completed,
    SUM(late15)     AS n_late,
    SUM(late30)     AS n_late30,
    SUM(cancelled)  AS n_cancelled,
    SUM(diverted)   AS n_diverted,
    SUM(problem)    AS n_problem
FROM flights
GROUP BY month, origin_key, dest_key, daypart, airline;

CREATE INDEX idx_cell_route ON cell_airline (month, origin_key, dest_key);
