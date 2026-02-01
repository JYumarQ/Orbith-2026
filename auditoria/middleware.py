from contextvars import ContextVar

# Definimos una variable de contexto global.
# ContextVar gestiona el almacenamiento de forma segura para Async y Threads.
_user_ctx_var = ContextVar('user', default=None)

def get_current_user():
    """
    Recupera el usuario del contexto actual de ejecución.
    Si no hay usuario seteado, devuelve el valor por defecto (None).
    """
    return _user_ctx_var.get()

class CurrentUserMiddleware:
    """
    Middleware que intercepta cada petición y guarda el usuario (request.user)
    en una ContextVar. Esto permite acceder al usuario actual desde cualquier
    parte del código (como en el método save() de los modelos) sin pasar el request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Obtenemos el usuario del request (o None si no está autenticado)
        user = getattr(request, 'user', None)
        
        # 2. Establecemos el valor en el contexto y guardamos el 'token'
        # Este token es necesario para limpiar la variable después.
        token = _user_ctx_var.set(user)
        
        try:
            # 3. Procesamos la petición
            response = self.get_response(request)
        finally:
            # 4. Limpieza: Es CRÍTICO resetear la variable al finalizar.
            # Esto evita que una petición posterior reutilice accidentalmente 
            # el usuario de la petición anterior si el servidor recicla el hilo/contexto.
            _user_ctx_var.reset(token)
            
        return response