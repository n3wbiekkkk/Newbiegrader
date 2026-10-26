-- Only disposable PostgreSQL. Existing sessions survive migration; roles stay live.
begin;
set local role service_role;
do $test$
declare email_ text:='live-role-sql@example.invalid'; hash_ text:=repeat('a',64);
 result_ jsonb; job_ uuid:=gen_random_uuid(); sid_ uuid; admitted_ timestamptz:=now()-interval '20 minutes';
 original_ timestamptz;
begin
 insert into public.users(email,name,password_hash,email_verified_at,auth_version)
 values(email_,'Synthetic','',now(),1);
 result_:=public.auth_session_start(hash_,email_,1,false,false,'password','',array[]::text[]);
 if result_->>'valid'<>'true' then raise exception 'session creation failed'; end if;
 result_:=public.auth_session_identity(hash_,'session',array[]::text[]);
 if result_->>'db_admin'<>'false' then raise exception 'ordinary user has admin'; end if;
 insert into public.admins(email) values(email_);
 result_:=public.auth_session_identity(hash_,'session',array[]::text[]);
 if result_->>'db_admin'<>'true' then raise exception 'existing session did not observe grant'; end if;
 delete from public.admins where email=email_;
 result_:=public.auth_session_identity(hash_,'session',array[]::text[]);
 if result_->>'valid'<>'true' or result_->>'db_admin'<>'false' then
  raise exception 'revocation is stale or revoked ordinary session';
 end if;

 insert into public.judge_jobs(id,kind,user_email,problem,language,status,worker_id,attempt,lease_until,created_at)
 values(job_,'submit',email_,'synthetic','c','running','time-worker',1,now()+interval '5 minutes',admitted_);
 result_:=public.judge_queue_finish(job_,'time-worker',1,'{}',
  jsonb_build_object('problem','synthetic','language','c','user_email',email_,
   'verdict','AC','accepted',true,'score',100,'created_at',now()+interval '1 day'),'');
 sid_:=(result_->>'submission_id')::uuid;
 select created_at into original_ from public.submissions where id=sid_;
 if original_ is distinct from admitted_ then raise exception 'history did not use DB admission timestamp'; end if;
 -- Freeze at ten minutes ago: a job sent twenty minutes ago must count even
 -- though the worker only finished now. A caller cannot forge its timestamp.
 if original_ > now()-interval '10 minutes' then raise exception 'pre-freeze submission hidden'; end if;

 job_:=gen_random_uuid();
 insert into public.judge_jobs(id,kind,target_id,user_email,problem,language,status,worker_id,attempt,lease_until)
 values(job_,'rejudge',sid_,email_,'synthetic','c','running','time-worker',1,now()+interval '5 minutes');
 result_:=public.judge_queue_finish(job_,'time-worker',1,'{}',
  jsonb_build_object('problem','synthetic','language','c','user_email',email_,
   'verdict','AC','accepted',true,'score',100,'passed',1,'total',1,'counts','{}'::jsonb,
   'results','[]'::jsonb,'detail','','tests_hash','synthetic','grader_version','synthetic',
   'kind','rejudge','created_at',now()),'');
 select created_at into original_ from public.submissions where id=sid_;
 if original_ is distinct from admitted_ then raise exception 'rejudge moved original timestamp'; end if;
end $test$;
rollback;
