-- ============================================================
-- views.sql
-- BigQuery analytical views for the YouTube Reading Intelligence Dashboard
-- Project: portolioprojects  |  Dataset: youtube_dashboard
--
-- Run order: run all CREATE OR REPLACE VIEW statements.
-- They are safe to re-run — idempotent by design.
-- ============================================================


-- ────────────────────────────────────────────────────────────
-- 1. videos_by_keyword
--    Every video matched to its keyword(s), with current metrics.
--    Primary source for keyword-level analysis in Tableau.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW `portolioprojects.yt_dashboard.videos_by_keyword` AS
SELECT
  sr.keyword_id,
  kr.keyword,
  kr.category,
  kr.subcategory,
  kr.keyword_type,
  kr.priority,
  v.video_id,
  v.title,
  v.channel_id,
  ch.channel_title,
  v.published_at,
  DATE(v.published_at) AS publish_date,
  FORMAT_TIMESTAMP('%Y-%m', v.published_at) AS publish_month,
  EXTRACT(YEAR FROM v.published_at) AS publish_year,
  v.duration,
  v.view_count,
  v.like_count,
  v.comment_count,
  SAFE_DIVIDE(v.like_count + v.comment_count, v.view_count) AS engagement_rate,
  v.last_updated
FROM `portolioprojects.yt_dashboard.search_results` sr
JOIN `portolioprojects.yt_dashboard.videos` v
  ON sr.video_id = v.video_id
JOIN `portolioprojects.yt_dashboard.keyword_registry` kr
  ON sr.keyword_id = kr.keyword_id
LEFT JOIN `portolioprojects.yt_dashboard.channels` ch
  ON v.channel_id = ch.channel_id
;


-- ────────────────────────────────────────────────────────────
-- 2. monthly_video_count_by_keyword
--    How many videos were published per keyword per month.
--    Drives the historical trend line in Tableau.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW `portolioprojects.yt_dashboard.monthly_video_count_by_keyword` AS
SELECT
  kr.keyword,
  kr.category,
  kr.subcategory,
  kr.keyword_type,
  FORMAT_TIMESTAMP('%Y-%m', v.published_at)  AS publish_month,
  DATE_TRUNC(DATE(v.published_at), MONTH)    AS publish_month_date,
  EXTRACT(YEAR FROM v.published_at)          AS publish_year,
  COUNT(DISTINCT v.video_id)                 AS video_count,
  SUM(v.view_count)                          AS total_views,
  AVG(SAFE_DIVIDE(v.like_count + v.comment_count, v.view_count)) AS avg_engagement_rate
FROM `portolioprojects.yt_dashboard.search_results` sr
JOIN `portolioprojects.yt_dashboard.videos` v
  ON sr.video_id = v.video_id
JOIN `portolioprojects.yt_dashboard.keyword_registry` kr
  ON sr.keyword_id = kr.keyword_id
GROUP BY 1, 2, 3, 4, 5, 6, 7
;


-- ────────────────────────────────────────────────────────────
-- 3. top_channels_by_keyword
--    Which channels produce the most content per keyword.
--    Drives the "emerging channels" section of the dashboard.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW `portolioprojects.yt_dashboard.top_channels_by_keyword` AS
SELECT
  kr.keyword,
  kr.category,
  kr.subcategory,
  v.channel_id,
  ch.channel_title,
  ch.subscriber_count,
  COUNT(DISTINCT v.video_id)                              AS video_count,
  SUM(v.view_count)                                       AS total_views,
  SUM(v.like_count)                                       AS total_likes,
  SUM(v.comment_count)                                    AS total_comments,
  AVG(SAFE_DIVIDE(v.like_count + v.comment_count, v.view_count)) AS avg_engagement_rate,
  MIN(DATE(v.published_at))                               AS first_video_date,
  MAX(DATE(v.published_at))                               AS latest_video_date
FROM `portolioprojects.yt_dashboard.search_results` sr
JOIN `portolioprojects.yt_dashboard.videos` v
  ON sr.video_id = v.video_id
JOIN `portolioprojects.yt_dashboard.channels` ch
  ON v.channel_id = ch.channel_id
JOIN `portolioprojects.yt_dashboard.keyword_registry` kr
  ON sr.keyword_id = kr.keyword_id
GROUP BY 1, 2, 3, 4, 5, 6
;


-- ────────────────────────────────────────────────────────────
-- 4. daily_metric_growth
--    Day-over-day growth for each video in video_daily_snapshots.
--    Used for real-time momentum tracking (Phase 3 onward).
--    NOTE: Requires data in video_daily_snapshots — will return
--    empty results until daily_snapshot.py has run at least twice.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW `portolioprojects.yt_dashboard.daily_metric_growth` AS
SELECT
  snapshot_date,
  video_id,
  view_count,
  like_count,
  comment_count,
  view_count    - LAG(view_count)    OVER (PARTITION BY video_id ORDER BY snapshot_date) AS view_delta,
  like_count    - LAG(like_count)    OVER (PARTITION BY video_id ORDER BY snapshot_date) AS like_delta,
  comment_count - LAG(comment_count) OVER (PARTITION BY video_id ORDER BY snapshot_date) AS comment_delta,
  SAFE_DIVIDE(
    view_count - LAG(view_count) OVER (PARTITION BY video_id ORDER BY snapshot_date),
    LAG(view_count) OVER (PARTITION BY video_id ORDER BY snapshot_date)
  ) AS view_growth_pct
FROM `portolioprojects.yt_dashboard.video_daily_snapshots`
;


-- ────────────────────────────────────────────────────────────
-- 5. keyword_summary
--    Aggregated totals per keyword — for KPI cards in Tableau.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW `portolioprojects.yt_dashboard.keyword_summary` AS
SELECT
  kr.keyword_id,
  kr.keyword,
  kr.category,
  kr.subcategory,
  kr.keyword_type,
  kr.priority,
  COUNT(DISTINCT v.video_id)                              AS total_videos,
  COUNT(DISTINCT v.channel_id)                           AS total_channels,
  SUM(v.view_count)                                      AS total_views,
  SUM(v.like_count)                                      AS total_likes,
  SUM(v.comment_count)                                   AS total_comments,
  AVG(v.view_count)                                      AS avg_views_per_video,
  AVG(SAFE_DIVIDE(v.like_count + v.comment_count, v.view_count)) AS avg_engagement_rate,
  MIN(DATE(v.published_at))                              AS earliest_video,
  MAX(DATE(v.published_at))                              AS latest_video,
  COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', v.published_at)) AS months_with_content
FROM `portolioprojects.yt_dashboard.search_results` sr
JOIN `portolioprojects.yt_dashboard.videos` v
  ON sr.video_id = v.video_id
JOIN `portolioprojects.yt_dashboard.keyword_registry` kr
  ON sr.keyword_id = kr.keyword_id
GROUP BY 1, 2, 3, 4, 5, 6
;


-- ────────────────────────────────────────────────────────────
-- 6. backfill_coverage
--    Shows which keyword × month combinations have been collected.
--    Use in BigQuery to audit completeness before demo.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW `portolioprojects.yt_dashboard.backfill_coverage` AS
SELECT
  keyword_id,
  keyword,
  published_after,
  published_before,
  total_results,
  executed_at,
  FORMAT_TIMESTAMP('%Y-%m', CAST(published_after AS TIMESTAMP)) AS month_label
FROM `portolioprojects.yt_dashboard.search_runs`
WHERE run_type = 'backfill'
ORDER BY keyword_id, published_after
;
