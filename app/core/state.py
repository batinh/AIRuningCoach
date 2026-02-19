class AppState:
    _instance = None
    service_active = True

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AppState, cls).__new__(cls)
        return cls._instance

# Singleton instance
state = AppState()