class PrivatePageCacheMiddleware:
    """Authenticated pages must not remain available in shared-browser HTTP caches."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated or request.path in ('/connexion/','/deconnexion/','/inscription/'):
            response['Cache-Control'] = 'no-store, private'
        return response
