-- Account lifecycle: backend-only, append-only; maintainer review required.
begin;
create table if not exists public.account_deletion_blocks (
 email_hash text primary key, requested_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '90 days'
);
create table if not exists public.account_deletion_work (
 email text primary key, auth_subject uuid, requested_at timestamptz not null default now()
);
create table if not exists public.account_audit (
 id uuid primary key default gen_random_uuid(), created_at timestamptz not null default now(),
 event text not null, counts jsonb not null default '{}'::jsonb
);
create table if not exists public.account_privacy_salt (
 singleton boolean primary key default true check(singleton), salt text not null
);
insert into public.account_privacy_salt values(true,gen_random_uuid()::text) on conflict do nothing;
alter table public.account_deletion_blocks enable row level security;
revoke all on public.account_deletion_blocks from public,anon,authenticated,service_role;
grant select,insert,update,delete on public.account_deletion_blocks to service_role;
alter table public.account_deletion_work enable row level security;
revoke all on public.account_deletion_work from public,anon,authenticated,service_role;
grant select,insert,update,delete on public.account_deletion_work to service_role;
alter table public.account_audit enable row level security;
revoke all on public.account_audit from public,anon,authenticated,service_role;
grant select,insert,update,delete on public.account_audit to service_role;
alter table public.account_privacy_salt enable row level security;
revoke all on public.account_privacy_salt from public,anon,authenticated,service_role;
grant select on public.account_privacy_salt to service_role;

create or replace function public.account_email_hash(p_email text) returns text
language sql security invoker set search_path='' as $$
 select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(salt||lower(btrim(p_email)),'UTF8')),'hex') from public.account_privacy_salt where singleton;
$$;
create or replace function public.account_is_deleted(p_email text) returns boolean
language sql security invoker set search_path='' as $$
 select exists(select 1 from public.account_deletion_blocks where email_hash=public.account_email_hash(p_email) and expires_at>now())
 or exists(select 1 from public.account_deletion_work where email=p_email);
$$;
create or replace function public.account_auth_allowed(p_email text) returns jsonb
language sql security invoker set search_path='' as $$
 select jsonb_build_object('allowed',not public.account_is_deleted(p_email));
$$;
create or replace function public.account_delete_begin(p_email text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare u public.users%rowtype;
begin
 perform pg_catalog.pg_advisory_xact_lock(64723487231);
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('identity:'||p_email));
 select * into u from public.users where email=p_email for update;
 if not found then return jsonb_build_object('error','account missing'); end if;
 if exists(select 1 from public.judge_jobs where user_email=p_email and (status in ('queued','running') or lease_until>now())) then
  return jsonb_build_object('busy',true);
 end if;
 insert into public.account_deletion_blocks(email_hash) values(public.account_email_hash(p_email)) on conflict do nothing;
 insert into public.account_deletion_work(email,auth_subject) values(p_email,u.email_auth_subject) on conflict do nothing;
 update public.users set auth_version=auth_version+1,password_hash='',email_verified_at=null,google_subject=null where email=p_email;
 update public.web_sessions set revoked_at=clock_timestamp() where user_email=p_email;
 return jsonb_build_object('auth_subject',u.email_auth_subject,'pending',true);
end $$;
create or replace function public.account_delete_finish(p_email text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare counts_ jsonb:='{}'; n bigint; t text;
begin
 perform pg_catalog.pg_advisory_xact_lock(64723487231);
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('identity:'||p_email));
 if not exists(select 1 from public.account_deletion_work where email=p_email) then
  if public.account_is_deleted(p_email) and not exists(select 1 from public.users where email=p_email) then
   return jsonb_build_object('ok',true);
  end if;
  raise exception 'deletion not prepared';
 end if;
 if exists(select 1 from public.judge_jobs where user_email=p_email and (status in ('queued','running') or lease_until>now())) then raise exception 'live job'; end if;
 foreach t in array array['submissions','profiles','judge_jobs','judge_quota_events','contest_registrations','reports','web_sessions'] loop
  execute format('delete from public.%I where user_email=$1',t) using p_email;
  get diagnostics n=row_count; counts_:=counts_||jsonb_build_object(t,n);
 end loop;
 update public.contests set created_by='' where created_by=p_email;
 update public.contest_announcements set created_by='' where created_by=p_email;
 update public.admins set created_by='' where created_by=p_email;
 delete from public.admins where email=p_email;
 delete from public.users where email=p_email;
 delete from public.account_deletion_work where email=p_email;
 insert into public.account_audit(event,counts) values('account_deleted',counts_);
 return jsonb_build_object('ok',true);
