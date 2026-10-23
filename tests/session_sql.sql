-- Synthetic only. Never target production. Run after schema.sql twice.
begin;
do $$ begin
  if current_database() <> 'newbiegrader_test' then
    raise exception 'REFUSED: expected disposable newbiegrader_test';
  end if;
end $$;
set local role service_role;
insert into public.users(email,name,password_hash,email_verified_at,auth_version)
 values ('session-sql@example.invalid','Synthetic','pbkdf2$synthetic',clock_timestamp(),1);
do $$
declare
  result_ jsonb; before_ timestamptz; after_ timestamptz; rejected_ boolean;
  email_ text := 'session-sql@example.invalid';
begin
  result_ := public.auth_session_start(repeat('a',64),email_,1,true,false,'password','',array[]::text[]);
  if result_->>'valid'<>'true' then raise exception 'session creation failed'; end if;
  perform public.auth_session_start(repeat('b',64),email_,1,true,false,'password','',array[]::text[]);
  if public.auth_session_identity(repeat('a',64),'remember',array[]::text[])->>'valid'<>'true' then
    raise exception 'remember session rejected'; end if;
  select expires_at into before_ from public.web_sessions where token_hash=repeat('a',64);
  for i in 1..20 loop
    result_ := public.auth_session_identity(repeat('a',64),'session',array[]::text[]);
    if result_->'user'->>'email'<>email_ then raise exception 'wrong identity'; end if;
  end loop;
  select expires_at into after_ from public.web_sessions where token_hash=repeat('a',64);
  if after_ is distinct from before_ then raise exception 'hot path rewrites sessions'; end if;
  perform public.auth_session_revoke(array[repeat('a',64)]);
  perform public.auth_session_revoke(array[repeat('a',64)]);
  if public.auth_session_identity(repeat('a',64),'session',array[]::text[])->>'valid'<>'false'
     or public.auth_session_identity(repeat('a',64),'remember',array[]::text[])->>'valid'<>'false' then
    raise exception 'revoked session resurrected'; end if;
  if public.auth_session_identity(repeat('b',64),'session',array[]::text[])->>'valid'<>'true' then
    raise exception 'another device was revoked'; end if;
  perform public.auth_session_start(repeat('c',64),email_,1,true,true,'google','',array[]::text[]);
  if public.auth_session_identity(repeat('c',64),'session',array[]::text[])->>'valid'<>'false' then
    raise exception 'pending OAuth authenticated early'; end if;
  result_ := public.auth_session_identity(repeat('c',64),'finish',array[repeat('b',64)]);
  if result_->>'valid'<>'true' then raise exception 'OAuth finish failed'; end if;
  if public.auth_session_identity(repeat('c',64),'finish',array[]::text[])->>'valid'<>'false' then
    raise exception 'OAuth finish replay allowed'; end if;
  if public.auth_session_identity(repeat('b',64),'session',array[]::text[])->>'valid'<>'false' then
    raise exception 'old browser session not replaced'; end if;
  perform public.auth_session_start(repeat('d',64),email_,1,false,false,'password','',array[]::text[]);
  if public.auth_session_identity(repeat('d',64),'remember',array[]::text[])->>'valid'<>'false' then
    raise exception 'remember opt-in bypassed'; end if;
  update public.web_sessions set remember_until=clock_timestamp()-interval '1 second' where token_hash=repeat('c',64);
  if public.auth_session_identity(repeat('c',64),'remember',array[]::text[])->>'valid'<>'false'
     or public.auth_session_identity(repeat('c',64),'session',array[]::text[])->>'valid'<>'true' then
    raise exception 'remember expiry changed normal session policy'; end if;
  update public.web_sessions set expires_at=clock_timestamp()+interval '44 days' where token_hash=repeat('d',64);
  perform public.auth_session_identity(repeat('d',64),'session',array[]::text[]);
  if not exists(select 1 from public.web_sessions where token_hash=repeat('d',64)
                 and expires_at>clock_timestamp()+interval '59 days') then
    raise exception 'active cookie retention not renewed'; end if;
  result_ := public.auth_email_complete(email_,'22222222-2222-4222-8222-222222222222','pbkdf2$replacement','Owner');
  if result_->>'auth_version'<>'2' then raise exception 'credential version not incremented'; end if;
  if public.auth_session_identity(repeat('c',64),'session',array[]::text[])->>'valid'<>'false'
     or public.auth_session_identity(repeat('d',64),'session',array[]::text[])->>'valid'<>'false' then
    raise exception 'password replacement kept old sessions'; end if;
  result_ := public.auth_session_start(repeat('e',64),email_,1,false,false,'password','',array[]::text[]);
  if result_->>'valid'<>'false' then raise exception 'stale password proof issued a new session'; end if;
  rejected_ := false;
  begin
    perform public.auth_session_start('bad',email_,2,false,false,'password','',array[]::text[]);
  exception when others then rejected_ := true; end;
  if not rejected_ then raise exception 'invalid hash accepted'; end if;
end $$;
-- Restoring durable account data must leave the ephemeral session table empty.
delete from public.web_sessions;
do $$ begin
  if public.auth_session_identity(repeat('a',64),'remember',array[]::text[])->>'valid'<>'false' then
    raise exception 'empty session store authenticated a cookie'; end if;
end $$;
-- The indexed cleanup is bounded to 100 rows per login.
insert into public.web_sessions(token_hash,user_email,auth_version,expires_at,activated,provider)
 select lpad(to_hex(i),64,'0'),'session-sql@example.invalid',2,
        clock_timestamp()-interval '1 day',true,'password' from generate_series(1,105) i;
select public.auth_session_start(repeat('f',64),'session-sql@example.invalid',2,false,false,'password','',array[]::text[]);
do $$ begin
  if (select count(*) from public.web_sessions where expires_at<=clock_timestamp())<>5 then
    raise exception 'expired cleanup is not bounded'; end if;
end $$;
rollback;
