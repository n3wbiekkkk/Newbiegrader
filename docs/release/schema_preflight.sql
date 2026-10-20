-- Read-only schema preflight for Newbiegrader.
--
-- Run in the Supabase SQL Editor (or psql) BEFORE deploying the backend.
-- Every query is SELECT-only. Empty result sets mean the requirement is met;
-- a returned row is a blocking omission. Do not use this file to repair a
-- production schema.
--
-- The operator should record the output with the release/change ticket.

-- 1. Required tables.
with required(table_name) as (
  values ('submissions'), ('profiles'), ('reports'), ('users'), ('judge_jobs'),
         ('contests'), ('contest_registrations'), ('contest_announcements'),
         ('judge_quota_events'), ('problems'), ('auth_rate_buckets')
)
select r.table_name as missing_table
from required r
left join information_schema.tables t
  on t.table_schema = 'public' and t.table_name = r.table_name
 and t.table_type = 'BASE TABLE'
where t.table_name is null
order by r.table_name;

-- 2. Required submission traceability columns.
with required(column_name) as (
  values ('name'), ('user_email'), ('tests_hash'), ('grader_version'),
         ('kind'), ('contest_id'), ('job_id')
)
select r.column_name as missing_submissions_column
from required r
left join information_schema.columns c
  on c.table_schema = 'public' and c.table_name = 'submissions'
 and c.column_name = r.column_name
where c.column_name is null
order by r.column_name;

-- 3. Required queue columns.
with required(column_name) as (
  values ('payload'), ('track_active'), ('worker_id'), ('attempt'),
         ('lease_until'), ('submission_id'), ('target_id'), ('reveal'),
         ('tests_hash'), ('grader_version')
)
select r.column_name as missing_judge_jobs_column
from required r
left join information_schema.columns c
  on c.table_schema = 'public' and c.table_name = 'judge_jobs'
 and c.column_name = r.column_name
where c.column_name is null
order by r.column_name;

-- 4. Required queue/security functions. `service_role` must have EXECUTE and
-- anon/authenticated must not.
with required(function_name, argument_types) as (
  values
    ('judge_queue_admit', 'jsonb,integer,boolean,integer,integer'),
    ('judge_queue_claim', 'text,integer'),
    ('judge_queue_heartbeat', 'uuid,text,integer,integer'),
    ('judge_queue_finish', 'uuid,text,integer,jsonb,jsonb,text'),
    ('judge_queue_diagnostics', ''),
    ('auth_email_budget', 'text,text,text'),
    ('auth_email_complete', 'text,uuid,text,text'),
    ('auth_google_identity', 'text,text,text')
)
select r.function_name as missing_function
from required r
where not exists (
  select 1 from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname = r.function_name
);

-- 5. RLS must be enabled on every public application table.
select c.relname as table_without_rls
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
  and c.relname in ('submissions','profiles','reports','users','judge_jobs',
                    'contests','contest_registrations','contest_announcements',
                    'judge_quota_events','problems','auth_rate_buckets')
  and not c.relrowsecurity
order by c.relname;

-- 6. Public browser roles must not have direct table privileges.
select grantee, table_name, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon','authenticated')
  and table_name in ('submissions','profiles','reports','users','judge_jobs',
                     'contests','contest_registrations','contest_announcements',
                     'judge_quota_events','problems','auth_rate_buckets',
                     'leaderboard_scores','problem_stats')
order by grantee, table_name, privilege_type;

-- 7. Queue/security function execution must be service_role-only.
select p.proname as function_name, r.rolname as unexpected_grantee
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
cross join (values ('anon'), ('authenticated')) as browser(rolname)
join pg_roles r on r.rolname = browser.rolname
where n.nspname = 'public'
  and p.proname in ('judge_queue_admit','judge_queue_claim',
                    'judge_queue_heartbeat','judge_queue_finish',
                    'judge_queue_diagnostics',
                    'auth_email_budget','auth_email_complete','auth_google_identity')
  and has_function_privilege(r.oid, p.oid, 'EXECUTE')
order by p.proname, r.rolname;

-- 8. Both aggregate views must enforce the caller's RLS, not the creator's.
select c.relname as view_bypassing_rls
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'v'
  and c.relname in ('leaderboard_scores','problem_stats')
  and not coalesce('security_invoker=true' = any(c.reloptions), false);
