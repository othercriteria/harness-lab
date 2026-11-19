"""HTTP redirect policy shared by the local model client and prefix warm-up."""

import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects disabled for local model requests")
