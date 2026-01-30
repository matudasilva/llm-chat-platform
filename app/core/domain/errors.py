class ProviderTimeoutError(Exception):
    """Provider call exceeded the configured timeout."""
    pass


class ProviderExecutionError(Exception):
    """Provider call failed unexpectedly."""
    pass
