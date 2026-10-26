-- 2026-10-26: live request roles and durable admission timestamps.
-- Review, then apply with the maintainer's Supabase SQL Editor before deploying
-- the matching backend. Existing browser sessions and signing key are preserved.
-- No historical timestamp backfill: that requires a separate reviewed plan.
begin;

create or replace function public.auth_session_identity(
  p_token_hash text, p_mode text, p_previous text[]
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  session_ record;
  current_ timestamptz := clock_timestamp();
  claimed_ text;
  db_admin_ boolean := false;
begin
  if p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$'
     or p_mode is null or p_mode not in ('session','remember','finish')
     or p_previous is null or cardinality(p_previous) > 2
     or exists (select 1 from unnest(p_previous) x where x is null or x !~ '^[0-9a-f]{64}$') then
    raise exception 'invalid session parameters';
  end if;
  select s.*,u.name as account_name,u.auth_version as live_version,u.email_verified_at
    into session_ from public.web_sessions s join public.users u on u.email=s.user_email
    where s.token_hash=p_token_hash;
  if not found or session_.revoked_at is not null or session_.expires_at <= current_
     or session_.email_verified_at is null or session_.auth_version <> session_.live_version then
    return jsonb_build_object('valid', false);
  end if;
  if p_mode='finish' then
    if session_.activated or session_.handoff_until is null or session_.handoff_until <= current_ then
      return jsonb_build_object('valid', false);
    end if;
    -- Atomic consumption survives API restarts and concurrent replicas.
    update public.web_sessions set activated=true,handoff_until=null,
        remember_until=case when remember_until is not null then current_ + interval '365 days' end,
        expires_at=case when remember_until is not null then current_ + interval '365 days'
                        else current_ + interval '60 days' end
      where token_hash=p_token_hash and not activated and revoked_at is null
        and handoff_until > clock_timestamp() and expires_at > clock_timestamp()
      returning token_hash into claimed_;
    if not found then return jsonb_build_object('valid', false); end if;
    update public.web_sessions set revoked_at=current_,expires_at=current_
      where token_hash=any(p_previous) and token_hash<>p_token_hash and revoked_at is null;
  else
    if not session_.activated or (p_mode='remember' and
        (session_.remember_until is null or session_.remember_until <= current_)) then
      return jsonb_build_object('valid', false);
    end if;
    -- Cookie signatures still enforce the existing rolling 30-day age. A
    -- 60-day row retention, renewed only below 45 days, cannot expire a valid
    -- 30-day cookie and avoids a DB UPDATE on every authenticated request.
    if session_.expires_at < current_ + interval '45 days' then
      update public.web_sessions set expires_at=current_ + interval '60 days'
        where token_hash=p_token_hash and revoked_at is null
          and expires_at < current_ + interval '45 days';
    end if;
  end if;
  -- One fresh role decision per authorization, never an API-process cache.
  begin
    select exists(select 1 from public.admins where email=session_.user_email) into db_admin_;
  exception when undefined_table or insufficient_privilege then
    db_admin_ := false;
  end;
  return jsonb_build_object('valid',true,'db_admin',db_admin_,'user',jsonb_build_object(
    'email',session_.user_email,'name',coalesce(nullif(session_.account_name,''),session_.user_email),
    'auth_version',session_.live_version,'provider',session_.provider,'picture',session_.picture));
end $$;

create or replace function public.judge_queue_finish(
  p_id uuid,p_worker text,p_attempt integer,p_result jsonb,p_submission jsonb,p_error text
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare v_job public.judge_jobs; v_id uuid; v_sub public.submissions;
begin
  select * into v_job from public.judge_jobs where id=p_id for update;
  if not found or p_worker is null or p_attempt is null
      or v_job.worker_id is distinct from p_worker or v_job.attempt is distinct from p_attempt then
    return jsonb_build_object('applied',false);
  end if;
  if v_job.status in ('done','error') then
    return jsonb_build_object('applied',true,'submission_id',v_job.submission_id);
  end if;
  if v_job.status <> 'running' or v_job.lease_until is null or v_job.lease_until <= now() then
    return jsonb_build_object('applied',false);
  end if;
  -- History and terminal status commit together under the attempt fence.
  if p_submission is not null and coalesce(p_error,'')='' then
    v_sub := jsonb_populate_record(null::public.submissions,p_submission);
    if v_job.target_id is not null then
      update public.submissions set verdict=v_sub.verdict,accepted=v_sub.accepted,
        passed=v_sub.passed,total=v_sub.total,score=v_sub.score,counts=v_sub.counts,
        results=v_sub.results,detail=v_sub.detail,tests_hash=v_sub.tests_hash,
        grader_version=v_sub.grader_version,kind=v_sub.kind,job_id=p_id
        where id=v_job.target_id returning id into v_id;
    else
      insert into public.submissions(created_at,problem,language,filename,name,user_email,verdict,accepted,
        passed,total,score,counts,results,code,detail,tests_hash,grader_version,kind,contest_id,job_id)
      values(v_job.created_at,v_sub.problem,v_sub.language,v_sub.filename,coalesce(v_sub.name,''),coalesce(v_sub.user_email,''),
        v_sub.verdict,coalesce(v_sub.accepted,false),coalesce(v_sub.passed,0),coalesce(v_sub.total,0),
        coalesce(v_sub.score,0),coalesce(v_sub.counts,'{}'::jsonb),coalesce(v_sub.results,'[]'::jsonb),
        coalesce(v_sub.code,''),coalesce(v_sub.detail,''),coalesce(v_sub.tests_hash,''),
        coalesce(v_sub.grader_version,''),coalesce(v_sub.kind,'submit'),v_sub.contest_id,p_id)
      returning id into v_id;
    end if;
  end if;
  update public.judge_jobs set status=case when coalesce(p_error,'')='' then 'done' else 'error' end,
    result=case when p_result is null then null else p_result || jsonb_build_object('id',v_id) end,
    error=coalesce(p_error,''),finished_at=now(),lease_until=null,submission_id=v_id,
    -- The submission row owns the validated source. Terminal jobs need only
    -- the result; retaining source/payload would duplicate user code and
    -- playground input indefinitely in the queue table.
    source='',payload='{}'::jsonb where id=p_id;
  return jsonb_build_object('applied',true,'submission_id',v_id);
end $$;

revoke all on function public.auth_session_identity(text,text,text[]) from public,anon,authenticated;
grant execute on function public.auth_session_identity(text,text,text[]) to service_role;
revoke all on function public.judge_queue_finish(uuid,text,integer,jsonb,jsonb,text) from public,anon,authenticated;
grant execute on function public.judge_queue_finish(uuid,text,integer,jsonb,jsonb,text) to service_role;
notify pgrst,'reload schema';
commit;
