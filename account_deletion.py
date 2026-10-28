"""Resume prepared account deletion without HTTP or maintenance policy.

Callers must obtain durable pending work before resuming. Confirmation, admin
checks, begin/revocation, dry-run and retention remain with their callers.
"""
import email_auth


class DeletionIncomplete(RuntimeError):
    """Completion is unconfirmed; no successful erasure may be reported."""


class AccountDeletion:
    def __init__(self, client, auth_url, auth_key):
        self._client = client
        self._auth_url = auth_url
        self._auth_key = auth_key

    def resume(self, email, auth_subject=None):
        """Delete the provider identity before finishing prepared deletion.

        Missing provider identities are already idempotent in email_auth.
        Pending work can be resumed later. An ambiguous finish reply may have
        committed already; this attempt never retries it or reports success.
        """
        try:
            subject = auth_subject or email_auth.find_identity(
                self._auth_url, self._auth_key, email)
            if subject:
                email_auth.delete_identity(self._auth_url, self._auth_key, subject)
            result = self._client.rpc('account_delete_finish', {'p_email': email}).execute().data
            if not isinstance(result, dict) or not result.get('ok'):
                raise ValueError('finish not confirmed')
        except Exception:
            raise DeletionIncomplete('account deletion incomplete') from None
