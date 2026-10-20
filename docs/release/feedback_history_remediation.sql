-- HIGHLY SENSITIVE, TARGET-SPECIFIC historical feedback remediation template.
--
-- Do NOT run a blanket predicate against production. Fill the target list only
-- from docs/release/feedback_history_inspection.sql after a change-ticket
-- review. Keep the transaction ending in ROLLBACK until the preview and backup
-- have been reviewed; change only the final ROLLBACK to COMMIT when approved.
--
-- This script intentionally targets explicit submission IDs. It preserves only
-- result objects whose test name is in the problem's current public
-- problems.samples; it does not trust a stored `public` marker. It removes
-- fields that could carry hidden input/output/diagnostics, retains the test
-- name/verdict/timing metadata, and records a durable backup table when
-- committed.
begin;

-- Keep a short lock window on large history tables.
set local statement_timeout = '5min';

create temp table remediation_targets (
  id uuid primary key
) on commit drop;

-- OPERATOR: replace this placeholder with IDs copied from the read-only
-- inspection report. The placeholder matches no real row and is safe to run.
insert into remediation_targets (id) values
  ('00000000-0000-0000-0000-000000000000');

-- Durable before-image when this transaction is committed. Review it before
-- changing the final ROLLBACK to COMMIT; drop it only under the retention
-- policy after the incident is closed.
create table if not exists public.submission_feedback_backup_20261020
  as select s.id, s.results, now() as backed_up_at
     from public.submissions s
     join remediation_targets t on t.id = s.id
     where false;
insert into public.submission_feedback_backup_20261020 (id, results, backed_up_at)
select s.id, s.results, now()
from public.submissions s
join remediation_targets t on t.id = s.id
where not exists (
  select 1 from public.submission_feedback_backup_20261020 b where b.id = s.id
);

-- Preview: one row per target, with the number of result objects that would be
-- redacted. This is the review gate before the UPDATE below.
with expanded as (
  select s.id, item,
         exists (
           select 1
           from jsonb_array_elements_text(coalesce(p.samples, '[]'::jsonb)) as sample(name)
           where sample.name = item->>'test'
         ) as is_public
  from public.submissions s
  join remediation_targets t on t.id = s.id
  left join public.problems p on p.slug = s.problem
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(s.results) = 'array' then s.results else '[]'::jsonb end
  ) as item
)
select id, count(*) filter (where is_public is not true) as result_objects_to_redact
from expanded
group by id
order by id;

-- Redact non-current-sample result objects only for the explicit targets.
with redacted as (
  select s.id,
         coalesce(
           jsonb_agg(
             case
               when exists (
                      select 1
                      from jsonb_array_elements_text(coalesce(p.samples, '[]'::jsonb)) as sample(name)
                      where sample.name = item->>'test'
                    ) is true
                 then item
               else (
                 item
                 - 'input' - 'expected' - 'actual' - 'diff'
                 - 'stdout' - 'stderr' - 'detail' - 'practice_feedback'
               ) || '{"hidden": true}'::jsonb
             end
             order by ordinality
           ),
           '[]'::jsonb
         ) as results
  from public.submissions s
  join remediation_targets t on t.id = s.id
  left join public.problems p on p.slug = s.problem
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(s.results) = 'array' then s.results else '[]'::jsonb end
  ) with ordinality as expanded(item, ordinality)
  group by s.id
)
update public.submissions s
set results = r.results
from redacted r
where s.id = r.id;

-- Post-update verification: no target row may still carry test-data fields in
-- a result object that is not a current sample. This intentionally fails the
-- transaction if the redaction logic or fixture is wrong.
do $$
declare
  remaining integer;
begin
  with expanded as (
    select s.id, item,
           exists (
             select 1
             from jsonb_array_elements_text(coalesce(p.samples, '[]'::jsonb)) as sample(name)
             where sample.name = item->>'test'
           ) as is_public
    from public.submissions s
    join remediation_targets t on t.id = s.id
    left join public.problems p on p.slug = s.problem
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(s.results) = 'array' then s.results else '[]'::jsonb end
    ) as item
  )
  select count(*) into remaining
  from expanded
  where is_public is not true
    and (
      coalesce(length(item->>'input'), 0) > 0
      or coalesce(length(item->>'expected'), 0) > 0
      or coalesce(length(item->>'actual'), 0) > 0
      or coalesce(length(item->>'diff'), 0) > 0
      or coalesce(length(item->>'stdout'), 0) > 0
      or coalesce(length(item->>'stderr'), 0) > 0
      or coalesce(length(item->>'detail'), 0) > 0
    );
  if remaining <> 0 then
    raise exception 'remediation verification found % non-public result objects with test data', remaining;
  end if;
end $$;

-- REVIEW GATE: keep rollback until the preview, backup and application read
-- checks are approved. Replace with COMMIT only in the approved window.
rollback;
