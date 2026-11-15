"""Constants of the Skolengo mobile API.

The OIDC client below is the public client of the official Skolengo mobile app. It is shared by every
user of the app and is not a personal secret (it is also published by the scolengo-api project).
"""

from __future__ import annotations

from typing import Final

API_BASE_URL: Final = "https://api.skolengo.com/api/v1/bff-sko-app"

OIDC_CLIENT_ID: Final = "SkoApp.Prod.0d349217-9a4e-41ec-9af9-df9e69e09494"
OIDC_CLIENT_SECRET: Final = "7cb4d9a8-2580-4041-9ae8-d5803869183f"
OIDC_REDIRECT_URI: Final = "skoapp-prod://sign-in-callback"
OIDC_SCOPE: Final = "openid"

# Browser-like user agent for the sign-in pages (CAS, EduConnect); some identity providers
# serve degraded pages to unknown clients.
LOGIN_USER_AGENT: Final = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
)

# Upper bound of pages and redirects walked during one sign-in, to never loop forever.
LOGIN_MAX_STEPS: Final = 30

# Refresh the access token this many seconds before it expires.
TOKEN_REFRESH_MARGIN: Final = 120

REQUEST_TIMEOUT: Final = 30

# Services advertised in the users-info permissions (one entry per school).
SERVICE_HOMEWORK: Final = "TAF"
SERVICE_LESSONS: Final = "CDT"
SERVICE_MESSAGES: Final = "MSG"
SERVICE_EVALUATIONS: Final = "EVAL"
SERVICE_ABSENCES: Final = "ABS"