end $$;

create or replace function public.auth_email_complete(
  p_email text, p_subject uuid, p_password_hash text, p_name text
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare
  account_ public.users%rowtype;
begin
  if p_email is null or p_email <> lower(btrim(p_email)) or length(p_email) > 254
     or p_subject is null or p_password_hash not like 'pbkdf2$%' then
    raise exception 'invalid verified identity';
  end if;
  perform pg_advisory_xact_lock(hashtext('identity:' || p_email));
  if public.account_is_deleted(p_email) then raise exception 'account deleted'; end if;
  select * into account_ from public.users where email = p_email for update;
  if found and account_.email_auth_subject is not null and account_.email_auth_subject <> p_subject then
    raise exception 'identity subject mismatch';
  end if;
  insert into public.users as u(email, name, password_hash, email_verified_at, email_auth_subject, auth_version)
    values (p_email, left(p_name, 50), p_password_hash, clock_timestamp(), p_subject, 1)
  on conflict (email) do update set name = excluded.name, password_hash = excluded.password_hash,
    email_verified_at = excluded.email_verified_at, email_auth_subject = excluded.email_auth_subject,
    auth_version = u.auth_version + 1
  returning * into account_;
  return jsonb_build_object('email', account_.email, 'name', account_.name,
                           'auth_version', account_.auth_version);
end $$;

create or replace function public.auth_google_identity(
  p_email text, p_subject text, p_name text
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare
  account_ public.users%rowtype;
begin
  if p_email is null or p_email <> lower(btrim(p_email)) or p_subject is null
     or length(p_subject) not between 1 and 255 then
    raise exception 'invalid google identity';
  end if;
  perform pg_advisory_xact_lock(hashtext('identity:' || p_email));
  if public.account_is_deleted(p_email) then raise exception 'account deleted'; end if;
  select * into account_ from public.users where email = p_email for update;
  if found and account_.email_verified_at is not null then
    if account_.google_subject is distinct from p_subject then
      return jsonb_build_object('link_required', true);
    end if;
  else
    insert into public.users as u(email, name, password_hash, email_verified_at, google_subject, auth_version)
      values (p_email, left(p_name, 50), '', clock_timestamp(), p_subject, 1)
    on conflict (email) do update set name = excluded.name, password_hash = '',
      email_verified_at = excluded.email_verified_at, google_subject = excluded.google_subject,
      auth_version = u.auth_version + 1
    returning * into account_;
  end if;
  return jsonb_build_object('email', account_.email, 'name', account_.name,
                           'auth_version', account_.auth_version);
end $$;

create or replace function public.judge_queue_admit(
  p_job jsonb, p_queue_max integer, p_track_active boolean,
  p_quota_limit integer, p_quota_window integer
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare v_job public.judge_jobs; v_email text := coalesce(p_job->>'user_email', '');
  v_kind text := coalesce(p_job->>'kind', 'submit'); v_quota_kind text;
  v_first timestamptz; v_count integer;
begin
  -- Serialize admission across API replicas: queue and account checks plus insert
  -- form one transaction. A check in Python cannot provide this guarantee.
  perform pg_advisory_xact_lock(64723487231);
  if public.account_is_deleted(v_email) then return jsonb_build_object('error','account deleted','status_code',403); end if;
  if p_track_active and v_email <> '' and exists (
    select 1 from public.judge_jobs where user_email=v_email and track_active
      and status in ('queued','running')
  ) then
    return jsonb_build_object('error','you already have a submission judging, please wait','status_code',409);
  end if;
  if (select count(*) from public.judge_jobs where status='queued') >= p_queue_max then
    return jsonb_build_object('error','judge queue is full — try again in a moment','status_code',503,'retry_after',30);
  end if;
  v_quota_kind := case when v_kind='playground' then 'run' else 'submit' end;
  if p_quota_limit > 0 and p_quota_window > 0 and v_email <> '' then
    delete from public.judge_quota_events where admitted_at < now() - interval '7 days';
    select count(*), min(admitted_at) into v_count, v_first from public.judge_quota_events
      where user_email=v_email and kind=v_quota_kind
        and admitted_at > now() - make_interval(secs => p_quota_window);
    if v_count >= p_quota_limit then
      return jsonb_build_object('error','quota exceeded','status_code',429,
        'retry_after',greatest(1,ceil(extract(epoch from v_first + make_interval(secs => p_quota_window)-now()))::integer));
    end if;
    insert into public.judge_quota_events(user_email,kind) values(v_email,v_quota_kind);
  end if;
  insert into public.judge_jobs (id,kind,user_email,name,problem,language,filename,contest_id,
      source,target_id,reveal,tests_hash,grader_version,payload,track_active)
    values(coalesce((p_job->>'id')::uuid,gen_random_uuid()),v_kind,v_email,
      coalesce(p_job->>'name',''),coalesce(p_job->>'problem',''),coalesce(p_job->>'language',''),
      p_job->>'filename',p_job->>'contest_id',coalesce(p_job->>'source',''),
      (p_job->>'target_id')::uuid,coalesce(p_job->>'reveal','samples'),
      coalesce(p_job->>'tests_hash',''),coalesce(p_job->>'grader_version',''),
      coalesce(p_job->'payload','{}'::jsonb),p_track_active)
    returning * into v_job;
  return jsonb_build_object('job',to_jsonb(v_job));
end $$;
revoke all on function public.account_email_hash(text) from public,anon,authenticated;
grant execute on function public.account_email_hash(text) to service_role;
revoke all on function public.account_is_deleted(text) from public,anon,authenticated;
grant execute on function public.account_is_deleted(text) to service_role;
revoke all on function public.account_delete_begin(text) from public,anon,authenticated;
grant execute on function public.account_delete_begin(text) to service_role;
revoke all on function public.account_delete_finish(text) from public,anon,authenticated;
grant execute on function public.account_delete_finish(text) to service_role;
create or replace function public.account_retention_prune() returns jsonb
language plpgsql security invoker set search_path='' as $$
declare n bigint; count_ jsonb:='{}';
begin
 delete from public.judge_jobs where created_at < now()-interval '1 year'
  and status not in ('queued','running') and (lease_until is null or lease_until<=now());
 get diagnostics n=row_count; count_:=jsonb_build_object('jobs',n);
 delete from public.submissions s where created_at < now()-interval '1 year'
  and not exists(select 1 from public.judge_jobs j where (j.target_id=s.id or j.id=s.job_id)
   and (j.status in ('queued','running') or j.lease_until>now()));
 get diagnostics n=row_count; count_:=count_||jsonb_build_object('submissions',n);
 delete from public.reports where created_at < now()-interval '1 year';
 delete from public.account_audit where created_at < now()-interval '90 days';
 delete from public.account_deletion_blocks b where expires_at<=now()
  and not exists(select 1 from public.account_deletion_work w where public.account_email_hash(w.email)=b.email_hash);
 return count_;
end $$;
revoke all on function public.account_retention_prune() from public,anon,authenticated;
grant execute on function public.account_retention_prune() to service_role;
revoke all on function public.account_auth_allowed(text) from public,anon,authenticated;
grant execute on function public.account_auth_allowed(text) to service_role;
notify pgrst,'reload schema';
commit;
