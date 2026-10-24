-- Disposable PostgreSQL only. Fixtures contain no real identities or test data.
begin;
insert into public.users(email,name,password_hash,email_verified_at,email_auth_subject,auth_version)
values ('erase@example.invalid','Synthetic','pbkdf2$synthetic',now(),'00000000-0000-0000-0000-000000000001',1);
insert into public.web_sessions(token_hash,user_email,auth_version,expires_at,activated,provider)
values (repeat('a',64),'erase@example.invalid',1,now()+interval '1 day',true,'password'),
       (repeat('b',64),'erase@example.invalid',1,now()+interval '1 day',true,'password');
insert into public.submissions(problem,language,user_email,verdict,code,results) values('synthetic','python','erase@example.invalid','AC','PRIVATE_SOURCE','[{"expected":"PRIVATE_TEST"}]');
insert into public.profiles(user_email) values('erase@example.invalid');
insert into public.reports(problem,user_email,message) values('synthetic','erase@example.invalid','PRIVATE_REPORT');
insert into public.judge_quota_events(user_email,kind) values('erase@example.invalid','submit');
set local role service_role;
do $$ declare r jsonb;
begin
 r:=public.account_delete_begin('erase@example.invalid');
 if not (r->>'pending')::boolean then raise exception 'not prepared'; end if;
 if exists(select 1 from public.web_sessions where user_email='erase@example.invalid' and revoked_at is null) then raise exception 'other session not revoked'; end if;
 if (public.auth_session_identity(repeat('a',64),'session',array[]::text[])->>'valid')::boolean then raise exception 'old session authorized'; end if;
 if not public.account_is_deleted('erase@example.invalid') then raise exception 'identity not blocked'; end if;
 begin
  perform public.auth_google_identity('erase@example.invalid','google-old','Old');
  raise exception 'google recreated deleted account';
 exception when raise_exception then
  if sqlerrm='google recreated deleted account' then raise; end if;
 end;
 begin
  perform public.auth_email_complete('erase@example.invalid','00000000-0000-0000-0000-000000000001','pbkdf2$old-proof','Old');
  raise exception 'old OTP recreated account';
 exception when raise_exception then
  if sqlerrm='old OTP recreated account' then raise; end if;
 end;
 r:=public.judge_queue_admit('{"user_email":"erase@example.invalid","kind":"submit"}',50,true,10,60);
 if r->>'status_code'<>'403' then raise exception 'admission race'; end if;
 r:=public.account_delete_finish('erase@example.invalid');
 if not (r->>'ok')::boolean then raise exception 'finish failed'; end if;
 if exists(select 1 from public.users where email='erase@example.invalid') or exists(select 1 from public.submissions where user_email='erase@example.invalid') or exists(select 1 from public.web_sessions where user_email='erase@example.invalid') then raise exception 'personal data survived'; end if;
 if not exists(select 1 from public.account_audit where event='account_deleted' and (counts->>'submissions')::int=1) then raise exception 'audit lost'; end if;
 if exists(select 1 from public.account_audit where to_jsonb(account_audit)::text like '%erase@example.invalid%') then raise exception 'audit leaks email'; end if;
end $$;
reset role;
do $$ begin
 if has_table_privilege('anon','public.account_audit','select') or has_function_privilege('authenticated','public.account_delete_begin(text)','execute') then raise exception 'public privilege leak'; end if;
end $$;
rollback;

begin;
insert into public.users(email,name,password_hash,email_verified_at,auth_version)
values('busy@example.invalid','Busy','pbkdf2$synthetic',now(),1);
insert into public.judge_jobs(problem,language,user_email,status,lease_until)
values('synthetic','python','busy@example.invalid','done',now()+interval '1 hour');
set local role service_role;
do $$ declare r jsonb; begin
 r:=public.account_delete_begin('busy@example.invalid');
 if not (r->>'busy')::boolean then raise exception 'live lease ignored'; end if;
 if exists(select 1 from public.account_deletion_work where email='busy@example.invalid') then raise exception 'busy account revoked'; end if;
end $$;
reset role;
insert into public.submissions(problem,language,user_email,verdict,created_at,code)
values('old','python','retention@example.invalid','AC',now()-interval '367 days','OLD_SOURCE'),
      ('recent','python','retention@example.invalid','AC',now()-interval '364 days','RECENT_SOURCE');
insert into public.judge_jobs(problem,language,status,created_at,source)
values('old','python','done',now()-interval '367 days','OLD_SOURCE'),
      ('recent','python','done',now()-interval '364 days','RECENT_SOURCE'),
      ('active','python','running',now()-interval '367 days','ACTIVE_SOURCE');
insert into public.account_audit(event,created_at) values('expired',now()-interval '91 days'),('recent',now()-interval '89 days');
set local role service_role;
select public.account_retention_prune();
do $$ begin
 if exists(select 1 from public.submissions where user_email='retention@example.invalid' and problem='old') then raise exception 'old source retained'; end if;
 if not exists(select 1 from public.submissions where user_email='retention@example.invalid' and problem='recent') then raise exception 'recent source deleted'; end if;
 if exists(select 1 from public.judge_jobs where problem='old') then raise exception 'old job source retained'; end if;
 if not exists(select 1 from public.judge_jobs where problem='active') then raise exception 'active job deleted'; end if;
 if exists(select 1 from public.account_audit where event='expired') or not exists(select 1 from public.account_audit where event='recent') then raise exception 'audit age incorrect'; end if;
end $$;
reset role;
rollback;
