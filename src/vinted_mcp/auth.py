"""Single-owner OAuth, PKCE validation and redirect checks supplied by the MCP SDK.

Grants are intentionally in memory; restarting revokes all connections.
No Vinted session ever crosses this authentication boundary.
"""

import html
import secrets
import time
from urllib.parse import urlencode

from mcp.server.auth.provider import AccessToken, AuthorizationCode, TokenError
from mcp.shared.auth import OAuthToken
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse


class OwnerOAuth:
    def __init__(self, settings):
        self.settings = settings
        self.clients, self.pending, self.codes, self.tokens = {}, {}, {}, {}
        self.attempts = []

    def prune(self):
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v[2] > now}
        self.codes = {k: v for k, v in self.codes.items() if v.expires_at > now}
        self.tokens = {k: v for k, v in self.tokens.items() if v.expires_at > now}

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info):
        if len(self.clients) >= 100:
            from mcp.server.auth.provider import RegistrationError

            raise RegistrationError("invalid_client_metadata", "Registration limit reached; restart server")
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params):
        self.prune()
        if params.resource not in {None, self.settings.public_url + "/mcp"}:
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError("invalid_target", "Unexpected resource")
        if len(self.pending) >= 100:
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError("temporarily_unavailable", "Too many requests")
        request_id = secrets.token_urlsafe(32)
        self.pending[request_id] = (client, params, time.time() + 300)
        return self.settings.public_url + "/owner/consent?" + urlencode({"request": request_id})

    async def consent(self, request):
        self.prune()
        if request.method == "GET":
            request_id = request.query_params.get("request", "")
            if request_id not in self.pending:
                return PlainTextResponse("Richiesta scaduta", status_code=400)
            client, params, _ = self.pending[request_id]
            response = HTMLResponse(f'''<!doctype html><html lang="it"><meta charset="utf-8">
                <title>Collega Vinted MCP</title><h1>Autorizza il tuo server personale</h1>
                <p>Client: {html.escape(client.client_name or client.client_id)}</p>
                <p>Destinazione: {html.escape(str(params.redirect_uri))}</p>
                <p>Concedi accesso a foto, bozze e pubblicazione. Usa solo client di cui ti fidi.</p>
                <form method="post"><input type="hidden" name="request" value="{request_id}">
                <label>Segreto del proprietario <input type="password" name="secret" required autocomplete="off"></label>
                <button>Autorizza connessione</button></form></html>''')
            response.set_cookie(
                "vinted_oauth",
                request_id,
                httponly=True,
                samesite="strict",
                secure=self.settings.public_url.startswith("https:"),
                max_age=300,
                path="/owner/consent",
            )
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'",
                }
            )
            return response
        if request.headers.get("origin") != self.settings.public_url:
            return PlainTextResponse("Origine non valida", status_code=403)
        form = await request.form(max_fields=3)
        request_id, secret = str(form.get("request", "")), str(form.get("secret", ""))
        cookie = request.cookies.get("vinted_oauth", "")
        if request_id not in self.pending or not secrets.compare_digest(request_id, cookie):
            return PlainTextResponse("Richiesta non valida", status_code=403)
        self.attempts = [t for t in self.attempts if t > time.time() - 300]
        if len(self.attempts) >= 5:
            return PlainTextResponse("Troppi tentativi: attendi 5 minuti", status_code=429)
        self.attempts.append(time.time())
        if not secrets.compare_digest(secret.encode(), self.settings.owner_secret.encode()):
            return PlainTextResponse("Segreto non valido", status_code=403)
        client, params, _ = self.pending.pop(request_id)
        code = secrets.token_urlsafe(32)
        self.codes[code] = AuthorizationCode(
            code=code,
            client_id=client.client_id,
            scopes=params.scopes or ["vinted"],
            expires_at=time.time() + 60,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.settings.public_url + "/mcp",
        )
        from mcp.server.auth.provider import construct_redirect_uri

        response = RedirectResponse(
            construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state), status_code=303
        )
        response.delete_cookie("vinted_oauth", path="/owner/consent")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def load_authorization_code(self, client, authorization_code):
        self.prune()
        code = self.codes.get(authorization_code)
        return code if code and code.client_id == client.client_id else None

    async def exchange_authorization_code(self, client, authorization_code):
        # No await between pop and issuance, preventing reuse in a single worker.
        code = self.codes.pop(authorization_code.code, None)
        if not code or code.client_id != client.client_id or code.expires_at <= time.time():
            raise TokenError("invalid_grant", "Code expired or consumed")
        token = secrets.token_urlsafe(48)
        self.tokens[token] = AccessToken(
            token=token,
            client_id=client.client_id,
            scopes=code.scopes,
            expires_at=int(time.time()) + 86400,
            resource=code.resource,
        )
        return OAuthToken(
            access_token=token, token_type="Bearer", expires_in=86400, scope=" ".join(code.scopes)
        )

    async def load_access_token(self, token):
        self.prune()
        return self.tokens.get(token)

    async def load_refresh_token(self, client, refresh_token):
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        raise TokenError("invalid_grant", "Reconnect to renew authorization")

    async def revoke_token(self, token):
        self.tokens.pop(token.token, None)
