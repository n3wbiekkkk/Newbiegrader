-- Post-migration assertions for Newbiegrader.
--
-- Run AFTER applying supabase/schema.sql (twice for idempotence) in the
-- disposable or authorized maintenance window. This file only reads
-- catalogs/privileges and raises exceptions on unsafe omissions. It does not
-- mutate application data.
do $$
declare
  required_columns text[] := array[
    'tests_hash','grader_version','kind','contest_id','job_id'
  ];
  wanted text;
  app_table text;
  queue_function text;
  bad_grantee text;
  bad_view text;
begin
  foreach wanted in array required_columns loop
    if not exists (
      select 1 from information_schema.columns c
      where c.table_schema = 'public' and c.table_name = 'submissions'
        and c.column_name = wanted
    ) then
      raise exception 'submissions.% is missing; run supabase/schema.sql', wanted;
    end if;
  end loop;

  foreach app_table in array array[
    'submissions','profiles','reports','users','judge_jobs','contests',
    'contest_registrations','contest_announcements','judge_quota_events',
    'problems','auth_rate_buckets','admins'
  ] loop
    if not exists (
      select 1 from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = app_table
        and c.relkind = 'r' and c.relrowsecurity
    ) then
      raise exception '% is missing or has RLS disabled', app_table;
    end if;
  end loop;

  foreach queue_function in array array[
    'judge_queue_admit','judge_queue_claim','judge_queue_heartbeat',
    'judge_queue_finish','judge_queue_diagnostics',
    'auth_email_budget','auth_email_complete','auth_google_identity'
  ] loop
    if not exists (
      select 1 from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public' and p.proname = queue_function
    ) then
      raise exception '% is missing; queue/auth migration was not applied', queue_function;
    end if;
  end loop;

  foreach bad_grantee in array array['anon','authenticated'] loop
    if exists (
      select 1 from information_schema.role_table_grants g
      where g.table_schema = 'public' and g.grantee = bad_grantee
        and g.table_name in ('submissions','profiles','reports','users',
          'judge_jobs','contests','contest_registrations','contest_announcements',
          'judge_quota_events','problems','auth_rate_buckets','admins',
          'leaderboard_scores','problem_stats')
        and g.privilege_type in ('SELECT','INSERT','UPDATE','DELETE')
    ) then
      raise exception '% has a direct table grant; revoke it', bad_grantee;
    end if;
  end loop;

  foreach bad_view in array array['leaderboard_scores','problem_stats'] loop
    if not exists (
      select 1 from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = bad_view
        and coalesce('security_invoker=true' = any(c.reloptions), false)
    ) then
      raise exception '% is missing or bypasses caller RLS', bad_view;
    end if;
  end loop;
end $$;
