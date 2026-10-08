"""
agent/providers/__init__.py

Provider interfaces.  Every provider is a small class with a single async
method.  Swap the implementation by changing which class is instantiated in
the dependency-injection layer — the checks layer never imports concrete
providers directly.
"""
