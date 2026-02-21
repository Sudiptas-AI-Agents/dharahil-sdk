from .client import DharaHILClient
from .interceptor import ToolExecutionInterceptor, InterceptorResult

# Backward compatibility
DharaClient = DharaHILClient

__all__ = ["DharaHILClient", "DharaClient", "ToolExecutionInterceptor", "InterceptorResult"]

