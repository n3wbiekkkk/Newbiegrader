-- 2026-10-23: revocable browser sessions. Apply through Supabase SQL Editor.
-- This standalone patch is the identical trailing block of schema.sql.
-- Existing cookies without a session token are rejected by the new API.
-- Session rows are ephemeral: do not export/restore them with account data.
begin;
create table if not exists public.web_sessions (
  token_hash text primary key check (token_hash ~ '^[0-9a-f]{64}$'),
  user_email text not null references public.users(email) on delete cascade,
  auth_version bigint not null check (auth_version > 0),
  created_at timestamptz not null default clock_timestamp(),
  expires_at timestamptz not null,
  remember_until timestamptz,
  activated boolean not null,
  handoff_until timestamptz,
  provider text not null check (provider in ('google', 'password')),
  picture text not null default '' check (length(picture) <= 2048),
  revoked_at timestamptz
);
create index if not exists web_sessions_expiry on public.web_sessions(expires_at);
create index if not exists web_sessions_user on public.web_sessions(user_email);
alter table public.web_sessions enable row level security;
revoke all on public.web_sessions from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.web_sessions to service_role;

create or replace function public.auth_session_start(
  p_token_hash text, p_email text, p_auth_version bigint,
  p_remember boolean, p_pending boolean, p_provider text, p_picture text,
  p_previous text[]
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  account_ public.users%rowtype;
  current_ timestamptz := clock_timestamp();
  remember_ timestamptz;
begin
  if p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$'
     or p_remember is null or p_pending is null
     or p_provider is null or p_provider not in ('google','password')
     or p_picture is null or length(p_picture) > 2048
     or p_previous is null or cardinality(p_previous) > 2
     or exists (select 1 from unnest(p_previous) x where x is null or x !~ '^[0-9a-f]{64}$')
     or p_token_hash = any(p_previous) then
    raise exception 'invalid session parameters';
  end if;
  -- Serialize credential replacement with creation, not all user requests.
  select * into account_ from public.users where email = p_email for share;
  if not found or account_.email_verified_at is null
     or account_.auth_version is distinct from p_auth_version then
    return jsonb_build_object('valid', false);
  end if;
  if p_remember then remember_ := current_ + interval '365 days'; end if;
  update public.web_sessions set revoked_at = current_, expires_at = current_
    where token_hash = any(p_previous) and revoked_at is null;
  -- Indexed, bounded cleanup on login. No periodic job or write on each poll.
  delete from public.web_sessions where token_hash in (
    select token_hash from public.web_sessions where expires_at <= current_
      order by expires_at limit 100 for update skip locked);
  insert into public.web_sessions(token_hash,user_email,auth_version,expires_at,
      remember_until,activated,handoff_until,provider,picture)
    values (p_token_hash,p_email,p_auth_version,
      case when p_pending then current_ + interval '5 minutes'
           else greatest(current_ + interval '60 days', remember_) end,
      remember_,not p_pending,
      case when p_pending then current_ + interval '5 minutes' else null end,
      p_provider,p_picture);
  return jsonb_build_object('valid', true);
end $$;

create or replace function public.auth_session_identity(
  p_token_hash text, p_mode text, p_previous text[]
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  session_ record;
  current_ timestamptz := clock_timestamp();
  claimed_ text;
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
  return jsonb_build_object('valid',true,'user',jsonb_build_object(
    'email',session_.user_email,'name',coalesce(nullif(session_.account_name,''),session_.user_email),
    'auth_version',session_.live_version,'provider',session_.provider,'picture',session_.picture));
end $$;

create or replace function public.auth_session_revoke(p_token_hashes text[])
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare current_ timestamptz := clock_timestamp();
begin
  if p_token_hashes is null or cardinality(p_token_hashes)>2
     or exists (select 1 from unnest(p_token_hashes) x where x is null or x !~ '^[0-9a-f]{64}$') then
    raise exception 'invalid session parameters';
  end if;
  update public.web_sessions set revoked_at=current_,expires_at=current_
    where token_hash=any(p_token_hashes) and revoked_at is null;
  return jsonb_build_object('ok',true);
end $$;

revoke all on function public.auth_session_start(text,text,bigint,boolean,boolean,text,text,text[]) from public,anon,authenticated;
revoke all on function public.auth_session_identity(text,text,text[]) from public,anon,authenticated;
revoke all on function public.auth_session_revoke(text[]) from public,anon,authenticated;
grant execute on function public.auth_session_start(text,text,bigint,boolean,boolean,text,text,text[]) to service_role;
grant execute on function public.auth_session_identity(text,text,text[]) to service_role;
grant execute on function public.auth_session_revoke(text[]) to service_role;
notify pgrst, 'reload schema';
commit;
