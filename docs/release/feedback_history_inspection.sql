-- READ-ONLY historical feedback inspection for Newbiegrader.
--
-- DO NOT update or delete rows from this file. Run it only with a read-only
-- database role (service_role is acceptable for the query, but use a temporary
-- read-only connection in the authorized maintenance window). Record counts and
-- representative synthetic IDs in the change ticket; never publish hidden test
-- bytes or user code.
--
-- "test data" here means any of input/expected/actual/diff/stdout/stderr/detail.
-- A row is potentially over-disclosed when such data exists for a result that
-- is not a current public sample. Stored rows from older releases may omit the
-- `public` marker; the join against problems.samples is deliberately
-- conservative when that marker is absent or the problem row has been removed.

-- 1. Overall count by problem and contest association.
with result_items as (
  select s.id, s.problem, s.contest_id, s.created_at, s.kind,
         item,
         coalesce(
           (item->>'public')::boolean,
           exists (
             select 1
             from jsonb_array_elements_text(coalesce(p.samples, '[]'::jsonb)) as sample(name)
             where sample.name = item->>'test'
           )
         ) as is_public,
         (
           coalesce(length(item->>'input'), 0) > 0
           or coalesce(length(item->>'expected'), 0) > 0
           or coalesce(length(item->>'actual'), 0) > 0
           or coalesce(length(item->>'diff'), 0) > 0
           or coalesce(length(item->>'stdout'), 0) > 0
           or coalesce(length(item->>'stderr'), 0) > 0
           or coalesce(length(item->>'detail'), 0) > 0
         ) as has_test_data
  from public.submissions s
  left join public.problems p on p.slug = s.problem
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(s.results) = 'array' then s.results else '[]'::jsonb end
  ) as item
)
select problem, contest_id, count(*) as potentially_over_disclosed_results,
       count(distinct id) as affected_submissions
from result_items
where has_test_data and is_public is not true
group by problem, contest_id
order by potentially_over_disclosed_results desc, problem, contest_id;

-- 2. Bounded representative rows. IDs only; fetch code/results separately under
-- the incident-access procedure. Limit keeps the query safe on large tables.
with result_items as (
  select s.id, s.problem, s.contest_id, s.created_at, s.kind, s.user_email,
         item,
         coalesce(
           (item->>'public')::boolean,
           exists (
             select 1
             from jsonb_array_elements_text(coalesce(p.samples, '[]'::jsonb)) as sample(name)
             where sample.name = item->>'test'
           )
         ) as is_public,
         (
           coalesce(length(item->>'input'), 0) > 0
           or coalesce(length(item->>'expected'), 0) > 0
           or coalesce(length(item->>'actual'), 0) > 0
           or coalesce(length(item->>'diff'), 0) > 0
           or coalesce(length(item->>'stdout'), 0) > 0
           or coalesce(length(item->>'stderr'), 0) > 0
           or coalesce(length(item->>'detail'), 0) > 0
         ) as has_test_data
  from public.submissions s
  left join public.problems p on p.slug = s.problem
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(s.results) = 'array' then s.results else '[]'::jsonb end
  ) as item
)
select id, created_at, problem, contest_id, kind, user_email
from result_items
where has_test_data and is_public is not true
group by id, created_at, problem, contest_id, kind, user_email
order by created_at desc
limit 100;

-- 3. Contest rows whose submissions now have no matching contest metadata.
-- These are the rows that read-time policy must fail closed on; they are not
-- evidence that the stored bytes were safe at write time.
select s.id, s.created_at, s.problem, s.contest_id, s.kind
from public.submissions s
left join public.contests c on c.id = s.contest_id
where s.contest_id is not null and c.id is null
order by s.created_at desc
limit 100;

-- 4. Submissions belonging to currently running contests with samples off.
-- They must not be visible to their owners with sample/hidden feedback during
-- the round. This query identifies the policy window, not user access.
select s.id, s.created_at, s.problem, s.contest_id, s.kind
from public.submissions s
join public.contests c on c.id = s.contest_id
where c.show_samples = false
  and c.starts_at <= now() and c.ends_at >= now()
order by s.created_at desc
limit 100;

-- 5. Persisted job results can also contain feedback. Jobs are service-role-only,
-- but old rows may still be exported/backed up. `reveal='all'` is expected only
-- for an admin owner; anything else with hidden fields is suspicious.
with job_items as (
  select j.id, j.created_at, j.kind, j.user_email, j.contest_id, j.reveal,
         item,
         coalesce((item->>'public')::boolean, false) as was_marked_public,
         (
           coalesce(length(item->>'input'), 0) > 0
           or coalesce(length(item->>'expected'), 0) > 0
           or coalesce(length(item->>'actual'), 0) > 0
           or coalesce(length(item->>'diff'), 0) > 0
           or coalesce(length(item->>'stdout'), 0) > 0
           or coalesce(length(item->>'stderr'), 0) > 0
           or coalesce(length(item->>'detail'), 0) > 0
         ) as has_test_data
  from public.judge_jobs j
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(j.result->'results') = 'array'
         then j.result->'results' else '[]'::jsonb end
  ) as item
)
select id, created_at, kind, user_email, contest_id, reveal
from job_items
where has_test_data and not was_marked_public and reveal <> 'all'
group by id, created_at, kind, user_email, contest_id, reveal
order by created_at desc
limit 100;

-- 6. Counts by job reveal mode, for a quick change-ticket summary.
select reveal, count(*) as jobs_with_results
from public.judge_jobs
where result is not null
group by reveal
order by jobs_with_results desc, reveal;
