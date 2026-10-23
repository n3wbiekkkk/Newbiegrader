"""Database transports for the pinned Supabase/PostgREST SDK versions.

Long-lived worker polling encounters HTTP/2 GOAWAY at connection turnover.
Use pooled, certificate-verified HTTP/1.1 for worker PostgREST traffic only.
An ambiguous RPC failure is never automatically replayed by this adapter.
"""
from postgrest import SyncPostgrestClient
from postgrest.utils import SyncClient as PostgrestSession
from supabase import create_client
from supabase._sync.client import SyncClient as SupabaseClient


class WorkerPostgrestClient(SyncPostgrestClient):
    def create_session(self, base_url, headers, timeout, verify=True):
        return PostgrestSession(base_url=base_url, headers=headers,
                                timeout=timeout, verify=verify,
                                follow_redirects=True, http2=False)


class WorkerSupabaseClient(SupabaseClient):
    # Supabase 2.7.1 has no public transport-injection option. Keep this narrow
    # factory override covered by real SDK tests when updating either SDK.
    @staticmethod
    def _init_postgrest_client(rest_url, headers, schema, timeout=120, verify=True):
        return WorkerPostgrestClient(rest_url, headers=headers, schema=schema,
                                    timeout=timeout, verify=verify)


def create_database_client(url, key, *, role):
    if role == "worker":
        return WorkerSupabaseClient.create(url, key)
    return create_client(url, key)
