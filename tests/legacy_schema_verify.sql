-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Copyright (C) 2026 Newbiegrader contributors
-- Assertions after applying supabase/schema.sql twice to tests/legacy_schema.sql.
-- Run in the disposable legacy database from the queue-sql CI job.
do $$
declare
  expected text[] := array['name','user_email','tests_hash','grader_version',
                          'kind','contest_id','job_id'];
  wanted text;
  legacy_count int;
  traceability record;
  role_name text;
  privilege_name text;
begin
  foreach wanted in array expected loop
    if not exists (
      select 1 from information_schema.columns c
      where c.table_schema = 'public' and c.table_name = 'submissions'
        and c.column_name = wanted
    ) then
      raise exception 'submissions.% was not added by the migration', wanted;
    end if;
  end loop;

  select count(*) into legacy_count from public.submissions
  where problem = 'legacy_problem';
  if legacy_count <> 1 then
    raise exception 'legacy submission row was lost';
  end if;

  select kind, contest_id, job_id, tests_hash, grader_version
    into traceability
  from public.submissions where problem = 'legacy_problem';
  if traceability.kind is distinct from 'submit'
     or traceability.contest_id is not null
     or traceability.job_id is not null
     or traceability.tests_hash is distinct from ''
     or traceability.grader_version is distinct from '' then
    raise exception 'legacy row defaults are unsafe: %', to_jsonb(traceability);
  end if;

  if not exists (select 1 from pg_proc where proname = 'judge_queue_admit')
     or not exists (select 1 from pg_proc where proname = 'judge_queue_finish') then
    raise exception 'queue RPCs missing after migration';
  end if;

  if not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'admins'
      and c.relkind = 'r' and c.relrowsecurity
  ) then
    raise exception 'database admins table is missing or has RLS disabled';
  end if;
  if has_table_privilege('anon', 'public.admins', 'select,insert,update,delete')
     or has_table_privilege('authenticated', 'public.admins', 'select,insert,update,delete') then
    raise exception 'a browser role has direct access to database admins';
  end if;
  if not has_table_privilege('service_role', 'public.admins', 'select,insert,update,delete') then
    raise exception 'service_role cannot manage database admins';
  end if;
end $$;
